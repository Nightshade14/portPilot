"""docs/api/openapi.json must match the schema `create_app` currently produces."""

from __future__ import annotations

import json

from portpilot.api.openapi import OUTPUT_PATH, _build_app_for_export


def test_openapi_file_is_up_to_date() -> None:
    app = _build_app_for_export()
    current_schema = app.openapi()
    assert OUTPUT_PATH.exists(), f"{OUTPUT_PATH} is missing; run `python -m portpilot.api.openapi`"
    on_disk = json.loads(OUTPUT_PATH.read_text())
    assert on_disk == current_schema, (
        "docs/api/openapi.json is stale; regenerate with `python -m portpilot.api.openapi`"
    )
