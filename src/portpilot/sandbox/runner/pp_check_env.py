"""Runs inside the sandbox container (baked into the image at
/opt/pp/bin/pp_check_env.py). Reports OS/arch, free disk+memory, installed CLIs
(everything currently executable on /opt/pp/tools) and repo languages (a count of
file extensions under /workspace/repo). Prints exactly one JSON line to stdout.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from collections import Counter
from pathlib import Path

TOOLS_DIR = Path(os.environ.get("PP_TOOLS_DIR", "/opt/pp/tools"))
REPO_DIR = Path("/workspace/repo")


def _installed() -> dict[str, str]:
    installed: dict[str, str] = {}
    if not TOOLS_DIR.is_dir():
        return installed
    for entry in sorted(TOOLS_DIR.iterdir()):
        if not (entry.is_file() and os.access(entry, os.X_OK)):
            continue
        version = "unknown"
        for flag in ("--version", "version", "-v"):
            try:
                proc = subprocess.run(
                    [str(entry), flag], capture_output=True, text=True, timeout=10, check=False
                )
            except (OSError, subprocess.SubprocessError):
                continue
            output = (proc.stdout + proc.stderr).strip()
            if output:
                version = output.splitlines()[0][:200]
                break
        installed[entry.name] = version
    return installed


def _repo_languages() -> dict[str, int]:
    if not REPO_DIR.is_dir():
        return {}
    counts: Counter[str] = Counter()
    for path in REPO_DIR.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.suffix:
            counts[path.suffix.lstrip(".")] += 1
    return dict(counts)


def main() -> int:
    disk = shutil.disk_usage("/workspace")
    mem_total_kb = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break
    except OSError:
        pass

    report = {
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "disk_free_mb": disk.free // (1024 * 1024),
        "mem_mb": mem_total_kb // 1024,
        "installed": _installed(),
        "repo_languages": _repo_languages(),
    }
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
