FROM docker.io/node:24.6.0-bookworm-slim

# Ajuster UID/GID de l’utilisateur node existant
RUN groupmod -g 1000 node \
  && usermod -u 1000 -g 1000 node

# Ajouter sudo si besoin
RUN apt-get update && apt-get install -y sudo \
  && echo "node ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/node \
  && chmod 0440 /etc/sudoers.d/node

USER node
WORKDIR /app

COPY ./package.json /app

RUN npm install && npm cache clean --force

ENV PATH=./node_modules/.bin/:$PATH
