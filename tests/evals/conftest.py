"""Adds the repo-root evals/ directory to sys.path so tests/evals/*.py can
`import client`, `import scenarios`, `import assertions`, `import chaos`
the same way evals/*.py import each other (plain sibling imports, no
package __init__.py -- evals/ is a script directory, not a package).
"""

from __future__ import annotations

import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent.parent.parent / "evals"
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))
