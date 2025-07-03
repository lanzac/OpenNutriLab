# Variables
DC=docker compose
WEB=$(DC) run --rm web

# 🔹 Docker Compose
up:
	$(DC) up --build

up-detached:
	$(DC) up -d

down:
	$(DC) down

restart:
	$(DC) down && $(DC) up

# 🔹 Django Management
migrate:
	$(WEB) python manage.py migrate

makemigrations:
	$(WEB) python manage.py makemigrations

createsuperuser:
	$(WEB) python manage.py createsuperuser

shell:
	$(WEB) python manage.py shell

dbshell:
	$(WEB) python manage.py dbshell

check:
	$(WEB) python manage.py check

collectstatic:
	$(WEB) python manage.py collectstatic --noinput

# 🔹 Tests
test:
	$(WEB) python manage.py test

# 🔹 Custom Nutrient Init
init_nutrients:
	$(WEB) python manage.py init_nutrients

load_nutrients:
	$(WEB) python manage.py load_nutrients
