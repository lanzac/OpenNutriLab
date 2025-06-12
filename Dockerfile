# Dockerfile simplifié pour Django + PostgreSQL
FROM python:3.13-slim

WORKDIR /app

# Installer les dépendances système nécessaires à psycopg
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de dépendances et installer les dépendances Python
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --no-root

# Copier le reste du projet
COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]