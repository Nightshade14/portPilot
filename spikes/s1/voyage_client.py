"""Spike S1 goal 3: Atlas Embedding API (Voyage AI) client.

API: POST https://ai.mongodb.com/v1/embeddings
Auth: Authorization: Bearer <model API key created in the Atlas UI>
Model: voyage-4, default output_dimension=1024 (also supports 256/512/2048).
input_type: "document" when storing, "query" when searching.
Batch limits: up to 1000 input strings per request; max total tokens per
request is 320K for voyage-4 (see docs/spikes/S1_ATLAS.md decision table).
Retries on 429 (rate limit) and 5xx (500/502/503/504) with exponential backoff.

The live call cannot be made in this spike -- VOYAGE_API_KEY is not set in
.env. This module is UNVERIFIED against the live endpoint.

Once a key exists, verify with:
    VOYAGE_API_KEY=<key> uv run python -c \
        "from spikes.s1.voyage_client import embed; print(embed(['hello world'], input_type='document'))"
"""

from __future__ import annotations

import time
from typing import Literal

import httpx

ENDPOINT = "https://ai.mongodb.com/v1/embeddings"
DEFAULT_MODEL = "voyage-4"
DEFAULT_DIMENSION = 1024  # voyage-4 default; also supports 256, 512, 2048
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class VoyageEmbeddingError(RuntimeError):
    """Raised when the Atlas Embedding API returns a non-retryable error, or retries are exhausted."""


def embed(
    texts: list[str],
    *,
    api_key: str,
    input_type: Literal["document", "query"],
    model: str = DEFAULT_MODEL,
    output_dimension: int = DEFAULT_DIMENSION,
    max_retries: int = 5,
    base_backoff_s: float = 1.0,
    timeout_s: float = 30.0,
) -> list[list[float]]:
    """Embed a batch of texts via the Atlas Embedding and Reranking API.

    Retries on 429 and 5xx with exponential backoff (base_backoff_s * 2**attempt,
    capped implicitly by max_retries). Raises VoyageEmbeddingError on 400/401/403
    (non-retryable) or once retries are exhausted.
    """
    if not texts:
        return []
    if len(texts) > 1000:
        raise ValueError("Atlas Embedding API accepts at most 1000 input strings per request")

    body = {
        "input": texts,
        "model": model,
        "input_type": input_type,
        "output_dimension": output_dimension,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_error: Exception | None = None
    with httpx.Client(timeout=timeout_s) as client:
        for attempt in range(max_retries + 1):
            try:
                resp = client.post(ENDPOINT, json=body, headers=headers)
            except httpx.RequestError as e:
                last_error = e
                if attempt < max_retries:
                    time.sleep(base_backoff_s * (2**attempt))
                    continue
                raise VoyageEmbeddingError(f"network error after {max_retries} retries: {e}") from e

            if resp.status_code == 200:
                data = resp.json()
                ordered = sorted(data["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in ordered]

            if resp.status_code in RETRYABLE_STATUS and attempt < max_retries:
                time.sleep(base_backoff_s * (2**attempt))
                continue

            detail = _safe_detail(resp)
            raise VoyageEmbeddingError(f"HTTP {resp.status_code}: {detail}")

    raise VoyageEmbeddingError(f"exhausted retries: {last_error}")


def _safe_detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))
    except Exception:  # noqa: BLE001
        return resp.text
