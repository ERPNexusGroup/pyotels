# OtelMS API - Unofficial API for OtelMS

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-green)](https://fastapi.tiangolo.com)
[![Camoufox](https://img.shields.io/badge/Camoufox-0.5%2B-orange)](https://github.com/daijro/camoufox)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red)](https://sqlalchemy.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> **⚠️ Disclaimer**: This is an unofficial API for OtelMS. Use responsibly and only with explicit authorization from the hotel/property owner. Scraping may violate terms of service. The authors are not responsible for any misuse.

---

## 🎯 Overview

OtelMS API provides a robust, production-ready solution for extracting hotel reservation data from the OtelMS platform and exposing it via a clean REST API. Built with modern Python async architecture, it handles anti-bot protection, rate limiting, and data persistence automatically.

### Key Features

- 🕷️ **Anti-detect Scraping** - Camoufox (Firefox-based) with fingerprint randomization
- ⚡ **Async Architecture** - Full async/await with FastAPI, SQLAlchemy 2.x, Playwright
- 🛡️ **Rate Limiting** - Distributed token bucket (Redis) per hotel
- 🔄 **Auto-retry & Recovery** - Tenacity policies, session management, auto-relogin
- 🗄️ **Persistence** - PostgreSQL/SQLite with SQLAlchemy + Alembic migrations
- 📊 **Observability** - Structured logging (structlog), Prometheus metrics, OpenTelemetry tracing
- ⏰ **Background Jobs** - Celery + Redis for scheduled sync (calendar, categories, details)
- 🔐 **API Security** - API Key authentication with rate limiting
- 🐳 **Containerized** - Multi-stage Docker builds, docker-compose for full stack

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FastAPI       │     │   Celery        │     │   Camoufox      │
│   REST API      │────▶│   Workers       │────▶│   Browser Pool  │
│   (Port 8000)   │     │   (Beat +       │     │   (Anti-detect) │
└─────────────────┘     │    Workers)     │     └────────┬────────┘
        │               └────────┬────────┘              │
        │                        │                       ▼
        ▼                        ▼              ┌─────────────────┐
┌─────────────────┐     ┌─────────────────┐     │   OtelMS        │
│   PostgreSQL    │◀───▶│   Redis         │     │   Platform      │
│   (Primary DB)  │     │   (Cache +      │     │   (Target)      │
└─────────────────┘     │    Queue)       │     └─────────────────┘
                        └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (recommended)
- Or: PostgreSQL 16+, Redis 7+, uv package manager

### Option 1: Docker Compose (Recommended)

```bash
# Clone and configure
git clone <repo>
cd scraping_otelms_api
cp .env.example .env
# Edit .env with your credentials

# Start all services
docker compose -f docker/docker-compose.yml up -d

# Verify
curl http://localhost:8000/health
# {"status":"healthy","checks":{"database":true,"cache":true},"version":"1.0.0"}
```

### Option 2: Local Development

```bash
# Install dependencies
uv sync --all-extras

# Setup database
cp .env.example .env
# Edit .env with DATABASE_URL=sqlite+aiosqlite:///./otelms.db (for quick start)

# Initialize DB
otelms db init
otelms db seed

# Run API server
otelms api --reload

# Run worker (in separate terminal)
otelms worker

# Run scheduler (in separate terminal)
otelms beat
```

---

## 📖 API Documentation

Once running, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

### Authentication

All endpoints require API Key in header:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/hotels
```

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/health/ready` | GET | Kubernetes readiness |
| `/health/live` | GET | Kubernetes liveness |
| `/metrics` | GET | Prometheus metrics |
| `/hotels` | GET | List hotels |
| `/hotels` | POST | Create hotel |
| `/hotels/{id}` | GET | Get hotel |
| `/hotels/{id}` | PATCH | Update hotel |
| `/reservations` | GET | List reservations (paginated) |
| `/reservations/{id}` | GET | Get reservation with details |
| `/reservations/today/checkins` | GET | Today's check-ins |
| `/reservations/today/checkouts` | GET | Today's check-outs |
| `/reservations/sync/calendar` | POST | Trigger calendar sync |
| `/reservations/sync/categories` | POST | Trigger categories sync |
| `/reservations/sync/full` | POST | Trigger full sync |
| `/reservations/sync/history` | GET | Sync history |
| `/guests` | GET | List guests (searchable) |
| `/guests/{id}` | GET | Get guest |
| `/guests` | POST | Create guest |
| `/categories` | GET | List categories with rooms |

### Query Parameters

```bash
# Reservations with filters
GET /reservations?hotel_id=118510&status=1&check_in_from=2026-01-01&page=1&page_size=50

# Guests with search
GET /guests?hotel_id=118510&search=John&limit=100
```

---

## 🔧 Configuration

All configuration via environment variables (`.env`):

```bash
# App
APP_ENV=production          # development|staging|production
APP_DEBUG=false
APP_HOST=0.0.0.0
APP_PORT=8000

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/otelms

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# OtelMS Credentials
OTELMS_DEFAULT_HOTEL_ID=118510
OTELMS_DEFAULT_USERNAME=gerencia@harmonyhotelgroup.com
OTELMS_DEFAULT_PASSWORD=your_password

# Scraping
SCRAPER_HEADLESS=true
SCRAPER_RATE_LIMIT_REQUESTS_PER_MINUTE=30
SCRAPER_RATE_LIMIT_BURST=5
BROWSER_POOL_SIZE=2

# Security
API_KEY=your-secure-api-key-here
JWT_SECRET_KEY=your-jwt-secret-min-32-chars
```

See `.env.example` for all 80+ options.

---

## 🧪 Testing

```bash
# Run all tests
python scripts/run_tests.py

# Or individually
uv run pytest tests/unit -v              # Unit tests
uv run pytest tests/integration -v       # Integration tests
uv run pytest tests/unit --cov=src/otelms # With coverage

# Linting
uv run ruff check .
uv run ruff format --check .
uv run mypy src/otelms
```

### Test Structure

```
tests/
├── unit/                    # Fast, isolated tests
│   ├── test_parsers.py      # HTML parser tests
│   └── test_repositories.py # Repository CRUD tests
├── integration/             # DB/Redis required
│   ├── test_sync_service.py # Sync service tests
│   └── test_api_contracts.py # API contract tests
└── conftest.py              # Pytest fixtures
```

---

## 📦 Project Structure

```
scraping_otelms_api/
├── .github/workflows/       # CI/CD
├── docker/                  # Docker files
│   ├── Dockerfile.api       # API image
│   ├── Dockerfile.worker    # Worker image (with Camoufox)
│   └── docker-compose.yml   # Full stack
├── migrations/              # Alembic migrations
├── scripts/                 # Utility scripts
├── src/otelms/
│   ├── api/                 # FastAPI layer
│   │   ├── main.py          # App factory
│   │   ├── dependencies.py  # DI container
│   │   ├── schemas.py       # Pydantic models
│   │   └── routes/          # API endpoints
│   ├── config/              # Settings & constants
│   ├── domain/              # Domain layer
│   │   ├── models/          # API contracts (Pydantic)
│   │   ├── entities/        # DB models (SQLAlchemy)
│   │   └── repositories/    # Data access
│   ├── scraping/            # Scraping engine
│   │   ├── browser.py       # Camoufox pool
│   │   ├── auth.py          # Login & session
│   │   ├── rate_limiter.py  # Token bucket
│   │   ├── retry.py         # Retry policies
│   │   ├── extractors/      # Page extractors
│   │   ├── parsers/         # HTML parsers
│   │   └── orchestrator.py  # Main pipeline
│   ├── services/            # Business logic
│   │   └── sync_service.py  # Scraping → DB sync
│   ├── tasks/               # Celery tasks
│   │   ├── celery_app.py    # Celery config
│   │   └── scraping_tasks.py # Scheduled tasks
│   └── utils/               # Shared utilities
│       ├── logging.py       # Structlog setup
│       ├── cache.py         # Redis/diskcache
│       └── telemetry.py     # OpenTelemetry
├── tests/                   # Test suite
├── pyproject.toml           # Project config
├── alembic.ini              # Migrations config
└── .env.example             # Env template
```

---

## 🔄 Sync Operations

### Automatic (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| `sync_calendar` | Every 15 min | Calendar grid sync |
| `sync_categories` | Hourly | Categories & rooms |
| `sync_full` | Daily 3 AM | Complete sync |

### Manual via API

```bash
# Calendar sync
curl -X POST -H "X-API-Key: $KEY" \
  "http://localhost:8000/reservations/sync/calendar?hotel_id=118510&target_date=2026-01-15"

# Full sync
curl -X POST -H "X-API-Key: $KEY" \
  "http://localhost:8000/reservations/sync/full?hotel_id=118510"
```

### CLI

```bash
# One-off sync
otelms sync --hotel-id 118510 --full

# Scraping only (no DB)
otelms scraper --hotel-id 118510 --strategy calendar --date 2026-01-15
```

---

## 📊 Monitoring

### Prometheus Metrics

```
GET /metrics
```

Key metrics:
- `otelms_http_requests_total` - Request count by endpoint/status
- `otelms_http_request_duration_seconds` - Latency histogram
- `otelms_scraping_operations_total` - Scraping ops by type/status
- `otelms_scraping_duration_seconds` - Scraping latency
- `otelms_sync_records_processed_total` - Records created/updated
- `otelms_celery_tasks_total` - Background task stats
- `otelms_active_browsers` - Browser pool usage

### Structured Logs

```json
{
  "timestamp": "2026-01-15T10:30:00.123Z",
  "level": "INFO",
  "logger": "otelms.scraping.orchestrator",
  "message": "Calendar scraping completed",
  "hotel_id": "118510",
  "operation": "calendar",
  "duration_ms": 2341,
  "records_processed": 45
}
```

### Health Checks

```bash
# Liveness (process alive)
curl http://localhost:8000/health/live

# Readiness (dependencies ready)
curl http://localhost:8000/health/ready

# Full health
curl http://localhost:8000/health
```

---

## 🐳 Deployment

### Production Docker Compose

```bash
# Production profile with Nginx
docker compose -f docker/docker-compose.yml --profile production up -d

# Scale workers
docker compose up -d --scale worker=3
```

### Kubernetes (Helm values example)

```yaml
replicaCount: 2
image:
  repository: otelms-api
  tag: latest
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: otelms-secrets
        key: database-url
  - name: REDIS_URL
    value: "redis://redis:6379/0"
resources:
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

---

## 🔐 Security Considerations

- **API Keys**: Rotate regularly, use strong random values (32+ chars)
- **JWT Secret**: Minimum 32 characters, store in secret manager
- **Database**: Use SSL connections, restrict network access
- **Redis**: Enable authentication, use TLS in production
- **Rate Limiting**: Configure per your infrastructure capacity
- **Credentials**: Never commit `.env` - use secret management
- **Scraping**: Only run against authorized properties

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`python scripts/run_tests.py`)
4. Commit changes (`git commit -m 'Add amazing feature'`)
5. Push to branch (`git push origin feature/amazing-feature`)
6. Open Pull Request

### Code Style

- **Ruff** for linting/formatting (`ruff check . && ruff format .`)
- **MyPy** for type checking (`mypy src/otelms`)
- **Pre-commit** hooks configured

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## ⚠️ Legal Disclaimer

This software is provided for educational and authorized use only. The authors:

- **Do not endorse** scraping without explicit permission
- **Are not responsible** for any legal consequences of misuse
- **Recommend** reviewing OtelMS Terms of Service before use
- **Advise** obtaining written authorization from property owners

Use responsibly and ethically.

---

## 🙏 Acknowledgments

- [Camoufox](https://github.com/daijro/camoufox) - Anti-detect browser
- [FastAPI](https://fastapi.tiangolo.com) - Modern web framework
- [SQLAlchemy](https://sqlalchemy.org) - Database toolkit
- [Celery](https://docs.celeryq.dev) - Distributed task queue
- [Playwright](https://playwright.dev) - Browser automation
- [structlog](https://www.structlog.org) - Structured logging

---

**Built with ❤️ for Harmony Hotel Group**