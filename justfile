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

# node-shell: Open a bash shell in the opennutrilab_local_node container.
node-shell:
    @docker exec -it opennutrilab_local_node bash

# node-reset: Reset node container and rebuild assets
node-reset:
    @echo "Stopping node container..."
    @docker compose stop node
    @echo "Removing node container..."
    @docker compose rm -f node
    @echo "Rebuilding node container..."
    @docker compose build node
    @echo "Starting node container..."
    @docker compose up -d node
    @echo "node container reset complete."



# django-shell: Open the Django shell in the opennutrilab_local_django container.
django-shell:
    @docker exec -it opennutrilab_local_django /entrypoint python manage.py shell

django-container-shell:
    @docker exec -it opennutrilab_local_django /entrypoint bash
