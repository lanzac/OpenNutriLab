FROM docker.io/node:24.6.0-bookworm-slim

# Ajuster UID/GID de l’utilisateur node existant
RUN groupmod -g 1000 node \
  && usermod -u 1000 -g 1000 node

USER node
WORKDIR /app

COPY ./frontend/package.json ./frontend/package-lock.json /app/

# ci rather than install: the lockfile is authoritative, and the image
# should not silently drift from what the compose service installs.
RUN npm ci && npm cache clean --force

ENV PATH=./node_modules/.bin/:$PATH
