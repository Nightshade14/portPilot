"""`docker` marker: strands DockerSandbox binding (vended sandbox_shell /
sandbox_file_editor tools) via `manager.sandbox(run_id)`.
"""

from __future__ import annotations

import asyncio

import pytest
from strands import Agent

pytestmark = pytest.mark.docker


def test_sandbox_returns_docker_sandbox_bound_to_container(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))

    sbx = manager.sandbox(run_id)

    assert sbx.container == manager._container(run_id)
    assert sbx.working_dir == "/workspace/repo"


def test_sandbox_direct_api_executes_in_container(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    sbx = manager.sandbox(run_id)

    async def probe():
        result = await sbx.execute("echo hello-from-sandbox")
        await sbx.write_text("/workspace/repo/probe.txt", "line one\n")
        content = await sbx.read_text("/workspace/repo/probe.txt")
        return result, content

    result, content = asyncio.run(probe())

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello-from-sandbox"
    assert content == "line one\n"
    # Visible from the host side too -- proves it landed in the real container.
    assert manager.read_file(run_id, "/workspace/repo/probe.txt") == "line one\n"


def test_vended_tools_route_into_the_container(manager, run_id, local_repo):
    manager.ensure(run_id, repo_url=str(local_repo))
    sbx = manager.sandbox(run_id)
    agent = Agent(sandbox=sbx, tools=sbx.get_tools())

    result = agent.tool.sandbox_shell(command="pwd && whoami")

    text = result["content"][0]["text"]
    assert "/workspace/repo" in text
    assert "pp" in text
