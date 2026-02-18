# TFT Analytics — Architecture Document

---

## 1. System Overview

This system crawls TFT match data from the Riot Games API, stores it in a dual-database setup, and serves analytical queries through a REST API consumed by a React frontend.

### Tech Stack

| Concern | Tool | Reason |
|---|---|---|
| Language | Python (backend), JavaScript (frontend) | Ecosystem fit |
| Task queue | Celery | Distributed task execution, retries, chaining |
| Message broker | Redis | Task queuing, rate limit state, deduplication |
| Raw JSON storage | PostgreSQL | Relational source of truth, JSONB support |
| ORM | SQLAlchemy + Alembic | Pythonic DB access, schema migrations |
| Analytics database | ClickHouse | Columnar storage, fast aggregations on flat data |
| CH client | clickhouse-connect | Official Python ClickHouse client |
| HTTP client | httpx | Async-capable, clean timeout/retry support |
| Data validation | Pydantic | Parsing and validating nested Riot API responses |
| Backend API | FastAPI | Modern, async, auto-docs, Pydantic native |
| Frontend | React + Recharts | Interactive filters, tables, charts |
| Pipeline monitoring | Flower | Celery queue and worker visibility |
| Logging | structlog | Structured JSON logs, traceable by match ID |
| Local orchestration | Docker Compose | Single command brings up all services |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CRAWLER PIPELINE                         │
│                                                                 │
│  ┌──────────────┐                                               │
│  │ Celery Beat  │  ← triggers league fetch when queues empty   │
│  └──────┬───────┘                                               │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                        REDIS                            │   │
│  │                                                         │   │
│  │  queue:league        (low volume)                       │   │
│  │  queue:match_list    (medium volume)                     │   │
│  │  queue:match_detail  (high volume)                       │   │
│  │  queue:save                                              │   │
│  │                                                          │   │
│  │  set:fetched_match_ids     ← deduplication               │   │
│  │  set:crawled_puuids_cycle  ← per-cycle dedup (TTL)       │   │
│  │  key:pause_until           ← shared rate limit signal    │   │
│  └──────────────────────────────────────────────────────────┘  │
│         │                                                       │
│   ┌─────┴──────┬─────────────────┬──────────────────┐          │
│   ▼            ▼                 ▼                  ▼          │
│ League      Match List      Match Detail          Save          │
│ Workers     Workers         Workers               Workers       │
│ (1-2)       (2-3)           (5-10)                (2-4)         │
└─────────────────────────────────────────────────────────────────┘
                                                    │
                              ┌─────────────────────┴──────────┐
                              │                                │
                         PostgreSQL                       ClickHouse
                      (raw JSONB + metadata)          (flat analytical rows)
                              │                                │
                              └─────────────────┬─────────────┘
                                                │
                                           FastAPI
                                                │
                                          React Frontend
```

---

## 3. Crawler Event Flow

### 3.1 Pipeline Trigger

The pipeline is self-regulating — it does not run on a fixed timer. Instead:

- Celery Beat monitors `queue:match_list`
- When the queue drains to empty, it triggers a new league fetch cycle
- A cooldown is enforced (minimum time between league fetches) to prevent tight loops when all players are already up to date
- Celery Beat also runs a lightweight patch detection check independently, triggering a ClickHouse partition drop when a new patch is detected

### 3.2 Step-by-Step Event Flow

```
[1] LEAGUE FETCH
    Celery Beat → fetch_league task (x3: Challenger, Grandmaster, Master)
        → GET /tft/league/v1/{tier}
        → read rate limit headers → update pause_until if needed
        → for each puuid in response:
            if puuid not in set:crawled_puuids_cycle (TTL set):
                push fetch_match_list(puuid) → queue:match_list

[2] MATCH LIST FETCH
    fetch_match_list(puuid)
        → check pause_until before request
        → GET /tft/match/v1/matches/by-puuid/{puuid}/ids?count=20
        → read rate limit headers → update pause_until if needed
        → for each match_id:
            atomic check: is match_id in set:fetched_match_ids?
                NO  → push fetch_match_detail(match_id) → queue:match_detail
                YES → discard
        → if all 20 IDs already known: stop (player is fully up to date)

[3] MATCH DETAIL FETCH
    fetch_match_detail(match_id)
        → check pause_until before request
        → GET /tft/match/v1/matches/{match_id}
        → read rate limit headers → update pause_until if needed
        → on 429: read Retry-After header, requeue task with that delay
        → on success:
            atomically add match_id to set:fetched_match_ids
            push save_match(raw_json) → queue:save

[4] SAVE
    save_match(raw_json)
        → validate and parse with Pydantic
        → write raw JSON to PostgreSQL (jsonb column)
        → explode nested structure into flat unit-level rows
        → batch insert flat rows into ClickHouse
```

### 3.3 Fan-Out and Deduplication

A single match appears in up to 8 different players' match histories. Without deduplication, each match would be fetched 8 times. The atomic Redis set check at step [2] prevents this — the first worker to see a match ID claims it; all others discard it.

The atomic check uses a Redis `SETNX`-equivalent operation so two workers processing different players simultaneously cannot both decide to fetch the same match.

---

## 4. Rate Limit Management

Riot enforces two independent limit buckets:

- **App rate limit** — shared across all endpoints (e.g. 100 req / 2 min)
- **Method rate limit** — per endpoint, varies by endpoint

### Strategy

Every API response includes headers reporting current usage. All workers share rate limit state through a single Redis key:

```
Before every request:
  → read pause_until from Redis
  → if now < pause_until: sleep until then, then proceed

After every response:
  → parse X-App-Rate-Limit-Count and X-Method-Rate-Limit-Count
  → if app_calls_remaining < 5:
      SET pause_until = now + window_reset_seconds (atomic Redis write)
```

The threshold of 5 remaining calls absorbs in-flight requests that were already dispatched before the flag was set. The `pause_until` key carries a TTL equal to the rate limit window so it never blocks workers after a restart.

Worker pool sizes per queue are calibrated to each endpoint's method rate limit — the match detail endpoint is most generous and receives the most workers.

---

## 5. Stop / Restart Behaviour

The system is designed to be stopped and restarted at any time without losing progress or wasting API calls.

| State | Survives restart? | How |
|---|---|---|
| Queued tasks | ✅ Yes | Redis persistence (AOF/RDB) |
| Fetched match IDs | ✅ Yes | Redis set, pre-populated from PostgreSQL on startup |
| In-progress tasks | ✅ Yes | `acks_late=True` — requeued if worker dies mid-task |
| Rate limit pause | ✅ Yes | TTL on `pause_until` key expires naturally |
| Per-cycle puuid tracking | ✅ Yes | TTL on `crawled_puuids_cycle` expires naturally |
| In-flight HTTP requests | ⚠️ Requeued | `acks_late=True` handles this at the cost of one duplicate attempt, blocked by dedup |

### Graceful Shutdown

Use `celery control shutdown` rather than killing processes directly. This allows currently executing tasks to complete before workers stop, preventing unnecessary requeues and avoiding wasted API calls mid-request.

On startup, the application pre-populates `set:fetched_match_ids` from the PostgreSQL `matches` table to ensure Redis state is consistent with the database after any restart.

---

## 6. Data Storage Design

### PostgreSQL — Raw Storage

Stores one row per match with the full raw Riot API JSON response alongside key metadata columns for indexing and querying.

Purpose: source of truth, replay capability if ClickHouse schema changes or data needs reprocessing.

### ClickHouse — Analytical Storage

Stores one row per unit per participant per game — fully flat and denormalized. A single 8-player game produces approximately 72 rows.

**Partitioning:** partitioned by `patch`. Old partitions are dropped entirely at patch change — no row-level deletes needed.

**Sort key:** `ORDER BY (lp, unit_name)` — optimized for the most common query pattern of filtering by player strength and champion.

**Projections:** additional projections defined for item-first query patterns (e.g. "best champions for item X") where the base sort key is suboptimal.

**No precalculation:** all analytics are calculated live at query time. Query results are cached in Redis with a TTL to avoid redundant computation for repeated identical queries.

---

## 7. Analytics Query Flow

```
User sets filters in React UI (champion, item, LP threshold, tier)
    → POST /api/analytics with filter parameters
    → FastAPI hashes filter params → check Redis query cache
        HIT  → return cached result immediately
        MISS → build and execute ClickHouse query
             → store result in Redis (TTL: 30-60 min)
             → return result
    → React renders tables and Recharts visualizations
```

---

## 8. Folder / File Structure

```
tft-analytics/
│
├── docker-compose.yml
├── .env                             # Secrets and config — never committed to Git
├── .gitignore                       # Excludes .env, __pycache__, node_modules, etc.
├── .gitattributes                   # Consistent line endings across Windows and Linux
├── README.md
├── ARCHITECTURE.md
│
├── crawler/                         # Standalone crawler service
│   ├── Dockerfile
│   ├── requirements.txt             # celery, redis, httpx, pydantic, sqlalchemy, clickhouse-connect, structlog
│   ├── celeryconfig.py              # Queue routing, worker concurrency, acks_late
│   ├── main.py                      # Celery app entrypoint
│   │
│   ├── tasks/                       # Celery task definitions ONLY — no business logic
│   │   ├── __init__.py
│   │   ├── league.py                # fetch_league task
│   │   ├── match_list.py            # fetch_match_list task
│   │   ├── match_detail.py          # fetch_match_detail task
│   │   └── save.py                  # save_match task
│   │
│   ├── services/                    # Business logic — called by tasks, testable independently
│   │   ├── __init__.py
│   │   ├── riot_client.py           # httpx wrapper, rate limit header parsing
│   │   ├── rate_limiter.py          # pause_until Redis logic
│   │   ├── deduplication.py         # fetched_match_ids Redis set logic
│   │   ├── match_parser.py          # Pydantic models, raw JSON → flat rows explosion
│   │   └── patch_detector.py        # Patch change detection logic
│   │
│   └── db/                          # Database write logic
│       ├── __init__.py
│       ├── postgres.py              # SQLAlchemy session, raw match insert
│       └── clickhouse.py            # clickhouse-connect, flat row batch insert
│
├── backend/                         # FastAPI service
│   ├── Dockerfile
│   ├── requirements.txt             # fastapi, uvicorn, redis, pydantic, clickhouse-connect, structlog
│   ├── main.py                      # FastAPI app entrypoint
│   │
│   ├── routers/                     # Route definitions — no business logic
│   │   ├── __init__.py
│   │   └── analytics.py             # /api/analytics endpoints
│   │
│   ├── services/                    # Business logic
│   │   ├── __init__.py
│   │   ├── query_builder.py         # Translates user filters → ClickHouse SQL
│   │   └── cache.py                 # Redis query result cache
│   │
│   └── db/                          # Database read logic
│       ├── __init__.py
│       └── clickhouse.py            # clickhouse-connect, query execution
│
├── shared/                          # Code shared between crawler and backend
│   ├── __init__.py
│   ├── requirements.txt             # pydantic-settings, shared dependencies
│   ├── config.py                    # pydantic-settings, loads .env
│   ├── models/                      # Pydantic models shared across services
│   │   ├── __init__.py
│   │   ├── match.py                 # Raw match structure
│   │   └── unit.py                  # Flat unit row structure
│   └── logging.py                   # structlog configuration
│
├── alembic.ini                      # Alembic config — must live at project root
├── migrations/                      # Alembic PostgreSQL migrations
│   ├── env.py
│   └── versions/
│
└── frontend/                        # React application
    ├── package.json
    ├── public/
    └── src/
        ├── App.jsx
        ├── components/
        │   ├── FilterPanel.jsx      # LP threshold, tier, champion, item filters
        │   ├── StatsTable.jsx       # Tabular results display
        │   └── StatsChart.jsx       # Recharts visualizations
        └── services/
            └── api.js               # FastAPI client calls
```

---

## 9. Design Rules

These rules govern the codebase structure and must be followed consistently:

**No direct DB calls inside tasks.**
Celery tasks in `crawler/tasks/` are thin orchestrators only. All database reads and writes go through `crawler/db/`. This keeps tasks testable and decoupled from storage concerns.

**No business logic inside tasks or routers.**
Tasks call services. Routers call services. Business logic lives exclusively in `services/` directories. A service function should be callable and testable without Celery or FastAPI running.

**No business logic inside tasks or routers.**
Tasks call services. Routers call services. Business logic lives exclusively in `services/` directories. A service function should be callable and testable without Celery or FastAPI running.

**Rate limiting is a service, not inline code.**
All rate limit logic lives in `crawler/services/rate_limiter.py`. Tasks call `rate_limiter.check_and_wait()` before every request. This makes the behaviour explicit, testable, and easy to modify.

**Deduplication is always atomic.**
No task ever performs a check-then-queue in two separate Redis operations. The check and the queue push are always a single atomic Redis operation to prevent race conditions between concurrent workers.

**Pydantic validates at the boundary.**
Raw Riot API JSON is parsed and validated by Pydantic models the moment it arrives, before anything is written to any database. Invalid or unexpected data is logged and discarded, never silently written.

**Shared code belongs in `shared/`.**
Config, Pydantic models, and logging setup used by both crawler and backend live in `shared/`. No cross-importing between `crawler/` and `backend/`.

**ClickHouse is write-once.**
No updates or deletes on individual rows. Patch data expiry is handled exclusively by partition drops. This preserves ClickHouse performance characteristics.

**Query results are cached, not precalculated.**
No scheduled aggregation jobs. ClickHouse is queried live; Redis caches results with a TTL. Cache invalidation happens naturally via TTL expiry, not via explicit invalidation logic.

**Secrets never in code.**
All credentials, API keys, and environment-specific config live in `.env` and are accessed exclusively through `shared/config.py` using pydantic-settings. The `.env` file is never committed to version control.
