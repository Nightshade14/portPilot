from portpilot.agent import runtime
from portpilot.core.config import MvpSettings
from portpilot.core.fakes import InMemoryRunStore, InMemoryToolStore


def _settings() -> MvpSettings:
    return MvpSettings(
        mongodb_uri=None,
        mongodb_db="portpilot_test",
        openrouter_api_key=None,
        openrouter_base_url="https://openrouter.ai/api/v1",
        model_id="test-model",
        model_id_aux="test-aux-model",
        model_temperature=0.1,
        voyage_api_key=None,
        voyage_base_url="https://api.voyageai.com/v1",
        embedding_model="voyage-4",
        embedding_dims=1024,
        api_token="test-token",
        api_cors_origins=(),
        sandbox_image="portpilot-sandbox:dev",
        buildkit_addr=None,
        worker_id="test-worker",
        lease_seconds=60,
        store_backend="memory",
    )


def test_build_agent_deps_uses_the_real_sandbox_composition(monkeypatch):
    run_store = InMemoryRunStore()
    tool_store = InMemoryToolStore()
    sandbox = object()
    installer = object()
    monkeypatch.setattr(runtime, "open_stores", lambda settings: (run_store, tool_store))
    monkeypatch.setattr(runtime, "open_sandbox", lambda settings: (sandbox, installer))

    deps = runtime.build_agent_deps(_settings())

    assert deps.run_store is run_store
    assert deps.tool_store is tool_store
    assert deps.sandbox is sandbox
    assert deps.installer is installer
    assert deps.tool_library is None
