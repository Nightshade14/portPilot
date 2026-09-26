"""Repo survey (lane-a.md build step 2).

Runs a self-contained, stdlib-only Python script inside the sandbox to collect a cheap
structural picture of the repo before planning starts. Idempotent on resume: skipped if
a `survey` artifact already exists for the run.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from portpilot.core.models import Run

if TYPE_CHECKING:  # pragma: no cover
    from portpilot.agent.deps import AgentDeps

# Runs with `python3 -` inside the sandbox via SandboxManager.exec. Stdlib only, per the
# brief. Emits one JSON object on stdout.
_SURVEY_SCRIPT = r'''
import json
import os

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
EXT_LANG = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby",
    ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".sh": "shell", ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".md": "markdown",
    ".html": "html", ".css": "css", ".sql": "sql",
}
MANIFESTS = {
    "package.json", "pyproject.toml", "requirements.txt", "Pipfile", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "Gemfile", "composer.json",
}
CI_HINTS = (".github/workflows", ".gitlab-ci.yml", ".circleci", "Jenkinsfile", ".travis.yml")

root = "."
languages: dict[str, int] = {}
manifests: list[str] = []
dockerfiles: list[str] = []
ci_configs: list[str] = []
top_level_modules: list[str] = []
py_imports: dict[str, list[str]] = {}
js_imports: dict[str, list[str]] = {}
file_count = 0

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
    rel_dir = os.path.relpath(dirpath, root)
    for name in filenames:
        file_count += 1
        rel = os.path.normpath(os.path.join(rel_dir, name))
        ext = os.path.splitext(name)[1]
        if ext in EXT_LANG:
            languages[EXT_LANG[ext]] = languages.get(EXT_LANG[ext], 0) + 1
        if name in MANIFESTS:
            manifests.append(rel)
        if name == "Dockerfile" or name.endswith(".Dockerfile"):
            dockerfiles.append(rel)
        for hint in CI_HINTS:
            if hint in rel:
                ci_configs.append(rel)
                break
        if rel_dir == ".":
            if ext == ".py" or (os.path.isdir(os.path.join(root, name)) and not name.startswith(".")):
                top_level_modules.append(name)
        if ext == ".py" and file_count < 4000:
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8", errors="ignore") as fh:
                    mods = []
                    for line in fh:
                        line = line.strip()
                        if line.startswith("import ") or line.startswith("from "):
                            mods.append(line.split()[1].split(".")[0])
                    if mods:
                        py_imports[rel] = sorted(set(mods))[:20]
            except OSError:
                pass
        if ext in (".js", ".jsx", ".ts", ".tsx") and file_count < 4000:
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8", errors="ignore") as fh:
                    text = fh.read(20000)
                mods = []
                import re as _re
                for m in _re.finditer(r"""(?:import\s+.*?from\s+|require\()\s*['"]([^'"]+)['"]""", text):
                    mods.append(m.group(1))
                if mods:
                    js_imports[rel] = sorted(set(mods))[:20]
            except OSError:
                pass

test_commands: list[str] = []
if os.path.exists("pyproject.toml") or os.path.exists("requirements.txt"):
    test_commands.append("pytest")
if os.path.exists("package.json"):
    try:
        with open("package.json", encoding="utf-8") as fh:
            pkg = json.load(fh)
        if "test" in (pkg.get("scripts") or {}):
            test_commands.append("npm test")
    except (OSError, ValueError):
        pass

print(json.dumps({
    "languages": languages,
    "files": file_count,
    "manifests": sorted(set(manifests)),
    "dockerfiles": sorted(set(dockerfiles)),
    "ci_configs": sorted(set(ci_configs)),
    "test_commands": test_commands,
    "top_level_modules": sorted(set(top_level_modules)),
    "import_graph": {"python": py_imports, "javascript": js_imports},
}))
'''


def _existing_survey_artifact_id(deps: AgentDeps, run_id: str) -> str | None:
    for meta in deps.run_store.list_artifacts(run_id, kind="survey"):
        return meta["artifact_id"]
    return None


def survey(deps: AgentDeps, run: Run) -> dict[str, Any]:
    """Collect and store the repo survey; emit `survey_done`.

    Resumable: if a `survey` artifact already exists for this run, it is loaded and
    returned unchanged (no re-exec, no duplicate event).
    """

    existing_id = _existing_survey_artifact_id(deps, run.run_id)
    if existing_id is not None:
        return deps.run_store.get_artifact(existing_id)["content"]

    result = deps.sandbox.exec(
        run.run_id,
        'python3 -c "$SURVEY_SCRIPT"',
        timeout_s=120,
        env={"SURVEY_SCRIPT": _SURVEY_SCRIPT},
    )
    if result.exit_code != 0 or not result.stdout.strip():
        # Fall back to piping via stdin, in case env-var passing mangles the script on
        # some shells.
        result = deps.sandbox.exec(run.run_id, "python3 -", timeout_s=120, stdin=_SURVEY_SCRIPT)
    if result.exit_code != 0:
        raise RuntimeError(
            f"survey script failed (exit {result.exit_code}): {result.stderr[:2000]}"
        )

    survey_data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    artifact_id = deps.run_store.put_artifact(
        run.run_id, None, "survey", survey_data, name="survey.json"
    )
    survey_data["artifact_id"] = artifact_id

    deps.run_store.log_event(
        run.run_id,
        "survey_done",
        None,
        {
            "languages": survey_data.get("languages", {}),
            "files": survey_data.get("files", 0),
            "dockerfiles": survey_data.get("dockerfiles", []),
            "artifact_id": artifact_id,
        },
    )
    return survey_data


__all__ = ["survey"]
