"""Per-milestone agent/tool configuration. Owner: Lane C.

Each milestone gets only its own tools (milestone_tools) and the active policy.
Only generation/regeneration uses an LLM; every other milestone is
deterministic code (plan section 2, rule 3).
"""

from __future__ import annotations

from typing import Any

from portpilot.config import Settings
from portpilot.models import Milestone, Policy

GENERATION_MILESTONES: tuple[Milestone, ...] = ("generation", "regeneration")

GENERATION_SYSTEM_PROMPT = """\
You are PortPilot's code generator. You port a legacy Python/Flask service to a brand-new
TypeScript service built on Hono, starting from an empty project.

The project already contains package.json (hono, @hono/node-server, @hono/zod-validator, zod),
tsconfig.json (strict, NodeNext modules) and node_modules. You write ONLY TypeScript files
under src/. The entry point must be src/index.ts. Relative imports between your files must
use the .js extension (NodeNext), e.g. `import { x } from "./x.js"`.

The MIGRATION POLICY below is authoritative. Where the policy and the way the legacy source
does something disagree, follow the policy. Output every file in full; no placeholders.

=== MIGRATION POLICY (name={name}, version={version}) ===
{body}
=== END MIGRATION POLICY ===
"""


def build_model(settings: Settings) -> Any:
    """OpenRouter through Strands' OpenAI-compatible provider."""
    from strands.models.openai import OpenAIModel

    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (see .env.example)")
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


def generation_system_prompt(policy: Policy) -> str:
    return (
        GENERATION_SYSTEM_PROMPT.replace("{name}", policy.name)
        .replace("{version}", str(policy.version))
        .replace("{body}", policy.body)
    )


def build_agent(milestone: Milestone, policy: Policy, settings: Settings) -> Any:
    """The LLM agent for a generation milestone: no tools, active policy in the system
    prompt. Other milestones are deterministic and have no agent."""
    if milestone not in GENERATION_MILESTONES:
        raise ValueError(f"milestone {milestone!r} is deterministic and has no LLM agent")
    from strands import Agent

    return Agent(
        model=build_model(settings),
        tools=[],
        system_prompt=generation_system_prompt(policy),
        callback_handler=None,
        name=f"portpilot-{milestone}",
    )
