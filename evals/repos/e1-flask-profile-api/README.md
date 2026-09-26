# Profile Normalization API

A small Flask service that normalizes and validates user profile payloads.
Standalone: no dependency on any other repo.

## Endpoints

See `contracts/v1/SPEC.md` for the full behavior contract.

- `GET /health`
- `POST /profiles/normalize`
- `POST /profiles/validate`
- `GET /profiles/<id>`

## Run

```bash
pip install -r requirements.txt
python app.py --port 5001
```

## Test

```bash
pip install -r requirements.txt pytest
pytest
```

`pytest` runs the unit tests and also shells out to `check.sh`, which boots
the service on `127.0.0.1:5001` and drives every case in `contracts/v1/cases.json`
via `run_contract.py`.

## Docker

```bash
docker build -t e1-flask-profile-api .
docker run --rm -p 5001:5001 e1-flask-profile-api
```
