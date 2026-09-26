"""Lane C: harness tools + orchestrator, end to end on InMemoryStore.

The LLM is replaced by a deterministic generator that returns the
hand-written reference targets' src/ (v1 -> hono-v1-miss, v2 -> hono-good).
That exercises every real component -- workspace prep, tsc, service boot,
contract suite, diagnosis, candidate policy, evaluation, pause/resume --
without a model call. Reference output is test-only and never presented as
generated output.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from portpilot.config import POLICY_NAME, REFERENCE_TARGETS_DIR, TEMPLATE_DIR
from portpilot.harness import orchestrator
from portpilot.harness.agent import build_agent, generation_system_prompt, milestone_tools
from portpilot.harness.context import bind
from portpilot.harness.generation import (
    GenerationError,
    GenerationRequest,
    build_user_prompt,
    validate_files,
)
from portpilot.harness.tools.inspect_source import analyze_source
from portpilot.models import MILESTONES, Policy
from portpilot.store.memory import InMemoryStore

needs_node = pytest.mark.skipif(shutil.which("npx") is None, reason="node/npx not installed")


def _read_src(target: str) -> dict[str, str]:
    root = REFERENCE_TARGETS_DIR / target
    return {str(p.relative_to(root)): p.read_text() for p in sorted((root / "src").rglob("*.ts"))}


class ReferenceGenerator:
    """v1 -> idiomatic-errors stand-in, v2+ -> full-parity stand-in."""

    def __init__(self, broken_first: bool = False) -> None:
        self.requests: list[GenerationRequest] = []
        self.broken_first = broken_first

    def __call__(self, request: GenerationRequest) -> dict[str, str]:
        self.requests.append(request)
        if self.broken_first and len(self.requests) == 1:
            return {"src/index.ts": "const x: number = 'not a number';\n"}
        return _read_src("hono-v1-miss" if request.policy.version == 1 else "hono-good")


@pytest.fixture(autouse=True)
def _isolated_runs(monkeypatch):
    # Under the repo's gitignored runs/, not tmp_path: Node's realpath walk can be
    # denied on sandboxed temp dirs.
    import uuid

    from portpilot.config import RUNS_DIR

    root = RUNS_DIR / "_pytest" / uuid.uuid4().hex[:8]
    monkeypatch.setattr("portpilot.config.RUNS_DIR", root)
    yield
    shutil.rmtree(root, ignore_errors=True)


def test_analyze_source_extracts_routes_and_keeps_files_verbatim():
    analysis = analyze_source()
    routes = {(r["method"], r["path"]) for r in analysis["routes"]}
    assert {
        ("POST", "/profiles/normalize"),
        ("POST", "/profiles/validate"),
        ("GET", "/profiles/:profile_id"),
    } <= routes
    app = next(f for f in analysis["files"] if f["path"] == "app.py")
    assert "def " in app["content"] and len(app["sha256"]) == 64
    assert 422 in analysis["error_statuses_in_source"]


def test_validate_files_refuses_paths_outside_src():
    for bad in ("../x.ts", "/etc/x.ts", "package.json", "src/a.js", "lib/a.ts"):
        with pytest.raises(GenerationError):
            validate_files({"src/index.ts": "", bad: ""})
    with pytest.raises(GenerationError):
        validate_files({"src/other.ts": ""})
    assert validate_files({"./src/index.ts": "x"}) == {"src/index.ts": "x"}


def test_generation_prompt_carries_policy_and_repair_feedback():
    policy = Policy(POLICY_NAME, 2, "candidate", "RULE: return 422", [], 1, None)
    assert "RULE: return 422" in generation_system_prompt(policy)
    req = GenerationRequest("regeneration", policy, {"routes": []}, 2)
    assert '"routes"' in build_user_prompt(req)
    req.compiler_errors = "src/index.ts(1,7): error TS2322"
    assert "TS2322" in build_user_prompt(req)


def test_only_generation_milestones_have_an_llm_agent():
    policy = Policy(POLICY_NAME, 1, "active", "b")
    from portpilot.config import load_settings

    with pytest.raises(ValueError):
        build_agent("diagnosis", policy, load_settings())


def test_orchestrator_refuses_a_tool_outside_its_milestone():
    from portpilot.harness import tools as t

    store = InMemoryStore()
    bind(store)
    run_id = store.create_run("x", 1)
    assert t.generate_target.tool_name not in {x.tool_name for x in milestone_tools("test")}
    with pytest.raises(RuntimeError, match="not allowed"):
        orchestrator._call("test", t.generate_target, run_id, run_id=run_id)


def test_pause_after_rejects_non_pausable_milestone():
    with pytest.raises(ValueError):
        orchestrator.start_run(InMemoryStore(), pause_after="generation")


@needs_node
def test_full_run_promotes_v2_after_v1_misses_error_cases():
    store = InMemoryStore()
    gen = ReferenceGenerator()
    run_id = orchestrator.start_run(store, generator=gen)

    run = store.get_run(run_id)
    assert run["status"] == "completed"
    assert [m for m, _ in store.completed_milestones(run_id)] == list(MILESTONES)

    tests = [a["content"] for a in store.artifacts(run_id, "test_output")]
    assert [(t["policy_version"], t["passed"], t["total"]) for t in tests] == [
        (1, 6, 10),
        (2, 10, 10),
    ]

    decision = store.latest_artifact(run_id, "evaluation")["content"]
    assert decision["promoted"] is True and decision["regressions"] == []
    assert sorted(decision["fixed"]) == sorted(
        [
            "normalize_rejects_invalid_payload_with_422",
            "validate_missing_required_field_returns_422",
            "validate_uncoercible_age_returns_422",
            "get_profile_not_found_returns_nested_404",
        ]
    )
    statuses = {p.version: p.status for p in store.list_policies(POLICY_NAME)}
    assert statuses == {1: "retired", 2: "active"}
    assert run["summary"]["active_policy_version"] == 2

    # Each attempt was generated into its own fresh directory from the template.
    targets = [a["content"] for a in store.artifacts(run_id, "target_version")]
    assert [t["policy_version"] for t in targets] == [1, 2]
    assert len({t["path"] for t in targets}) == 2
    for t in targets:
        assert (Path(t["path"]) / "node_modules").resolve() == (
            TEMPLATE_DIR / "node_modules"
        ).resolve()
        assert t["typecheck"]["ok"]

    kinds = {e["type"] for e in store.events(run_id)}
    assert {"run_started", "tool_call", "tool_done", "checkpoint", "decision"} <= kinds


@needs_node
def test_pause_then_resume_does_not_redo_source_analysis():
    store = InMemoryStore()
    gen = ReferenceGenerator()
    run_id = orchestrator.start_run(store, generator=gen, pause_after="candidate_policy")
    run = store.get_run(run_id)
    assert run["status"] == "paused" and run["current_milestone"] == "candidate_policy"
    assert {p.version: p.status for p in store.list_policies(POLICY_NAME)} == {
        1: "active",
        2: "candidate",
    }

    orchestrator.resume(store, run_id, generator=gen)
    assert store.get_run(run_id)["status"] == "completed"
    names = [m for m, _ in store.completed_milestones(run_id)]
    assert names.count("source_analysis") == 1
    assert len(store.artifacts(run_id, "source_analysis")) == 1
    assert [r.policy.version for r in gen.requests] == [1, 2]
    resume_events = [e for e in store.events(run_id) if e["type"] == "resume"]
    assert resume_events[0]["payload"]["skipping_completed"][:1] == ["source_analysis"]


@needs_node
def test_compile_error_gets_one_repair_round():
    store = InMemoryStore()
    gen = ReferenceGenerator(broken_first=True)
    run_id = orchestrator.start_run(store, generator=gen, pause_after="diagnosis")
    first = store.artifacts(run_id, "target_version")[0]["content"]
    assert first["typecheck"] == {"ok": True, "output": first["typecheck"]["output"], "repairs": 1}
    assert "TS" in gen.requests[1].compiler_errors
