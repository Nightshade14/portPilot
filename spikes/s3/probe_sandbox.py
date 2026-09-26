"""Spike S3 goal 2: drive pp-test-s3-container via strands.sandbox.docker.DockerSandbox.

Run with:
    uv run python spikes/s3/probe_sandbox.py
Container must already be running (see docs/spikes/S3_SANDBOX.md for the docker run
command). No LLM involved -- calls agent.tool.shell / agent.tool.file_editor directly.
"""

import asyncio

from strands import Agent
from strands.sandbox.docker import DockerSandbox

CONTAINER = "pp-test-s3-container"


async def main() -> None:
    sandbox = DockerSandbox(container=CONTAINER, working_dir="/workspace", user="pp")

    # --- direct Sandbox API ---
    result = await sandbox.execute("echo hello-from-sandbox")
    print("execute():", result.exit_code, result.stdout.strip())

    await sandbox.write_text("/workspace/probe.txt", "line one\n")
    content = await sandbox.read_text("/workspace/probe.txt")
    print("read_text():", repr(content))

    files = await sandbox.list_files("/workspace")
    print("list_files():", [f.name for f in files])

    # --- vended tools through an Agent, called directly (no LLM) ---
    agent = Agent(sandbox=sandbox, tools=sandbox.get_tools())

    # get_tools() names them sandbox_shell / sandbox_file_editor (see docker.py).
    shell_result = agent.tool.sandbox_shell(command="pwd && whoami")
    print("agent.tool.sandbox_shell():", shell_result)

    editor_result = agent.tool.sandbox_file_editor(
        command="create",
        path="/workspace/from_editor.txt",
        file_text="written by sandbox_file_editor\n",
    )
    print("agent.tool.sandbox_file_editor() create:", editor_result)

    view_result = agent.tool.sandbox_file_editor(command="view", path="/workspace/from_editor.txt")
    print("agent.tool.sandbox_file_editor() view:", view_result)


if __name__ == "__main__":
    asyncio.run(main())
