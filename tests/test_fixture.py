"""Integration tests: live source-vs-target contract runs.

Boots real subprocesses (Flask via sys.executable, Hono via `npx tsx`). The
Node tests skip when `npx` is unavailable or a reference target has no
node_modules installed.
"""

from __future__ import annotations

import shutil

import pytest

from portpilot.config import REFERENCE_TARGETS_DIR
from portpilot.contracts.runner import run_source_only, run_suite
from portpilot.contracts.services import flask_source, hono_target

EXPECTED_V1_MISS_FAILURES = {
    "normalize_rejects_invalid_payload_with_422",
    "validate_missing_required_field_returns_422",
    "validate_uncoercible_age_returns_422",
    "get_profile_not_found_returns_nested_404",
}

HONO_GOOD = REFERENCE_TARGETS_DIR / "hono-good"
HONO_V1_MISS = REFERENCE_TARGETS_DIR / "hono-v1-miss"

npx_missing = shutil.which("npx") is None


def _node_ready(target_dir) -> bool:
    return (target_dir / "node_modules").is_dir()


def test_source_only_passes_all_ten_cases():
    with flask_source() as source_url:
        result = run_source_only(source_url)
    assert result.total == 10
    assert result.passed == 10, [c.diff for c in result.cases if not c.passed]


@pytest.mark.skipif(npx_missing, reason="npx not available")
def test_hono_good_reaches_full_parity():
    if not _node_ready(HONO_GOOD):
        pytest.skip("hono-good node_modules not installed")
    with flask_source() as source_url, hono_target(HONO_GOOD) as target_url:
        result = run_suite(source_url, target_url)
    assert result.total == 10
    assert result.passed == 10, [c.diff for c in result.cases if not c.passed]


@pytest.mark.skipif(npx_missing, reason="npx not available")
def test_hono_v1_miss_fails_exactly_the_four_legacy_error_cases():
    if not _node_ready(HONO_V1_MISS):
        pytest.skip("hono-v1-miss node_modules not installed")
    with flask_source() as source_url, hono_target(HONO_V1_MISS) as target_url:
        result = run_suite(source_url, target_url)
    assert result.total == 10
    assert result.passed == 6, [c.diff for c in result.cases if not c.passed]
    assert result.failed_ids == EXPECTED_V1_MISS_FAILURES
