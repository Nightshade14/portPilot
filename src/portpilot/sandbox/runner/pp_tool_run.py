"""FROZEN protocol -- Lane T relies on this exact stdin/stdout/exit-code contract.

Baked into the image at /opt/pp/bin/pp_tool_run.py. Invoked as:

    python3 /opt/pp/bin/pp_tool_run.py --dir /workspace/.pp/tools/<name>/<version> --timeout 300

Reads the params JSON from stdin, imports `main.py` from --dir and calls
`run(params) -> dict`. Prints exactly one JSON line to stdout:
`{"ok": true, "result": {...}}` or `{"ok": false, "error": "...", "traceback": "..."}`.
Exit code 0 when ok, 1 otherwise, and 124 on timeout. Caps the result at 256 KB
(`{"ok": false, "error": "result too large"}`). Runs the tool with
cwd=/workspace/repo.
"""

from __future__ import annotations

import argparse
import faulthandler
import importlib.util
import json
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any

RESULT_CAP_BYTES = 256 * 1024
REPO_CWD = "/workspace/repo"


class _Timeout(Exception):
    pass


def _alarm_handler(signum: int, frame: Any) -> None:
    raise _Timeout()


def _load_main(tool_dir: Path):
    main_path = tool_dir / "main.py"
    spec = importlib.util.spec_from_file_location(f"pp_tool_{tool_dir.name}", main_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {main_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _emit(payload: dict) -> int:
    text = json.dumps(payload)
    if len(text.encode("utf-8")) > RESULT_CAP_BYTES and payload.get("ok"):
        return _emit({"ok": False, "error": "result too large"})
    print(text)
    return 0 if payload.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Tool directory containing main.py")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    tool_dir = Path(args.dir)

    try:
        params_text = sys.stdin.read()
        params: dict = json.loads(params_text) if params_text.strip() else {}
    except json.JSONDecodeError as exc:
        return _emit({"ok": False, "error": f"invalid params JSON: {exc}"})

    if os.path.isdir(REPO_CWD):
        os.chdir(REPO_CWD)

    faulthandler.enable()
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(args.timeout)
    try:
        module = _load_main(tool_dir)
        result = module.run(params)
        return _emit({"ok": True, "result": result})
    except _Timeout:
        print(json.dumps({"ok": False, "error": f"timed out after {args.timeout}s"}))
        return 124
    except Exception as exc:  # noqa: BLE001 - report every tool failure, never crash bare
        return _emit({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


if __name__ == "__main__":
    sys.exit(main())
