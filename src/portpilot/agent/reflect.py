"""Reflection: lessons, gotchas and tool feedback after a step (lane-a.md build step 10)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from portpilot.core.models import KnowledgeItem, KnowledgeSource, Run, ShortTermPlan, new_id

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

PROMPTS_DIR = Path(__file__).parent / "prompts"


class LessonSpec(BaseModel):
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)


class GotchaSpec(BaseModel):
    title: str
    symptom: str
    cause: str
    fix: str
    tags: list[str] = Field(default_factory=list)


class ToolFeedbackSpec(BaseModel):
    name: str
    version: int
    helpful: bool
    note: str = ""


class ReflectionSpec(BaseModel):
    lessons: list[LessonSpec] = Field(default_factory=list)
    gotchas: list[GotchaSpec] = Field(default_factory=list)
    tool_feedback: list[ToolFeedbackSpec] = Field(default_factory=list)


def reflect_on_step(deps: AgentDeps, run: Run, step: ShortTermPlan) -> ReflectionSpec:
    """Aux-model typed-output reflection; upserts lessons/gotchas, records tool feedback,
    then writes readable copies via `deps.render_markdown` when configured."""

    from strands import Agent

    agent = Agent(
        model=deps.model_factory("aux"),
        tools=[],
        system_prompt=(PROMPTS_DIR / "reflect.md").read_text(),
    )
    prompt = (
        f"Step: {step.title}\nObjective: {step.objective}\nOutcome: {step.outcome}\n"
        f"Selected tools: {[(p.name, p.version, p.used, p.helpful) for p in step.selected_tools]}\n"
        "Extract lessons, gotchas, and tool feedback (per selected tool, whether it helped)."
    )
    result = agent(prompt, structured_output_model=ReflectionSpec)
    spec: ReflectionSpec = result.structured_output

    for lesson in spec.lessons:
        item = KnowledgeItem(
            id=new_id("lesson"),
            kind="lesson",
            title=lesson.title,
            body=lesson.body,
            tags=lesson.tags,
            sources=[
                KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)
            ],
        )
        item_id = deps.knowledge.upsert(item)
        deps.run_store.log_event(
            run.run_id,
            "lesson_recorded",
            step.step_id,
            {"item_id": item_id, "title": lesson.title, "merged": item_id != item.id},
        )

    for gotcha in spec.gotchas:
        body = f"Symptom: {gotcha.symptom}\nCause: {gotcha.cause}\nFix: {gotcha.fix}"
        item = KnowledgeItem(
            id=new_id("gotcha"),
            kind="gotcha",
            title=gotcha.title,
            body=body,
            tags=gotcha.tags,
            sources=[
                KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)
            ],
        )
        item_id = deps.knowledge.upsert(item)
        deps.run_store.log_event(
            run.run_id,
            "gotcha_recorded",
            step.step_id,
            {"item_id": item_id, "title": gotcha.title, "merged": item_id != item.id},
        )

    if deps.tool_library is not None:
        for fb in spec.tool_feedback:
            deps.tool_library.record_use(fb.name, fb.version, run.run_id, fb.helpful, fb.note)

    if deps.render_markdown is not None:
        for kind in ("lesson", "gotcha", "memory"):
            items = deps.knowledge.list_items(kinds=[kind], limit=200)  # type: ignore[list-item]
            content = deps.render_markdown(kind=kind, items=items)
            filename = {"lesson": "LESSONS.md", "gotcha": "GOTCHAS.md", "memory": "MEMORY.md"}[kind]
            deps.sandbox.write_file(run.run_id, f"/workspace/repo/.portpilot/{filename}", content)

    return spec


__all__ = ["GotchaSpec", "LessonSpec", "ReflectionSpec", "ToolFeedbackSpec", "reflect_on_step"]
