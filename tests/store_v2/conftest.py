"""Shared fixtures for store_v2 tests. Owner: Lane M."""

from __future__ import annotations

import os
import secrets

import pytest

MONGO_URI_ENV = "PORTPILOT_TEST_MONGODB_URI"


def _test_mongo_uri() -> str | None:
    return os.environ.get(MONGO_URI_ENV)


@pytest.fixture
def mongo_uri() -> str:
    uri = _test_mongo_uri()
    if not uri:
        pytest.skip(f"{MONGO_URI_ENV} not set")
    return uri


@pytest.fixture
def mongo_db_name() -> str:
    return f"pp_test_m_{secrets.token_hex(6)}"
