"""Policy seeding. Owner: Lane B.

`seed_policy` reads a markdown policy body from disk and installs it as the
active policy for a name/version. Idempotent: if that (name, version) already
exists it is returned unchanged.
"""

from __future__ import annotations

from pathlib import Path

from portpilot.models import Policy
from portpilot.store.base import NotFound, Store


def _extract_rules(body: str) -> list[str]:
    """The `- ` bullet lines under a `## Rules` heading, in order.

    Collection stops at the next heading of the same or higher level (``##`` or
    ``#``). Blank lines and non-bullet prose inside the section are ignored.
    """
    rules: list[str] = []
    in_section = False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            if not in_section:
                in_section = heading == "rules"
            else:
                # A new heading ends the Rules section.
                break
            continue
        if in_section and line.startswith("- "):
            rules.append(line[2:].strip())
    return rules


def seed_policy(
    store: Store,
    path: str | Path,
    name: str = "flask-to-hono",
    version: int = 1,
) -> Policy:
    """Install the markdown at ``path`` as the active ``(name, version)`` policy.

    Idempotent: returns the existing policy if ``(name, version)`` is already
    stored, without reading or overwriting it.
    """
    try:
        return store.get_policy(name, version)
    except NotFound:
        pass

    body = Path(path).read_text(encoding="utf-8")
    policy = Policy(
        name=name,
        version=version,
        status="active",
        body=body,
        rules=_extract_rules(body),
    )
    store.save_policy(policy)
    return policy
