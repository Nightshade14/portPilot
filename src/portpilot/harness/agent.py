"""Per-milestone Strands agent factory. Owner: Lane C.

Each milestone gets only its own tools (MILESTONE_TOOLS) and the active
policy body in the system prompt (charter C).
"""

from __future__ import annotations

from typing import Any

from portpilot.config import Settings
from portpilot.models import Milestone, Policy


def build_model(settings: Settings) -> Any:
    """OpenRouter through Strands' OpenAI-compatible provider."""
    from strands.models.openai import OpenAIModel

    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return OpenAIModel(
        client_args={
            "api_key": settings.openrouter_api_key,
            "base_url": settings.openrouter_base_url,
        },
        model_id=settings.model_id,
        params={"temperature": settings.model_temperature},
    )


def milestone_tools(milestone: Milestone) -> list[Any]:
    """Tool objects allowed at this milestone (plan 4.5)."""
    from portpilot.harness import tools as t

    table: dict[str, list[Any]] = {
        "source_analysis": [t.inspect_source],
        "generation": [t.generate_target],
        "regeneration": [t.generate_target],
        "test": [t.run_contract_tests],
        "retest": [t.run_contract_tests],
        "diagnosis": [t.diagnose_failure],
        "candidate_policy": [t.create_candidate_policy],
        "evaluation": [t.evaluate_policy],
        "completion": [],
    }
    return [*table[milestone], t.persist_checkpoint]


def build_agent(milestone: Milestone, policy: Policy, settings: Settings) -> Any:
    raise NotImplementedError("Lane C: build_agent")
