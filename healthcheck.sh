#!/bin/bash

# =============================================================================
# TFT Analytics — Infrastructure Health Check
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

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

echo ""
echo "Checking infrastructure health..."
echo "-----------------------------------"

check "Redis" \
    "docker-compose exec -T redis redis-cli ping" \
    "PONG"

check "PostgreSQL" \
    "docker-compose exec -T postgres psql -U tft -d tft -c 'SELECT 1;'" \
    "1"

check "ClickHouse" \
    "docker-compose exec -T clickhouse clickhouse-client --query 'SELECT 1'" \
    "1"

check "Flower UI" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:5555" \
    "200"

check "Backend API" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health" \
    "200"

echo "-----------------------------------"
echo -e "Results: ${GREEN}$PASS passed${NC} / ${RED}$FAIL failed${NC}"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${YELLOW}Tip: for more details run: docker-compose logs <service>${NC}"
    echo -e "${YELLOW}     e.g: docker-compose logs postgres${NC}"
    echo ""
    exit 1
fi
