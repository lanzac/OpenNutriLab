export COMPOSE_FILE := "docker-compose.local.yml"

## Just does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments.
## For more information, see https://github.com/casey/just/issues/2473 .


# Default command to list all available commands.
default:
    @just --list

# build: Build python image.
build:
    @echo "Building python image..."
    @docker compose build

# rebuild: Force build from scratch (no cache)
rebuild:
    @echo "Hard rebuilding images..."
    @docker compose build --no-cache

# up: Start up containers.
up:
    @echo "Starting up containers..."
    @docker compose up -d --remove-orphans

# down: Stop containers.
down:
    @echo "Stopping containers..."
    @docker compose down

# restart: Restart containers.
restart:
    @echo "Restarting containers..."
    @docker compose restart

# prune: Remove containers and their volumes.
prune *args:
    @echo "Killing containers and removing volumes..."
    @docker compose down -v {{args}}

# logs: View container logs
logs *args:
    @docker compose logs -f {{args}}

# manage: Executes `manage.py` command.
manage +args:
    @docker compose run --rm django python ./manage.py {{args}}

# vite-shell: Open a bash shell in the opennutrilab_local_vite container.
vite-shell:
    @docker exec -it opennutrilab_local_vite bash

# vite-reset: Reset the vite container and reinstall frontend dependencies
vite-reset:
    @echo "Stopping vite container..."
    @docker compose stop vite
    @echo "Removing vite container..."
    @docker compose rm -f vite
    @echo "Rebuilding vite container..."
    @docker compose build vite
    @echo "Starting vite container..."
    @docker compose up -d vite
    @echo "vite container reset complete."



# django-shell: Open the Django shell in the opennutrilab_local_django container.
django-shell:
    @docker exec -it opennutrilab_local_django /entrypoint python manage.py shell

django-container-shell:
    @docker exec -it opennutrilab_local_django /entrypoint bash


# =============================================================================
# Production
#
# These drive docker-compose.production.yml and are meant to be run on the
# server, from a checkout of the repository. They need .envs/.production/.django,
# .envs/.production/.postgres and a .env holding DOMAIN_NAME and ACME_EMAIL.
# See docs/deployment.rst.
# =============================================================================

# prod-build: Build the production image (frontend bundle, deps, collectstatic).
prod-build:
    @echo "Building production image..."
    @COMPOSE_FILE=docker-compose.production.yml docker compose build

# prod-up: Start the production stack.
prod-up:
    @echo "Starting production stack..."
    @COMPOSE_FILE=docker-compose.production.yml docker compose up -d --remove-orphans

# prod-down: Stop the production stack.
prod-down:
    @echo "Stopping production stack..."
    @COMPOSE_FILE=docker-compose.production.yml docker compose down

# prod-logs: Follow production logs.
prod-logs *args:
    @COMPOSE_FILE=docker-compose.production.yml docker compose logs -f {{args}}

# prod-manage: Execute a `manage.py` command against production.
prod-manage +args:
    @COMPOSE_FILE=docker-compose.production.yml docker compose run --rm django python ./manage.py {{args}}

# prod-deploy: Pull, rebuild and restart. Migrations run from /start on boot.
prod-deploy:
    @git pull --ff-only
    @COMPOSE_FILE=docker-compose.production.yml docker compose build
    @COMPOSE_FILE=docker-compose.production.yml docker compose up -d --remove-orphans

# prod-backup: Dump the database into the backups volume.
prod-backup:
    @COMPOSE_FILE=docker-compose.production.yml docker compose exec postgres backup

# prod-backups: List the dumps held in the backups volume.
prod-backups:
    @COMPOSE_FILE=docker-compose.production.yml docker compose exec postgres backups
