# Deliberately bad: full node:18 image, no apt cleanup, single-stage build,
# whole context copied before `npm install`, runs as root, no
# .dockerignore. Same problem shape as the Python fixture, on purpose —
# it is the tool-reuse target for image-optimization tooling.
FROM node:18

RUN apt-get update && apt-get install -y curl git vim build-essential

COPY . /app
WORKDIR /app

RUN npm install

EXPOSE 8080
CMD ["node", "server.js"]
