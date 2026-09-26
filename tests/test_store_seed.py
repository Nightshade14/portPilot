"""Tests for store/seed.py seed_policy. Owner: Lane B."""

from __future__ import annotations

from pathlib import Path

from portpilot.store.memory import InMemoryStore
from portpilot.store.seed import seed_policy

POLICY_MD = """\
# flask-to-hono migration policy

Some preamble prose that is not a rule.

## Rules

- Preserve HTTP status codes exactly.
- Return validation failures as 422 with a nested error schema.
- Coerce numeric strings before validating.

## Notes

- This bullet is under Notes and must be ignored.
"""


def _write_policy(tmp_path: Path) -> Path:
    path = tmp_path / "policy.md"
    path.write_text(POLICY_MD, encoding="utf-8")
    return path


def test_seed_policy_installs_active_policy_with_parsed_rules(tmp_path: Path) -> None:
    store = InMemoryStore()
    path = _write_policy(tmp_path)

    policy = seed_policy(store, path)

    assert policy.name == "flask-to-hono"
    assert policy.version == 1
    assert policy.status == "active"
    assert policy.body == POLICY_MD
    assert policy.rules == [
        "Preserve HTTP status codes exactly.",
        "Return validation failures as 422 with a nested error schema.",
        "Coerce numeric strings before validating.",
    ]
    assert store.get_policy("flask-to-hono").version == 1


def test_seed_policy_is_idempotent(tmp_path: Path) -> None:
    store = InMemoryStore()
    path = _write_policy(tmp_path)

    first = seed_policy(store, path)
    # Change the file on disk; a second seed must NOT overwrite the stored one.
    path.write_text("# changed\n\n## Rules\n\n- different rule\n", encoding="utf-8")
    second = seed_policy(store, path)

    assert first == second
    assert second.body == POLICY_MD
    assert len(store.list_policies("flask-to-hono")) == 1


def test_seed_policy_respects_custom_name_and_version(tmp_path: Path) -> None:
    store = InMemoryStore()
    path = _write_policy(tmp_path)

    policy = seed_policy(store, path, name="other", version=3)

    assert policy.name == "other"
    assert policy.version == 3
    assert store.get_policy("other", 3).status == "active"
