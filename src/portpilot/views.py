"""Pure Rich renderers over plain data (plan 4.6). Owner: Lane E.

These functions never touch a Store. Callers fetch plain dicts / models from
the Store and hand them here, so the same views survive a process restart.
Every renderer returns a Rich renderable; the CLI prints it. Tests render with
``Console(record=True, width=120)`` and assert on ``export_text()``.
"""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from portpilot.models import MILESTONES, ContractResult, Decision

# --- status colors ----------------------------------------------------------

_RUN_STATUS_STYLE = {
    "running": "yellow",
    "paused": "cyan",
    "completed": "green",
    "failed": "red",
}
_POLICY_STATUS_STYLE = {
    "active": "green",
    "candidate": "yellow",
    "retired": "dim",
    "rejected": "red",
}


def _status_text(status: str, table: dict[str, str]) -> Text:
    return Text(status, style=table.get(status, "white"))


def render_run_status(
    run: dict[str, Any],
    milestones: list[tuple[str, int]],
    test_outputs: list[ContractResult],
) -> RenderableType:
    """Run id, colored status, current milestone, an ordered milestone progress
    line, and one line per attempt (``attempt 1 · policy v1 · 6/10``).

    ``milestones`` is ``(name, attempt)`` pairs in completion order (from
    ``Store.completed_milestones``). ``test_outputs`` are the run's
    ``ContractResult``s (from the ``test_output`` artifacts).
    """
    run_id = run.get("run_id", "?")
    status = run.get("status", "?")
    current = run.get("current_milestone")

    header = Text.assemble(
        ("run ", "bold"),
        (str(run_id), "bold white"),
        "  ",
        _status_text(str(status), _RUN_STATUS_STYLE),
    )

    current_line = Text.assemble(
        ("current milestone: ", "dim"),
        (str(current) if current else "—", "bold"),
    )

    done = {name for name, _ in milestones}
    progress = Text("progress: ", style="dim")
    for i, name in enumerate(MILESTONES):
        if i:
            progress.append(" → ", style="dim")
        if name == current:
            progress.append(name, style="bold yellow")
        elif name in done:
            attempts = sorted({a for n, a in milestones if n == name})
            marker = "/".join(str(a) for a in attempts)
            progress.append(f"{name}#{marker}", style="green")
        else:
            progress.append(name, style="dim")

    attempts_lines: list[Text] = []
    for result in sorted(test_outputs, key=lambda r: r.attempt):
        attempts_lines.append(
            Text.assemble(
                (f"attempt {result.attempt}", "bold"),
                " · ",
                (f"policy v{result.policy_version}", "cyan"),
                " · ",
                (
                    f"{result.passed}/{result.total}",
                    "green" if result.passed == result.total else "yellow",
                ),
            )
        )
    if not attempts_lines:
        attempts_lines.append(Text("no attempts recorded yet", style="dim"))

    body = Group(current_line, progress, Text(""), *attempts_lines)
    return Panel(
        body,
        title=header,
        title_align="left",
        border_style=_RUN_STATUS_STYLE.get(str(status), "white"),
    )


def _first_diff(case: Any) -> str:
    diff = getattr(case, "diff", None) or []
    return diff[0] if diff else ""


def render_contract_result(result: ContractResult) -> RenderableType:
    """A table of case id | category | PASS/FAIL | first diff line, plus a
    ``passed/total`` footer line."""
    table = Table(
        title=f"contract result · attempt {result.attempt} · policy v{result.policy_version}",
        title_justify="left",
        expand=False,
    )
    table.add_column("case", style="white", no_wrap=True)
    table.add_column("category", style="cyan")
    table.add_column("result", justify="center")
    table.add_column("first diff", style="dim")

    for case in result.cases:
        if case.passed:
            verdict = Text("PASS", style="green")
        else:
            verdict = Text("FAIL", style="red")
        table.add_row(case.case_id, case.category, verdict, _first_diff(case))

    footer = Text.assemble(
        ("passed ", "dim"),
        (
            f"{result.passed}/{result.total}",
            "green" if result.passed == result.total else "yellow",
        ),
    )
    return Group(table, footer)


def _excerpt(text: str | None, limit: int = 80) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_policy_comparison(
    policies: list[Any],
    baseline: ContractResult | None,
    candidate: ContractResult | None,
    decision: Decision | None,
) -> RenderableType:
    """Policy versions (status + rationale excerpt), a per-case v1-vs-v2 table
    marking fixed cases and regressions, and the decision with its reason.

    ``policies`` are ``Policy`` instances; ``baseline`` / ``candidate`` are the
    two ``ContractResult``s being compared; ``decision`` is the ``Decision``.
    """
    pol_table = Table(title="policies", title_justify="left", expand=False)
    pol_table.add_column("version", no_wrap=True)
    pol_table.add_column("status")
    pol_table.add_column("rationale", style="dim")
    for policy in sorted(policies, key=lambda p: p.version):
        pol_table.add_row(
            f"v{policy.version}",
            _status_text(policy.status, _POLICY_STATUS_STYLE),
            _excerpt(policy.rationale),
        )

    renderables: list[RenderableType] = [pol_table]

    if baseline is not None and candidate is not None:
        fixed = set(getattr(decision, "fixed", []) or [])
        regressions = set(getattr(decision, "regressions", []) or [])
        base_pass = baseline.passed_ids
        cand_pass = candidate.passed_ids

        cmp_table = Table(
            title=f"cases · v{baseline.policy_version} vs v{candidate.policy_version}",
            title_justify="left",
            expand=False,
        )
        cmp_table.add_column("case", no_wrap=True)
        cmp_table.add_column(f"v{baseline.policy_version}", justify="center")
        cmp_table.add_column(f"v{candidate.policy_version}", justify="center")
        cmp_table.add_column("change")

        ordered = [c.case_id for c in baseline.cases] or sorted(base_pass | cand_pass)
        for case_id in ordered:
            b_ok = case_id in base_pass
            c_ok = case_id in cand_pass
            b_cell = Text("PASS", style="green") if b_ok else Text("FAIL", style="red")
            c_cell = Text("PASS", style="green") if c_ok else Text("FAIL", style="red")
            if case_id in fixed or (not b_ok and c_ok):
                change = Text("fixed", style="green")
            elif case_id in regressions or (b_ok and not c_ok):
                change = Text("REGRESSION", style="bold red")
            else:
                change = Text("—", style="dim")
            cmp_table.add_row(case_id, b_cell, c_cell, change)
        renderables.append(cmp_table)

    if decision is not None:
        verdict = "PROMOTED" if decision.promoted else "REJECTED"
        style = "green" if decision.promoted else "red"
        decision_line = Text.assemble(
            ("decision: ", "dim"),
            (verdict, f"bold {style}"),
            "  ",
            (
                (
                    f"v{decision.baseline_version} {decision.baseline_passed}/{decision.total}"
                    f" → v{decision.candidate_version} {decision.candidate_passed}/{decision.total}"
                ),
                "white",
            ),
        )
        renderables.append(Group(decision_line, Text(decision.reason, style="dim")))

    return Group(*renderables)


def render_events(events: list[dict[str, Any]], limit: int = 20) -> RenderableType:
    """A compact timeline of the most recent ``limit`` events."""
    table = Table(title=f"events (last {limit})", title_justify="left", expand=False)
    table.add_column("ts", style="dim", no_wrap=True)
    table.add_column("type", style="cyan", no_wrap=True)
    table.add_column("milestone", no_wrap=True)
    table.add_column("detail", style="dim")

    shown = events[-limit:] if limit and len(events) > limit else events
    for ev in shown:
        ts = ev.get("ts")
        ts_str = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts or "")
        payload = ev.get("payload") or {}
        detail = payload.get("note") or _excerpt(str(payload) if payload else "", 60)
        table.add_row(ts_str, str(ev.get("type", "")), str(ev.get("milestone", "")), detail)

    if not shown:
        return Text("no events", style="dim")
    return table
