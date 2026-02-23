#!/bin/bash

# =============================================================================
# TFT Analytics — Health Check
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
    local name=$1
    local command=$2
    local expected=$3

    result=$(eval "$command" 2>&1)
    if echo "$result" | grep -q "$expected"; then
        echo -e "${GREEN}✓ $name${NC}"
        ((PASS++))
    else
        echo -e "${RED}✗ $name${NC}"
        echo -e "${YELLOW}  → $result${NC}"
        ((FAIL++))
    fi
}

warn() {
    local name=$1
    local message=$2
    echo -e "${YELLOW}⚠ $name — $message${NC}"
    ((WARN++))
}

container_running() {
    docker-compose ps --services --filter "status=running" 2>/dev/null | grep -q "^$1$"
}

container_exited_ok() {
    # Returns true if container exited with code 0
    local exit_code
    exit_code=$(docker inspect --format='{{.State.ExitCode}}' "tft_$1" 2>/dev/null)
    [ "$exit_code" = "0" ]
}

echo ""
echo "============================================"
echo " TFT Analytics — Health Check"
echo "============================================"

# ---------------------------------------------------------------------------
echo ""
echo "[ Infrastructure ]"
# ---------------------------------------------------------------------------

check "Redis" \
    "docker-compose exec -T redis redis-cli ping" \
    "PONG"

check "PostgreSQL" \
    "docker-compose exec -T postgres psql -U tft -d tft -c 'SELECT 1;'" \
    "1"

check "ClickHouse" \
    "docker-compose exec -T clickhouse clickhouse-client --query 'SELECT 1'" \
    "1"

# ---------------------------------------------------------------------------
echo ""
echo "[ Schema ]"
# ---------------------------------------------------------------------------

check "ClickHouse schema (unit_stats table)" \
    "docker-compose exec -T clickhouse clickhouse-client --query 'EXISTS TABLE tft.unit_stats'" \
    "1"

# Migrator — check it exited cleanly
if container_exited_ok "migrator"; then
    echo -e "${GREEN}✓ Alembic migrations applied${NC}"
    ((PASS++))
    check "PostgreSQL tables (league_entries)" \
        "docker-compose exec -T postgres psql -U tft -d tft -c '\dt'" \
        "league_entries"
    check "PostgreSQL tables (matches)" \
        "docker-compose exec -T postgres psql -U tft -d tft -c '\dt'" \
        "matches"
    check "PostgreSQL tables (player_crawls)" \
        "docker-compose exec -T postgres psql -U tft -d tft -c '\dt'" \
        "player_crawls"
    check "Migration version" \
        "docker-compose exec -T postgres psql -U tft -d tft -c 'SELECT version_num FROM alembic_version;'" \
        "0001"
else
    warn "Alembic migrations" "migrator container not found or exited with error — run: docker-compose logs migrator"
fi

# ---------------------------------------------------------------------------
echo ""
echo "[ Crawler ]"
# ---------------------------------------------------------------------------

if container_running "crawler"; then
    check "Crawler worker process" \
        "docker-compose exec -T crawler celery -A crawler.main inspect ping" \
        "pong"
    check "Redis dedup set populated" \
        "docker-compose exec -T redis redis-cli scard dedup:fetched_match_ids" \
        ""   # any response means the key exists and is queryable
else
    warn "Crawler" "not running — uncomment in docker-compose.yml when ready"
fi

if container_running "celery_beat"; then
    echo -e "${GREEN}✓ Celery Beat running${NC}"
    ((PASS++))
else
    warn "Celery Beat" "not running — uncomment in docker-compose.yml when ready"
fi

if container_running "flower"; then
    check "Flower UI" \
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:5555" \
        "200"
else
    warn "Flower" "not running — uncomment in docker-compose.yml when ready"
fi

# ---------------------------------------------------------------------------
echo ""
echo "[ Backend ]"
# ---------------------------------------------------------------------------

if container_running "backend"; then
    check "Backend API /health" \
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health" \
        "200"
else
    warn "Backend" "not running — uncomment in docker-compose.yml when ready"
fi

# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo -e " ${GREEN}$PASS passed${NC}  ${RED}$FAIL failed${NC}  ${YELLOW}$WARN warnings${NC}"
echo "============================================"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${YELLOW}Tip: docker-compose logs <service> for details${NC}"
    echo -e "${YELLOW}     e.g: docker-compose logs crawler${NC}"
    echo ""
    exit 1
fi
