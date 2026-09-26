"""Shared pytest fixtures for Lane E: a demo-fixture loader and a read-only
FakeStore backed by a demo JSON file.

Exposed as fixtures (``load_demo``, ``fake_store``) so test modules need no
cross-module import. ``FakeStore`` implements exactly the Store protocol
methods the CLI exercises; datetime strings are parsed to timezone-aware
datetimes so views render timestamps the same way they will against a real
store.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from portpilot.models import Policy
from portpilot.store.base import NotFound

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "demo"


def _parse_dt(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _hydrate_dates(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: (_parse_dt(v) if k in {"created_at", "updated_at", "ts"} else _hydrate_dates(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_hydrate_dates(v) for v in obj]
    return obj


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    return _hydrate_dates(json.loads(path.read_text()))


class FakeStore:
    """A read-only, in-memory Store loaded from a demo fixture.

    Implements only the methods the CLI calls; anything else is absent, so an
    accidental new dependency shows up as an AttributeError in tests.
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self._run = fixture["run"]
        self._milestones = [tuple(m) for m in fixture.get("milestones", [])]
        self._artifacts = list(fixture.get("artifacts", []))
        self._events = list(fixture.get("events", []))
        self._policies = [Policy.from_doc(p) for p in fixture.get("policies", [])]

    def get_run(self, run_id: str) -> dict[str, Any]:
        if run_id != self._run["run_id"]:
            raise NotFound(run_id)
        return dict(self._run)

    def completed_milestones(self, run_id: str) -> list[tuple[str, int]]:
        if run_id != self._run["run_id"]:
            raise NotFound(run_id)
        return list(self._milestones)

    def artifacts(
        self, run_id: str, kind: str | None = None, attempt: int | None = None
    ) -> list[dict[str, Any]]:
        if run_id != self._run["run_id"]:
            raise NotFound(run_id)
        out = [a for a in self._artifacts if kind is None or a["kind"] == kind]
        if attempt is not None:
            out = [a for a in out if a["attempt"] == attempt]
        return out

    def list_policies(self, name: str) -> list[Policy]:
        return [p for p in self._policies if p.name == name]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        if run_id != self._run["run_id"]:
            raise NotFound(run_id)
        return list(self._events)


@pytest.fixture
def load_demo():
    """Return a callable ``load_demo(name) -> dict`` for a demo fixture."""
    return _load_fixture


@pytest.fixture
def make_fake_store():
    """Return a factory ``make_fake_store(name) -> FakeStore`` from a fixture."""
    return lambda name: FakeStore(_load_fixture(name))
