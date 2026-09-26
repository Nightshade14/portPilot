"""Voyage embeddings client (MVP_PLAN section 5, lane brief step 1).

The user's `VOYAGE_API_KEY` is a **direct Voyage key**: it gets HTTP 403 from the
Atlas Embedding API (`ai.mongodb.com`), which expects a model API key minted in the
Atlas UI (see spike S1). This client therefore calls Voyage's own API directly:

    POST https://api.voyageai.com/v1/embeddings
    Authorization: Bearer <VOYAGE_API_KEY>
    {"input": [...], "model": "voyage-4", "input_type": "document"|"query"}

Response: `data[].embedding` (1024 dims for voyage-4's default `output_dimension`)
and `usage.total_tokens`. Batch limits and retry semantics follow spike S1's
findings for `voyage-4`: <=1000 inputs per request, retry on 429/5xx with
exponential backoff, never leak the key in an error message.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

import httpx

from portpilot.core.interfaces import Embedder

if TYPE_CHECKING:
    from portpilot.core.config import MvpSettings

DEFAULT_MODEL = "voyage-4"
DEFAULT_DIMS = 1024
MAX_BATCH = 1000
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class VoyageEmbeddingError(RuntimeError):
    """Raised on a non-retryable Voyage error or exhausted retries. Never contains the API key."""


class VoyageEmbedder:
    """`core.interfaces.Embedder` backed by Voyage AI's own embeddings endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.voyageai.com/v1",
        model: str = DEFAULT_MODEL,
        dims: int = DEFAULT_DIMS,
        *,
        max_retries: int = 5,
        base_backoff_s: float = 1.0,
        timeout_s: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("VoyageEmbedder requires a non-empty api_key")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dims = dims
        self.max_retries = max_retries
        self.base_backoff_s = base_backoff_s
        self.timeout_s = timeout_s

    def embed(
        self, texts: list[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            out.extend(self._embed_batch(texts[start : start + MAX_BATCH], input_type))
        return out

    def _embed_batch(
        self, batch: list[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        body = {
            "input": batch,
            "model": self.model,
            "input_type": input_type,
            "output_dimension": self.dims,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        with httpx.Client(timeout=self.timeout_s) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.post(url, json=body, headers=headers)
                except httpx.RequestError as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        time.sleep(self.base_backoff_s * (2**attempt))
                        continue
                    raise VoyageEmbeddingError(
                        f"network error after {self.max_retries} retries: {type(exc).__name__}"
                    ) from None

                if resp.status_code == 200:
                    data = resp.json()
                    ordered = sorted(data["data"], key=lambda d: d["index"])
                    return [d["embedding"] for d in ordered]

                if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    time.sleep(self.base_backoff_s * (2**attempt))
                    continue

                raise VoyageEmbeddingError(
                    f"HTTP {resp.status_code} from Voyage embeddings API "
                    f"(attempt {attempt + 1}/{self.max_retries + 1})"
                )

        raise VoyageEmbeddingError(f"exhausted retries: {type(last_error).__name__}")


def make_embedder(settings: MvpSettings) -> Embedder:
    """`VoyageEmbedder(settings)` when a key is configured; else `FakeEmbedder` iff
    `settings.store_backend == "memory"` (never silently fake against a real store)."""
    if settings.voyage_api_key:
        return VoyageEmbedder(
            api_key=settings.voyage_api_key,
            base_url=settings.voyage_base_url,
            model=settings.embedding_model,
            dims=settings.embedding_dims,
        )
    if settings.store_backend == "memory":
        from portpilot.core.fakes import FakeEmbedder

        return FakeEmbedder(dims=settings.embedding_dims)
    raise RuntimeError(
        "VOYAGE_API_KEY is not set and store_backend != 'memory': "
        "refusing to fall back to FakeEmbedder against a real store"
    )
