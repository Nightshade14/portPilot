"""inspect_source. Owner: Lane C.

Deterministic: reads the Flask fixture, extracts the route table, and keeps
every source file verbatim for the generator. Stored once as a
source_analysis artifact and never recomputed on resume.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from strands import tool

from portpilot.config import FIXTURE_DIR
from portpilot.harness.context import ctx

ROUTE_RE = re.compile(
    r"@app\.(get|post|put|patch|delete|route)\(\s*[\"']([^\"']+)[\"'][^)]*\)\s*\n\s*def\s+(\w+)"
)
STATUS_RE = re.compile(r"\b(4\d\d|5\d\d)\b")
SOURCE_SUFFIXES = {".py", ".txt"}


def analyze_source(source_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    files = sorted(p for p in source_dir.rglob("*") if p.is_file() and p.suffix in SOURCE_SUFFIXES)
    routes: list[dict[str, str]] = []
    statuses: set[int] = set()
    file_docs: list[dict[str, Any]] = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        rel = str(p.relative_to(source_dir))
        file_docs.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
                "content": text,
            }
        )
        if p.suffix == ".py":
            for method, path, handler in ROUTE_RE.findall(text):
                routes.append(
                    {
                        "method": "GET" if method == "route" else method.upper(),
                        "path": re.sub(r"<(?:\w+:)?(\w+)>", r":\1", path),
                        "flask_path": path,
                        "handler": handler,
                    }
                )
            statuses.update(int(s) for s in STATUS_RE.findall(text))
    return {
        "framework": "flask",
        "source_dir": str(source_dir),
        "routes": routes,
        "error_statuses_in_source": sorted(statuses),
        "files": file_docs,
    }


@tool
def inspect_source(run_id: str) -> str:
    """Read the Flask source fixture and store a structured source_analysis artifact
    (routes, fields, coercions, defaults, error handling). Never recomputed on resume.

    Args:
        run_id: The migration run id.

    Returns:
        The source_analysis artifact id.
    """
    store = ctx().store
    existing = store.latest_artifact(run_id, "source_analysis")
    if existing is not None:
        return existing["artifact_id"]
    analysis = analyze_source()
    artifact_id = store.put_artifact(run_id, "source_analysis", 0, analysis)
    store.log_event(
        run_id,
        "tool_result",
        "source_analysis",
        {
            "tool": "inspect_source",
            "artifact_id": artifact_id,
            "routes": [f"{r['method']} {r['path']}" for r in analysis["routes"]],
            "files": [f["path"] for f in analysis["files"]],
        },
    )
    return artifact_id
