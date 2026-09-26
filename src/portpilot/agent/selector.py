"""Per-STP tool selection (lane-a.md build step 4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from portpilot.core.models import Run, ShortTermPlan, ToolPick

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

PROMPTS_DIR = Path(__file__).parent / "prompts"


class ToolSelection(BaseModel):
    name: str
    version: int
    reason: str


class ToolSelectionSpec(BaseModel):
    """Typed output for the aux-model tool-selector call."""

    picks: list[ToolSelection] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)


def _selection_query(step: ShortTermPlan) -> str:
    checks = " ".join(c.command for c in step.acceptance)
    hints = " ".join(step.capability_hints)
    return f"{step.objective} {checks} {hints}".strip()


def _filters_from_survey(survey: dict) -> dict:
    languages = list((survey or {}).get("languages", {}).keys())
    return {} if not languages else {"facets.language": languages[0]}


def select_tools(deps: AgentDeps, run: Run, step: ShortTermPlan, survey: dict) -> ShortTermPlan:
    """Pick at most `budgets.max_selected_tools` tools for `step`; emits `tools_selected`.

    Empty `tool_library` (None) means no library tools are available yet: candidates
    is `[]`, so the selector call still runs (it may report `missing_capabilities`) but
    picks nothing.
    """

    query = _selection_query(step)
    candidates = (
        []
        if deps.tool_library is None
        else deps.tool_library.candidates(query, filters=_filters_from_survey(survey), limit=20)
    )

    from strands import Agent

    agent = Agent(
        model=deps.model_factory("aux"),
        tools=[],
        system_prompt=(PROMPTS_DIR / "selector.md").read_text(),
    )
    prompt = (
        f"Step objective: {step.objective}\n"
        f"Acceptance checks: {[c.command for c in step.acceptance]}\n"
        f"Capability hints: {step.capability_hints}\n"
        f"max_selected_tools: {run.budgets.max_selected_tools}\n\n"
        f"Candidate tools:\n"
        + "\n".join(
            f"- {c.name}@{c.version}: {c.description} (when_to_use: {c.when_to_use}, "
            f"uses={c.uses}, failure_rate={c.failure_rate:.2f})"
            for c in candidates
        )
    )
    result = agent(prompt, structured_output_model=ToolSelectionSpec)
    spec: ToolSelectionSpec = result.structured_output

    max_selected = run.budgets.max_selected_tools
    picks = spec.picks[:max_selected]

    step.selected_tools = [ToolPick(name=p.name, version=p.version, reason=p.reason) for p in picks]
    step.missing_capabilities = spec.missing_capabilities
    deps.run_store.update_step(
        step.step_id,
        selected_tools=step.selected_tools,
        missing_capabilities=step.missing_capabilities,
    )

    core_tools = [
        "shell",
        "file_editor",
        "complete_step",
        "search_knowledge",
        "search_tools",
        "load_tool",
        "create_tool",
        "check_environment",
        "install_cli_tool",
        "record_lesson",
        "record_gotcha",
    ]
    all_specs = [
        {"name": c.name, "description": c.description}
        for c in candidates
        if c.name in {p.name for p in picks}
    ]
    tool_schema_tokens = sum(len(str(s)) for s in all_specs) // 4 + len(core_tools) * 30

    deps.run_store.log_event(
        run.run_id,
        "tools_selected",
        step.step_id,
        {
            "candidates": [
                {"name": c.name, "version": c.version, "score": c.score} for c in candidates
            ],
            "picks": [{"name": p.name, "version": p.version, "reason": p.reason} for p in picks],
            "missing": spec.missing_capabilities,
            "core_tools": core_tools,
            "tool_schema_tokens": tool_schema_tokens,
        },
    )
    return step


__all__ = ["ToolSelection", "ToolSelectionSpec", "select_tools"]
