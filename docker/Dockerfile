# Unified Dockerfile for OtelMS API + Worker (multi-target)
# Build: docker build -f docker/Dockerfile --target api -t otelms-api .
#        docker build -f docker/Dockerfile --target worker -t otelms-worker .
#
# Both targets share the base + deps + camoufox layers; only the final CMD differs.

# ============================================================
# Base: system deps + non-root user
# ============================================================
FROM python:3.12-slim-bookworm AS base

# System deps for Camoufox/Firefox (both targets need these)
# The list is superset of api/worker requirements; having them all here
# avoids "XPCOMGlueLoad error ... cannot open shared object file" at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libdbus-glib-1-2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    libxtst6 \
    libxi6 \
    libxt6 \
    libxss1 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libcairo-gobject2 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser

WORKDIR /app

# uv for fast dependency installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# ============================================================
# Deps: install Python deps (shared)
# ============================================================
FROM base AS deps

# Copy dependency files + source (src layout requires source at install time)
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install production deps (includes camoufox/playwright for both targets)
RUN uv pip install --system --no-cache . "camoufox>=0.5.4" "playwright>=1.50.0"

# ============================================================
# Camoufox: fetch Firefox binary into shared cache
# ============================================================
FROM deps AS camoufox

ENV XDG_CACHE_HOME=/usr/local/share/cache
RUN mkdir -p /usr/local/share/cache && \
    python -m camoufox fetch && \
    python -c "from camoufox.pkgman import installed_verstr; print('camoufox browser:', installed_verstr())" && \
    chown -R appuser:appuser /usr/local/share/cache

# ============================================================
# API target
# ============================================================
FROM camoufox AS api

# Alembic config & migrations for DB upgrades in container
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Logs dir
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAMOUFOX_HEADLESS=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "otelms.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================
# Worker target (Celery + redbeat)
# ============================================================
FROM camoufox AS worker

# Install redbeat (scheduler) + packaging (required by kombu.transport.redis) on top of shared deps
RUN uv pip install --system --no-cache "redbeat" "packaging"

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CAMOUFOX_HEADLESS=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

HEALTHCHECK --interval=60s --timeout=45s --start-period=45s --retries=3 \
    CMD celery -A otelms.tasks.celery_app inspect ping --timeout=10 || exit 1

# Consume default + scraping queue (task_routes sends sync_* to "scraping")
CMD ["celery", "-A", "otelms.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=2", "-Q", "celery,scraping"]

# ============================================================
# Beat target (scheduler, same image as worker)
# ============================================================
FROM worker AS beat

# No additional installs; entrypoint override in compose
# CMD provided by compose override