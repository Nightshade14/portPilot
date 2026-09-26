"""MVP settings (env-driven; no secret defaults). Owner: Lead.

`load_mvp_settings()` reads the process env, loading the repo `.env` first when present.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_ALLOWLIST_PATH = REPO_ROOT / "config" / "cli_allowlist.yaml"
SANDBOX_DOCKERFILE_DIR = REPO_ROOT / "docker" / "sandbox"
WORKSPACES_DIR = REPO_ROOT / "runs" / "mvp"


@dataclass(frozen=True)
class MvpSettings:
    mongodb_uri: str | None
    mongodb_db: str
    openrouter_api_key: str | None
    openrouter_base_url: str
    model_id: str  # executor + planner
    model_id_aux: str  # selector, reflection, digest, summarizer
    model_temperature: float
    voyage_api_key: str | None
    voyage_base_url: str
    embedding_model: str
    embedding_dims: int
    api_token: str | None
    api_cors_origins: tuple[str, ...]
    sandbox_image: str
    buildkit_addr: str | None
    worker_id: str
    lease_seconds: int
    store_backend: str  # "atlas" | "memory"


def load_mvp_settings(env_file: Path | None = None) -> MvpSettings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    env = os.environ.get
    return MvpSettings(
        mongodb_uri=env("MONGODB_URI") or None,
        mongodb_db=env("MVP_MONGODB_DB", "portpilot_mvp"),  # v0 uses MONGODB_DB
        openrouter_api_key=env("OPENROUTER_API_KEY") or None,
        openrouter_base_url=env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model_id=env("MODEL_ID", "anthropic/claude-sonnet-4.5"),
        model_id_aux=env("MODEL_ID_AUX", "google/gemini-2.5-flash-lite"),
        model_temperature=float(env("MODEL_TEMPERATURE", "0.1")),
        voyage_api_key=env("VOYAGE_API_KEY") or None,
        voyage_base_url=env("VOYAGE_BASE_URL", "https://api.voyageai.com/v1"),
        embedding_model=env("EMBEDDING_MODEL", "voyage-4"),
        embedding_dims=int(env("EMBEDDING_DIMS", "1024")),
        api_token=env("PORTPILOT_API_TOKEN") or None,
        api_cors_origins=tuple(
            o.strip() for o in env("PORTPILOT_CORS_ORIGINS", "").split(",") if o.strip()
        ),
        sandbox_image=env("SANDBOX_IMAGE", "portpilot-sandbox:dev"),
        buildkit_addr=env("BUILDKIT_ADDR") or None,
        worker_id=env("WORKER_ID", f"worker-{os.getpid()}"),
        lease_seconds=int(env("LEASE_SECONDS", "60")),
        store_backend=env("PORTPILOT_MVP_STORE", "atlas"),
    )
