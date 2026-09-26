# Task Notes API

A small Flask service for creating, listing and completing text notes.
Standalone: no dependency on any other repo.

The `Dockerfile` here is **intentionally bad** — it is an eval fixture for
image-optimization tooling (old base image, no apt cleanup, single-stage
build, whole context copied before deps, runs as root, no `.dockerignore`).
Do not use it as a template for a real deployment.

## Endpoints

- `GET /health`
- `POST /notes` `{"text": str}` -> `201`
- `GET /notes`
- `POST /notes/<id>/complete`

## Run

```bash
pip install -r requirements.txt
python app.py
```

## Test

```bash
pip install -r requirements.txt pytest
pytest
```

## Docker (bloated, by design)

```bash
docker build -t e2-bloated-python-service .
docker run --rm -p 8000:8000 e2-bloated-python-service
```
