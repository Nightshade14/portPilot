"""MVP core models (MVP_PLAN section 5). Owner: Lead. Frozen: lanes build against it.

Plain dataclasses that serialize to Mongo documents with `to_doc()` and are rebuilt
with `Cls.from_doc(doc)`. Timestamps are timezone-aware UTC datetimes. Ids are
strings generated with `new_id(prefix)`.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any, Literal, get_args, get_type_hints

RunStatus = Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
RUN_STATUSES: tuple[RunStatus, ...] = get_args(RunStatus)
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

StepStatus = Literal[
    "planned", "selecting_tools", "running", "verifying", "reflecting", "done", "failed", "skipped"
]
STEP_STATUSES: tuple[StepStatus, ...] = get_args(StepStatus)
TERMINAL_STEP_STATUSES: frozenset[str] = frozenset({"done", "failed", "skipped"})

KnowledgeKind = Literal["lesson", "gotcha", "memory", "tool_card", "run_digest"]
KNOWLEDGE_KINDS: tuple[KnowledgeKind, ...] = get_args(KnowledgeKind)

ToolStatus = Literal["draft", "candidate", "active", "deprecated", "rejected"]
TOOL_STATUSES: tuple[ToolStatus, ...] = get_args(ToolStatus)

SearchMode = Literal["hybrid", "vector", "text"]

EventType = Literal[
    "run_created",
    "lease_acquired",
    "resumed",
    "paused",
    "cancelled",
    "completed",
    "failed",
    "survey_done",
    "plan_created",
    "plan_revised",
    "step_planned",
    "step_started",
    "step_verified",
    "step_failed",
    "tools_selected",
    "tool_loaded",
    "tool_call",
    "tool_result",
    "tool_error",
    "tool_created",
    "tool_validated",
    "tool_promoted",
    "tool_rejected",
    "tool_deprecated",
    "cli_checked",
    "cli_installed",
    "cli_refused",
    "compaction",
    "checkpoint",
    "lesson_recorded",
    "gotcha_recorded",
    "budget_exceeded",
    "note",
]
EVENT_TYPES: tuple[EventType, ...] = get_args(EventType)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class _Doc:
    """Mixin: dataclass <-> Mongo document (nested dataclasses and lists of them)."""

    def to_doc(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_doc(cls, doc: dict[str, Any]):
        hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        for key, value in doc.items():
            if key not in names:
                continue  # tolerate _id and fields added later
            kwargs[key] = _coerce(hints.get(key), value)
        return cls(**kwargs)


def _coerce(hint: Any, value: Any) -> Any:
    if value is None or hint is None:
        return value
    origin = getattr(hint, "__origin__", None)
    if isinstance(hint, type) and is_dataclass(hint) and isinstance(value, dict):
        return hint.from_doc(value)  # type: ignore[attr-defined]
    if origin is list and isinstance(value, list):
        (inner,) = getattr(hint, "__args__", (Any,))
        return [_coerce(inner, v) for v in value]
    args = getattr(hint, "__args__", ())
    if args and origin is not list and origin is not dict:  # Optional[X] / X | None
        for arg in args:
            if isinstance(arg, type) and is_dataclass(arg) and isinstance(value, dict):
                return arg.from_doc(value)  # type: ignore[attr-defined]
    return value


# --------------------------------------------------------------------- runs & plans


@dataclass
class Lease(_Doc):
    owner: str
    expires_at: datetime


@dataclass
class Budgets(_Doc):
    max_steps: int = 40
    max_tokens: int = 3_000_000
    max_minutes: int = 240
    max_tools_created: int = 10
    max_selected_tools: int = 8
    max_mid_step_loads: int = 3


@dataclass
class Usage(_Doc):
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    compactions: int = 0

    def add(self, other: Usage) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))


@dataclass
class Run(_Doc):
    run_id: str
    repo_url: str
    goal: str
    status: RunStatus = "queued"
    current_step_id: str | None = None
    ltp_version: int = 0
    lease: Lease | None = None
    budgets: Budgets = field(default_factory=Budgets)
    usage: Usage = field(default_factory=Usage)
    cli_manifest: list[dict[str, Any]] = field(default_factory=list)  # [{name, version}]
    tool_pins: dict[str, int] = field(default_factory=dict)  # tool name -> version used
    control: str | None = None  # "pause" | "cancel" requested by the UI
    error: str | None = None
    workspace_branch: str = ""
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class Phase(_Doc):
    id: str
    title: str
    goal: str
    exit_criteria: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)


@dataclass
class LongTermPlan(_Doc):
    run_id: str
    version: int
    goal: str
    phases: list[Phase]
    assumptions: list[str] = field(default_factory=list)
    rationale: str = ""
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Check(_Doc):
    """An acceptance check the harness runs in the sandbox (never trusted from the agent)."""

    name: str
    command: str
    expect_exit: int = 0
    timeout_s: int = 600


@dataclass
class StepBudget(_Doc):
    max_turns: int = 40
    max_tokens: int = 400_000
    max_minutes: int = 45


@dataclass
class ToolPick(_Doc):
    name: str
    version: int
    reason: str
    used: bool = False
    helpful: bool | None = None


@dataclass
class ShortTermPlan(_Doc):
    step_id: str
    run_id: str
    seq: int
    phase_id: str
    title: str
    objective: str
    inputs: list[str] = field(default_factory=list)  # files / modules in scope
    acceptance: list[Check] = field(default_factory=list)
    capability_hints: list[str] = field(default_factory=list)
    budget: StepBudget = field(default_factory=StepBudget)
    status: StepStatus = "planned"
    selected_tools: list[ToolPick] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    attempts: int = 0
    commit_sha: str | None = None
    outcome: str | None = None
    usage: Usage = field(default_factory=Usage)
    started_at: datetime | None = None
    ended_at: datetime | None = None


# -------------------------------------------------------------------------- tools


@dataclass
class ToolProvenance(_Doc):
    run_id: str | None = None
    step_id: str | None = None
    repo_url: str | None = None
    parent_version: int | None = None
    author: Literal["agent", "seed"] = "agent"


@dataclass
class ToolStats(_Doc):
    uses: int = 0
    successes: int = 0
    failures: int = 0
    runs_used_in: list[str] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        return self.failures / self.uses if self.uses else 0.0


@dataclass
class ToolRecord(_Doc):
    """A library tool version. `files` must contain `main.py` defining
    `run(params: dict) -> dict`; `tests` holds pytest files run in the sandbox."""

    name: str  # snake_case, [a-z][a-z0-9_]{2,47}
    version: int
    description: str
    when_to_use: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    files: dict[str, str]
    tests: dict[str, str] = field(default_factory=dict)
    requires_cli: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: ToolStatus = "draft"
    provenance: ToolProvenance = field(default_factory=ToolProvenance)
    stats: ToolStats = field(default_factory=ToolStats)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ToolCard(_Doc):
    """What the selector sees: small, embedded into `knowledge` as kind=tool_card."""

    name: str
    version: int
    description: str
    when_to_use: str
    tags: list[str] = field(default_factory=list)
    uses: int = 0
    failure_rate: float = 0.0
    builtin: bool = False
    score: float = 0.0


@dataclass
class ValidationReport(_Doc):
    name: str
    version: int
    ok: bool
    checks: list[dict[str, Any]] = field(default_factory=list)  # [{name, ok, output}]
    error: str | None = None


@dataclass
class PromotionDecision(_Doc):
    name: str
    version: int
    promoted: bool
    reason: str
    previous_active: int | None = None


# ---------------------------------------------------------------------- knowledge


@dataclass
class KnowledgeSource(_Doc):
    run_id: str | None = None
    step_id: str | None = None
    repo_url: str | None = None


@dataclass
class KnowledgeItem(_Doc):
    id: str
    kind: KnowledgeKind
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    facets: dict[str, str] = field(default_factory=dict)  # language, framework, ecosystem, tool
    sources: list[KnowledgeSource] = field(default_factory=list)
    seen_count: int = 1
    status: str = "active"
    ref: str | None = None  # e.g. "tool:<name>@<version>" for tool cards
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class Hit(_Doc):
    item: KnowledgeItem
    score: float
    via: Literal["vector", "text", "both"]


# ------------------------------------------------------------------ sandbox / CLIs


@dataclass
class ExecResult(_Doc):
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float = 0.0
    timed_out: bool = False


@dataclass
class InstallResult(_Doc):
    name: str
    ok: bool
    version: str | None = None
    already_installed: bool = False
    refused: bool = False
    reason: str | None = None
