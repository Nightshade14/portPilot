"""Computed response shapes not modeled as `core.models` dataclasses (contract §Shapes)."""

from __future__ import annotations

from typing import Any

from portpilot.api.serialize import doc
from portpilot.core.models import Run, ShortTermPlan, ToolRecord


def run_summary(run: Run, steps: list[ShortTermPlan]) -> dict[str, Any]:
    """`RunSummary`: run_id, repo_url, goal, status, created_at, updated_at,
    steps_total, steps_done, current_step_title, usage."""
    steps_done = sum(1 for s in steps if s.status == "done")
    current_step_title = None
    if run.current_step_id is not None:
        for step in steps:
            if step.step_id == run.current_step_id:
                current_step_title = step.title
                break
    d = doc(run)
    return {
        "run_id": d["run_id"],
        "repo_url": d["repo_url"],
        "goal": d["goal"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "steps_total": len(steps),
        "steps_done": steps_done,
        "current_step_title": current_step_title,
        "usage": d["usage"],
    }


def tool_summary(latest: ToolRecord, versions_count: int) -> dict[str, Any]:
    """`ToolSummary`: latest version's metadata, no files/tests, plus versions_count."""
    d = doc(latest)
    return {
        "name": d["name"],
        "version": d["version"],
        "status": d["status"],
        "description": d["description"],
        "when_to_use": d["when_to_use"],
        "tags": d["tags"],
        "requires_cli": d["requires_cli"],
        "stats": d["stats"],
        "provenance": d["provenance"],
        "created_at": d["created_at"],
        "versions_count": versions_count,
    }
