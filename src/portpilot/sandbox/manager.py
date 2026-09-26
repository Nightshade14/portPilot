"""`DockerSandboxManager`: implements `core.interfaces.SandboxManager` over Docker Desktop.

One container + two named volumes per run, per docs/spikes/S3_SANDBOX.md and
docs/plan/mvp-lanes/lane-s.md. Every docker invocation goes through
`subprocess.run([...])` with argument lists -- never `shell=True` on the host.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from portpilot.core.interfaces import Refused
from portpilot.core.models import ExecResult
from portpilot.sandbox.validation import validate_repo_url, validate_run_id

try:  # pragma: no cover - exercised via the `docker` marker
    from strands.sandbox.docker import DockerSandbox
except ImportError:  # pragma: no cover
    DockerSandbox = None  # type: ignore[assignment,misc]

DEFAULT_RUN_FLAGS: tuple[str, ...] = (
    "--cpus",
    "2",
    "--memory",
    "512m",
    "--pids-limit",
    "256",
    "--security-opt",
    "no-new-privileges",
    "--cap-drop",
    "ALL",
    "--read-only",
    "--tmpfs",
    "/tmp",
)

MAX_OUTPUT_BYTES = 1024 * 1024  # 1 MB, per output stream
CLONE_TIMEOUT_S = 120
GIT_IDENTITY_NAME = "PortPilot"
GIT_IDENTITY_EMAIL = "portpilot@localhost"


def _truncate(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="replace") + "\n...[truncated]"


class DockerSandboxManager:
    """`core.interfaces.SandboxManager` implementation.

    Names: container `pp-sbx-<run_id>`; volumes `pp-ws-<run_id>` (/workspace) and
    `pp-tools-<run_id>` (/opt/pp/tools).
    """

    def __init__(
        self,
        image: str = "portpilot-sandbox:dev",
        network: str = "pp-net",
        *,
        allow_local_repos: bool = False,
        run_flags: tuple[str, ...] = DEFAULT_RUN_FLAGS,
        container_prefix: str = "pp-sbx-",
    ) -> None:
        self.image = image
        self.network = network
        self.allow_local_repos = allow_local_repos
        self.run_flags = run_flags
        self.container_prefix = container_prefix

    # ------------------------------------------------------------- naming

    def _container(self, run_id: str) -> str:
        return f"{self.container_prefix}{run_id}"

    def _ws_volume(self, run_id: str) -> str:
        return f"pp-ws-{run_id}"

    def _tools_volume(self, run_id: str) -> str:
        return f"pp-tools-{run_id}"

    # --------------------------------------------------------------- host docker CLI

    def _docker(
        self, args: list[str], *, timeout_s: int = 60, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=check,
        )

    def _container_exists(self, name: str) -> bool:
        proc = self._docker(["ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
        return name in proc.stdout.split()

    def _container_running(self, name: str) -> bool:
        proc = self._docker(["ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}"])
        return name in proc.stdout.split()

    def _ensure_network(self) -> None:
        proc = self._docker(
            ["network", "ls", "--filter", f"name=^{self.network}$", "--format", "{{.Name}}"]
        )
        if self.network not in proc.stdout.split():
            self._docker(["network", "create", self.network])

    # -------------------------------------------------------------- SandboxManager

    def ensure(self, run_id: str, repo_url: str | None = None) -> str:
        validate_run_id(run_id)
        if repo_url is not None:
            validate_repo_url(repo_url, allow_local=self.allow_local_repos)

        container = self._container(run_id)
        self._ensure_network()

        if self._container_running(container):
            return container

        if self._container_exists(container):
            self._docker(["start", container])
            return container

        # First creation: named volumes, then the container itself.
        ws_volume = self._ws_volume(run_id)
        tools_volume = self._tools_volume(run_id)
        self._docker(["volume", "create", ws_volume])
        self._docker(["volume", "create", tools_volume])

        run_args = [
            "run",
            "-d",
            "--name",
            container,
            "--network",
            self.network,
            *self.run_flags,
            "-v",
            f"{ws_volume}:/workspace",
            "-v",
            f"{tools_volume}:/opt/pp/tools",
            self.image,
        ]
        self._docker(run_args)

        if repo_url is not None:
            is_local = self.allow_local_repos and repo_url.startswith("/")
            if is_local:
                # `docker cp` preserves the HOST uid/gid, and the container's
                # `--cap-drop ALL` removes CAP_CHOWN even from root, so a
                # post-cp `chown` is refused. Instead tar the repo on the host
                # and extract it inside the container as the `pp` user, so
                # every file is owned by `pp` from the start.
                self._docker(["exec", "-u", "pp", container, "mkdir", "-p", "/workspace/repo"])
                tar_proc = subprocess.run(
                    ["tar", "--no-mac-metadata", "-C", repo_url, "-cf", "-", "."],
                    capture_output=True,
                    check=False,
                    timeout=CLONE_TIMEOUT_S,
                )
                if tar_proc.returncode != 0:
                    # Older/non-BSD tar (e.g. GNU tar in CI) has no
                    # --no-mac-metadata; fall back to a plain tar.
                    tar_proc = subprocess.run(
                        ["tar", "-C", repo_url, "-cf", "-", "."],
                        capture_output=True,
                        check=True,
                        timeout=CLONE_TIMEOUT_S,
                    )
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        "-u",
                        "pp",
                        "-w",
                        "/workspace/repo",
                        container,
                        "tar",
                        "-xf",
                        "-",
                    ],
                    input=tar_proc.stdout,
                    capture_output=True,
                    check=True,
                    timeout=CLONE_TIMEOUT_S,
                )
            else:
                self._docker(
                    [
                        "exec",
                        "-u",
                        "pp",
                        container,
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        repo_url,
                        "/workspace/repo",
                    ],
                    timeout_s=CLONE_TIMEOUT_S,
                )
            for args in (
                ["config", "user.email", GIT_IDENTITY_EMAIL],
                ["config", "user.name", GIT_IDENTITY_NAME],
                ["checkout", "-b", f"portpilot/{run_id}"],
                ["commit", "--allow-empty", "-m", "portpilot: start"],
            ):
                self._docker(["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", *args])

        return container

    def exec(
        self,
        run_id: str,
        command: str,
        *,
        timeout_s: int = 600,
        cwd: str = "/workspace/repo",
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> ExecResult:
        container = self._container(run_id)
        args = ["exec", "-i", "-u", "pp", "-w", cwd]
        for key, value in (env or {}).items():
            args += ["-e", f"{key}={value}"]
        args += [container, "sh", "-c", command]

        started = time.monotonic()
        try:
            proc = subprocess.run(
                ["docker", *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            return ExecResult(
                exit_code=proc.returncode,
                stdout=_truncate(proc.stdout),
                stderr=_truncate(proc.stderr),
                duration_s=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout or b"").decode("utf-8", errors="replace")
            )
            stderr = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr or b"").decode("utf-8", errors="replace")
            )
            return ExecResult(
                exit_code=124,
                stdout=_truncate(stdout),
                stderr=_truncate(stderr or "timeout"),
                duration_s=time.monotonic() - started,
                timed_out=True,
            )

    def write_file(self, run_id: str, path: str, content: str) -> None:
        # Goes through exec+stdin so content never touches a host shell/tempfile.
        result = self.exec(
            run_id,
            f"mkdir -p \"$(dirname '{path}')\" && cat > '{path}'",
            cwd="/",
            stdin=content,
        )
        if result.exit_code != 0:
            raise Refused(f"write_file({path}) failed: {result.stderr}")

    def read_file(self, run_id: str, path: str) -> str:
        result = self.exec(run_id, f"cat '{path}'", cwd="/")
        if result.exit_code != 0:
            raise Refused(f"read_file({path}) failed: {result.stderr}")
        return result.stdout

    def sandbox(self, run_id: str) -> Any:
        if DockerSandbox is None:  # pragma: no cover
            raise RuntimeError("strands.sandbox.docker.DockerSandbox is not installed")
        container = self._container(run_id)
        return DockerSandbox(container=container, working_dir="/workspace/repo", user="pp")

    def commit(self, run_id: str, message: str) -> str:
        container = self._container(run_id)
        self._docker(["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", "add", "-A"])
        # --allow-empty: the interface promises "returns HEAD unchanged when there is
        # nothing to commit" -- an empty commit with a stable message still advances
        # HEAD, so skip committing when the tree is clean instead.
        status = self._docker(
            ["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", "status", "--porcelain"]
        )
        if status.stdout.strip():
            self._docker(
                [
                    "exec",
                    "-u",
                    "pp",
                    "-w",
                    "/workspace/repo",
                    container,
                    "git",
                    "commit",
                    "-m",
                    message,
                ]
            )
        rev = self._docker(
            ["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", "rev-parse", "HEAD"]
        )
        return rev.stdout.strip()

    def restore(self, run_id: str, sha: str) -> None:
        container = self._container(run_id)
        self._docker(
            ["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", "reset", "--hard", sha]
        )
        self._docker(
            ["exec", "-u", "pp", "-w", "/workspace/repo", container, "git", "clean", "-fd"]
        )

    def export_archive(self, run_id: str) -> bytes:
        container = self._container(run_id)
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "pp",
                "-w",
                "/workspace/repo",
                container,
                "git",
                "archive",
                "--format=tar.gz",
                "HEAD",
            ],
            capture_output=True,
            check=True,
        )
        return proc.stdout

    def stop(self, run_id: str) -> None:
        container = self._container(run_id)
        if self._container_exists(container):
            self._docker(["stop", container], check=False)

    def destroy(self, run_id: str) -> None:
        container = self._container(run_id)
        self._docker(["rm", "-f", container], check=False)
        self._docker(["volume", "rm", "-f", self._ws_volume(run_id)], check=False)
        self._docker(["volume", "rm", "-f", self._tools_volume(run_id)], check=False)
