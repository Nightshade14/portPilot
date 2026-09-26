# Bookmark API

A small Express service for saving and listing URL bookmarks. Standalone:
no dependency on any other repo.

The `Dockerfile` here is **intentionally bad** — it is an eval fixture for
image-optimization tooling (old base image, no apt cleanup, single-stage
build, whole context copied before `npm install`, runs as root, no
`.dockerignore`). Same problem shape as the Python fixture in this eval
suite, on purpose, so a tool built against one can be reused on the other.
Do not use it as a template for a real deployment.

## Endpoints

- `GET /health`
- `POST /bookmarks` `{"url": str}` -> `201`
- `GET /bookmarks`
- `DELETE /bookmarks/:id`

## Run

```bash
npm install
npm start
```

## Test

```bash
npm install
npm test
```

## Docker (bloated, by design)

```bash
docker build -t e3-bloated-node-service .
docker run --rm -p 8080:8080 e3-bloated-node-service
```
