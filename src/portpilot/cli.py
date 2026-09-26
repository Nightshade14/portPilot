"""PortPilot CLI (plan 4.6). Owner: Lane E.

Views read only from the Store so they survive a process restart.
The `smoke` commands are the Lead's 0:00-0:20 connectivity checks.

Cross-lane code (orchestrator, contracts CLI, seed) is reached only via lazy
imports inside the command bodies. While those lanes are still
``NotImplementedError``/import stubs, the affected command degrades to a
friendly "not implemented yet (lane X)" message and exit code 2, with no
traceback.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from portpilot import views
from portpilot.config import POLICIES_DIR, POLICY_NAME
from portpilot.models import PAUSABLE_MILESTONES, ContractResult, Decision, Policy
from portpilot.store import get_store
from portpilot.store.base import NotFound, Store

app = typer.Typer(no_args_is_help=True, help="PortPilot migration harness")
smoke = typer.Typer(no_args_is_help=True, help="Connectivity smoke tests")
app.add_typer(smoke, name="smoke")

console = Console()
err_console = Console(stderr=True)


# --- shared helpers ---------------------------------------------------------


def _fail(message: str, code: int) -> None:
    """Print a clean red error and exit with ``code`` (no traceback)."""
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def _not_implemented(lane: str) -> None:
    """A lane not merged yet: friendly message, exit 2, no traceback."""
    err_console.print(f"[yellow]not implemented yet ({lane})[/yellow]")
    raise typer.Exit(2)


def _parse_policy_version(policy: str | None) -> int | None:
    """Validate a ``vN`` policy string into an int, or ``None`` when omitted."""
    if policy is None:
        return None
    text = policy.strip()
    if text.startswith(("v", "V")):
        text = text[1:]
    if not text.isdigit():
        _fail(f"invalid --policy {policy!r}; expected v<int>, e.g. v1", 2)
    return int(text)


def _validate_pause_after(pause_after: str | None) -> str | None:
    if pause_after is None:
        return None
    if pause_after not in PAUSABLE_MILESTONES:
        allowed = " | ".join(PAUSABLE_MILESTONES)
        _fail(f"invalid --pause-after {pause_after!r}; expected one of: {allowed}", 2)
    return pause_after


def _test_outputs(store: Store, run_id: str) -> list[ContractResult]:
    """All ``test_output`` artifacts for a run, as ``ContractResult``s."""
    docs = store.artifacts(run_id, kind="test_output")
    return [ContractResult.from_doc(d["content"]) for d in docs]


def _show_status(store: Store, run_id: str) -> None:
    run = store.get_run(run_id)
    milestones = store.completed_milestones(run_id)
    outputs = _test_outputs(store, run_id)
    console.print(views.render_run_status(run, milestones, outputs))


# --- commands ---------------------------------------------------------------


@app.command()
def run(
    policy: Annotated[str | None, typer.Option(help="Policy version, e.g. v1")] = None,
    pause_after: Annotated[str | None, typer.Option(help="diagnosis | candidate_policy")] = None,
) -> None:
    """Start a migration run and print its run_id."""
    policy_version = _parse_policy_version(policy)
    pause = _validate_pause_after(pause_after)
    store = get_store()

    try:
        from portpilot.harness import orchestrator

        run_id = orchestrator.start_run(store, policy_version=policy_version, pause_after=pause)
    except (NotImplementedError, ImportError):
        _not_implemented("lane C: orchestrator")
        return  # pragma: no cover

    console.print(f"[bold]run started:[/bold] [white]{run_id}[/white]")
    try:
        run_doc = store.get_run(run_id)
    except NotFound:
        _fail(f"run {run_id} not found after start", 1)
        return  # pragma: no cover
    if run_doc.get("status") == "paused":
        console.print(f"[cyan]paused — resume with:[/cyan] portpilot resume {run_id}")
    _show_status(store, run_id)


@app.command()
def resume(run_id: str) -> None:
    """Resume a paused run from its stored checkpoint."""
    store = get_store()
    try:
        from portpilot.harness import orchestrator

        orchestrator.resume(store, run_id)
    except (NotImplementedError, ImportError):
        _not_implemented("lane C: orchestrator")
        return  # pragma: no cover
    except NotFound:
        _fail(f"run {run_id} not found", 1)
        return  # pragma: no cover

    run_doc = store.get_run(run_id)
    if run_doc.get("status") == "paused":
        console.print(f"[cyan]paused — resume with:[/cyan] portpilot resume {run_id}")
    _show_status(store, run_id)


@app.command()
def status(run_id: str) -> None:
    """Show milestone, attempts and pass rates."""
    store = get_store()
    try:
        _show_status(store, run_id)
    except NotFound:
        _fail(f"run {run_id} not found", 1)


@app.command()
def events(run_id: str) -> None:
    """Show a compact timeline of the run's persisted events."""
    store = get_store()
    try:
        evs = store.events(run_id)
    except NotFound:
        _fail(f"run {run_id} not found", 1)
        return  # pragma: no cover
    console.print(views.render_events(evs))


@app.command()
def policies(
    run: Annotated[str | None, typer.Option(help="Show v1-vs-v2 comparison for this run")] = None,
) -> None:
    """Show policy versions and status; with --run, the v1-vs-v2 evaluation."""
    store = get_store()
    pols: list[Policy] = store.list_policies(POLICY_NAME)

    if run is None:
        console.print(views.render_policy_comparison(pols, None, None, None))
        return

    try:
        eval_docs = store.artifacts(run, kind="evaluation")
    except NotFound:
        _fail(f"run {run} not found", 1)
        return  # pragma: no cover

    decision: Decision | None = None
    baseline: ContractResult | None = None
    candidate: ContractResult | None = None
    if eval_docs:
        decision = Decision(**eval_docs[-1]["content"])
        outputs = {r.attempt: r for r in _test_outputs(store, run)}
        baseline = outputs.get(decision.baseline_attempt)
        candidate = outputs.get(decision.candidate_attempt)

    console.print(views.render_policy_comparison(pols, baseline, candidate, decision))


@app.command()
def contracts(
    source_only: Annotated[bool, typer.Option("--source-only")] = False,
    target: Annotated[str | None, typer.Option(help="Target dir to test")] = None,
) -> None:
    """Run the contract suite (source vs itself, or source vs a target dir)."""
    try:
        from portpilot.contracts.cli import contracts_command
    except (NotImplementedError, ImportError):
        _not_implemented("lane A: contracts")
        return  # pragma: no cover
    try:
        code = contracts_command(source_only, target)
    except NotImplementedError:
        _not_implemented("lane A: contracts")
        return  # pragma: no cover
    raise typer.Exit(int(code))


@app.command()
def seed() -> None:
    """Seed policy v1 from policies/flask-to-hono.v1.md into the store."""
    store = get_store()
    try:
        from portpilot.store.seed import seed_policy

        policy = seed_policy(store, POLICIES_DIR / "flask-to-hono.v1.md")
    except (NotImplementedError, ImportError):
        _not_implemented("lane B: seed")
        return  # pragma: no cover
    console.print(f"[green]seeded[/green] {policy.name} v{policy.version} ({policy.status})")


# --- smoke (Lead-owned; do not change) --------------------------------------


@smoke.command("atlas")
def smoke_atlas() -> None:
    """Write, read and delete one document in Atlas."""
    from portpilot.smoke import atlas_roundtrip

    typer.echo(atlas_roundtrip())


@smoke.command("llm")
def smoke_llm() -> None:
    """One Strands tool call through OpenRouter with MODEL_ID."""
    from portpilot.smoke import llm_tool_call

    typer.echo(llm_tool_call())


# --- api / worker (Lane P) --------------------------------------------------


@app.command()
def api(
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8000,
) -> None:
    """Run the FastAPI server with uvicorn. Defaults to 127.0.0.1: Caddy terminates
    TLS in front of it."""
    import uvicorn

    from portpilot.api.deps import build_api_deps
    from portpilot.core.config import load_mvp_settings

    settings = load_mvp_settings()
    from portpilot.api.app import create_app

    fastapi_app = create_app(build_api_deps(settings))
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def worker() -> None:
    """Run the worker loop (claims runs, drives the agent, heartbeats the lease)."""
    from portpilot.worker.main import main as worker_main

    worker_main()


if __name__ == "__main__":
    app()
