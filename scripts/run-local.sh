#!/usr/bin/env bash
# ============================================================
# OtelMS API - Local Development Runner (Linux/macOS)
# ============================================================
# Starts all services locally for development:
# - PostgreSQL (via Docker)
# - Redis (via Docker)
# - FastAPI API server
# - Celery Worker
# - Celery Beat (scheduler)
# ============================================================
# Browser runs in HEADFUL mode (visible) for local debugging
# In Docker, it runs headless via SCRAPER_HEADLESS=true
# ============================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  OtelMS API - Local Development Runner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if Docker is running
docker_running() {
    docker info >/dev/null 2>&1
}

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check for python (python3 on Linux/macOS, python on Windows)
if command_exists python3; then
    PYTHON_CMD="python3"
elif command_exists python; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: python not found${NC}"
    exit 1
fi

if ! command_exists uv; then
    echo -e "${RED}Error: uv not found. Install with: pip install uv${NC}"
    exit 1
fi

if ! docker_running; then
    echo -e "${RED}Error: Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

echo -e "${GREEN}Prerequisites OK${NC}"
echo ""

# Start PostgreSQL and Redis via Docker Compose (only infra services)
echo -e "${YELLOW}Starting PostgreSQL and Redis...${NC}"
docker compose -f docker/docker-compose.yml up -d postgres redis

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
sleep 5

# Check health
for i in {1..30}; do
    if docker compose -f docker/docker-compose.yml exec -T postgres pg_isready -U otelms -d otelms >/dev/null 2>&1; then
        echo -e "${GREEN}PostgreSQL is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}PostgreSQL failed to start${NC}"
        exit 1
    fi
    sleep 1
done

for i in {1..30}; do
    if docker compose -f docker/docker-compose.yml exec -T redis redis-cli ping >/dev/null 2>&1; then
        echo -e "${GREEN}Redis is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}Redis failed to start${NC}"
        exit 1
    fi
    sleep 1
done

echo ""

# Run database migrations
echo -e "${YELLOW}Running database migrations...${NC}"
uv run alembic upgrade head
echo -e "${GREEN}Migrations complete${NC}"
echo ""

# Create .env.local for local development (overrides for visible browser, no API key required)
cat > .env.local << 'EOF'
# Local development overrides
# This file is loaded AFTER .env, so it takes precedence

# API - disable key requirement for local testing
API_KEY_REQUIRED=false

# Browser - VISIBLE (headless=false) for local debugging
SCRAPER_HEADLESS=false
BROWSER_HEADLESS=false

# Logging - console format for local dev
LOG_FORMAT=console
LOG_LEVEL=DEBUG

# Disable proxy for local testing (unless needed)
USE_PROXY=false

# Database - use PostgreSQL from Docker (port 5433)
DATABASE_URL=postgresql+asyncpg://otelms:otelms_dev_password@localhost:5433/otelms

# Redis - use Redis from Docker (port 6380)
REDIS_URL=redis://localhost:6380/0
CELERY_BROKER_URL=redis://localhost:6380/1
CELERY_RESULT_BACKEND=redis://localhost:6380/2
EOF

echo -e "${GREEN}Created .env.local with local overrides${NC}"
echo ""

# Load environment files safely (no eval)
load_env() {
    local file="$1"
    if [ -f "$file" ]; then
        while IFS= read -r line; do
            # Remove carriage returns (Windows line endings)
            line="${line%$'\r'}"
            # Skip comments and empty lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${line// }" ]] && continue
            # Handle spaces around = and export
            # Format: KEY=value or KEY = value
            if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
                key="${BASH_REMATCH[1]}"
                value="${BASH_REMATCH[2]}"
                # Remove surrounding quotes if present
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'} "
                value="${value#\'}"
                export "$key=$value"
            fi
        done < "$file"
    fi
}

load_env ".env"
load_env ".env.local"

# Function to run a service in background and track PID
run_service() {
    local name="$1"
    shift
    local log_file="logs/${name}.log"
    
    mkdir -p logs
    echo -e "${BLUE}Starting ${name}...${NC}"
    # Use array for command to avoid shell injection
    "$@" > "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "logs/${name}.pid"
    echo -e "${GREEN}${name} started (PID: $pid, log: $log_file)${NC}"
}

# Start API server
run_service "api" uv run uvicorn otelms.api.main:app --host 0.0.0.0 --port 8000 --reload --log-level debug

# Start Celery Worker
run_service "worker" uv run celery -A otelms.tasks.celery_app worker --loglevel=info --concurrency=2 -Q celery,scraping

# Start Celery Beat
run_service "beat" uv run celery -A otelms.tasks.celery_app beat --loglevel=info --scheduler redbeat.RedBeatScheduler

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}All services started!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "API Server:      ${BLUE}http://localhost:8000${NC}"
echo -e "Swagger UI:      ${BLUE}http://localhost:8000/docs${NC}"
echo -e "ReDoc:           ${BLUE}http://localhost:8000/redoc${NC}"
echo -e "OpenAPI JSON:    ${BLUE}http://localhost:8000/openapi.json${NC}"
echo -e "Prometheus:      ${BLUE}http://localhost:9090/metrics${NC}"
echo ""
echo -e "PostgreSQL:      ${BLUE}localhost:5433${NC} (user: otelms, pass: otelms_dev_password, db: otelms)"
echo -e "Redis:           ${BLUE}localhost:6380${NC}"
echo ""
echo -e "Logs:            ${BLUE}./logs/${NC}"
echo -e "PIDs:            ${BLUE}./logs/*.pid${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Trap Ctrl+C to cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping services...${NC}"
    
    for pid_file in logs/*.pid; do
        if [ -f "$pid_file" ]; then
            pid=$(cat "$pid_file")
            name=$(basename "$pid_file" .pid)
            if kill -0 "$pid" 2>/dev/null; then
                echo -e "${BLUE}Stopping ${name} (PID: $pid)...${NC}"
                kill "$pid" 2>/dev/null || true
            fi
        fi
    done
    
    # Stop Docker services
    echo -e "${BLUE}Stopping PostgreSQL and Redis...${NC}"
    docker compose -f docker/docker-compose.yml down
    
    echo -e "${GREEN}All services stopped${NC}"
    exit 0
}

trap cleanup INT TERM

# Wait for background processes
wait