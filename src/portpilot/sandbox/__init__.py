"""Lane S: sandbox container, CLI environment and image builds.

Implements `core.interfaces.SandboxManager` and `CliInstaller` (frozen, Lead-owned)
against Docker Desktop, per `docs/spikes/S3_SANDBOX.md` and
`docs/plan/mvp-lanes/lane-s.md`.
"""

from __future__ import annotations

from portpilot.sandbox.buildkit import build_image, ensure_buildkit
from portpilot.sandbox.factory import open_sandbox
from portpilot.sandbox.image import build_image as build_sandbox_image
from portpilot.sandbox.installer import DockerCliInstaller
from portpilot.sandbox.manager import DockerSandboxManager
from portpilot.sandbox.shell_guard import looks_like_install

__all__ = [
    "DockerCliInstaller",
    "DockerSandboxManager",
    "build_image",
    "build_sandbox_image",
    "ensure_buildkit",
    "looks_like_install",
    "open_sandbox",
]
