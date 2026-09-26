"""`knowledge` Typer sub-app (lane brief step 5). The Lead wires this into
`portpilot.cli` later -- do not edit `src/portpilot/cli.py` from this lane."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

from portpilot.core.config import load_mvp_settings
from portpilot.core.models import KnowledgeItem, KnowledgeKind, KnowledgeSource, SearchMode, new_id
from portpilot.knowledge.embedder import make_embedder
from portpilot.knowledge.indexes import ensure_indexes
from portpilot.knowledge.store import AtlasKnowledgeStore

knowledge_app = typer.Typer(help="Knowledge base: indexes, search, add.")
console = Console()


def _store() -> AtlasKnowledgeStore:
    settings = load_mvp_settings()
    if not settings.mongodb_uri:
        raise typer.BadParameter("MONGODB_URI is not set")
    embedder = make_embedder(settings)
    return AtlasKnowledgeStore(settings.mongodb_uri, settings.mongodb_db, embedder)


@knowledge_app.command("init-indexes")
def init_indexes(
    wait: Annotated[bool, typer.Option(help="Poll until both indexes are queryable.")] = True,
    timeout_s: Annotated[int, typer.Option(help="Max seconds to wait for queryable.")] = 180,
) -> None:
    """Create/update `knowledge_text` and `knowledge_vec` on `<db>.knowledge`."""
    settings = load_mvp_settings()
    if not settings.mongodb_uri:
        raise typer.BadParameter("MONGODB_URI is not set")
    embedder = make_embedder(settings)
    store = AtlasKnowledgeStore(settings.mongodb_uri, settings.mongodb_db, embedder)
    try:
        report = ensure_indexes(store.db, embedder.dims, wait=wait, timeout_s=timeout_s)
    finally:
        store.close()
    console.print_json(json.dumps(report, default=str))


@knowledge_app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search text.")],
    kind: Annotated[
        list[str], typer.Option("--kind", help="Restrict to these kinds (repeatable).")
    ] = [],  # noqa: B006 - typer needs the literal default; it never mutates it
    mode: Annotated[SearchMode, typer.Option("--mode", help="hybrid | vector | text.")] = "hybrid",
    limit: Annotated[int, typer.Option("--limit")] = 8,
) -> None:
    """Search the knowledge base and print ranked hits."""
    store = _store()
    try:
        hits = store.search(query, kinds=kind or None, mode=mode, limit=limit)
    finally:
        store.close()
    for hit in hits:
        console.print(
            f"[bold]{hit.item.title}[/bold]  (kind={hit.item.kind}, via={hit.via}, "
            f"score={hit.score:.4f})"
        )
        console.print(hit.item.body[:200])
        console.print()


@knowledge_app.command("add")
def add(
    kind: Annotated[KnowledgeKind, typer.Option("--kind")],
    title: Annotated[str, typer.Option("--title")],
    body: Annotated[str, typer.Option("--body")],
    tag: Annotated[list[str], typer.Option("--tag", help="Repeatable tag.")] = [],  # noqa: B006
) -> None:
    """Add a knowledge item (embedded and upserted with dedupe)."""
    store = _store()
    try:
        item = KnowledgeItem(
            id=new_id("kn"),
            kind=kind,
            title=title,
            body=body,
            tags=list(tag),
            sources=[KnowledgeSource()],
        )
        item_id = store.upsert(item)
    finally:
        store.close()
    console.print(f"stored: {item_id}")
