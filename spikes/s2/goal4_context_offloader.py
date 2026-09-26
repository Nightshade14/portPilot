"""Goal 4: minimal custom Storage wired to the ContextOffloader plugin."""

from __future__ import annotations

import json

from common import load_env, make_model
from strands import Agent, tool
from strands.storage.storage import StorageSearchResult
from strands.vended_plugins.context_offloader import ContextOffloader


class DictStorage:
    """Minimal dict-backed strands.storage.Storage implementation (async, 4 methods)."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def write(self, key: str, data: bytes) -> None:
        self._data[key] = data

    async def read(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def list(self, query: str) -> list[str]:
        return sorted(k for k in self._data if k.startswith(query))

    async def search(self, query: str) -> list[StorageSearchResult]:
        # Trivial substring scan; good enough for the spike.
        hits = []
        for k, v in self._data.items():
            if query.lower().encode() in v.lower():
                hits.append(StorageSearchResult(key=k, score=1.0))
        return hits


@tool
def huge_file_read(path: str = "spec.txt") -> str:
    """Read a (synthetic) huge file so the tool result exceeds the offload threshold."""
    return "\n".join(f"row {i}: " + ("x" * 40) for i in range(400))


def main() -> None:
    env = load_env()
    model = make_model(env)
    storage = DictStorage()

    agent = Agent(
        model=model,
        tools=[huge_file_read],
        system_prompt="You are a terse assistant that reads files with huge_file_read when asked.",
        plugins=[ContextOffloader(storage=storage, max_result_tokens=200, preview_tokens=50)],
    )

    result = agent(
        "Read spec.txt with huge_file_read and tell me how many rows it has, in one sentence."
    )

    stored_keys_raw = list(storage._data.keys())

    out = {
        "stored_keys_in_dict_storage": stored_keys_raw,
        "num_stored_blocks": len(stored_keys_raw),
        "final_response": str(result).strip(),
        "note": "keys are namespaced under 'offloader/' by ContextOffloader._resolve_storage",
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
