"""Build the sandbox image (`docker/sandbox/Dockerfile`) via a `docker build` subprocess.

Kept separate from `manager.py` (which builds run images with BuildKit inside the
sandbox): this builds the *sandbox* image itself, on the host, once per dev/CI cycle.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from portpilot.core.config import REPO_ROOT, SANDBOX_DOCKERFILE_DIR


def build_image(
    tag: str = "portpilot-sandbox:dev",
    *,
    context: Path | None = None,
    dockerfile: Path | None = None,
    timeout_s: int = 900,
) -> dict[str, object]:
    """Run `docker build` for the sandbox image. Returns {tag, seconds}.

    The build context is the repo root (not `docker/sandbox/`): the Dockerfile
    COPYs the frozen runner scripts from `src/portpilot/sandbox/runner/`.

    Raises subprocess.CalledProcessError on a failed build (stderr is attached via
    `output`/`stderr` on the exception).
    """
    ctx = context or REPO_ROOT
    dockerfile_path = dockerfile or (SANDBOX_DOCKERFILE_DIR / "Dockerfile")
    started = time.monotonic()
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            tag,
            "-f",
            str(dockerfile_path),
            str(ctx),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return {"tag": tag, "seconds": time.monotonic() - started}
