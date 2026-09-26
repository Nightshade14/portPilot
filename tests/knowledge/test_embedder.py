"""Unit tests for VoyageEmbedder: batching against MAX_BATCH, and retry on 429/5xx
using httpx.MockTransport (no live network)."""

from __future__ import annotations

import httpx
import pytest

from portpilot.knowledge.embedder import VoyageEmbedder, VoyageEmbeddingError


def _embedding_response(indices: list[int]) -> dict:
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": i, "embedding": [float(i)] * 4} for i in indices],
        "model": "voyage-4",
        "usage": {"total_tokens": len(indices) * 3},
    }


def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Point `portpilot.knowledge.embedder`'s `httpx.Client(...)` calls at `transport`.

    `embedder_module.httpx` is the *same* module object as this test's `httpx` import,
    so building the replacement Client with the real (unpatched) class first avoids
    accidentally making the patched constructor call itself.
    """
    import portpilot.knowledge.embedder as embedder_module

    real_client_cls = httpx.Client

    def _client(timeout=None):
        return real_client_cls(transport=transport, timeout=timeout)

    monkeypatch.setattr(embedder_module.httpx, "Client", _client)


def test_embed_batches_at_max_batch_size(monkeypatch):
    calls: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        calls.append(payload["input"])
        return httpx.Response(200, json=_embedding_response(list(range(len(payload["input"])))))

    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    embedder = VoyageEmbedder(api_key="k", dims=4)

    texts = [f"doc {i}" for i in range(2500)]
    out = embedder.embed(texts, "document")

    assert len(out) == 2500
    assert [len(c) for c in calls] == [1000, 1000, 500]


def test_embed_empty_returns_empty():
    embedder = VoyageEmbedder(api_key="k", dims=4)
    assert embedder.embed([], "document") == []


def test_embed_retries_on_429_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"detail": "rate limited"})
        import json

        payload = json.loads(request.content)
        return httpx.Response(200, json=_embedding_response(list(range(len(payload["input"])))))

    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    embedder = VoyageEmbedder(api_key="k", dims=4, base_backoff_s=0.0, max_retries=5)

    out = embedder.embed(["hello"], "document")

    assert attempts["n"] == 3
    assert len(out) == 1
    assert len(out[0]) == 4


def test_embed_retries_on_5xx_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(503, text="service unavailable")
        import json

        payload = json.loads(request.content)
        return httpx.Response(200, json=_embedding_response(list(range(len(payload["input"])))))

    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    embedder = VoyageEmbedder(api_key="k", dims=4, base_backoff_s=0.0, max_retries=5)

    out = embedder.embed(["hello"], "document")

    assert attempts["n"] == 2
    assert len(out) == 1


def test_embed_raises_on_401_without_retry_and_without_leaking_key(monkeypatch):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    embedder = VoyageEmbedder(api_key="super-secret-key", dims=4, base_backoff_s=0.0, max_retries=3)

    with pytest.raises(VoyageEmbeddingError) as exc_info:
        embedder.embed(["hello"], "document")

    assert attempts["n"] == 1  # no retry on 401
    assert "super-secret-key" not in str(exc_info.value)


def test_embed_raises_after_exhausting_retries_on_persistent_429(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    transport = httpx.MockTransport(handler)
    _patch_httpx_client(monkeypatch, transport)
    embedder = VoyageEmbedder(api_key="k", dims=4, base_backoff_s=0.0, max_retries=2)

    with pytest.raises(VoyageEmbeddingError):
        embedder.embed(["hello"], "document")


def test_make_embedder_falls_back_to_fake_when_no_key_and_memory_backend():
    from types import SimpleNamespace

    from portpilot.core.fakes import FakeEmbedder
    from portpilot.knowledge.embedder import make_embedder

    settings = SimpleNamespace(
        voyage_api_key=None,
        store_backend="memory",
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=64,
    )
    embedder = make_embedder(settings)
    assert isinstance(embedder, FakeEmbedder)
    assert embedder.dims == 64


def test_make_embedder_refuses_fake_fallback_against_real_store():
    from types import SimpleNamespace

    from portpilot.knowledge.embedder import make_embedder

    settings = SimpleNamespace(
        voyage_api_key=None,
        store_backend="atlas",
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=1024,
    )
    with pytest.raises(RuntimeError):
        make_embedder(settings)


def test_make_embedder_uses_voyage_when_key_present():
    from types import SimpleNamespace

    from portpilot.knowledge.embedder import make_embedder

    settings = SimpleNamespace(
        voyage_api_key="k",
        store_backend="atlas",
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=1024,
    )
    embedder = make_embedder(settings)
    assert isinstance(embedder, VoyageEmbedder)
    assert embedder.dims == 1024
