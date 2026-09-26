"""Small task-notes API: create, list and complete short text notes.

In-memory store; standalone service with no dependency on any other repo.
"""

from __future__ import annotations

import itertools
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

NOTES: dict[int, dict] = {}
_id_counter = itertools.count(1)


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/notes")
def create_note():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        return jsonify({"error": "text (string) is required"}), 400
    text = payload["text"].strip()
    if not text:
        return jsonify({"error": "text must not be empty"}), 400
    note_id = next(_id_counter)
    note = {"id": note_id, "text": text, "done": False, "created_at": time.time()}
    NOTES[note_id] = note
    return jsonify(note), 201


@app.get("/notes")
def list_notes():
    return jsonify({"notes": list(NOTES.values())})


@app.post("/notes/<int:note_id>/complete")
def complete_note(note_id: int):
    note = NOTES.get(note_id)
    if note is None:
        return jsonify({"error": "not found"}), 404
    note["done"] = True
    return jsonify(note)


def main() -> None:
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
