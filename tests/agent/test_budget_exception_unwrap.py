"""Regression: a BudgetExceeded/LeaseLost raised from inside StepPolicy during a live
tool call arrives at execute_step wrapped in strands.types.exceptions.EventLoopException
(confirmed against the real Strands event loop in the 2026-09-26 live-LLM rerun, which
hit `max_turns` mid-step and propagated an uncaught EventLoopException instead of
stopping cleanly). execute_step must unwrap it and treat it as a normal step stop."""

from __future__ import annotations

import pytest
from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn

from portpilot.agent.executor import execute_step
from portpilot.core.models import ShortTermPlan, StepBudget


def test_budget_exceeded_wrapped_by_strands_is_unwrapped_and_stops_cleanly(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_wrapped_budget")
    deps.run_store.create_run(run)
    deps.sandbox.ensure(run.run_id, run.repo_url)

    step = ShortTermPlan(
        step_id="step_wrapped_budget",
        run_id=run.run_id,
        seq=1,
        phase_id="p1",
        title="t",
        objective="o",
        budget=StepBudget(max_turns=2, max_tokens=1_000_000, max_minutes=60),
    )
    deps.run_store.save_step(step)

    executor_model = ScriptedModel(
        turns=[
            ScriptedTurn(tool_calls=[ScriptedToolCall("check_environment", {})]) for _ in range(6)
        ]
    )
    deps.model_factory = lambda role: executor_model if role == "executor" else ScriptedModel()

    # Must return normally (the step object), not raise -- this is the whole point of
    # the fix: a BudgetExceeded raised mid-tool-call must not become an uncaught crash.
    result = execute_step(deps, run, step)
    assert result is step

    events = deps.run_store.events(run.run_id)
    budget_events = [
        e
        for e in events
        if e["type"] == "budget_exceeded" and e["payload"]["budget"] == "max_turns"
    ]
    assert budget_events, "expected a max_turns budget_exceeded event"


def test_non_budget_exception_from_a_tool_call_still_propagates(sandbox_root):
    """The unwrap must be narrow: an unrelated exception raised inside a tool call
    should NOT be swallowed as if it were a clean budget/lease stop."""

    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_other_exc")
    deps.run_store.create_run(run)
    deps.sandbox.ensure(run.run_id, run.repo_url)

    step = ShortTermPlan(
        step_id="step_other_exc",
        run_id=run.run_id,
        seq=1,
        phase_id="p1",
        title="t",
        objective="o",
    )
    deps.run_store.save_step(step)

    from portpilot.core.models import Usage

    class _CrashingHooks:
        def __init__(self, *a, **kw) -> None:
            self.usage = Usage()

        def register_hooks(self, registry, **kwargs):
            from strands.hooks.events import BeforeToolCallEvent

            registry.add_callback(BeforeToolCallEvent, self._boom)

        def _boom(self, event):
            raise ValueError("unrelated crash, not a budget/lease issue")

    executor_model = ScriptedModel(
        turns=[ScriptedTurn(tool_calls=[ScriptedToolCall("check_environment", {})])]
    )
    deps.model_factory = lambda role: executor_model if role == "executor" else ScriptedModel()

    import portpilot.agent.executor as executor_mod

    real_recording_hooks_cls = executor_mod._RecordingHooks
    executor_mod._RecordingHooks = lambda *a, **kw: _CrashingHooks()
    try:
        with pytest.raises(Exception, match="unrelated crash"):
            execute_step(deps, run, step)
    finally:
        executor_mod._RecordingHooks = real_recording_hooks_cls
