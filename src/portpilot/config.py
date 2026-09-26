"""Environment configuration. Owner: Lead.

All settings come from the process environment (optionally a local `.env`).
Nothing here has secret defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

FIXTURE_DIR = REPO_ROOT / "fixtures" / "flask-profile-api"
REFERENCE_TARGETS_DIR = REPO_ROOT / "fixtures" / "reference-targets"
CONTRACTS_DIR = REPO_ROOT / "contracts" / "profile-api" / "v1"
CASES_PATH = CONTRACTS_DIR / "cases.json"
GOLDEN_PATH = CONTRACTS_DIR / "golden.json"
TEMPLATE_DIR = REPO_ROOT / "templates" / "hono-empty"
POLICIES_DIR = REPO_ROOT / "policies"
RUNS_DIR = REPO_ROOT / "runs"

POLICY_NAME = "flask-to-hono"


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str | None
    mongodb_db: str
    openrouter_api_key: str | None
    openrouter_base_url: str
    model_id: str
    model_temperature: float
    store_backend: str  # "memory" | "atlas"
    source_port: int
    target_port: int


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI") or None,
        mongodb_db=os.getenv("MONGODB_DB", "portpilot"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model_id=os.getenv("MODEL_ID", "anthropic/claude-sonnet-4.5"),
        model_temperature=float(os.getenv("MODEL_TEMPERATURE", "0.1")),
        store_backend=os.getenv("PORTPILOT_STORE", "memory"),
        source_port=int(os.getenv("SOURCE_PORT", "5001")),
        target_port=int(os.getenv("TARGET_PORT", "8787")),
    )


def target_dir(run_id: str, attempt: int, policy_version: int) -> Path:
    """Fresh, empty-at-start directory for one generated target (plan section 3)."""
    return RUNS_DIR / run_id / f"attempt-{attempt}-policy-v{policy_version}" / "target"
