"""BuildKit-backed image builds, with no Docker socket in the sandbox container.

Per docs/spikes/S3_SANDBOX.md Goal 4: a rootless BuildKit sidecar
(`moby/buildkit:v0.33.0-rootless`) needs `--privileged` on Docker Desktop to run
nested build steps; that privilege lives on the disposable sidecar container, not
the per-run sandbox, which never gets a Docker socket or elevated privileges.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from portpilot.core.interfaces import SandboxManager

BUILDKIT_IMAGE = "moby/buildkit:v0.33.0-rootless"
BUILDKIT_CONTAINER = "pp-buildkitd"
BUILDKIT_PORT = 1234


def ensure_buildkit(network: str = "pp-net") -> str:
    """Idempotently run the buildkitd sidecar on `network`. Returns its container name.

    Documented risk: `--privileged` is required for BuildKit's nested runc on
    Docker Desktop (see S3_SANDBOX.md Goal 4). Acceptable only because this runs on
    the disposable backend VM, never inside a per-run sandbox container.
    """
    running = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{BUILDKIT_CONTAINER}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    if BUILDKIT_CONTAINER in running.stdout.split():
        return BUILDKIT_CONTAINER

    exists = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{BUILDKIT_CONTAINER}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if BUILDKIT_CONTAINER in exists.stdout.split():
        subprocess.run(["docker", "start", BUILDKIT_CONTAINER], check=True)
        return BUILDKIT_CONTAINER

    net_ls = subprocess.run(
        ["docker", "network", "ls", "--filter", f"name=^{network}$", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    if network not in net_ls.stdout.split():
        subprocess.run(["docker", "network", "create", network], check=True)

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            BUILDKIT_CONTAINER,
            "--network",
            network,
            "--privileged",
            BUILDKIT_IMAGE,
            "--addr",
            f"tcp://0.0.0.0:{BUILDKIT_PORT}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return BUILDKIT_CONTAINER


def build_image(
    manager: SandboxManager,
    run_id: str,
    *,
    context: str = "/workspace/repo",
    dockerfile: str = "Dockerfile",
    tag: str = "pp-run-image:latest",
    buildkit_addr: str = f"tcp://{BUILDKIT_CONTAINER}:{BUILDKIT_PORT}",
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Run `buildctl` inside the sandbox, output docker-archive to
    /workspace/.pp/images/<tag>.tar, and return {tar_path, size_bytes, seconds}.

    trivy and dive both require docker-archive output (`type=docker`), not OCI (see
    S3_SANDBOX.md decision table): a plain gzip stream is not the OCI directory
    layout they expect for archives.
    """
    safe_tag = tag.replace("/", "_").replace(":", "_")
    tar_path = f"/workspace/.pp/images/{safe_tag}.tar"

    started = time.monotonic()
    mkdir_result = manager.exec(run_id, "mkdir -p /workspace/.pp/images", cwd="/")
    if mkdir_result.exit_code != 0:
        raise RuntimeError(f"could not create image output dir: {mkdir_result.stderr}")

    command = (
        f"DOCKER_CONFIG=/workspace/.docker-config "
        f"buildctl --addr {buildkit_addr} build "
        f"--frontend dockerfile.v0 "
        f"--local context={context} --local dockerfile={context} "
        f"--opt filename={dockerfile} "
        f"--output type=docker,name={tag},dest={tar_path}"
    )
    result = manager.exec(run_id, command, cwd="/", timeout_s=timeout_s)
    if result.exit_code != 0:
        raise RuntimeError(f"buildctl build failed (exit {result.exit_code}): {result.stderr}")

    size_result = manager.exec(run_id, f"stat -c %s '{tar_path}'", cwd="/")
    size_bytes = int(size_result.stdout.strip()) if size_result.exit_code == 0 else -1

    return {"tar_path": tar_path, "size_bytes": size_bytes, "seconds": time.monotonic() - started}
