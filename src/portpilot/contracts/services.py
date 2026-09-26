"""Service process management. Owner: Lane A.

Starts the Flask source and a Hono target directory as subprocesses on
127.0.0.1 only, waits for GET /health, and tears them down cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from portpilot.config import FIXTURE_DIR


def free_port() -> int:
    raise NotImplementedError("Lane A: free_port")


@contextmanager
def flask_source(port: int | None = None, source_dir: Path = FIXTURE_DIR) -> Iterator[str]:
    """Yield the source base URL, e.g. http://127.0.0.1:5001."""
    raise NotImplementedError("Lane A: flask_source")
    yield ""  # pragma: no cover


@contextmanager
def hono_target(target_dir: Path, port: int | None = None) -> Iterator[str]:
    """Run `npx tsx src/index.ts` in target_dir with PORT set; yield base URL."""
    raise NotImplementedError("Lane A: hono_target")
    yield ""  # pragma: no cover
