import pytest
from app import NOTES, app


@pytest.fixture(autouse=True)
def _clear_notes():
    NOTES.clear()
    yield
    NOTES.clear()


def test_health():
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_create_and_list_note():
    client = app.test_client()
    created = client.post("/notes", json={"text": "buy milk"})
    assert created.status_code == 201
    body = created.get_json()
    assert body["text"] == "buy milk"
    assert body["done"] is False

    listed = client.get("/notes")
    assert listed.status_code == 200
    assert len(listed.get_json()["notes"]) == 1


def test_create_note_rejects_empty_text():
    client = app.test_client()
    resp = client.post("/notes", json={"text": "   "})
    assert resp.status_code == 400


def test_complete_note():
    client = app.test_client()
    created = client.post("/notes", json={"text": "walk dog"}).get_json()
    resp = client.post(f"/notes/{created['id']}/complete")
    assert resp.status_code == 200
    assert resp.get_json()["done"] is True


def test_complete_missing_note_returns_404():
    client = app.test_client()
    resp = client.post("/notes/9999/complete")
    assert resp.status_code == 404
