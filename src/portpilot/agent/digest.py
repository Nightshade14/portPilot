"""Run digest rewriting (lane-a.md build step 10)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from portpilot.core.models import KnowledgeItem, KnowledgeSource, Run, ShortTermPlan

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

PROMPTS_DIR = Path(__file__).parent / "prompts"
DIGEST_TOKEN_CAP = 1_500


class DigestSpec(BaseModel):
    digest: str


def _existing_digest_text(deps: AgentDeps, run_id: str) -> str:
    for meta in deps.run_store.list_artifacts(run_id, kind="digest"):
        artifact = deps.run_store.get_artifact(meta["artifact_id"])
        return (
            artifact["content"].get("digest", "") if isinstance(artifact["content"], dict) else ""
        )
    return ""


def update_digest(deps: AgentDeps, run: Run, step: ShortTermPlan) -> str:
    """Aux-model rewrite of the run digest (<=1,500 tokens); stored as a `digest`
    artifact and upserted into knowledge as `run_digest` with `dedupe=False`."""

    from strands import Agent

    previous = _existing_digest_text(deps, run.run_id)
    agent = Agent(
        model=deps.model_factory("aux"),
        tools=[],
        system_prompt=(PROMPTS_DIR / "digest.md").read_text(),
    )
    prompt = (
        f"Previous digest:\n{previous or '(none yet)'}\n\n"
        f"Most recent step: {step.title}\nOutcome: {step.outcome}\n"
        f"Objective: {step.objective}\n\nRewrite the digest, <= {DIGEST_TOKEN_CAP} tokens."
    )
    result = agent(prompt, structured_output_model=DigestSpec)
    spec: DigestSpec = result.structured_output
    text = spec.digest[: DIGEST_TOKEN_CAP * 4]

    deps.run_store.put_artifact(run.run_id, step.step_id, "digest", {"digest": text}, name="digest")

    item = KnowledgeItem(
        id=f"digest_{run.run_id}",
        kind="run_digest",
        title=f"Run digest for {run.run_id}",
        body=text,
        sources=[KnowledgeSource(run_id=run.run_id, step_id=step.step_id, repo_url=run.repo_url)],
    )
    deps.knowledge.upsert(item, dedupe=False)
    return text


__all__ = ["DIGEST_TOKEN_CAP", "DigestSpec", "update_digest"]
