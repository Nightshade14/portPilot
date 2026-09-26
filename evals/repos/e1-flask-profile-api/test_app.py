import subprocess
import sys
from pathlib import Path

from app import app


def test_health():
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_normalize_happy_path():
    client = app.test_client()
    resp = client.post(
        "/profiles/normalize",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "age": 36,
            "country": "GB",
            "newsletter": True,
            "tags": ["math"],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json() == {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "age": 36,
        "country": "GB",
        "newsletter": True,
        "tags": ["math"],
    }


def test_normalize_defaults_and_coercion():
    client = app.test_client()
    resp = client.post(
        "/profiles/normalize",
        json={"name": "Grace Hopper", "email": "grace@example.com", "age": "4.5"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["age"] == 4
    assert body["country"] == "US"
    assert body["newsletter"] is False
    assert body["tags"] == []


def test_normalize_rejects_invalid_payload():
    client = app.test_client()
    resp = client.post("/profiles/normalize", json={"email": "ada@example.com", "age": -3})
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    fields = [d["field"] for d in body["error"]["details"]]
    assert fields == sorted(
        fields, key=["name", "email", "age", "country", "newsletter", "tags"].index
    )


def test_validate_uses_error_body_not_valid_false():
    client = app.test_client()
    resp = client.post("/profiles/validate", json={"name": "Ada", "age": 30})
    assert resp.status_code == 422
    assert "valid" not in resp.get_json()


def test_get_profile_found_and_not_found():
    client = app.test_client()
    ok = client.get("/profiles/p_001")
    assert ok.status_code == 200
    assert ok.get_json()["email"] == "ada@example.com"

    missing = client.get("/profiles/p_999")
    assert missing.status_code == 404
    assert missing.get_json()["error"]["code"] == "NOT_FOUND"


def test_check_sh_runner_passes_all_cases():
    """End-to-end: check.sh boots the real service and drives every contract case."""
    repo_root = Path(__file__).parent
    result = subprocess.run(
        ["bash", "check.sh"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    sys.exit(0)
