# ============================================================
# Stage 1: Builder — install deps, build frontend, collect static
# ============================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Node.js and pnpm via npm
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pnpm

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

# Install Node dependencies and build frontend
COPY src/backend/frontend/package.json src/backend/frontend/pnpm-lock.yaml ./src/backend/frontend/
RUN cd src/backend/frontend && pnpm install --frozen-lockfile

COPY src/backend/frontend/ ./src/backend/frontend/
RUN cd src/backend/frontend && pnpm build

# Copy backend source
COPY src/backend/ ./src/backend/

# Build Tailwind CSS
RUN cd src/backend && uv run python manage.py tailwind build

# Collect static files (WhiteNoise will serve these)
ENV DJANGO_SETTINGS_MODULE=config.settings \
    SECRET_KEY=build-only-not-used-at-runtime \
    DEBUG=False \
    POSTGRES_HOST=localhost
RUN cd src/backend && uv run python manage.py collectstatic --noinput 2>/dev/null || true

# ============================================================
# Stage 2: Runtime — minimal production image
# ============================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Copy uv and virtual environment from builder
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Copy backend source with built static files
COPY --from=builder /app/src/backend /app/src/backend

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE ${PORT}

WORKDIR /app/src/backend

# ASGI (gunicorn + uvicorn worker) so the assistant's SSE streaming works under async.
CMD ["sh", "-c", "gunicorn config.asgi:application --bind 0.0.0.0:${PORT} --worker-class uvicorn.workers.UvicornWorker --workers 2 --timeout 300 --access-logfile - --error-logfile -"]
