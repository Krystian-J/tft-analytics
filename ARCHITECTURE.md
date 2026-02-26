# TFT Analytics — Architecture Document

---

## 1. System Overview

This system crawls TFT match data from the Riot Games API, stores it in a dual-database setup, and serves analytical queries through a REST API consumed by a React frontend.

### Tech Stack

| Concern | Tool | Reason |
|---|---|---|
| Language | Python (backend), JavaScript (frontend) | Ecosystem fit |
| Task queue | Celery | Distributed task execution, retries, chaining |
| Message broker | Redis | Task queuing, rate limit state, deduplication, query cache |
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
| Testing | pytest + fakeredis | Unit tests for services, no real infra needed |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CRAWLER PIPELINE                         │
│                                                                 │
│  ┌──────────────┐                                               │
│  │ Celery Beat  │  ← triggers league fetch on schedule         │
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
│  │  cache:*                   ← backend query result cache  │   │
│  └──────────────────────────────────────────────────────────┘  │
│         │                                                       │
│   ┌─────┴──────┬─────────────────┬──────────────────┐          │
│   ▼            ▼                 ▼                  ▼          │
│ League      Match List      Match Detail          Save          │
│ Workers     Workers         Workers               Workers       │
│ (1-2)       (2-3)           (2)                   (2)           │
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

Celery Beat triggers a new league fetch cycle every `CRAWLER_COOLDOWN_MINUTES` (default: 30 minutes). Deduplication ensures players already crawled this cycle are skipped automatically.

#### Season Start Corner Case

At the beginning of a new season, Challenger, Grandmaster and Master leagues are empty until players climb the ladder. The crawler uses a cascading seeder strategy to handle this:

```
fetch_league(CHALLENGER + GRANDMASTER + MASTER)
    → count total unique puuids collected
    → if total < MIN_PLAYERS_THRESHOLD (default: 300):
        fetch_league(DIAMOND I)
    → if still < MIN_PLAYERS_THRESHOLD:
        fetch_league(EMERALD I)
    → if still < MIN_PLAYERS_THRESHOLD:
        fetch_league(PLATINUM I)
    → if still < MIN_PLAYERS_THRESHOLD:
        fetch_league(GOLD I)
    → ... continue down ladder until threshold is met
```

Additionally a small hardcoded list of known top player puuids is kept in config as a fallback seed. These are injected directly into `queue:match_list` regardless of league endpoint results, ensuring the crawler always has something to work with even on day one of a new season.

`MIN_PLAYERS_THRESHOLD` is configurable via `.env`. This logic lives entirely in `crawler/services/league_seeder.py`.

### 3.2 Step-by-Step Event Flow

```
[1] LEAGUE FETCH
    Celery Beat → fetch_league task
        → cascading tier fetch via league_seeder.collect_puuids_for_cycle()
        → GET /tft/league/v1/{tier}
        → read rate limit headers → update pause_until if needed
        → on 403: set pause_until for 1 hour, raise InvalidKeyError
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
            push save_match(raw_json) → queue:save

[4] SAVE
    save_match(raw_json)
        → validate and parse with Pydantic
        → write raw JSON to PostgreSQL (jsonb column)
        → detect patch change → drop old ClickHouse partitions if needed
        → look up player ranks from PostgreSQL for LP denormalization
        → explode nested structure into flat unit-level rows
        → batch insert flat rows into ClickHouse
```

### 3.3 Fan-Out and Deduplication

A single match appears in up to 8 different players' match histories. Without deduplication, each match would be fetched 8 times. The atomic Redis set check at step [2] prevents this — the first worker to see a match ID claims it; all others discard it.

The atomic check uses a Lua script so two workers processing different players simultaneously cannot both decide to fetch the same match.

### 3.4 Expired API Key Handling

When Riot returns a 403 (expired or invalid key), `riot_client.py` immediately sets `pause_until` in Redis for 1 hour, halting all workers. A clear error is logged:

```
riot api key invalid or expired — update RIOT_API_KEY in .env and restart the crawler
```

To recover: update `RIOT_API_KEY` in `.env` and run `docker-compose restart crawler`. The pause is cleared on restart and all queued tasks resume normally.

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
  → if app_calls_remaining < RATE_LIMIT_BUFFER (default: 5):
      SET pause_until = now + window_reset_seconds (atomic Redis write)
```

The threshold of 5 remaining calls absorbs in-flight requests that were already dispatched before the flag was set. The `pause_until` key carries a TTL equal to the rate limit window so it never blocks workers after a restart.

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

**Partitioning:** partitioned by `game_version` (patch). Old partitions are dropped entirely at patch change — no row-level deletes needed.

**Sort key:** `ORDER BY (character_id, lp)` — optimized for the most common query pattern of filtering by champion then by player strength.

**Projections:** additional projections defined for item-first query patterns (e.g. "best champions for item X") where the base sort key is suboptimal.

**No precalculation:** all analytics are calculated live at query time. Query results are cached in Redis with a TTL to avoid redundant computation for repeated identical queries.

---

## 7. Backend API

The FastAPI backend exposes four endpoints, all under `/api`:

| Endpoint | Description |
|---|---|
| `GET /api/patches` | All available patches, most recent first |
| `GET /api/champions` | Champion stats for all champions |
| `GET /api/champions/{character_id}` | Stats + top item combos for one champion |
| `GET /api/items` | Item combo stats for a specific champion |

### Query Parameters

All analytics endpoints accept the same filter parameters:

| Parameter | Type | Description |
|---|---|---|
| `patch` | string | Game version e.g. `16.4`. Defaults to current patch automatically. |
| `tiers` | list[string] | One or more tiers e.g. `?tiers=CHALLENGER&tiers=GRANDMASTER` |
| `min_lp` | integer | Minimum LP — only applied when all selected tiers are Master/GM/Challenger |

### Patch Defaulting

The current patch is determined dynamically by querying ClickHouse for the most recent `game_version` present in `tft.unit_stats`. The result is cached in Redis for 5 minutes so patch transitions are picked up automatically without requiring a restart.

### Caching

All query results are cached in Redis with a 1 hour TTL. Cache keys are derived from a hash of the filter parameters, so different filter combinations have independent cache entries. Cache invalidation happens naturally via TTL expiry.

---

## 8. Analytics Query Flow

```
User sets filters in React UI (tiers, LP threshold, patch)
    → GET /api/champions with filter parameters
    → FastAPI hashes filter params → check Redis query cache
        HIT  → return cached result immediately
        MISS → build and execute ClickHouse query
             → store result in Redis (TTL: 1 hour)
             → return result
    → React renders tables and Recharts visualizations
```

---

## 9. Testing

Tests live in `tests/` at the project root. They run locally in a virtual environment — not inside Docker.

### Running Tests

```powershell
# From project root with venv activated
pytest
```

### What Is Tested

| Module | Approach |
|---|---|
| `crawler/services/match_parser.py` | Unit tests with real match JSON fixture — no mocking needed |
| `crawler/services/rate_limiter.py` | Unit tests with `fakeredis` — no real Redis needed |
| `crawler/services/deduplication.py` | Unit tests with `fakeredis` — no real Redis needed |
| `backend/services/query_builder.py` | Unit tests — pure functions, no infra needed |

### What Is Not Tested

- Celery tasks — thin wrappers around services; service tests provide sufficient coverage
- Database write/read functions — require real PostgreSQL/ClickHouse
- Riot API responses — mocked via `pytest-mock` where needed

### Pre-commit Hook

Tests run automatically before every `git commit` via pre-commit hook. A failing test blocks the commit.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: venv/Scripts/pytest.exe
        language: system
        pass_filenames: false
        always_run: true
```

---

## 10. Folder / File Structure

```
tft-analytics/
│
├── docker-compose.yml
├── .env                             # Secrets and config — never committed to Git
├── .gitignore                       # Excludes .env, __pycache__, node_modules, etc.
├── .gitattributes                   # Consistent line endings across Windows and Linux
├── .pre-commit-config.yaml          # Pre-commit hook — runs pytest before every commit
├── README.md
├── ARCHITECTURE.md
├── pytest.ini                       # pytest configuration
├── requirements-test.txt            # Local test dependencies (no psycopg2/docker needed)
├── clickhouse_schema.sql            # ClickHouse schema — applied once via init script
│
├── tests/                           # All tests live here — run locally, not in Docker
│   ├── __init__.py
│   ├── fixtures/
│   │   └── match_response.json      # Real Riot API match response for testing
│   ├── test_match_parser.py         # Tests for explosion logic and version parsing
│   ├── test_rate_limiter.py         # Tests for pause_until logic and header parsing
│   ├── test_deduplication.py        # Tests for atomic check-and-mark logic
│   └── test_query_builder.py        # Tests for SQL generation and filter logic
│
├── crawler/                         # Standalone crawler service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── celeryconfig.py              # Queue routing, worker concurrency, acks_late, beat schedule
│   ├── main.py                      # Celery app entrypoint with startup preload
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
│   │   ├── riot_client.py           # httpx wrapper, rate limit + 403 handling
│   │   ├── rate_limiter.py          # pause_until Redis logic
│   │   ├── deduplication.py         # fetched_match_ids Redis set logic
│   │   ├── match_parser.py          # Pydantic models, raw JSON → flat rows explosion
│   │   ├── league_seeder.py         # Cascading league fetch logic, season start handling
│   │   └── patch_detector.py        # Patch change detection, ClickHouse partition drops
│   │
│   └── db/                          # Database write logic
│       ├── __init__.py
│       ├── postgres.py              # SQLAlchemy session, raw match + rank insert
│       └── clickhouse.py            # clickhouse-connect, flat row batch insert
│
├── backend/                         # FastAPI service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                      # FastAPI app entrypoint, CORS config
│   │
│   ├── routers/                     # Route definitions — no business logic
│   │   ├── __init__.py
│   │   └── analytics.py             # /api/patches, /api/champions, /api/items endpoints
│   │
│   ├── services/                    # Business logic
│   │   ├── __init__.py
│   │   ├── query_builder.py         # Translates user filters → ClickHouse SQL
│   │   ├── cache.py                 # Redis query result cache with configurable TTL
│   │   └── patch.py                 # Current patch detection with 5-min Redis cache
│   │
│   └── db/                          # Database read logic
│       ├── __init__.py
│       └── clickhouse.py            # clickhouse-connect, query execution
│
├── shared/                          # Code shared between crawler and backend
│   ├── __init__.py
│   ├── requirements.txt
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
        │   ├── FilterPanel.jsx      # Tier multi-select, LP threshold, patch selector
        │   ├── StatsTable.jsx       # Champion stats table with sorting
        │   └── StatsChart.jsx       # Recharts visualizations
        └── services/
            └── api.js               # FastAPI client calls
```

---

## 11. Design Rules

These rules govern the codebase structure and must be followed consistently:

**No direct DB calls inside tasks.**
Celery tasks in `crawler/tasks/` are thin orchestrators only. All database reads and writes go through `crawler/db/`. This keeps tasks testable and decoupled from storage concerns.

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

**Current patch is never hardcoded.**
The backend always determines the current patch dynamically from ClickHouse data. This ensures patch transitions happen automatically without restarts or config changes.

**Secrets never in code.**
All credentials, API keys, and environment-specific config live in `.env` and are accessed exclusively through `shared/config.py` using pydantic-settings. The `.env` file is never committed to version control.

**Tests run locally, not in Docker.**
Tests use `fakeredis` and fixture JSON files to run without any real infrastructure. The Docker setup is for production only.
