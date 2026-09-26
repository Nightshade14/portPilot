"""Small httpx client for the PortPilot HTTP API (docs/api/CONTRACT.md, frozen).

Covers exactly what evals/scenarios.py needs: create a run, get a run, poll
events. Not a full API client -- extend as evals need more surface.
"""

from __future__ import annotations

from typing import Any, Self

import httpx


class PortPilotClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        resp = self._client.get("/api/health")
        resp.raise_for_status()
        return resp.json()

    def create_run(self, repo_url: str, goal: str, budgets: dict[str, Any] | None = None) -> str:
        """POST /api/runs. Returns run_id."""
        body: dict[str, Any] = {"repo_url": repo_url, "goal": goal}
        if budgets is not None:
            body["budgets"] = budgets
        resp = self._client.post("/api/runs", json=body)
        resp.raise_for_status()
        return resp.json()["run_id"]

    def get_run(self, run_id: str) -> dict[str, Any]:
        """GET /api/runs/{run_id}. Returns {"run", "plan", "steps"}."""
        resp = self._client.get(f"/api/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    def get_events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> dict[str, Any]:
        """GET /api/runs/{run_id}/events. Returns {"events", "next_after_seq"}."""
        resp = self._client.get(
            f"/api/runs/{run_id}/events",
            params={"after_seq": after_seq, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    def iter_all_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Page through every event currently recorded for a run."""
        events: list[dict[str, Any]] = []
        after_seq = 0
        while True:
            page = self.get_events(run_id, after_seq=after_seq, limit=limit)
            batch = page["events"]
            events.extend(batch)
            if not batch or page["next_after_seq"] == after_seq:
                break
            after_seq = page["next_after_seq"]
        return events

    def pause_run(self, run_id: str) -> dict[str, Any]:
        resp = self._client.post(f"/api/runs/{run_id}/pause")
        resp.raise_for_status()
        return resp.json()

    def resume_run(self, run_id: str) -> dict[str, Any]:
        resp = self._client.post(f"/api/runs/{run_id}/resume")
        resp.raise_for_status()
        return resp.json()

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        resp = self._client.post(f"/api/runs/{run_id}/cancel")
        resp.raise_for_status()
        return resp.json()
