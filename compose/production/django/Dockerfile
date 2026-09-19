# syntax=docker/dockerfile:1

# Kept in step with compose/local/vite/Dockerfile and .github/workflows/ci.yml.
ARG NODE_VERSION=24.6.0
# Builder and runtime must share this image. The virtualenv copied between them
# hardcodes its interpreter path, so a different Python would leave it broken.
ARG PYTHON_IMAGE=ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# =========================
# Stage 1: build the frontend
# =========================
FROM docker.io/node:${NODE_VERSION}-bookworm-slim AS frontend

WORKDIR /app/frontend

# Dependencies first: this layer is reused for as long as the lockfile is
# unchanged, which is most commits.
COPY frontend/package.json frontend/package-lock.json ./
# ci rather than install: the lockfile is authoritative and a production image
# must never resolve a version the tests did not see.
RUN npm ci

COPY frontend/ ./

# frontend/vite.config.js writes outside its own directory, to
# ../opennutrilab/static/vite - so /app/opennutrilab/static/vite here. That is
# the hashed bundle plus the .vite/manifest.json django-vite reads.
RUN npm run build

# =========================
# Stage 2: resolve Python dependencies
# =========================
FROM ${PYTHON_IMAGE} AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Compilers for any dependency without a prebuilt wheel. They stay in this
# stage; only the finished virtualenv is carried over.
RUN apt-get update && apt-get install --no-install-recommends -y \
      build-essential \
      libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --no-dev drops pytest, ruff, the debug toolbar and the rest of the dev group.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# =========================
# Stage 3: runtime
# =========================
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="${APP_HOME}/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

# gettext compiles the translation catalogues; wait-for-it is what the
# entrypoint uses to hold until Postgres accepts connections.
RUN apt-get update && apt-get install --no-install-recommends -y \
      gettext \
      wait-for-it \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Running as root inside a container means a container escape starts as root.
RUN groupadd --gid 1000 django \
    && useradd --uid 1000 --gid django --home-dir ${APP_HOME} --no-create-home django

COPY --from=builder --chown=django:django /app/.venv ${APP_HOME}/.venv

# Copied as root so the line-ending fix and chmod work, then handed over.
COPY ./compose/production/django/entrypoint /entrypoint
COPY ./compose/production/django/start /start
COPY ./compose/production/django/celery/worker/start /start-celeryworker
COPY ./compose/production/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /entrypoint /start /start-celeryworker /start-celerybeat \
    && chmod +x /entrypoint /start /start-celeryworker /start-celerybeat \
    && chown django:django /entrypoint /start /start-celeryworker /start-celerybeat

COPY --chown=django:django . ${APP_HOME}

# .dockerignore keeps the local build out of the context, so this is the only
# bundle in the image.
COPY --from=frontend --chown=django:django /app/opennutrilab/static/vite ${APP_HOME}/opennutrilab/static/vite

# Docker creates a missing mount target as root:root, which would leave the
# media volume unwritable for the django user. Same trap as the named volumes
# in compose/local/django/Dockerfile.
RUN mkdir -p ${APP_HOME}/opennutrilab/media ${APP_HOME}/staticfiles \
    && chown -R django:django ${APP_HOME}/opennutrilab/media ${APP_HOME}/staticfiles

USER django

# Importing the production settings requires these three. They exist for the
# length of this layer only and are never part of the image environment: the
# real values arrive from docker compose at run time. Neither command touches
# the database - collectstatic reads the Vite manifest and writes hashed,
# pre-compressed copies under staticfiles/, which is what WhiteNoise serves.
RUN DATABASE_URL="postgres://build:build@localhost:5432/build" \
    DJANGO_SECRET_KEY="build-time-only-never-used-to-sign-anything" \
    DJANGO_ALLOWED_HOSTS="localhost" \
    sh -c "python manage.py compilemessages && python manage.py collectstatic --noinput"

ENTRYPOINT ["/entrypoint"]
CMD ["/start"]
