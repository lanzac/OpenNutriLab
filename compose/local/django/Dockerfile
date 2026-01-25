# =========================
# Stage 1: Base Python image
# =========================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

# =========================
# Stage 2: Build dependencies
# =========================
FROM base AS builder

# Define working directory
ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# UV environment settings for build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# -------------------------
# Install system dependencies
# -------------------------
RUN apt-get update && apt-get install --no-install-recommends -y \
      # build tools for Python packages
      build-essential \
      # PostgreSQL client headers
      libpq-dev \
      # for i18n, required by Django
      gettext \
      # for waiting for other services
      wait-for-it \
      sudo git bash-completion nano ssh locales \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -------------------------
# Install Python dependencies (cacheable)
# -------------------------
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-editable

# -------------------------
# Copy project source and install project
# -------------------------
COPY . ${APP_HOME}
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# -------------------------
# Create dev user for non-root execution
# -------------------------
RUN groupadd --gid 1000 dev-user \
    && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
    && echo "dev-user ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/dev-user \
    && chmod 0440 /etc/sudoers.d/dev-user

# -------------------------
# Prepare entrypoints
# -------------------------
COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint && chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r$//g' /start && chmod +x /start

COPY ./compose/local/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker && chmod +x /start-celeryworker

COPY ./compose/local/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat && chmod +x /start-celerybeat

COPY ./compose/local/django/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower && chmod +x /start-flower

# -------------------------
# Environment paths
# -------------------------
ENV PATH="${APP_HOME}/.venv/bin:$PATH"
ENV PYTHONPATH="${APP_HOME}/.venv/lib/python3.13/site-packages:$PYTHONPATH"

# -------------------------
# Entrypoint
# -------------------------
ENTRYPOINT ["/entrypoint"]
