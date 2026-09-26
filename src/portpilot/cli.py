"""PortPilot CLI (plan 4.6). Owner: Lane E.

Views read only from the Store so they survive a process restart.
The `smoke` commands are the Lead's 0:00-0:20 connectivity checks.
"""

from __future__ import annotations

from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, help="PortPilot migration harness")
smoke = typer.Typer(no_args_is_help=True, help="Connectivity smoke tests")
app.add_typer(smoke, name="smoke")


@app.command()
def run(
    policy: Annotated[str | None, typer.Option(help="Policy version, e.g. v1")] = None,
    pause_after: Annotated[str | None, typer.Option(help="diagnosis | candidate_policy")] = None,
) -> None:
    """Start a migration run and print its run_id."""
    raise NotImplementedError("Lane E: run")


@app.command()
def resume(run_id: str) -> None:
    """Resume a paused run from its stored checkpoint."""
    raise NotImplementedError("Lane E: resume")


@app.command()
def status(run_id: str) -> None:
    """Show milestone, attempts and pass rates."""
    raise NotImplementedError("Lane E: status")


@app.command()
def policies() -> None:
    """Show policy versions, status and evaluation evidence."""
    raise NotImplementedError("Lane E: policies")


@app.command()
def contracts(
    source_only: Annotated[bool, typer.Option("--source-only")] = False,
    target: Annotated[str | None, typer.Option(help="Target dir to test")] = None,
) -> None:
    """Run the contract suite (source vs itself, or source vs a target dir)."""
    raise NotImplementedError("Lane A/E: contracts")


@app.command()
def seed() -> None:
    """Seed policy v1 from policies/flask-to-hono.v1.md into the store."""
    raise NotImplementedError("Lane B: seed")


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


if __name__ == "__main__":
    app()
