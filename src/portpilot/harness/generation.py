"""Target workspace + code generation. Owner: Lane C (critical path).

A Generator turns (policy, source analysis, compiler feedback) into a file map
{relative_path: content} limited to src/**. The default is the LLM generator;
tests inject a deterministic one through harness.context.bind(generator=...).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, Field

from portpilot.config import TEMPLATE_DIR, Settings
from portpilot.models import Milestone, Policy

TEMPLATE_COPY = ("package.json", "tsconfig.json")
MAX_FILES = 20
MAX_FILE_BYTES = 200_000


class GenerationError(RuntimeError):
    pass


# ---------------------------------------------------------------- generator API


@dataclass
class GenerationRequest:
    milestone: Milestone
    policy: Policy
    analysis: dict[str, Any]
    attempt: int
    # Filled on a repair round: the previous files and the compiler output.
    previous_files: dict[str, str] = field(default_factory=dict)
    compiler_errors: str | None = None


class Generator(Protocol):
    def __call__(self, request: GenerationRequest) -> dict[str, str]: ...


class GeneratedFile(BaseModel):
    path: str = Field(description="Relative path, must start with src/ and end with .ts")
    content: str = Field(description="Full file content")


class GeneratedTarget(BaseModel):
    """The complete set of source files for the ported service."""

    files: list[GeneratedFile]
    notes: str = Field(default="", description="One or two sentences on key decisions")


def build_user_prompt(request: GenerationRequest) -> str:
    if request.compiler_errors is None:
        return (
            "Port this legacy Flask service to Hono. Source analysis (JSON) follows; "
            "it includes every source file verbatim.\n\n"
            + json.dumps(request.analysis, indent=2)
            + "\n\nReturn the complete file set for src/."
        )
    return (
        "The TypeScript compiler (tsc --noEmit) rejected your files:\n\n"
        + request.compiler_errors[-6000:]
        + "\n\nFix every error and return the COMPLETE corrected file set for src/ "
        "(all files, not only the changed ones)."
    )


class LLMGenerator:
    """One Strands agent per generation milestone; repair rounds continue the same
    conversation so the model sees its own previous answer."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._agents: dict[tuple[str, int], Any] = {}

    def __call__(self, request: GenerationRequest) -> dict[str, str]:
        from portpilot.harness.agent import build_agent

        key = (request.milestone, request.attempt)
        if request.compiler_errors is None or key not in self._agents:
            self._agents[key] = build_agent(request.milestone, request.policy, self.settings)
        agent = self._agents[key]
        result = agent(build_user_prompt(request), structured_output_model=GeneratedTarget)
        out = result.structured_output
        if not isinstance(out, GeneratedTarget):
            raise GenerationError(f"model returned no structured file set: {str(result)[:500]}")
        return {f.path: f.content for f in out.files}


# ---------------------------------------------------------------- workspace


def validate_files(files: dict[str, str]) -> dict[str, str]:
    """Allow only src/**.ts with sane sizes; normalize paths."""
    if not files:
        raise GenerationError("generator returned no files")
    if len(files) > MAX_FILES:
        raise GenerationError(f"generator returned {len(files)} files (max {MAX_FILES})")
    clean: dict[str, str] = {}
    for raw, content in files.items():
        name = raw.strip()
        name = name.removeprefix("./")
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "src":
            raise GenerationError(f"refusing path outside src/: {raw!r}")
        if p.suffix != ".ts":
            raise GenerationError(f"refusing non-.ts file: {raw!r}")
        if len(content.encode()) > MAX_FILE_BYTES:
            raise GenerationError(f"file too large: {raw!r}")
        clean[str(p)] = content
    if "src/index.ts" not in clean:
        raise GenerationError("generator did not produce src/index.ts")
    return clean


def ensure_template_installed(template: Path = TEMPLATE_DIR) -> Path:
    modules = template / "node_modules"
    if not (modules / ".bin" / "tsc").exists():
        subprocess.run(
            ["npm", "ci", "--no-fund", "--no-audit"],
            cwd=template,
            check=True,
            capture_output=True,
            text=True,
        )
    return modules


def prepare_workspace(dest: Path, template: Path = TEMPLATE_DIR) -> None:
    """Fresh, empty target: template config + symlinked node_modules, no src/."""
    modules = ensure_template_installed(template)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in TEMPLATE_COPY:
        shutil.copy2(template / name, dest / name)
    os.symlink(modules, dest / "node_modules", target_is_directory=True)


def write_files(dest: Path, files: dict[str, str]) -> None:
    src = dest / "src"
    if src.exists():
        shutil.rmtree(src)
    for rel, content in files.items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def typecheck(dest: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(dest / "node_modules" / ".bin" / "tsc"), "--noEmit", "-p", str(dest)],
        cwd=dest,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def manifest(dest: Path, files: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "path": rel,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "bytes": len(content.encode()),
        }
        for rel, content in sorted(files.items())
    ]


def generate_into(
    dest: Path,
    request: GenerationRequest,
    generator: Callable[[GenerationRequest], dict[str, str]],
    max_repairs: int = 1,
) -> dict[str, Any]:
    """Prepare dest, generate, write, type-check with up to max_repairs repair rounds.
    Returns the target_version artifact content (minus run bookkeeping)."""
    prepare_workspace(dest)
    files = validate_files(generator(request))
    write_files(dest, files)
    ok, output = typecheck(dest)
    repairs = 0
    while not ok and repairs < max_repairs:
        repairs += 1
        request.previous_files = files
        request.compiler_errors = output
        files = validate_files(generator(request))
        write_files(dest, files)
        ok, output = typecheck(dest)
    return {
        "path": str(dest),
        "files": manifest(dest, files),
        "typecheck": {"ok": ok, "output": output[-4000:], "repairs": repairs},
    }
