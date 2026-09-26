"""MVP frozen interfaces (MVP_PLAN section 5). Owner: Lead.

Every lane codes against these protocols and the models in `core.models`. Changing a
signature needs the Lead: stop and report instead of editing this file from a lane.

All methods are synchronous (the agent loop and tools call them from worker threads);
Atlas implementations may wrap an async client internally (see v0 `store/atlas.py`).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from portpilot.core.models import (
    ExecResult,
    Hit,
    InstallResult,
    KnowledgeItem,
    KnowledgeKind,
    LongTermPlan,
    PromotionDecision,
    Run,
    SearchMode,
    ShortTermPlan,
    ToolCard,
    ToolRecord,
    ToolStatus,
    ValidationReport,
)

if TYPE_CHECKING:  # pragma: no cover
    from strands.sandbox import Sandbox
    from strands.types.tools import AgentTool


class NotFound(KeyError):
    """Raised by stores when a requested document does not exist."""


class Conflict(RuntimeError):
    """Raised on a unique-key violation (e.g. a duplicate tool version or step seq)."""


class Refused(PermissionError):
    """Raised when a guardrail refuses an action (allow-list, budget, lease lost)."""


# ------------------------------------------------------------------ state (Lane M)


@runtime_checkable
class RunStore(Protocol):
    def create_run(self, run: Run) -> str: ...
    def get_run(self, run_id: str) -> Run: ...
    def list_runs(self, limit: int = 50) -> list[Run]: ...
    def update_run(self, run_id: str, **fields: Any) -> None:
        """Set top-level fields (dataclass values are serialized). Bumps updated_at."""

    # Lease: exactly one worker drives a run. claim_run picks the oldest run that is
    # queued, or running/paused-for-resume with an expired lease, and leases it.
    def claim_run(self, worker_id: str, lease_s: int = 60) -> Run | None: ...
    def heartbeat(self, run_id: str, worker_id: str, lease_s: int = 60) -> bool:
        """Extend the lease. False means the lease was lost: stop working on the run."""

    def release(self, run_id: str, worker_id: str) -> None: ...

    def save_plan(self, plan: LongTermPlan) -> None: ...
    def latest_plan(self, run_id: str) -> LongTermPlan | None: ...

    def save_step(self, step: ShortTermPlan) -> None:
        """Insert or replace by step_id. (run_id, seq) is unique."""

    def get_step(self, step_id: str) -> ShortTermPlan: ...
    def update_step(self, step_id: str, **fields: Any) -> None: ...
    def steps(self, run_id: str) -> list[ShortTermPlan]:
        """Ordered by seq."""

    def log_event(
        self, run_id: str, type: str, step_id: str | None = None, payload: dict | None = None
    ) -> int:
        """Append an event and return its per-run seq (1, 2, 3, ...)."""

    def events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        """Events with seq > after_seq, ascending. Each: {run_id, seq, ts, type, step_id, payload}."""

    def put_artifact(
        self, run_id: str, step_id: str | None, kind: str, content: Any, name: str = ""
    ) -> str:
        """Store JSON-able content (large bytes/str go to GridFS). Returns artifact_id."""

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        """{artifact_id, run_id, step_id, kind, name, created_at, content}."""

    def list_artifacts(self, run_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        """Metadata only (no content), ascending by created_at."""


@runtime_checkable
class ToolStore(Protocol):
    """Persistence for library tools. Lane T owns the lifecycle logic on top."""

    def save(self, record: ToolRecord) -> None:
        """Insert a new (name, version); raises Conflict if it exists."""

    def get(self, name: str, version: int | None = None) -> ToolRecord:
        """version=None returns the active version; NotFound if none."""

    def versions(self, name: str) -> list[ToolRecord]: ...
    def list_tools(self, status: ToolStatus | None = None) -> list[ToolRecord]:
        """Latest version per name (optionally filtered by that version's status)."""

    def set_status(self, name: str, version: int, status: ToolStatus) -> None: ...
    def record_use(self, name: str, version: int, run_id: str, ok: bool) -> None: ...
    def next_version(self, name: str) -> int: ...


# -------------------------------------------------------------- knowledge (Lane K)


@runtime_checkable
class Embedder(Protocol):
    model: str
    dims: int

    def embed(
        self, texts: list[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]: ...


@runtime_checkable
class KnowledgeStore(Protocol):
    def upsert(self, item: KnowledgeItem, dedupe: bool = True) -> str:
        """Insert, or merge into a near-duplicate of the same kind (seen_count += 1,
        sources appended). Returns the id of the stored item. Embedding is computed here."""

    def get(self, item_id: str) -> KnowledgeItem: ...
    def search(
        self,
        query: str,
        *,
        kinds: list[KnowledgeKind] | None = None,
        mode: SearchMode = "hybrid",
        filters: dict[str, Any]
        | None = None,  # e.g. {"facets.language": "python", "status": "active"}
        limit: int = 8,
    ) -> list[Hit]: ...

    def list_items(
        self, kinds: list[KnowledgeKind] | None = None, run_id: str | None = None, limit: int = 100
    ) -> list[KnowledgeItem]: ...

    def set_status(self, item_id: str, status: str) -> None: ...


# ---------------------------------------------------------------- sandbox (Lane S)


@runtime_checkable
class SandboxManager(Protocol):
    """One container + named volume per run. The worker never runs repo code itself."""

    def ensure(self, run_id: str, repo_url: str | None = None) -> str:
        """Create or re-attach (restart) the run's container; clone repo_url into
        /workspace/repo on first creation and create branch portpilot/<run_id>.
        Idempotent. Returns the container name."""

    def exec(
        self,
        run_id: str,
        command: str,
        *,
        timeout_s: int = 600,
        cwd: str = "/workspace/repo",
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> ExecResult: ...

    def write_file(self, run_id: str, path: str, content: str) -> None: ...
    def read_file(self, run_id: str, path: str) -> str: ...

    def sandbox(self, run_id: str) -> Sandbox:
        """A strands Sandbox (DockerSandbox) bound to the run's container, for the vended
        sandbox_shell / sandbox_file_editor tools."""

    def commit(self, run_id: str, message: str) -> str:
        """git add -A + commit in /workspace/repo on portpilot/<run_id>; returns SHA
        (returns HEAD unchanged when there is nothing to commit)."""

    def restore(self, run_id: str, sha: str) -> None:
        """git reset --hard <sha> + git clean -fd in /workspace/repo."""

    def export_archive(self, run_id: str) -> bytes:
        """tar.gz of the workspace branch (git archive), for the download endpoint."""

    def stop(self, run_id: str) -> None: ...
    def destroy(self, run_id: str) -> None: ...


@runtime_checkable
class CliInstaller(Protocol):
    def check_environment(self, run_id: str) -> dict[str, Any]:
        """{os, arch, disk_free_mb, mem_mb, installed: {name: version}, allowlisted: [names],
        repo_languages: {...}}."""

    def install(self, run_id: str, name: str) -> InstallResult:
        """Only names in config/cli_allowlist.yaml with a sha256 for the arch; pinned
        version; checksum verified; idempotent. Never raises for refusals (refused=True)."""

    def allowlist(self) -> dict[str, dict[str, Any]]: ...


# ------------------------------------------------------------ tool library (Lane T)


@runtime_checkable
class ToolLibrary(Protocol):
    def propose(self, draft: ToolRecord, run_id: str | None, step_id: str | None) -> ToolRecord:
        """Assign version (next_version), set status=candidate, provenance; persist."""

    def validate(self, name: str, version: int, run_id: str) -> ValidationReport:
        """Lint, schema checks, the tool's tests and a smoke call, all in the run's sandbox."""

    def promote(self, name: str, version: int, run_id: str) -> PromotionDecision:
        """Active only if validation passed AND the previous active version's tests pass
        against the new version. Writes the tool card into knowledge."""

    def candidates(
        self, query: str, filters: dict[str, Any] | None = None, limit: int = 20
    ) -> list[ToolCard]:
        """Active library tools + selectable built-ins, ranked by hybrid search."""

    def as_agent_tool(self, record: ToolRecord, run_id: str) -> AgentTool:
        """A SandboxScriptTool proxy executing `pp-tool-run` in the run's sandbox."""

    def record_use(
        self, name: str, version: int, run_id: str, ok: bool, note: str = ""
    ) -> None: ...


# ------------------------------------------------------------------------ misc


class Clock(Protocol):
    def now(self) -> datetime: ...
