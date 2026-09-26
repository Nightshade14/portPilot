"""`open_sandbox(settings) -> tuple[SandboxManager, CliInstaller]`."""

from __future__ import annotations

from portpilot.core.config import MvpSettings
from portpilot.core.interfaces import CliInstaller, SandboxManager
from portpilot.sandbox.installer import DockerCliInstaller
from portpilot.sandbox.manager import DockerSandboxManager


def open_sandbox(settings: MvpSettings) -> tuple[SandboxManager, CliInstaller]:
    manager = DockerSandboxManager(image=settings.sandbox_image)
    installer = DockerCliInstaller(manager)
    return manager, installer
