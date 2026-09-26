"""Contract tests for ToolStore, parametrized over InMemoryToolStore and AtlasToolStore."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from portpilot.core.fakes import InMemoryToolStore
from portpilot.core.interfaces import Conflict, NotFound, ToolStore
from portpilot.core.models import ToolRecord


def _make_tool(name: str = "grep_repo", version: int = 1, **overrides) -> ToolRecord:
    defaults: dict = {
        "name": name,
        "version": version,
        "description": "grep the repo",
        "when_to_use": "when you need to search files",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"matches": {"type": "array"}}},
        "files": {"main.py": "def run(params):\n    return {'matches': []}\n"},
    }
    defaults.update(overrides)
    return ToolRecord(**defaults)


@pytest.fixture(params=["memory", pytest.param("atlas", marks=pytest.mark.mongo)])
def tool_store(request) -> Iterator[ToolStore]:
    if request.param == "memory":
        yield InMemoryToolStore()
        return

    uri = request.getfixturevalue("mongo_uri")
    db_name = request.getfixturevalue("mongo_db_name")
    from portpilot.store.v2.atlas import AtlasToolStore

    store = AtlasToolStore(uri, db_name)
    try:
        yield store
    finally:
        store.drop()
        store.close()


def test_save_and_get_by_version(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1))
    fetched = tool_store.get("grep_repo", version=1)
    assert fetched.name == "grep_repo"
    assert fetched.version == 1


def test_save_duplicate_name_version_conflicts(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1))
    with pytest.raises(Conflict):
        tool_store.save(_make_tool(version=1))


def test_get_no_version_returns_active(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1, status="deprecated"))
    tool_store.save(_make_tool(version=2, status="active"))
    tool_store.save(_make_tool(version=3, status="candidate"))

    active = tool_store.get("grep_repo")
    assert active.version == 2
    assert active.status == "active"


def test_get_no_active_version_not_found(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1, status="draft"))
    with pytest.raises(NotFound):
        tool_store.get("grep_repo")


def test_get_missing_version_not_found(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1))
    with pytest.raises(NotFound):
        tool_store.get("grep_repo", version=99)


def test_versions_ascending(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=2))
    tool_store.save(_make_tool(version=1))
    versions = tool_store.versions("grep_repo")
    assert [t.version for t in versions] == [1, 2]


def test_list_tools_latest_version_per_name(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(name="a", version=1, status="active"))
    tool_store.save(_make_tool(name="a", version=2, status="candidate"))
    tool_store.save(_make_tool(name="b", version=1, status="active"))

    tools = tool_store.list_tools()
    by_name = {t.name: t for t in tools}
    assert by_name["a"].version == 2
    assert by_name["b"].version == 1


def test_list_tools_filtered_by_status_considers_matching_versions_only(
    tool_store: ToolStore,
) -> None:
    """`list_tools(status=...)` filters to versions matching that status first, then
    keeps the latest version among those -- not the latest version overall gated by
    status (see core.fakes.InMemoryToolStore.list_tools, the reference semantics)."""
    tool_store.save(_make_tool(name="a", version=1, status="active"))
    tool_store.save(_make_tool(name="a", version=2, status="candidate"))

    active_only = tool_store.list_tools(status="active")
    assert [(t.name, t.version) for t in active_only] == [("a", 1)]

    candidate_only = tool_store.list_tools(status="candidate")
    assert [(t.name, t.version) for t in candidate_only] == [("a", 2)]


def test_set_status(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1, status="candidate"))
    tool_store.set_status("grep_repo", 1, "active")
    assert tool_store.get("grep_repo", version=1).status == "active"


def test_set_status_not_found(tool_store: ToolStore) -> None:
    with pytest.raises(NotFound):
        tool_store.set_status("grep_repo", 1, "active")


def test_record_use_increments_stats(tool_store: ToolStore) -> None:
    tool_store.save(_make_tool(version=1))
    tool_store.record_use("grep_repo", 1, "run_1", ok=True)
    tool_store.record_use("grep_repo", 1, "run_1", ok=False)
    tool_store.record_use("grep_repo", 1, "run_2", ok=True)

    fetched = tool_store.get("grep_repo", version=1)
    assert fetched.stats.uses == 3
    assert fetched.stats.successes == 2
    assert fetched.stats.failures == 1
    assert sorted(fetched.stats.runs_used_in) == ["run_1", "run_2"]


def test_record_use_not_found(tool_store: ToolStore) -> None:
    with pytest.raises(NotFound):
        tool_store.record_use("grep_repo", 1, "run_1", ok=True)


def test_next_version(tool_store: ToolStore) -> None:
    assert tool_store.next_version("grep_repo") == 1
    tool_store.save(_make_tool(version=1))
    assert tool_store.next_version("grep_repo") == 2
    tool_store.save(_make_tool(version=2))
    assert tool_store.next_version("grep_repo") == 3


def test_duplicate_tool_version_conflict_race(tool_store: ToolStore) -> None:
    """Two attempts to save the same (name, version) -- the second is a Conflict."""
    tool_store.save(_make_tool(version=1))
    with pytest.raises(Conflict):
        tool_store.save(_make_tool(version=1, description="different"))
