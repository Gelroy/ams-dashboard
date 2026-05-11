# syntax=docker/dockerfile:1.7

# ─────────────────────────────────────────────────────────────────────────
# Stage 1: build the React SPA
# ─────────────────────────────────────────────────────────────────────────
FROM node:24-alpine AS web-builder
WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build
# Produces /web/dist/ with index.html and assets/ (Vite base="/static/")

# ─────────────────────────────────────────────────────────────────────────
# Stage 2: Python runtime (API + SPA served from one container)
# ─────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg[binary] doesn't need libpq-dev, but other native deps may.
# Install minimal runtime headers in case any wheel falls back to source.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps before copying app code so layer caches.
COPY api/pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Copy app source
COPY api/ ./

# Copy the built SPA from stage 1
COPY --from=web-builder /web/dist ./web_build

# Collect static files (Django admin + SPA) into STATIC_ROOT.
# Use throwaway env values so settings load without real secrets.
ENV SECRET_KEY=build-time-throwaway \
    DATABASE_URL=postgres://x:x@localhost/x \
    DEBUG=False \
    AUTH_BYPASS=1
RUN python manage.py collectstatic --noinput

# Drop privileges
RUN groupadd --system app && useradd --system --gid app app \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default command: run the API server. Override CMD to run management
# commands (e.g. migrations, the JIRA sync workers).
CMD ["gunicorn", "ams_dashboard.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
