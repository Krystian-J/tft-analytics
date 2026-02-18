# TFT Analytics

A personal project that crawls TFT match data from the Riot Games API, stores it in a dual-database setup, and serves analytical queries through a web interface.

For full architecture details see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## What It Does

- Crawls match data from Challenger, Grandmaster and Master leagues via Riot API
- Stores raw match JSON in PostgreSQL and flat analytical rows in ClickHouse
- Serves live analytics queries through a FastAPI backend
- Displays stats, item builds, and champion performance in a React frontend
- Respects Riot API rate limits via a Redis-coordinated crawler pipeline

---

## Prerequisites

- [Git](https://git-scm.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with WSL2 backend on Windows)
- A Riot Games API key from [developer.riotgames.com](https://developer.riotgames.com)

---

## Setup & Installation

**1. Clone the repository**
```bash
git clone <your-repo-url>
cd tft-analytics
```

**2. Create your environment file**
```bash
cp .env.example .env
```
Then open `.env` and fill in your values (see [Environment Variables](#environment-variables) below).

**3. Build and start all services**
```bash
docker-compose up --build
```

This starts: PostgreSQL, ClickHouse, Redis, Celery workers, Flower, and the FastAPI backend.

**4. Run database migrations**
```bash
docker-compose exec backend alembic upgrade head
```

**5. Open the frontend**
```bash
cd frontend
npm install
npm start
```

The React app will be available at `http://localhost:3000`.

---

## Running the Full Stack

### Start everything
```bash
docker-compose up
```

### Start in background
```bash
docker-compose up -d
```

### Stop everything
```bash
docker-compose down
```

### Stop and wipe all data volumes (full reset)
```bash
docker-compose down -v
```

### View logs for a specific service
```bash
docker-compose logs -f crawler
docker-compose logs -f backend
```

### Gracefully stop Celery workers (without losing queued tasks)
```bash
docker-compose exec crawler celery control shutdown
```

### Monitor the crawler pipeline
Flower UI is available at `http://localhost:5555` when the stack is running.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values below.

| Variable | Description | Example |
|---|---|---|
| `RIOT_API_KEY` | Your Riot Games API key | `RGAPI-xxxx-xxxx` |
| `RIOT_REGION` | Region for match data | `europe` |
| `POSTGRES_URL` | PostgreSQL connection string | `postgresql://user:pass@postgres/tft` |
| `POSTGRES_USER` | PostgreSQL username | `tft` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `yourpassword` |
| `POSTGRES_DB` | PostgreSQL database name | `tft` |
| `CLICKHOUSE_HOST` | ClickHouse host | `clickhouse` |
| `CLICKHOUSE_PORT` | ClickHouse port | `8123` |
| `CLICKHOUSE_DB` | ClickHouse database name | `tft` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `RATE_LIMIT_BUFFER` | Remaining calls threshold before pausing | `5` |
| `CRAWLER_COOLDOWN_MINUTES` | Min minutes between league fetch cycles | `30` |

---

## Useful Commands

### Re-normalize line endings after cloning on Windows
```bash
git add --renormalize .
```

### Rebuild a single service after code changes
```bash
docker-compose up --build crawler
```

### Access PostgreSQL directly
```bash
docker-compose exec postgres psql -U tft -d tft
```

### Access ClickHouse directly
```bash
docker-compose exec clickhouse clickhouse-client
```

### Access Redis directly
```bash
docker-compose exec redis redis-cli
```
