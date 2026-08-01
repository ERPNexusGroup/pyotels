# Architecture Decision Records (ADR)

This document records significant architectural decisions for the OtelMS API project.

---

## ADR-001: Use Camoufox over Playwright/Chrome for Scraping

**Status**: Accepted
**Date**: 2026-01-31

### Context
OtelMS employs bot detection (Cloudflare, fingerprinting). Standard Playwright with Chromium is easily detected.

### Decision
Use **Camoufox** (Firefox-based anti-detect browser) instead of raw Playwright.

### Consequences
- **Pros**: Real Firefox fingerprints, automatic randomization, uBlock Origin built-in, undetected by most WAFs
- **Cons**: Larger Docker image (~500MB Firefox binary), requires `camoufox fetch` at build time, async API only
- **Mitigation**: Multi-stage Docker build, browser pool reuses instances

---

## ADR-002: Hybrid Login Strategy (requests + Playwright)

**Status**: Accepted
**Date**: 2026-01-31

### Context
OtelMS login uses standard form POST. Doing full browser navigation for login is slow and fragile.

### Decision
Use `httpx`/`requests` for the initial POST login, then sync cookies to Playwright/Camoufox context.

### Consequences
- **Pros**: Faster login (~2s vs ~10s), simpler error handling for credentials, retries at HTTP level
- **Cons**: Must maintain cookie sync, CSRF tokens if added later
- **Mitigation**: `OtelMSAuth` class encapsulates this logic, auto-relogin on session expiry

---

## ADR-003: Token Bucket Rate Limiting in Redis

**Status**: Accepted
**Date**: 2026-01-31

### Context
Need distributed rate limiting across multiple workers/containers. Per-hotel limits to avoid IP bans.

### Decision
Implement Token Bucket algorithm using Redis with Lua scripts for atomic operations.

### Consequences
- **Pros**: Truly distributed, burst handling, per-hotel isolation, minimal latency
- **Cons**: Redis dependency, Lua script complexity
- **Mitigation**: Fallback to local diskcache if Redis unavailable (dev only)

---

## ADR-004: SQLAlchemy 2.x Async + Alembic for Persistence

**Status**: Accepted
**Date**: 2026-01-31

### Context
Need robust relational storage with migrations. Previous version used only JSON files.

### Decision
Use SQLAlchemy 2.0 async ORM with Alembic for migrations. Declarative models with proper indexes.

### Consequences
- **Pros**: Type-safe queries, migration versioning, connection pooling, relationship loading
- **Cons**: Learning curve for 2.0 async patterns, more boilerplate
- **Mitigation**: BaseRepository pattern encapsulates common CRUD

---

## ADR-005: Separate Domain Models (API vs DB)

**Status**: Accepted
**Date**: 2026-01-31

### Context
API contracts (Pydantic) and DB models (SQLAlchemy) have different concerns.

### Decision
Maintain separate model hierarchies:
- `domain/models/` - Pydantic v2 for API requests/responses
- `domain/entities/` - SQLAlchemy for database

### Consequences
- **Pros**: API can evolve independently, DB optimizations don't leak to API, clear serialization boundaries
- **Cons**: Mapping overhead between layers
- **Mitigation**: Repository layer handles conversion, `model_dump()` / `**entity.__dict__`

---

## ADR-006: Celery for Background Jobs (not FastAPI BackgroundTasks)

**Status**: Accepted
**Date**: 2026-01-31

### Context
Scraping operations take 30s-5min. FastAPI BackgroundTasks don't survive restarts, no retry, no scheduling.

### Decision
Use Celery with Redis broker for all scraping/sync tasks. Celery Beat for periodic tasks.

### Consequences
- **Pros**: Persistent queue, retries with backoff, scheduling, scaling workers independently, monitoring (Flower)
- **Cons**: Additional infrastructure (Redis, workers), more complex deployment
- **Mitigation**: Docker Compose includes all services, health checks

---

## ADR-007: Browser Pool with Camoufox

**Status**: Accepted
**Date**: 2026-01-31

### Context
Launching Firefox for each request is prohibitively slow (~5-10s per launch).

### Decision
Maintain a pool of persistent Camoufox browser contexts. Acquire/release pages from pool.

### Consequences
- **Pros**: Sub-second page acquisition, connection reuse, automatic cleanup of idle instances
- **Cons**: Memory usage, session state management, crash recovery
- **Mitigation**: Health checks, max idle timeout, max pool size config, graceful shutdown

---

## ADR-008: Structured JSON Logging + Prometheus Metrics

**Status**: Accepted
**Date**: 2026-01-31

### Context
Need production observability: debugging, alerting, dashboards.

### Decision
Use `structlog` for JSON logs with correlation IDs. Prometheus client for metrics exposition.

### Consequences
- **Pros**: Queryable logs, standard metrics format, OpenTelemetry ready
- **Cons**: Verbose local dev logs
- **Mitigation**: Console pretty printer for dev, JSON for prod, log level config

---

## ADR-009: API Key Authentication (Simple, Effective)

**Status**: Accepted
**Date**: 2026-01-31

### Context
Need to protect the unofficial API. OAuth2/JWT adds complexity for internal tooling.

### Decision
Single API Key header (`X-API-Key`) with SHA-256 hashed storage in DB. Rate limiting per key.

### Consequences
- **Pros**: Simple for clients, revocable, auditable, no token refresh logic
- **Cons**: No user context, no scopes/permissions
- **Mitigation**: Extensible to JWT later, `ApiKey` entity supports expiration

---

## ADR-010: Multi-stage Docker Builds with uv

**Status**: Accepted
**Date**: 2026-01-31

### Context
Fast, reproducible builds. Camoufox binary is large.

### Decision
Use `uv` for dependency resolution. Separate `Dockerfile.api` (lightweight) and `Dockerfile.worker` (with Camoufox).

### Consequences
- **Pros**: Layer caching, minimal API image, `uv` is 10-100x faster than pip
- **Cons**: Two Dockerfiles to maintain
- **Mitigation**: Shared base stage where possible, `.dockerignore` optimized

---

## ADR-011: Testcontainers for Integration Tests

**Status**: Accepted
**Date**: 2026-01-31

### Context
Integration tests need real PostgreSQL/Redis. Mocking misses real behavior.

### Decision
Use `testcontainers-python` in CI for ephemeral DB/Redis. SQLite for unit tests.

### Consequences
- **Pros**: Realistic tests, no shared test DB conflicts, parallel CI runs
- **Cons**: Slower tests, Docker-in-Docker in CI
- **Mitigation**: Unit tests default to SQLite, integration tests opt-in

---

## ADR-012: Configuration via Pydantic-Settings + .env

**Status**: Accepted
**Date**: 2026-01-31

### Context
80+ configuration options across scraping, API, DB, Celery, logging.

### Decision
Centralized `Settings` class with `pydantic-settings`. All config via `.env` with `.env.example` template.

### Consequences
- **Pros**: Type validation, IDE autocomplete, environment-specific overrides, documentation in code
- **Cons**: All settings loaded at startup
- **Mitigation**: `@lru_cache` on `get_settings()`, env-specific `.env` files

---

## ADR-013: OpenTelemetry for Distributed Tracing

**Status**: Accepted (Optional)
**Date**: 2026-01-31

### Context
Need end-to-end visibility across API → Celery → Scraping → DB.

### Decision
Instrument with OpenTelemetry SDK. Export to OTLP (Grafana Tempo, Jaeger) or Prometheus.

### Consequences
- **Pros**: Full request traces, bottleneck identification, SLO monitoring
- **Cons**: Overhead, additional exporter config
- **Mitigation**: Feature-flagged (`OTEL_ENABLED`), console exporter for dev

---

## ADR-014: Repository Pattern for Data Access

**Status**: Accepted
**Date**: 2026-01-31

### Context
Direct SQLAlchemy usage in services creates tight coupling, hard to test.

### Decision
`BaseRepository` with generic CRUD + specific repositories per entity with domain methods.

### Consequences
- **Pros**: Testable (mock repo), consistent API, encapsulates query logic, upsert patterns
- **Cons**: Boilerplate for simple entities
- **Mitigation**: Generic `BaseRepository` covers 80% cases

---

## ADR-015: SyncService Orchestrates Scraping → Persistence

**Status**: Accepted
**Date**: 2026-01-31

### Context
Scraping and persistence are separate concerns but must be coordinated atomically.

### Decision
`SyncService` calls `ScrapingOrchestrator`, then persists via repositories. Logs each sync to `SyncLog`.

### Consequences
- **Pros**: Clear separation, testable independently, audit trail, idempotent upserts
- **Cons**: Two-phase (scrape then persist) - partial failure handling
- **Mitigation**: Transaction per sync type, hash-based change detection

---

*End of Architecture Decision Records*