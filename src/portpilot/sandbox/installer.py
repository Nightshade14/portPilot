"""`DockerCliInstaller`: implements `core.interfaces.CliInstaller`.

Drives the allow-listed installer (`portpilot.sandbox.runner.pp_tool_run` companion
script, copied into the image as `/opt/pp/bin/pp_cli_install.py`) inside the run's
container via `SandboxManager.exec`. The allow-list itself
(`config/cli_allowlist.yaml`) is read on the HOST and passed to the container as JSON
on stdin, so the container never needs its own copy or write access to the file --
"human-reviewed data, read-only to the agent at runtime" per the lane brief.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from portpilot.core.config import CLI_ALLOWLIST_PATH
from portpilot.core.interfaces import SandboxManager
from portpilot.core.models import InstallResult

INSTALL_SCRIPT_PATH = "/opt/pp/bin/pp_cli_install.py"
CHECK_ENV_SCRIPT_PATH = "/opt/pp/bin/pp_check_env.py"


class DockerCliInstaller:
    def __init__(
        self,
        manager: SandboxManager,
        allowlist_path: Path = CLI_ALLOWLIST_PATH,
    ) -> None:
        self.manager = manager
        self.allowlist_path = allowlist_path

    def allowlist(self) -> dict[str, dict[str, Any]]:
        text = self.allowlist_path.read_text()
        doc = yaml.safe_load(text) or {}
        return dict(doc.get("tools", {}))

    def install(self, run_id: str, name: str) -> InstallResult:
        tools = self.allowlist()
        if name not in tools:
            return InstallResult(
                name=name,
                ok=False,
                refused=True,
                reason=f"unknown tool: {name!r} is not in the allow-list",
            )

        payload = json.dumps({"name": name, "entry": tools[name]})
        result = self.manager.exec(
            run_id,
            f"python3 {INSTALL_SCRIPT_PATH}",
            cwd="/",
            stdin=payload,
            timeout_s=180,
        )
        try:
            out = (
                json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
            )
        except (ValueError, IndexError):
            out = {}

        if result.exit_code != 0:
            return InstallResult(
                name=name,
                ok=False,
                refused=bool(out.get("refused", True)),
                reason=out.get("reason") or result.stderr.strip() or "install failed",
            )

        return InstallResult(
            name=name,
            ok=True,
            version=out.get("version") or str(tools[name].get("version")),
            already_installed=bool(out.get("already_installed", False)),
        )

    def check_environment(self, run_id: str) -> dict[str, Any]:
        result = self.manager.exec(
            run_id, f"python3 {CHECK_ENV_SCRIPT_PATH}", cwd="/", timeout_s=60
        )
        if result.exit_code != 0:
            raise RuntimeError(f"check_environment failed: {result.stderr}")
        report: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
        report["allowlisted"] = sorted(self.allowlist())
        return report
