"""Long-term and short-term planning (lane-a.md build step 3).

Uses `agent.structured_output_model=` typed output on the planner model role
(`settings.model_id`, same as the executor -- see deps.py). Prompts live in
`agent/prompts/*.md` and are loaded lazily so tests can run fully offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from portpilot.core.models import (
    Check,
    LongTermPlan,
    Phase,
    Run,
    ShortTermPlan,
    StepBudget,
    new_id,
)

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


# --------------------------------------------------------------------- typed schemas


class PhaseSpec(BaseModel):
    id: str
    title: str
    goal: str
    exit_criteria: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)


class LongTermPlanSpec(BaseModel):
    """Typed output for the planner's long-term-plan call."""

    phases: list[PhaseSpec]
    assumptions: list[str] = Field(default_factory=list)
    rationale: str = ""


class CheckSpec(BaseModel):
    name: str
    command: str
    expect_exit: int = 0
    timeout_s: int = 600


class ShortTermPlanSpec(BaseModel):
    phase_id: str
    title: str
    objective: str
    inputs: list[str] = Field(default_factory=list)
    acceptance: list[CheckSpec] = Field(default_factory=list)
    capability_hints: list[str] = Field(default_factory=list)
    max_turns: int = 40
    max_tokens: int = 400_000
    max_minutes: int = 45


class NextStepsSpec(BaseModel):
    """Typed output for `next_steps`: at most 3 STPs, or an empty list when done."""

    steps: list[ShortTermPlanSpec] = Field(default_factory=list)
    goal_complete: bool = False


# ------------------------------------------------------------------------- planning


def _planner_agent(deps: AgentDeps):
    from strands import Agent

    return Agent(
        model=deps.model_factory("planner"), tools=[], system_prompt=_load_prompt("planner.md")
    )


def _relevant_lessons_and_gotchas(
    deps: AgentDeps, goal: str, limit: int = 5
) -> list[dict[str, Any]]:
    hits = deps.knowledge.search(goal, kinds=["lesson", "gotcha"], limit=limit)
    return [{"title": h.item.title, "body": h.item.body, "kind": h.item.kind} for h in hits]


def create_long_term_plan(deps: AgentDeps, run: Run, survey: dict[str, Any]) -> LongTermPlan:
    """Build LTP v1 from the goal, the survey and top-5 relevant lessons/gotchas."""

    lessons = _relevant_lessons_and_gotchas(deps, run.goal)
    prompt = (
        f"Goal:\n{run.goal}\n\n"
        f"Repo survey:\n{survey}\n\n"
        f"Known lessons and gotchas (top {len(lessons)}):\n{lessons}\n\n"
        "Produce a long-term plan: phases with id, title, goal, exit_criteria, modules; "
        "plus assumptions and a short rationale."
    )
    agent = _planner_agent(deps)
    result = agent(prompt, structured_output_model=LongTermPlanSpec)
    spec: LongTermPlanSpec = result.structured_output

    plan = LongTermPlan(
        run_id=run.run_id,
        version=1,
        goal=run.goal,
        phases=[Phase(**p.model_dump()) for p in spec.phases],
        assumptions=spec.assumptions,
        rationale=spec.rationale,
    )
    deps.run_store.save_plan(plan)
    deps.run_store.log_event(
        run.run_id,
        "plan_created",
        None,
        {"version": plan.version, "phases": [{"id": p.id, "title": p.title} for p in plan.phases]},
    )
    return plan


def next_steps(
    deps: AgentDeps,
    run: Run,
    ltp: LongTermPlan,
    digest: str,
    completed_steps: list[ShortTermPlan],
    failed_steps: list[ShortTermPlan],
    open_gotchas: list[dict[str, Any]],
) -> list[ShortTermPlan]:
    """Produce at most 3 STPs from the LTP, digest, and history. `[]` means goal complete."""

    prompt = (
        f"Long-term plan phases:\n{[p.to_doc() for p in ltp.phases]}\n\n"
        f"Run digest:\n{digest}\n\n"
        f"Completed steps: {[s.title for s in completed_steps]}\n"
        f"Failed steps: {[s.title for s in failed_steps]}\n"
        f"Open gotchas: {open_gotchas}\n\n"
        "Produce at most 3 short-term plans (the next ones to run), each with an objective, "
        "inputs, runnable acceptance checks, capability hints and a budget. "
        "Set goal_complete=true and steps=[] only when the long-term plan's goal is fully met."
    )
    agent = _planner_agent(deps)
    result = agent(prompt, structured_output_model=NextStepsSpec)
    spec: NextStepsSpec = result.structured_output

    if spec.goal_complete or not spec.steps:
        return []

    existing = deps.run_store.steps(run.run_id)
    next_seq = (max((s.seq for s in existing), default=0)) + 1

    steps: list[ShortTermPlan] = []
    for i, item in enumerate(spec.steps[:3]):
        step = ShortTermPlan(
            step_id=new_id("step"),
            run_id=run.run_id,
            seq=next_seq + i,
            phase_id=item.phase_id,
            title=item.title,
            objective=item.objective,
            inputs=item.inputs,
            acceptance=[Check(**c.model_dump()) for c in item.acceptance],
            capability_hints=item.capability_hints,
            budget=StepBudget(
                max_turns=item.max_turns, max_tokens=item.max_tokens, max_minutes=item.max_minutes
            ),
        )
        deps.run_store.save_step(step)
        deps.run_store.log_event(
            run.run_id,
            "step_planned",
            step.step_id,
            {
                "step_id": step.step_id,
                "seq": step.seq,
                "title": step.title,
                "phase_id": step.phase_id,
            },
        )
        steps.append(step)
    return steps


def revise_plan(
    deps: AgentDeps, run: Run, ltp: LongTermPlan, reason: str, digest: str
) -> LongTermPlan:
    """Save a new LTP version after repeated step failure; emits `plan_revised`."""

    prompt = (
        f"The current plan (version {ltp.version}) needs revision.\n"
        f"Reason: {reason}\n\nRun digest:\n{digest}\n\n"
        f"Current phases:\n{[p.to_doc() for p in ltp.phases]}\n\n"
        "Produce a revised long-term plan (phases, assumptions, rationale) that accounts for this."
    )
    agent = _planner_agent(deps)
    result = agent(prompt, structured_output_model=LongTermPlanSpec)
    spec: LongTermPlanSpec = result.structured_output

    new_plan = LongTermPlan(
        run_id=run.run_id,
        version=ltp.version + 1,
        goal=run.goal,
        phases=[Phase(**p.model_dump()) for p in spec.phases],
        assumptions=spec.assumptions,
        rationale=spec.rationale,
    )
    deps.run_store.save_plan(new_plan)
    deps.run_store.update_run(run.run_id, ltp_version=new_plan.version)
    deps.run_store.log_event(
        run.run_id,
        "plan_revised",
        None,
        {
            "version": new_plan.version,
            "phases": [{"id": p.id, "title": p.title} for p in new_plan.phases],
            "reason": reason,
        },
    )
    return new_plan


__all__ = [
    "CheckSpec",
    "LongTermPlanSpec",
    "NextStepsSpec",
    "PhaseSpec",
    "ShortTermPlanSpec",
    "create_long_term_plan",
    "next_steps",
    "revise_plan",
]
