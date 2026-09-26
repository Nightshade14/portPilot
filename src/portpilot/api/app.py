"""`create_app(deps) -> FastAPI` implementing docs/api/CONTRACT.md exactly. Owner: Lane P."""

from __future__ import annotations

import hmac
import logging
import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from portpilot.api.errors import (
    ApiError,
    conflict,
    invalid_goal,
    invalid_repo_url,
    not_found,
    rate_limited,
    unauthorized,
)
from portpilot.api.rate_limit import RunCreationLimiter
from portpilot.api.serialize import doc
from portpilot.api.shapes import run_summary, tool_summary
from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import KnowledgeStore, NotFound, RunStore, SandboxManager, ToolStore
from portpilot.core.models import (
    TERMINAL_RUN_STATUSES,
    Budgets,
    KnowledgeKind,
    Run,
    SearchMode,
    new_id,
)

logger = logging.getLogger(__name__)

REPO_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?/?$")


@dataclass
class ApiDeps:
    run_store: RunStore
    tool_store: ToolStore
    knowledge: KnowledgeStore
    sandbox: SandboxManager | None
    settings: MvpSettings


class CreateRunBody(BaseModel):
    repo_url: str
    goal: str
    budgets: dict[str, Any] | None = Field(default=None)


def _validate_repo_url(repo_url: str, settings: MvpSettings) -> None:
    if REPO_URL_RE.match(repo_url):
        return
    import os

    if os.environ.get("PORTPILOT_ALLOW_LOCAL_REPOS") == "1":
        from pathlib import Path

        if Path(repo_url).is_absolute():
            return
        raise invalid_repo_url("repo_url must be an absolute local path when allowed")
    raise invalid_repo_url()


def _validate_goal(goal: str) -> None:
    if not (3 <= len(goal) <= 2000):
        raise invalid_goal()


def _require_auth(request: Request, settings: MvpSettings) -> None:
    token = settings.api_token
    if not token:
        # create_app() already refused to start without PORTPILOT_API_INSECURE_DEV=1;
        # reaching here means insecure dev mode, so every request is allowed through.
        return
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise unauthorized()
    supplied = header[len("Bearer ") :]
    if not hmac.compare_digest(supplied, token):
        raise unauthorized()


def _rate_limit_key(request: Request, settings: MvpSettings) -> str:
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    return "insecure-dev"


def create_app(deps: ApiDeps) -> FastAPI:
    """Build the FastAPI app. Refuses to start with no api_token unless
    PORTPILOT_API_INSECURE_DEV=1 (logs a loud warning and allows every request)."""
    settings = deps.settings
    if not settings.api_token:
        import os

        if os.environ.get("PORTPILOT_API_INSECURE_DEV") != "1":
            raise RuntimeError(
                "settings.api_token is unset; refusing to start. "
                "Set PORTPILOT_API_TOKEN, or PORTPILOT_API_INSECURE_DEV=1 for local dev only."
            )
        logger.warning(
            "PORTPILOT_API_INSECURE_DEV=1: starting with NO auth token. "
            "Every route is open. Never use this in production."
        )

    app = FastAPI(title="PortPilot API")
    app.state.deps = deps
    app.state.run_limiter = RunCreationLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api_cors_origins) or [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Contract 422s for POST /runs: distinguish repo_url vs goal errors where we can."""
        for err in exc.errors():
            loc = err.get("loc", ())
            if "repo_url" in loc:
                return JSONResponse(status_code=422, content=invalid_repo_url().detail)
            if "goal" in loc:
                return JSONResponse(status_code=422, content=invalid_goal().detail)
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "bad_request", "message": str(exc)}},
        )

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    def _auth(request: Request) -> None:
        _require_auth(request, settings)

    # ---------------------------------------------------------------- health

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": "0.1.0"}

    # ------------------------------------------------------------------ runs

    @app.post("/api/runs", status_code=201)
    async def create_run(request: Request, body: CreateRunBody) -> dict[str, Any]:
        _auth(request)
        key = _rate_limit_key(request, settings)
        if not app.state.run_limiter.allow(key):
            raise rate_limited()

        _validate_repo_url(body.repo_url, settings)
        _validate_goal(body.goal)

        budgets = Budgets(**body.budgets) if body.budgets else Budgets()
        run = Run(
            run_id=new_id("run"),
            repo_url=body.repo_url,
            goal=body.goal,
            status="queued",
            budgets=budgets,
        )
        deps.run_store.create_run(run)
        deps.run_store.log_event(
            run.run_id, "run_created", payload={"repo_url": run.repo_url, "goal": run.goal}
        )
        return {"run_id": run.run_id}

    @app.get("/api/runs")
    async def list_runs(request: Request, limit: int = 50) -> dict[str, Any]:
        _auth(request)
        runs = deps.run_store.list_runs(limit=limit)
        summaries = [run_summary(r, deps.run_store.steps(r.run_id)) for r in runs]
        return {"runs": summaries}

    @app.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            run = deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        plan = deps.run_store.latest_plan(run_id)
        steps = deps.run_store.steps(run_id)
        return {
            "run": doc(run),
            "plan": doc(plan) if plan is not None else None,
            "steps": [doc(s) for s in steps],
        }

    @app.get("/api/runs/{run_id}/steps/{step_id}")
    async def get_step(request: Request, run_id: str, step_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            step = deps.run_store.get_step(step_id)
        except NotFound:
            raise not_found(f"step {step_id} not found") from None
        if step.run_id != run_id:
            raise not_found(f"step {step_id} not found on run {run_id}")
        return {"step": doc(step)}

    @app.get("/api/runs/{run_id}/events")
    async def get_events(
        request: Request, run_id: str, after_seq: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        _auth(request)
        try:
            deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        events = deps.run_store.events(run_id, after_seq=after_seq, limit=limit)
        next_after_seq = events[-1]["seq"] if events else after_seq
        return {
            "events": [
                {
                    "run_id": e["run_id"],
                    "seq": e["seq"],
                    "ts": doc_ts(e["ts"]),
                    "type": e["type"],
                    "step_id": e["step_id"],
                    "payload": e["payload"],
                }
                for e in events
            ],
            "next_after_seq": next_after_seq,
        }

    def _control(run_id: str, control_value: str, immediate_status: dict[str, str]) -> Run:
        try:
            run = deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        new_status = immediate_status.get(run.status)
        if new_status is not None:
            deps.run_store.update_run(run_id, status=new_status, control=None)
        else:
            deps.run_store.update_run(run_id, control=control_value)
        return deps.run_store.get_run(run_id)

    @app.post("/api/runs/{run_id}/pause")
    async def pause_run(request: Request, run_id: str) -> dict[str, Any]:
        _auth(request)
        # A queued run goes straight to paused; anything else gets control="pause"
        # and the worker stops at its next tool boundary.
        run = _control(run_id, "pause", {"queued": "paused"})
        deps.run_store.log_event(run_id, "paused" if run.status == "paused" else "note")
        return {"ok": True, "status": run.status}

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(request: Request, run_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            run = deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        if run.status != "paused":
            raise conflict(f"run {run_id} is {run.status!r}, not paused")
        deps.run_store.update_run(run_id, status="queued", control=None)
        deps.run_store.log_event(run_id, "resumed")
        run = deps.run_store.get_run(run_id)
        return {"ok": True, "status": run.status}

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(request: Request, run_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            run = deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        if run.status in TERMINAL_RUN_STATUSES:
            raise conflict(f"run {run_id} is already {run.status!r}")
        # A queued or paused run goes straight to cancelled; a running one gets
        # control="cancel" and the worker sets status=cancelled itself.
        if run.status in ("queued", "paused"):
            deps.run_store.update_run(run_id, status="cancelled", control=None)
            deps.run_store.log_event(run_id, "cancelled")
        else:
            deps.run_store.update_run(run_id, control="cancel")
        run = deps.run_store.get_run(run_id)
        return {"ok": True, "status": run.status}

    # ------------------------------------------------------------- artifacts

    @app.get("/api/runs/{run_id}/artifacts")
    async def list_artifacts(request: Request, run_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        metas = deps.run_store.list_artifacts(run_id)
        return {"artifacts": [_jsonable_artifact_meta(m) for m in metas]}

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    async def get_artifact(request: Request, run_id: str, artifact_id: str) -> dict[str, Any]:
        _auth(request)
        try:
            artifact = deps.run_store.get_artifact(artifact_id)
        except NotFound:
            raise not_found(f"artifact {artifact_id} not found") from None
        if artifact["run_id"] != run_id:
            raise not_found(f"artifact {artifact_id} not found on run {run_id}")
        return {"artifact": _jsonable_artifact(artifact)}

    @app.get("/api/runs/{run_id}/download")
    async def download_run(request: Request, run_id: str) -> Response:
        _auth(request)
        try:
            deps.run_store.get_run(run_id)
        except NotFound:
            raise not_found(f"run {run_id} not found") from None
        if deps.sandbox is None:
            raise ApiError(503, "bad_request", "no sandbox is configured")
        archive = deps.sandbox.export_archive(run_id)
        return Response(
            content=archive,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.tar.gz"'},
        )

    # ----------------------------------------------------------------- tools

    @app.get("/api/tools")
    async def list_tools(request: Request, status: str | None = None) -> dict[str, Any]:
        _auth(request)
        latest = deps.tool_store.list_tools(status=status)  # type: ignore[arg-type]
        summaries = []
        for tool in latest:
            versions_count = len(deps.tool_store.versions(tool.name))
            summaries.append(tool_summary(tool, versions_count))
        return {"tools": summaries}

    @app.get("/api/tools/{name}")
    async def get_tool(request: Request, name: str) -> dict[str, Any]:
        _auth(request)
        versions = deps.tool_store.versions(name)
        if not versions:
            raise not_found(f"tool {name} not found")
        return {"name": name, "versions": [doc(v) for v in versions]}

    # ------------------------------------------------------------- knowledge

    @app.get("/api/knowledge/search")
    async def search_knowledge(
        request: Request,
        q: str,
        kinds: str | None = None,
        mode: SearchMode = "hybrid",
        limit: int = 10,
    ) -> dict[str, Any]:
        _auth(request)
        kind_list: list[KnowledgeKind] | None = (
            [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None  # type: ignore[list-item]
        )
        hits = deps.knowledge.search(q, kinds=kind_list, mode=mode, limit=limit)
        return {"hits": [{"item": doc(h.item), "score": h.score, "via": h.via} for h in hits]}

    @app.get("/api/knowledge")
    async def list_knowledge(
        request: Request, kinds: str | None = None, run_id: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        _auth(request)
        kind_list: list[KnowledgeKind] | None = (
            [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None  # type: ignore[list-item]
        )
        items = deps.knowledge.list_items(kinds=kind_list, run_id=run_id, limit=limit)
        return {"items": [doc(i) for i in items]}

    return app


def doc_ts(value: Any) -> Any:
    """ISO-format a single timestamp value the same way `serialize.doc` would."""
    from portpilot.api.serialize import to_jsonable

    return to_jsonable(value)


def _jsonable_artifact_meta(meta: dict[str, Any]) -> dict[str, Any]:
    from portpilot.api.serialize import to_jsonable

    return {
        "artifact_id": meta["artifact_id"],
        "run_id": meta["run_id"],
        "step_id": meta["step_id"],
        "kind": meta["kind"],
        "name": meta["name"],
        "created_at": to_jsonable(meta["created_at"]),
    }


def _jsonable_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    out = _jsonable_artifact_meta(artifact)
    out["content"] = artifact["content"]
    return out


__all__ = ["ApiDeps", "create_app"]
