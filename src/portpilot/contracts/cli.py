"""Contract suite CLI entry point. Owner: Lane A.

`contracts_command` boots the Flask source (and, unless --source-only, a Hono
target dir), runs the suite, prints a Rich table, and returns a shell exit code.
Lane E's `cli.py` calls this through a lazy import.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from portpilot.contracts.runner import run_source_only, run_suite
from portpilot.contracts.services import flask_source, hono_target
from portpilot.models import ContractResult


def _render(result: ContractResult, console: Console) -> None:
    table = Table(title=f"profile-api contract suite ({result.passed}/{result.total})")
    table.add_column("case id", style="cyan", no_wrap=True)
    table.add_column("category")
    table.add_column("result")
    table.add_column("first diff")
    for case in result.cases:
        verdict = "[green]PASS[/green]" if case.passed else "[red]FAIL[/red]"
        first_diff = case.diff[0] if case.diff else ""
        table.add_row(case.case_id, case.category, verdict, first_diff)
    console.print(table)
    console.print(f"passed/total: {result.passed}/{result.total}")


def contracts_command(source_only: bool, target: str | None) -> int:
    """Run the contract suite. Returns 0 when everything passes, else 1."""
    console = Console()
    with flask_source() as source_url:
        if source_only:
            result = run_source_only(source_url)
        else:
            if target is None:
                console.print("[red]--target is required unless --source-only is set[/red]")
                return 1
            with hono_target(Path(target)) as target_url:
                result = run_suite(source_url, target_url)
    _render(result, console)
    return 0 if result.passed == result.total else 1
