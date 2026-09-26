"""Budget: exceeding a budget emits `budget_exceeded`."""

from __future__ import annotations

import pytest
from conftest import make_deps, make_run
from fakes import ScriptedModel, ScriptedToolCall, ScriptedTurn
from strands import Agent, tool

from portpilot.agent.core_tools import StepContext, build_core_tools
from portpilot.agent.guard import StepPolicy
from portpilot.core.models import ShortTermPlan, StepBudget


def test_max_turns_budget_exceeded_emits_event_and_stops(sandbox_root):
    deps = make_deps(sandbox_root=sandbox_root)
    run = make_run(run_id="run_budget")
    deps.run_store.create_run(run)
    step = ShortTermPlan(
        step_id="step_budget",
        run_id="run_budget",
        seq=1,
        phase_id="p1",
        title="t",
        objective="o",
        budget=StepBudget(max_turns=2, max_tokens=1_000_000, max_minutes=60),
    )
    deps.run_store.save_step(step)

    ctx = StepContext(deps=deps, run=run, step=step)
    core_tools = build_core_tools(ctx)
    policy = StepPolicy(deps=deps, run=run, step=step, ctx=ctx)

    @tool
    def noop() -> str:
        """Does nothing, just burns a turn."""
        return "ok"

    # More tool calls than the max_turns=2 budget allows, each its own scripted turn.
    model = ScriptedModel(
        turns=[ScriptedTurn(tool_calls=[ScriptedToolCall("noop", {})]) for _ in range(5)]
    )
    agent = Agent(model=model, tools=[*core_tools, noop], interventions=[policy])
    ctx._agent_ref = agent

    with pytest.raises(Exception, match="max_turns"):
        for i in range(5):
            agent(f"call noop, turn {i}")

    events = deps.run_store.events(run.run_id)
    budget_events = [e for e in events if e["type"] == "budget_exceeded"]
    assert budget_events, "expected a budget_exceeded event"
    assert budget_events[0]["payload"]["budget"] == "max_turns"
    assert budget_events[0]["payload"]["limit"] == 2
    assert budget_events[0]["payload"]["used"] > budget_events[0]["payload"]["limit"]
