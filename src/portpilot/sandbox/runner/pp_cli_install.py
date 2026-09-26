"""Runs *inside* the sandbox container (baked into the image at
/opt/pp/bin/pp_cli_install.py). Reads `{"name": str, "entry": dict}` (one
allow-list entry, chosen by the host) from stdin, installs into
/opt/pp/tools (a writable volume separate from the read-only rootfs -- see
docs/spikes/S3_SANDBOX.md Goal 3), and prints exactly one JSON line to stdout.

Kept host-blind: no filesystem access to config/cli_allowlist.yaml, no yaml
dependency needed in the image. The host (installer.py) is the only party
that reads the allow-list file itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

INSTALL_ROOT = Path(os.environ.get("PP_TOOLS_DIR", "/opt/pp/tools"))


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "amd64"
    raise ValueError(f"unsupported architecture: {machine}")


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
        raise ValueError(f"unsupported archive type: {archive.name}")
    with tarfile.open(archive, mode) as tf:
        member = tf.getmember(member_path)
        extracted = tf.extractfile(member)
        if extracted is None:
            raise ValueError(f"{member_path} not found in {archive.name}")
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
    return bool(version) and version in (proc.stdout + proc.stderr)


def install(name: str, entry: dict) -> dict:
    arch = _arch()
    arch_entry = (entry.get("architectures") or {}).get(arch)
    if arch_entry is None:
        return {
            "ok": False,
            "refused": True,
            "reason": f"{name!r} has no allow-list entry for architecture {arch!r}",
        }

    sha256 = arch_entry.get("sha256")
    if not sha256:
        return {
            "ok": False,
            "refused": True,
            "reason": f"{name!r} ({arch}) has no published sha256 to pin against",
        }

    if _already_installed(entry):
        return {"ok": True, "already_installed": True, "version": str(entry.get("version"))}

    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"pp-install-{name}-") as tmp:
        tmp_path = Path(tmp)
        download_path = tmp_path / Path(arch_entry["url"]).name
        _download(arch_entry["url"], download_path)

        digest = _sha256(download_path)
        expected = sha256.lower()
        if digest.lower() != expected:
            return {
                "ok": False,
                "refused": True,
                "reason": f"checksum mismatch for {name} ({arch}): expected {expected}, got {digest}",
            }

        install_method = arch_entry.get("install_method", "binary")
        dest = INSTALL_ROOT / name
        if install_method == "binary":
            shutil.copyfile(download_path, dest)
        elif install_method.startswith("tarball:"):
            member_path = install_method.split(":", 1)[1]
            _extract_binary(download_path, member_path, dest)
        else:
            return {
                "ok": False,
                "refused": True,
                "reason": f"unsupported install_method for {name}: {install_method}",
            }

        dest.chmod(0o755)

    return {"ok": True, "already_installed": False, "version": str(entry.get("version"))}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        name = payload["name"]
        entry = payload["entry"]
    except Exception as exc:  # noqa: BLE001 - report, never traceback to the host parser
        print(json.dumps({"ok": False, "refused": True, "reason": f"bad request: {exc}"}))
        return 1

    try:
        result = install(name, entry)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "refused": False, "reason": f"install error: {exc}"}

    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
