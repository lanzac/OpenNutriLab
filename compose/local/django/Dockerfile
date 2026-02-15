# =========================
# Stage 1: Base Python image
# =========================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

# Define working directory
ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# UV environment settings
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
# Install dev tools globally
# -------------------------
RUN uv pip install --system ruff djlint basedpyright

# -------------------------
# Create dev user
# -------------------------
RUN groupadd --gid 1000 dev-user \
    && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
    && echo "dev-user ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/dev-user \
    && chmod 0440 /etc/sudoers.d/dev-user

# -------------------------
# 1. System Scripts (Root actions)
# -------------------------
# Copy scripts as root to allow 'sed' and 'chmod' to work without permission errors
COPY ./compose/production/django/entrypoint /entrypoint
COPY ./compose/local/django/start /start
COPY ./compose/local/django/celery/worker/start /start-celeryworker
COPY ./compose/local/django/celery/beat/start /start-celerybeat
COPY ./compose/local/django/celery/flower/start /start-flower

# Fix line endings, set execution rights, and transfer ownership (instant operation)
RUN sed -i 's/\r$//g' /entrypoint /start /start-celeryworker /start-celerybeat /start-flower \
    && chmod +x /entrypoint /start /start-celeryworker /start-celerybeat /start-flower \
    && chown dev-user:dev-user /entrypoint /start /start-celeryworker /start-celerybeat /start-flower

# Ensure the cache directory exists and is owned by dev-user
RUN mkdir -p /home/dev-user/.cache/pre-commit && \
    chown -R dev-user:dev-user /home/dev-user/.cache

# -------------------------
# 2. Dependencies and Code (Dev-user actions)
# -------------------------
# Prepare the application folder for the non-root user
RUN chown dev-user:dev-user ${APP_HOME}

USER dev-user

# Install Python dependencies
# Running as dev-user ensures the .venv is owned by the correct user from the start
RUN --mount=type=cache,target=/home/dev-user/.cache/uv,uid=1000 \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project

# Copy project source code
# Using --chown avoids a slow recursive 'chown -R' step
COPY --chown=dev-user:dev-user . ${APP_HOME}

# -------------------------
# Environment
# -------------------------
# Ensure the virtualenv is prioritized in the PATH
ENV PATH="${APP_HOME}/.venv/bin:$PATH"

ENTRYPOINT ["/entrypoint"]
