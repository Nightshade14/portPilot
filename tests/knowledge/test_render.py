"""Unit tests for render_markdown (LESSONS.md / GOTCHAS.md / MEMORY.md bodies)."""

from __future__ import annotations

from datetime import UTC, datetime

from portpilot.core.models import KnowledgeItem, KnowledgeSource
from portpilot.knowledge.render import render_markdown


def _item(**overrides) -> KnowledgeItem:
    base = {
        "id": "k1",
        "kind": "lesson",
        "title": "Retry on 429",
        "body": "Use exponential backoff.",
        "tags": ["voyage", "retry"],
        "seen_count": 1,
        "sources": [KnowledgeSource(run_id="run_1", step_id="s1")],
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return KnowledgeItem(**base)


def test_renders_only_the_requested_kind():
    items = [_item(id="k1", kind="lesson"), _item(id="k2", kind="gotcha", title="Other")]
    out = render_markdown(items, "lesson")
    assert "Retry on 429" in out
    assert "Other" not in out
    assert out.startswith("# Lessons")


def test_empty_kind_renders_placeholder():
    out = render_markdown([], "gotcha")
    assert "# Gotchas" in out
    assert "Nothing recorded" in out


def test_newest_first_ordering():
    old = _item(id="old", title="Old", updated_at=datetime(2025, 1, 1, tzinfo=UTC))
    new = _item(id="new", title="New", updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    out = render_markdown([old, new], "lesson")
    assert out.index("New") < out.index("Old")


def test_shows_tags_seen_count_and_sources():
    item = _item(seen_count=3)
    out = render_markdown([item], "lesson")
    assert "retry, voyage" in out  # sorted tags
    assert "**Seen:** 3" in out
    assert "run_1" in out and "s1" in out


def test_item_with_no_tags_or_sources_still_renders():
    item = _item(tags=[], sources=[])
    out = render_markdown([item], "lesson")
    assert "Retry on 429" in out
    assert "**Seen:** 1" in out
