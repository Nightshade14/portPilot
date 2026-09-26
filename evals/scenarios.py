"""Scenario runner: submit a run through the API, poll to a terminal status,
and reduce its events + steps into a metrics dict (MVP_PLAN §8, Lane E).

MVP_PLAN §7's TERMINAL_RUN_STATUSES are "completed", "failed", "cancelled"
(core/models.py); this module polls until one of those is reached or
timeout_s elapses.
"""

from __future__ import annotations

import time
from typing import Any

from client import PortPilotClient

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})

# Poll cadence while waiting for a run to reach a terminal status.
_POLL_INTERVAL_S = 2.0


def run_scenario(
    client: PortPilotClient,
    repo_url: str,
    goal: str,
    timeout_s: float,
    *,
    budgets: dict[str, Any] | None = None,
    poll_interval_s: float = _POLL_INTERVAL_S,
) -> dict[str, Any]:
    """Submit a run, wait for a terminal status, and return its metrics.

    Raises TimeoutError if the run has not reached a terminal status within
    timeout_s. The partial state (whatever events/steps existed at timeout)
    is not returned -- callers that want that should poll get_run/get_events
    themselves instead of using this helper.
    """
    run_id = client.create_run(repo_url, goal, budgets=budgets)

    deadline = time.monotonic() + timeout_s
    run_doc: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    while True:
        state = client.get_run(run_id)
        run_doc = state["run"]
        steps = state.get("steps") or []
        if run_doc.get("status") in TERMINAL_RUN_STATUSES:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"run {run_id} did not reach a terminal status within {timeout_s}s "
                f"(last status={run_doc.get('status')!r})"
            )
        time.sleep(poll_interval_s)

    events = client.iter_all_events(run_id)
    return extract_metrics(run_id, run_doc, steps, events)


def extract_metrics(
    run_id: str,
    run_doc: dict[str, Any],
    steps: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the metrics dict from a run's final doc, steps and event stream.

    Kept separate from run_scenario so tests can drive it directly against a
    synthetic event stream (tests/evals/test_scenarios.py), without needing a
    live API.
    """
    steps_done = sum(1 for s in steps if s.get("status") == "done")
    steps_failed = sum(1 for s in steps if s.get("status") == "failed")

    tokens_per_step: dict[str, int] = {}
    for step in steps:
        usage = step.get("usage") or {}
        tokens_per_step[step["step_id"]] = int(usage.get("input_tokens", 0)) + int(
            usage.get("output_tokens", 0)
        )

    tool_schema_tokens_per_step: dict[str, int] = {}
    tools_created: list[dict[str, Any]] = []
    tools_reused: list[dict[str, Any]] = []
    cli_installed: list[dict[str, Any]] = []
    cli_refused: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    lessons_recorded = 0
    gotchas_recorded = 0

    current_step_id: str | None = None
    for event in events:
        etype = event.get("type")
        payload = event.get("payload") or {}
        step_id = event.get("step_id")
        if step_id:
            current_step_id = step_id

        if etype == "step_started":
            current_step_id = step_id or current_step_id
        elif etype == "tools_selected":
            if current_step_id is not None:
                tool_schema_tokens_per_step[current_step_id] = int(
                    payload.get("tool_schema_tokens", 0)
                )
            for pick in payload.get("picks") or []:
                provenance_run_id = (pick.get("provenance") or {}).get("run_id")
                if provenance_run_id is not None and provenance_run_id != run_id:
                    tools_reused.append(pick)
        elif etype == "tool_created":
            tools_created.append(payload)
        elif etype == "cli_installed":
            cli_installed.append(payload)
        elif etype == "cli_refused":
            cli_refused.append(payload)
        elif etype == "compaction":
            compactions.append(payload)
        elif etype == "lesson_recorded":
            lessons_recorded += 1
        elif etype == "gotcha_recorded":
            gotchas_recorded += 1

    return {
        "run_id": run_id,
        "status": run_doc.get("status"),
        "steps_total": len(steps),
        "steps_done": steps_done,
        "steps_failed": steps_failed,
        "tokens_per_step": tokens_per_step,
        "tool_schema_tokens_per_step": tool_schema_tokens_per_step,
        "tools_created": tools_created,
        "tools_reused": tools_reused,
        "cli_installed": cli_installed,
        "cli_refused": cli_refused,
        "compactions": compactions,
        "lessons_recorded": lessons_recorded,
        "gotchas_recorded": gotchas_recorded,
    }
