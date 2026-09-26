"""Goal 7: cheap secondary model -- structured output + summarization test."""

from __future__ import annotations

import json
import time

from common import load_env
from pydantic import BaseModel
from strands import Agent
from strands.models.openai import OpenAIModel

CANDIDATES = ["anthropic/claude-haiku-4.5", "google/gemini-2.5-flash-lite"]


class StepVerdict(BaseModel):
    """Small structured-output target, matching an STP-reflection-shaped model."""

    passed: bool
    summary: str
    risk_level: str  # "low" | "medium" | "high"


TRANSCRIPT_3K = "You are reviewing a migration run transcript.\n\n" + "\n".join(
    f"[step {i}] agent ran `pytest tests/module_{i}.py`, "
    f"{'all green' if i % 3 else 'one flaky test retried and passed'}, "
    f"then edited src/module_{i}.py to translate the Flask route to a Hono handler, "
    f"then called complete_step; harness verification: PASS."
    for i in range(1, 55)
)  # ~3k tokens of synthetic transcript


def test_structured_output(env: dict[str, str], model_id: str) -> dict:
    model = OpenAIModel(
        client_args={"api_key": env["OPENROUTER_API_KEY"], "base_url": env["OPENROUTER_BASE_URL"]},
        model_id=model_id,
        params={"temperature": 0.0},
    )
    agent = Agent(
        model=model, tools=[], system_prompt="You are a terse migration-review assistant."
    )
    t0 = time.monotonic()
    try:
        result = agent.structured_output(
            StepVerdict,
            "The step passed all acceptance checks with no flaky tests, low risk. Summarize in one short sentence.",
        )
        elapsed = time.monotonic() - t0
        return {
            "ok": True,
            "elapsed_s": round(elapsed, 2),
            "passed": result.passed,
            "risk_level": result.risk_level,
            "summary": result.summary,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def test_summarization(env: dict[str, str], model_id: str) -> dict:
    model = OpenAIModel(
        client_args={"api_key": env["OPENROUTER_API_KEY"], "base_url": env["OPENROUTER_BASE_URL"]},
        model_id=model_id,
        params={"temperature": 0.1},
    )
    agent = Agent(
        model=model, tools=[], system_prompt="You summarize transcripts in under 80 words."
    )
    t0 = time.monotonic()
    try:
        result = agent(f"Summarize this transcript in under 80 words:\n\n{TRANSCRIPT_3K}")
        elapsed = time.monotonic() - t0
        usage = result.metrics.accumulated_usage
        return {
            "ok": True,
            "elapsed_s": round(elapsed, 2),
            "input_tokens": usage["inputTokens"],
            "output_tokens": usage["outputTokens"],
            "summary": str(result).strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    env = load_env()
    out = {}
    for model_id in CANDIDATES:
        out[model_id] = {
            "structured_output": test_structured_output(env, model_id),
            "summarization": test_summarization(env, model_id),
        }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
