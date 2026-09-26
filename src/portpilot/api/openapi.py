"""`python -m portpilot.api.openapi` writes docs/api/openapi.json (lane-p.md).

Uses in-memory deps and insecure-dev mode purely to construct the FastAPI app for
schema export; it starts nothing and makes no network/DB calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from portpilot.api.app import ApiDeps, create_app
from portpilot.core.config import MvpSettings

OUTPUT_PATH = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def _build_app_for_export():
    from portpilot.core.fakes import InMemoryKnowledgeStore, InMemoryRunStore, InMemoryToolStore

    os.environ.setdefault("PORTPILOT_API_INSECURE_DEV", "1")
    settings = MvpSettings(
        mongodb_uri=None,
        mongodb_db="portpilot_mvp",
        openrouter_api_key=None,
        openrouter_base_url="https://openrouter.ai/api/v1",
        model_id="anthropic/claude-sonnet-4.5",
        model_id_aux="google/gemini-2.5-flash-lite",
        model_temperature=0.1,
        voyage_api_key=None,
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=1024,
        api_token=None,
        api_cors_origins=(),
        sandbox_image="portpilot-sandbox:dev",
        buildkit_addr=None,
        worker_id="openapi-export",
        lease_seconds=60,
        store_backend="memory",
    )
    deps = ApiDeps(
        run_store=InMemoryRunStore(),
        tool_store=InMemoryToolStore(),
        knowledge=InMemoryKnowledgeStore(),
        sandbox=None,
        settings=settings,
    )
    return create_app(deps)


def main() -> None:
    app = _build_app_for_export()
    schema = app.openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
