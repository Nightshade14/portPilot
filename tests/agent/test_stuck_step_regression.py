"""Reproduces the hang the Lead reported in the live LLM test
(runs/_pytest/live-sbx_6736b6b5fd25, 2026-09-26): `LocalSandboxManager.sandbox()`
raises (`NotASandboxLocalEnvironment()` takes no constructor args -- a bug in the
frozen `core/fakes.py`, reported to the Lead rather than edited here), so the executor
previously got NO shell/file_editor tools at all and could only nudge in place forever.

This test asserts (1) the fallback shell/file_editor tools built on
`SandboxManager.exec`/`write_file`/`read_file` actually let the step touch the
workspace when `sandbox.sandbox()` is broken, and (2) the executor's wall-clock guard
stops a step that never calls `complete_step`, emitting `budget_exceeded` rather than
spinning forever."""

from __future__ import annotations

from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn

from portpilot.agent.executor import execute_step
from portpilot.core.models import Check, ShortTermPlan, StepBudget


def test_sandbox_get_tools_failure_falls_back_to_working_shell_and_file_editor(sandbox_root):
    """Reproduces the core/fakes.py bug directly: `LocalSandboxManager.sandbox()`
    really does raise TypeError today, so this is not a mocked scenario."""

    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_sbx_bug")
    deps.run_store.create_run(run)
    deps.sandbox.ensure(run.run_id, run.repo_url)

    # Confirm the underlying bug is still present -- if the Lead fixes core/fakes.py,
    # this assertion (not the fallback behavior) is what should start failing first.
    assert deps.sandbox.sandbox(run.run_id).get_tools() == []

    step = ShortTermPlan(
        step_id="step_sbx_bug",
        run_id=run.run_id,
        seq=1,
        phase_id="p1",
        title="write a file",
        objective="write hello.txt via the file_editor tool",
        acceptance=[Check(name="file exists", command="test -f hello.txt", expect_exit=0)],
        budget=StepBudget(max_turns=10, max_tokens=100_000, max_minutes=10),
    )
    deps.run_store.save_step(step)

    executor_model = ScriptedModel(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ScriptedToolCall(
                        "file_editor", {"action": "write", "path": "hello.txt", "content": "hi"}
                    )
                ]
            ),
            ScriptedTurn(tool_calls=[ScriptedToolCall("complete_step", {"summary": "wrote it"})]),
        ]
    )
    deps.model_factory = lambda role: executor_model if role == "executor" else ScriptedModel()

    result = execute_step(deps, run, step)

    assert result.usage.tool_calls >= 2
    written = deps.sandbox.read_file(run.run_id, "/workspace/repo/hello.txt")
    assert written == "hi"

    tool_errors = [e for e in deps.run_store.events(run.run_id) if e["type"] == "tool_error"]
    assert not tool_errors, f"file_editor should have worked via the fallback: {tool_errors}"


def test_step_that_never_completes_stops_at_wall_clock_budget(sandbox_root):
    """A step whose script never calls complete_step must not run forever: the
    executor's wall-clock guard (independent of StepPolicy's max_turns) stops it and
    emits budget_exceeded."""

    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_never_completes")
    deps.run_store.create_run(run)
    deps.sandbox.ensure(run.run_id, run.repo_url)

    step = ShortTermPlan(
        step_id="step_never_completes",
        run_id=run.run_id,
        seq=1,
        phase_id="p1",
        title="never finishes",
        objective="never call complete_step",
        budget=StepBudget(max_turns=1000, max_tokens=100_000_000, max_minutes=0),
    )
    deps.run_store.save_step(step)

    # Only text turns -- complete_step is never called, so ctx.step_complete never
    # becomes True; with max_minutes=0 the wall-clock deadline is already in the past
    # on the very first check, so this must stop after the first nudge rather than
    # running out max_turns=1000 nudges.
    executor_model = ScriptedModel(turns=[ScriptedTurn(text="still working...")])
    deps.model_factory = lambda role: executor_model if role == "executor" else ScriptedModel()

    result = execute_step(deps, run, step, max_nudges=1000)

    assert result.usage.model_calls < 1000, (
        "the wall-clock guard should have stopped this long before max_nudges"
    )

    events = deps.run_store.events(run.run_id)
    budget_events = [
        e
        for e in events
        if e["type"] == "budget_exceeded" and e["payload"]["budget"] == "max_minutes"
    ]
    assert budget_events, "expected a max_minutes budget_exceeded event from the wall-clock guard"
