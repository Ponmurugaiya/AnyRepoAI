# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build dependencies for compiled extensions (asyncpg, hiredis, psycopg2)
# git is required at build time by GitPython during pip install
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install all production dependencies into a venv so the runtime stage
# gets a clean, self-contained Python environment with no stray packages.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    "uvicorn[standard]==0.30.1" \
    httpx==0.27.0 \
    pydantic==2.7.4 \
    pydantic-settings==2.3.4 \
    sqlalchemy==2.0.31 \
    alembic==1.13.2 \
    asyncpg==0.29.0 \
    psycopg2-binary==2.9.9 \
    redis==5.0.7 \
    hiredis==2.3.2 \
    qdrant-client==1.10.1 \
    neo4j==5.22.0 \
    structlog==24.2.0 \
    python-json-logger==2.0.7 \
    python-ulid==2.7.0 \
    tenacity==8.4.1 \
    python-multipart==0.0.9 \
    gitpython==3.1.43 \
    celery==5.4.0 \
    flower==2.0.1


# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv"

# Runtime system libraries only — no compiler toolchain
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the complete venv (all packages + scripts like uvicorn) from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY --chown=appuser:appgroup backend/ ./backend/
COPY --chown=appuser:appgroup pyproject.toml ./

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "backend.app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
