"""Spike S3 goal 3: allow-listed CLI installer.

Installs a single tool, by name, from `config/cli_allowlist.yaml` into
/opt/pp/tools inside the sandbox container. Designed to run *inside* the
container (as the `pp` user) -- invoke it via the sandbox shell tool, e.g.:

    docker exec -u pp pp-test-s3-container \\
        python3 /workspace/install.py trivy

Refuses:
  - a name not present in the allow-list (`unknown tool`);
  - a downloaded artifact whose sha256 does not match the allow-list entry
    for the running architecture (`checksum mismatch`), and does not install it.

Idempotent: if the verify command already succeeds for the pinned version,
does nothing and exits 0.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - fallback for a bare image without pyyaml
    yaml = None

ALLOWLIST_PATH = Path(
    __import__("os").environ.get("PP_CLI_ALLOWLIST", "/workspace/config/cli_allowlist.yaml")
)
INSTALL_ROOT = Path(__import__("os").environ.get("PP_TOOLS_DIR", "/opt/pp/tools"))


class InstallError(RuntimeError):
    """Raised for refusals: unknown tool name or checksum mismatch."""


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    raise InstallError(f"unsupported architecture: {machine}")


def _load_allowlist() -> dict:
    if not ALLOWLIST_PATH.exists():
        raise InstallError(f"allow-list not found at {ALLOWLIST_PATH}")
    text = ALLOWLIST_PATH.read_text()
    if yaml is not None:
        return yaml.safe_load(text) or {}
    raise InstallError("pyyaml not installed and no fallback parser implemented")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def _extract_binary(archive: Path, member_path: str, dest: Path) -> None:
    if archive.suffixes[-2:] == [".tar", ".gz"] or archive.suffix == ".tgz":
        mode = "r:gz"
    elif archive.suffixes[-2:] == [".tar", ".xz"]:
        mode = "r:xz"
    else:
        raise InstallError(f"unsupported archive type: {archive.name}")
    with tarfile.open(archive, mode) as tf:
        member = tf.getmember(member_path)
        extracted = tf.extractfile(member)
        if extracted is None:
            raise InstallError(f"{member_path} not found in {archive.name}")
        dest.write_bytes(extracted.read())


def _already_installed(entry: dict) -> bool:
    verify_cmd = entry.get("verify_command")
    if not verify_cmd:
        return False
    try:
        proc = subprocess.run(
            verify_cmd,
            shell=True,
            capture_output=True,
            timeout=15,
            text=True,
            check=False,
            env={"PATH": f"{INSTALL_ROOT}:/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    version = str(entry.get("version", "")).lstrip("v")
    return version and version in (proc.stdout + proc.stderr)


def install(name: str) -> None:
    allowlist = _load_allowlist()
    tools = allowlist.get("tools", {})
    if name not in tools:
        raise InstallError(f"unknown tool: {name!r} is not in the allow-list")

    entry = tools[name]
    arch = _arch()
    arch_entry = (entry.get("architectures") or {}).get(arch)
    if arch_entry is None:
        raise InstallError(f"{name!r} has no allow-list entry for architecture {arch!r}")

    if _already_installed(entry):
        print(f"{name} already installed at pinned version {entry.get('version')}; skipping")
        return

    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"pp-install-{name}-") as tmp:
        tmp_path = Path(tmp)
        download_path = tmp_path / Path(arch_entry["url"]).name
        _download(arch_entry["url"], download_path)

        digest = _sha256(download_path)
        expected = arch_entry["sha256"].lower()
        if digest.lower() != expected:
            raise InstallError(
                f"checksum mismatch for {name} ({arch}): expected {expected}, got {digest}"
            )

        install_method = arch_entry.get("install_method", "binary")
        dest = INSTALL_ROOT / name
        if install_method == "binary":
            shutil.copyfile(download_path, dest)
        elif install_method.startswith("tarball:"):
            member_path = install_method.split(":", 1)[1]
            _extract_binary(download_path, member_path, dest)
        else:
            raise InstallError(f"unsupported install_method for {name}: {install_method}")

        dest.chmod(0o755)

    print(f"installed {name} {entry.get('version')} -> {dest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Tool name, must be a key in config/cli_allowlist.yaml")
    args = parser.parse_args()

    try:
        install(args.name)
    except InstallError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
