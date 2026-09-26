"""Heuristics flagging shell commands that look like they'd install software.

Used by the harness to warn/refuse an agent-issued command that tries to reach
outside the allow-listed `install_cli_tool` path (system package managers, global
npm/pip installs, curl|sh pipelines). Not a sandbox: purely a string classifier.
"""

from __future__ import annotations

import re

# Each pattern maps to a human-readable reason. Matching is case-insensitive and
# tolerant of leading `sudo`, a variable assignment, or being chained with && / ;.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bapt(?:-get)?\s+(?:-\S+\s+)*install\b"), "apt(-get) install"),
    (re.compile(r"\bapk\s+add\b"), "apk add"),
    (re.compile(r"\b(?:yum|dnf)\s+install\b"), "yum/dnf install"),
    (re.compile(r"\bbrew\s+install\b"), "brew install"),
    (re.compile(r"\bnpm\s+(?:i|install)\s+(?:.*\s)?-g\b"), "npm install -g"),
    (re.compile(r"\bnpm\s+(?:i|install)\s+(?:.*\s)?--global\b"), "npm install --global"),
    (re.compile(r"\bcurl\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash)\b"), "curl | sh|bash"),
    (re.compile(r"\bwget\b[^|]*\|\s*(?:sudo\s+)?(?:sh|bash)\b"), "wget | sh|bash"),
]

# pip install is flagged UNLESS it is running inside a venv (VIRTUAL_ENV set, or
# the command is scoped with `uv pip install` inside a project — heuristically,
# presence of "--user" or a bare global "pip install" without a preceding venv
# activation is what we can see from the string alone).
_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b")
_VENV_HINT = re.compile(r"\b(?:\.venv|venv)/bin/(?:pip3?|python3?)\b|VIRTUAL_ENV=")


def looks_like_install(cmd: str) -> str | None:
    """Return a reason string if `cmd` looks like a system/global install, else None.

    False-positive-averse for the common allowed case `npm install` (no -g) and
    `pip install` run through a venv's own pip/python.
    """
    stripped = cmd.strip()
    if not stripped:
        return None

    for pattern, reason in _PATTERNS:
        if pattern.search(stripped):
            return reason

    if _PIP_INSTALL.search(stripped) and not _VENV_HINT.search(stripped):
        return "pip install outside a venv"

    return None
