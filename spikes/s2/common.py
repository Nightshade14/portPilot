"""Shared helpers for the S2 Strands spike scripts."""

from __future__ import annotations

from dotenv import dotenv_values
from strands.models.openai import OpenAIModel

ENV_PATH = "/Users/satyamchatrola/codes/personal/portPilot/.env"


def load_env() -> dict[str, str]:
    values = dotenv_values(ENV_PATH)
    missing = [
        k for k in ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "MODEL_ID") if not values.get(k)
    ]
    if missing:
        raise RuntimeError(f"missing required .env keys: {missing}")
    return values


def make_model(
    env: dict[str, str], *, temperature: float = 0.1, model_id: str | None = None
) -> OpenAIModel:
    return OpenAIModel(
        client_args={"api_key": env["OPENROUTER_API_KEY"], "base_url": env["OPENROUTER_BASE_URL"]},
        model_id=model_id or env["MODEL_ID"],
        params={"temperature": temperature},
    )
