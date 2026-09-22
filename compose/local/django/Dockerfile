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
      # to fetch the act release below (and generally useful in the container)
      curl ca-certificates \
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
# Install act (nektos/act)
# -------------------------
# Runs the workflows in .github/workflows/ locally, against the host's Docker
# daemon (docker-compose.local.yml bind-mounts /var/run/docker.sock into this
# service). Pinned version + checksum, verified against the release's
# checksums.txt, rather than piping the project's install script into bash.
ARG ACT_VERSION=0.2.89
RUN ARCH="$(dpkg --print-architecture)" \
    && case "${ARCH}" in \
         amd64) ACT_ARCHIVE=act_Linux_x86_64.tar.gz \
                ACT_SHA256=0191d6f1f3b716b5c55820032605d05fc3c1cdbf581ebeff655019e5dd1524c0 ;; \
         arm64) ACT_ARCHIVE=act_Linux_arm64.tar.gz \
                ACT_SHA256=daa8679ba9615a74d2d0cec321dc593f21948a2a11bb65862b063d8b930f4bcb ;; \
         *) echo "Unsupported architecture for act: ${ARCH}" >&2 && exit 1 ;; \
       esac \
    && curl -fsSLo /tmp/act.tar.gz "https://github.com/nektos/act/releases/download/v${ACT_VERSION}/${ACT_ARCHIVE}" \
    && echo "${ACT_SHA256}  /tmp/act.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/act.tar.gz -C /usr/local/bin act \
    && rm /tmp/act.tar.gz

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

# Ensure the directories backed by named volumes exist and are owned by dev-user.
# Docker creates a missing mount target as root:root, which would leave them
# unwritable for dev-user (Claude Code could then not store its credentials).
RUN mkdir -p /home/dev-user/.cache/pre-commit /home/dev-user/.cache/ms-playwright /home/dev-user/.claude && \
    chown -R dev-user:dev-user /home/dev-user/.cache /home/dev-user/.claude

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
