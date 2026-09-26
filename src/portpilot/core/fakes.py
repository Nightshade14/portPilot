"""Reference in-memory implementations of the core interfaces. Owner: Lead.

Used by unit tests and by lanes that build before the real implementation lands.
Behavior here is the contract the Atlas/Docker implementations must match (Lane M's
parametrized contract suite runs against both). Not thread-safe beyond a single lock.

`LocalSandboxManager` executes commands on the HOST in a temp directory: it exists only
for tests with trusted commands. Never use it for real repos or agent-written code.
"""

from __future__ import annotations

import copy
import hashlib
import math
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from dataclasses import fields
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from portpilot.core.interfaces import Conflict, NotFound
from portpilot.core.models import (
    ExecResult,
    Hit,
    KnowledgeItem,
    KnowledgeKind,
    Lease,
    LongTermPlan,
    Run,
    SearchMode,
    ShortTermPlan,
    ToolRecord,
    ToolStatus,
    new_id,
    utcnow,
)


def _set(obj: Any, **values: Any) -> None:
    names = {f.name for f in fields(obj)}
    for key, value in values.items():
        if key not in names:
            raise KeyError(f"{type(obj).__name__} has no field {key!r}")
        setattr(obj, key, copy.deepcopy(value))


class InMemoryRunStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, Run] = {}
        self._plans: dict[str, list[LongTermPlan]] = {}
        self._steps: dict[str, ShortTermPlan] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._artifacts: dict[str, dict[str, Any]] = {}

    # runs
    def create_run(self, run: Run) -> str:
        with self._lock:
            if run.run_id in self._runs:
                raise Conflict(run.run_id)
            self._runs[run.run_id] = copy.deepcopy(run)
            return run.run_id

    def get_run(self, run_id: str) -> Run:
        with self._lock:
            if run_id not in self._runs:
                raise NotFound(run_id)
            return copy.deepcopy(self._runs[run_id])

    def list_runs(self, limit: int = 50) -> list[Run]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
            return copy.deepcopy(runs[:limit])

    def update_run(self, run_id: str, **fields_: Any) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise NotFound(run_id)
            _set(run, **fields_)
            run.updated_at = utcnow()

    def claim_run(self, worker_id: str, lease_s: int = 60) -> Run | None:
        now = utcnow()
        with self._lock:
            candidates = [
                r
                for r in self._runs.values()
                if r.status == "queued"
                or (r.status == "running" and (r.lease is None or r.lease.expires_at < now))
            ]
            if not candidates:
                return None
            run = min(candidates, key=lambda r: r.created_at)
            run.lease = Lease(owner=worker_id, expires_at=now + timedelta(seconds=lease_s))
            run.status = "running"
            run.updated_at = now
            return copy.deepcopy(run)

    def heartbeat(self, run_id: str, worker_id: str, lease_s: int = 60) -> bool:
        now = utcnow()
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.lease is None or run.lease.owner != worker_id:
                return False
            run.lease = Lease(owner=worker_id, expires_at=now + timedelta(seconds=lease_s))
            return True

    def release(self, run_id: str, worker_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and run.lease is not None and run.lease.owner == worker_id:
                run.lease = None

    # plans
    def save_plan(self, plan: LongTermPlan) -> None:
        with self._lock:
            versions = self._plans.setdefault(plan.run_id, [])
            if any(p.version == plan.version for p in versions):
                raise Conflict(f"{plan.run_id} v{plan.version}")
            versions.append(copy.deepcopy(plan))

    def latest_plan(self, run_id: str) -> LongTermPlan | None:
        with self._lock:
            versions = self._plans.get(run_id) or []
            return copy.deepcopy(max(versions, key=lambda p: p.version)) if versions else None

    # steps
    def save_step(self, step: ShortTermPlan) -> None:
        with self._lock:
            for other in self._steps.values():
                if (
                    other.run_id == step.run_id
                    and other.seq == step.seq
                    and other.step_id != step.step_id
                ):
                    raise Conflict(f"{step.run_id} seq {step.seq}")
            self._steps[step.step_id] = copy.deepcopy(step)

    def get_step(self, step_id: str) -> ShortTermPlan:
        with self._lock:
            if step_id not in self._steps:
                raise NotFound(step_id)
            return copy.deepcopy(self._steps[step_id])

    def update_step(self, step_id: str, **fields_: Any) -> None:
        with self._lock:
            step = self._steps.get(step_id)
            if step is None:
                raise NotFound(step_id)
            _set(step, **fields_)

    def steps(self, run_id: str) -> list[ShortTermPlan]:
        with self._lock:
            found = [s for s in self._steps.values() if s.run_id == run_id]
            return copy.deepcopy(sorted(found, key=lambda s: s.seq))

    # events
    def log_event(
        self, run_id: str, type: str, step_id: str | None = None, payload: dict | None = None
    ) -> int:
        with self._lock:
            log = self._events.setdefault(run_id, [])
            seq = len(log) + 1
            log.append(
                {
                    "run_id": run_id,
                    "seq": seq,
                    "ts": utcnow(),
                    "type": type,
                    "step_id": step_id,
                    "payload": copy.deepcopy(payload or {}),
                }
            )
            return seq

    def events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            log = self._events.get(run_id, [])
            return copy.deepcopy([e for e in log if e["seq"] > after_seq][:limit])

    # artifacts
    def put_artifact(
        self, run_id: str, step_id: str | None, kind: str, content: Any, name: str = ""
    ) -> str:
        with self._lock:
            artifact_id = new_id("art")
            self._artifacts[artifact_id] = {
                "artifact_id": artifact_id,
                "run_id": run_id,
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "created_at": utcnow(),
                "content": copy.deepcopy(content),
            }
            return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self._lock:
            if artifact_id not in self._artifacts:
                raise NotFound(artifact_id)
            return copy.deepcopy(self._artifacts[artifact_id])

    def list_artifacts(self, run_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            docs = [
                {k: v for k, v in a.items() if k != "content"}
                for a in self._artifacts.values()
                if a["run_id"] == run_id and (kind is None or a["kind"] == kind)
            ]
            return sorted(docs, key=lambda a: a["created_at"])


class InMemoryToolStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tools: dict[tuple[str, int], ToolRecord] = {}

    def save(self, record: ToolRecord) -> None:
        with self._lock:
            key = (record.name, record.version)
            if key in self._tools:
                raise Conflict(f"{record.name}@{record.version}")
            self._tools[key] = copy.deepcopy(record)

    def get(self, name: str, version: int | None = None) -> ToolRecord:
        with self._lock:
            if version is None:
                active = [
                    t for (n, _), t in self._tools.items() if n == name and t.status == "active"
                ]
                if not active:
                    raise NotFound(f"{name} (no active version)")
                return copy.deepcopy(max(active, key=lambda t: t.version))
            if (name, version) not in self._tools:
                raise NotFound(f"{name}@{version}")
            return copy.deepcopy(self._tools[(name, version)])

    def versions(self, name: str) -> list[ToolRecord]:
        with self._lock:
            found = [t for (n, _), t in self._tools.items() if n == name]
            return copy.deepcopy(sorted(found, key=lambda t: t.version))

    def list_tools(self, status: ToolStatus | None = None) -> list[ToolRecord]:
        with self._lock:
            latest: dict[str, ToolRecord] = {}
            for (name, _), tool in self._tools.items():
                if status is not None and tool.status != status:
                    continue
                if name not in latest or tool.version > latest[name].version:
                    latest[name] = tool
            return copy.deepcopy(sorted(latest.values(), key=lambda t: t.name))

    def set_status(self, name: str, version: int, status: ToolStatus) -> None:
        with self._lock:
            if (name, version) not in self._tools:
                raise NotFound(f"{name}@{version}")
            self._tools[(name, version)].status = status

    def record_use(self, name: str, version: int, run_id: str, ok: bool) -> None:
        with self._lock:
            tool = self._tools.get((name, version))
            if tool is None:
                raise NotFound(f"{name}@{version}")
            tool.stats.uses += 1
            if ok:
                tool.stats.successes += 1
            else:
                tool.stats.failures += 1
            if run_id not in tool.stats.runs_used_in:
                tool.stats.runs_used_in.append(run_id)

    def next_version(self, name: str) -> int:
        with self._lock:
            return max((v for (n, v) in self._tools if n == name), default=0) + 1


_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder: texts sharing words are close.

    Good enough to test ranking and dedupe logic; paraphrases without shared words are
    NOT close (that is what the real Voyage embedder is for)."""

    def __init__(self, dims: int = 64, model: str = "fake-bow") -> None:
        self.dims = dims
        self.model = model

    def embed(
        self, texts: list[str], input_type: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for word in _WORD.findall(text.lower()):
                digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
                vec[int.from_bytes(digest[:4], "big") % self.dims] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _match_filters(item: KnowledgeItem, filters: dict[str, Any] | None) -> bool:
    for key, want in (filters or {}).items():
        value: Any = item.to_doc()
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value != want:
            return False
    return True


class InMemoryKnowledgeStore:
    """Reference semantics: text = keyword overlap on title/body/tags; vector = cosine;
    hybrid = reciprocal-rank fusion (k=60) of both lists."""

    DEDUPE_THRESHOLD = 0.92

    def __init__(self, embedder: Any | None = None) -> None:
        self._lock = threading.RLock()
        self.embedder = embedder or FakeEmbedder()
        self._items: dict[str, KnowledgeItem] = {}
        self._vecs: dict[str, list[float]] = {}

    def _text(self, item: KnowledgeItem) -> str:
        return f"{item.title}\n{item.body}\n{' '.join(item.tags)}"

    def upsert(self, item: KnowledgeItem, dedupe: bool = True) -> str:
        with self._lock:
            vec = self.embedder.embed([self._text(item)], "document")[0]
            if item.id in self._items:
                self._items[item.id] = copy.deepcopy(item)
                self._vecs[item.id] = vec
                return item.id
            if dedupe:
                for other_id, other in self._items.items():
                    if (
                        other.kind == item.kind
                        and _cosine(vec, self._vecs[other_id]) >= self.DEDUPE_THRESHOLD
                    ):
                        other.seen_count += 1
                        other.sources.extend(copy.deepcopy(item.sources))
                        other.tags = sorted(set(other.tags) | set(item.tags))
                        other.updated_at = utcnow()
                        return other_id
            self._items[item.id] = copy.deepcopy(item)
            self._vecs[item.id] = vec
            return item.id

    def get(self, item_id: str) -> KnowledgeItem:
        with self._lock:
            if item_id not in self._items:
                raise NotFound(item_id)
            return copy.deepcopy(self._items[item_id])

    def _pool(self, kinds: list[KnowledgeKind] | None, filters: dict | None) -> list[KnowledgeItem]:
        return [
            i
            for i in self._items.values()
            if (kinds is None or i.kind in kinds) and _match_filters(i, filters)
        ]

    def search(
        self,
        query: str,
        *,
        kinds: list[KnowledgeKind] | None = None,
        mode: SearchMode = "hybrid",
        filters: dict[str, Any] | None = None,
        limit: int = 8,
    ) -> list[Hit]:
        with self._lock:
            pool = self._pool(kinds, filters)
            words = set(_WORD.findall(query.lower()))
            text_ranked = sorted(
                ((len(words & set(_WORD.findall(self._text(i).lower()))), i) for i in pool),
                key=lambda t: -t[0],
            )
            text_ranked = [(s, i) for s, i in text_ranked if s > 0]
            qvec = self.embedder.embed([query], "query")[0]
            vec_ranked = sorted(
                ((_cosine(qvec, self._vecs[i.id]), i) for i in pool), key=lambda t: -t[0]
            )
            vec_ranked = [(s, i) for s, i in vec_ranked if s > 0]
            if mode == "text":
                return [Hit(copy.deepcopy(i), float(s), "text") for s, i in text_ranked[:limit]]
            if mode == "vector":
                return [Hit(copy.deepcopy(i), s, "vector") for s, i in vec_ranked[:limit]]
            scores: dict[str, float] = {}
            seen: dict[str, set[str]] = {}
            for label, ranked in (("text", text_ranked), ("vector", vec_ranked)):
                for rank, (_, item) in enumerate(ranked):
                    scores[item.id] = scores.get(item.id, 0.0) + 1.0 / (60 + rank + 1)
                    seen.setdefault(item.id, set()).add(label)
            ordered = sorted(scores, key=lambda i: -scores[i])[:limit]
            return [
                Hit(
                    copy.deepcopy(self._items[i]),
                    scores[i],
                    "both" if len(seen[i]) == 2 else next(iter(seen[i])),  # type: ignore[arg-type]
                )
                for i in ordered
            ]

    def list_items(
        self, kinds: list[KnowledgeKind] | None = None, run_id: str | None = None, limit: int = 100
    ) -> list[KnowledgeItem]:
        with self._lock:
            items = [
                i
                for i in self._pool(kinds, None)
                if run_id is None or any(s.run_id == run_id for s in i.sources)
            ]
            items.sort(key=lambda i: i.updated_at, reverse=True)
            return copy.deepcopy(items[:limit])

    def set_status(self, item_id: str, status: str) -> None:
        with self._lock:
            if item_id not in self._items:
                raise NotFound(item_id)
            self._items[item_id].status = status


class LocalSandboxManager:
    """TEST-ONLY sandbox: runs commands on the host inside a temp dir per run.

    Paths under /workspace are mapped to <root>/<run_id>/workspace. `repo_url` may be a
    local directory path (copied with git clone). Never use with untrusted code."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or tempfile.mkdtemp(prefix="pp-local-sbx-"))

    def _ws(self, run_id: str) -> Path:
        return self.root / run_id / "workspace"

    def _map(self, run_id: str, path: str) -> Path:
        if path.startswith("/workspace"):
            return self._ws(run_id) / path[len("/workspace") :].lstrip("/")
        return Path(path)

    def ensure(self, run_id: str, repo_url: str | None = None) -> str:
        ws = self._ws(run_id)
        repo = ws / "repo"
        if not repo.exists():
            ws.mkdir(parents=True, exist_ok=True)
            if repo_url:
                subprocess.run(
                    ["git", "clone", "-q", "--depth", "1", repo_url, str(repo)], check=True
                )
            else:
                repo.mkdir()
                subprocess.run(["git", "init", "-q", str(repo)], check=True)
            for args in (
                ["config", "user.email", "portpilot@localhost"],
                ["config", "user.name", "PortPilot"],
                ["checkout", "-q", "-B", f"portpilot/{run_id}"],
                ["commit", "-q", "--allow-empty", "-m", "portpilot: start"],
            ):
                subprocess.run(["git", "-C", str(repo), *args], check=True)
        return f"local-{run_id}"

    def exec(
        self,
        run_id: str,
        command: str,
        *,
        timeout_s: int = 600,
        cwd: str = "/workspace/repo",
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> ExecResult:
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                check=False,
                cwd=self._map(run_id, cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                input=stdin,
                env={**os.environ, **(env or {})},
            )
            return ExecResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
        except subprocess.TimeoutExpired as exc:
            return ExecResult(
                124,
                (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else exc.stdout or "",
                "timeout",
                time.monotonic() - started,
                timed_out=True,
            )

    def write_file(self, run_id: str, path: str, content: str) -> None:
        target = self._map(run_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def read_file(self, run_id: str, path: str) -> str:
        return self._map(run_id, path).read_text()

    def sandbox(self, run_id: str):
        from strands.sandbox.not_a_sandbox_local_environment import NotASandboxLocalEnvironment

        return NotASandboxLocalEnvironment(working_dir=str(self._ws(run_id) / "repo"))

    def commit(self, run_id: str, message: str) -> str:
        repo = str(self._ws(run_id) / "repo")
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", message], check=True
        )
        return subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()

    def restore(self, run_id: str, sha: str) -> None:
        repo = str(self._ws(run_id) / "repo")
        subprocess.run(["git", "-C", repo, "reset", "-q", "--hard", sha], check=True)
        subprocess.run(["git", "-C", repo, "clean", "-q", "-fd"], check=True)

    def export_archive(self, run_id: str) -> bytes:
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(self._ws(run_id) / "repo", arcname="repo", filter=_skip_git)
        return buf.getvalue()

    def stop(self, run_id: str) -> None:
        return None

    def destroy(self, run_id: str) -> None:

        shutil.rmtree(self.root / run_id, ignore_errors=True)


def _skip_git(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if "/.git" in info.name or info.name.endswith(".git") else info


__all__ = [
    "FakeEmbedder",
    "InMemoryKnowledgeStore",
    "InMemoryRunStore",
    "InMemoryToolStore",
    "LocalSandboxManager",
]
