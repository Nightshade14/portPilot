"""Frozen core models (plan section 4.3). Owner: Lead.

Changes to this file need a heads-up in team chat: every lane builds against it.
Models are plain dataclasses so they serialize to Mongo documents via `to_doc`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, get_args

Milestone = Literal[
    "source_analysis",
    "generation",
    "test",
    "diagnosis",
    "candidate_policy",
    "regeneration",
    "retest",
    "evaluation",
    "completion",
]
MILESTONES: tuple[Milestone, ...] = get_args(Milestone)

RunStatus = Literal["running", "paused", "completed", "failed"]
PolicyStatus = Literal["active", "candidate", "retired", "rejected"]
ArtifactKind = Literal[
    "source_analysis",
    "target_version",
    "test_output",
    "diagnosis",
    "candidate_policy",
    "evaluation",
]
ARTIFACT_KINDS: tuple[ArtifactKind, ...] = get_args(ArtifactKind)

# Milestones after which `portpilot run --pause-after` may stop (charter E).
PAUSABLE_MILESTONES: tuple[Milestone, ...] = ("diagnosis", "candidate_policy")


class _Doc:
    def to_doc(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass
class HttpObservation(_Doc):
    status: int
    json: Any


@dataclass
class CaseResult(_Doc):
    """Outcome of one contract case, source vs target."""

    case_id: str
    category: str
    passed: bool
    source: dict[str, Any]  # {"status": int, "json": Any}
    target: dict[str, Any]  # {"status": int, "json": Any}; {"error": str} if unreachable
    diff: list[str] = field(default_factory=list)  # human-readable mismatches

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> CaseResult:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class ContractResult(_Doc):
    """One full suite execution against one target."""

    run_id: str
    attempt: int
    policy_version: int
    passed: int
    total: int
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed_ids(self) -> set[str]:
        return {c.case_id for c in self.cases if c.passed}

    @property
    def failed_ids(self) -> set[str]:
        return {c.case_id for c in self.cases if not c.passed}

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> ContractResult:
        return cls(
            run_id=d["run_id"],
            attempt=d["attempt"],
            policy_version=d["policy_version"],
            passed=d["passed"],
            total=d["total"],
            cases=[CaseResult.from_doc(c) for c in d.get("cases", [])],
        )


@dataclass
class Diagnosis(_Doc):
    run_id: str
    attempt: int
    categories: list[str]  # e.g. ["error_status_and_schema"]
    failed_case_ids: list[str]
    rationale: str

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> Diagnosis:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


@dataclass
class Policy(_Doc):
    name: str  # "flask-to-hono"
    version: int
    status: PolicyStatus
    body: str  # markdown instructions injected into generation
    rules: list[str] = field(default_factory=list)
    parent_version: int | None = None
    rationale: str | None = None
    decision: dict[str, Any] | None = None  # promotion/rejection evidence

    @classmethod
    def from_doc(cls, d: dict[str, Any]) -> Policy:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Decision(_Doc):
    """Result of evaluate_policy. Promotion rule lives in code, never in the LLM."""

    run_id: str
    baseline_attempt: int
    candidate_attempt: int
    baseline_version: int
    candidate_version: int
    baseline_passed: int
    candidate_passed: int
    total: int
    regressions: list[str]  # case ids passing under baseline, failing under candidate
    fixed: list[str]  # case ids failing under baseline, passing under candidate
    promoted: bool
    reason: str
