"""`docker` + `network` marker: BuildKit sidecar builds without a host Docker
socket in the sandbox, per docs/spikes/S3_SANDBOX.md Goal 4.

Uses a tiny local Dockerfile (no external clone) to keep the network dependency to
just the base-image pull BuildKit itself performs. The sandbox container and the
buildkitd sidecar must share one Docker network for embedded DNS to resolve
`pp-buildkitd`, so this module builds its own manager on that network rather than
using the shared `manager` fixture (which defaults to `pp-test-s-net`).
"""

from __future__ import annotations

import pytest

from portpilot.sandbox.buildkit import (
    BUILDKIT_CONTAINER,
    BUILDKIT_PORT,
    build_image,
    ensure_buildkit,
)
from portpilot.sandbox.manager import DockerSandboxManager

pytestmark = [pytest.mark.docker, pytest.mark.network]

BUILD_NETWORK = "pp-net"


@pytest.fixture
def buildkit_manager(run_id):
    mgr = DockerSandboxManager(
        image="portpilot-sandbox:dev",
        network=BUILD_NETWORK,
        container_prefix="pp-test-s-sbx-",
    )
    yield mgr
    mgr.destroy(run_id)


def test_ensure_buildkit_is_idempotent():
    first = ensure_buildkit(network=BUILD_NETWORK)
    second = ensure_buildkit(network=BUILD_NETWORK)

    assert first == second == BUILDKIT_CONTAINER


def test_build_image_produces_docker_archive(buildkit_manager, run_id):
    buildkit_manager.ensure(run_id)
    buildkit_manager.exec(run_id, "mkdir -p /workspace/repo", cwd="/")
    buildkit_manager.write_file(
        run_id,
        "/workspace/repo/Dockerfile",
        "FROM python:3.12-slim\nRUN pip install --no-cache-dir requests==2.32.4\n",
    )
    ensure_buildkit(network=BUILD_NETWORK)

    result = build_image(
        buildkit_manager,
        run_id,
        tag="pp-test-s-buildimg:dev",
        buildkit_addr=f"tcp://{BUILDKIT_CONTAINER}:{BUILDKIT_PORT}",
        timeout_s=300,
    )

    assert result["size_bytes"] > 0
    assert result["tar_path"].endswith(".tar")
    check = buildkit_manager.exec(run_id, f"test -f '{result['tar_path']}'", cwd="/")
    assert check.exit_code == 0
