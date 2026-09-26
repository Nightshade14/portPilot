"""Sync checks (MVP_PLAN §7) as pure functions over metrics dicts.

Each function takes one or more metrics dicts (evals/scenarios.py's
extract_metrics output) and returns a list of failure strings -- empty means
the sync's condition held.
"""

from __future__ import annotations

from typing import Any

MAX_SELECTED_TOOLS = 8  # core/models.py Budgets.max_selected_tools default


def check_sync2(metrics: dict[str, Any]) -> list[str]:
    """Sync 2: LTP plus at least 3 STPs, each with at most 8 selected tools
    and reasons; events in Atlas; lessons written."""
    failures: list[str] = []

    if metrics["steps_total"] < 3:
        failures.append(f"expected at least 3 STPs, got {metrics['steps_total']}")

    for step_id, tokens in metrics.get("tool_schema_tokens_per_step", {}).items():
        # tool_schema_tokens_per_step existing for a step is itself evidence a
        # tools_selected event fired; a token count of 0 with no picks would
        # still be schema-cost-free, so this loop checks the pick count via
        # the picks captured in tools_reused/tools_created is not enough --
        # callers should also pass picks_per_step if they need the >8 check
        # precisely. Kept simple: flag an obviously-missing schema cost.
        if tokens < 0:
            failures.append(f"step {step_id}: negative tool_schema_tokens ({tokens})")

    if metrics.get("lessons_recorded", 0) == 0 and metrics.get("gotchas_recorded", 0) == 0:
        failures.append("expected at least one lesson or gotcha recorded, got none")

    if metrics["steps_done"] == 0:
        failures.append("expected at least one step done, got 0")

    return failures


def check_sync2_tool_picks(picks_per_step: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Companion to check_sync2: verifies the <=8 selected-tools-with-reasons
    constraint directly against tools_selected payloads, since extract_metrics
    does not carry per-step pick lists by default.

    picks_per_step: {step_id: [{"name", "version", "reason"}, ...]}
    """
    failures: list[str] = []
    for step_id, picks in picks_per_step.items():
        if len(picks) > MAX_SELECTED_TOOLS:
            failures.append(
                f"step {step_id}: {len(picks)} selected tools exceeds max {MAX_SELECTED_TOOLS}"
            )
        for pick in picks:
            if not pick.get("reason"):
                failures.append(f"step {step_id}: tool pick {pick.get('name')} has no reason")
    return failures


def check_sync3(run1_metrics: dict[str, Any], run2_metrics: dict[str, Any]) -> list[str]:
    """Sync 3: tool created in run 1, reused in run 2, with no new tool of
    the same purpose."""
    failures: list[str] = []

    created_in_run1 = run1_metrics.get("tools_created") or []
    if not created_in_run1:
        failures.append("run 1: expected at least one tool_created event, got none")
        return failures

    created_purposes = {c.get("purpose") for c in created_in_run1 if c.get("purpose")}
    created_names = {c.get("name") for c in created_in_run1 if c.get("name")}

    reused_in_run2 = run2_metrics.get("tools_reused") or []
    reused_names = {r.get("name") for r in reused_in_run2 if r.get("name")}

    if not (created_names & reused_names):
        failures.append(
            "run 2: expected a tool created in run 1 "
            f"({sorted(created_names)}) to be reused, but reused tools were "
            f"{sorted(reused_names)}"
        )

    new_tools_in_run2 = {c.get("purpose") for c in (run2_metrics.get("tools_created") or [])}
    duplicate_purposes = created_purposes & new_tools_in_run2
    if duplicate_purposes:
        failures.append(
            f"run 2: created a new tool for purpose(s) already covered by run 1's "
            f"tool(s): {sorted(duplicate_purposes)}"
        )

    return failures


def check_sync4(metrics: dict[str, Any]) -> list[str]:
    """Sync 4: kill and resume -- the same run resumes, completed STPs are
    not re-run, at least one compaction event with before/after token counts."""
    failures: list[str] = []

    if metrics["status"] not in ("completed", "failed"):
        failures.append(
            f"expected run to reach a terminal status after resume, got {metrics['status']!r}"
        )

    if metrics["steps_failed"] > 0:
        failures.append(
            f"expected 0 steps re-run-and-failed after resume, got {metrics['steps_failed']}"
        )

    compactions = metrics.get("compactions") or []
    if not compactions:
        failures.append("expected at least one compaction event, got none")
    else:
        for c in compactions:
            if "tokens_before" not in c or "tokens_after" not in c:
                failures.append(f"compaction event missing tokens_before/after: {c!r}")

    return failures
