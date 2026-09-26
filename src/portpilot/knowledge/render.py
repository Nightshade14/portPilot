"""Readable markdown copies of knowledge items (lane brief step 4).

`render_markdown` produces the body written to `.portpilot/LESSONS.md`,
`.portpilot/GOTCHAS.md` and `.portpilot/MEMORY.md` at the end of every STP
(MVP_PLAN section 3.10). Atlas stays the source of truth; the harness (Lane M/the
worker loop) decides when and where to write these files -- this module only renders
text from a list of `KnowledgeItem`.
"""

from __future__ import annotations

from portpilot.core.models import KnowledgeItem, KnowledgeKind

_TITLES: dict[str, str] = {
    "lesson": "Lessons",
    "gotcha": "Gotchas",
    "memory": "Memory",
    "tool_card": "Tool cards",
    "run_digest": "Run digests",
}


def render_markdown(items: list[KnowledgeItem], kind: KnowledgeKind) -> str:
    """Newest-first markdown listing of `items` filtered to `kind`. Each entry shows
    title, body, tags, `seen_count` and sources."""
    filtered = [i for i in items if i.kind == kind]
    filtered.sort(key=lambda i: i.updated_at, reverse=True)

    title = _TITLES.get(kind, kind.title())
    lines = [f"# {title}", ""]
    if not filtered:
        lines.append("_Nothing recorded yet._")
        return "\n".join(lines) + "\n"

    for item in filtered:
        lines.append(f"## {item.title}")
        lines.append("")
        lines.append(item.body)
        lines.append("")
        if item.tags:
            lines.append(f"- **Tags:** {', '.join(sorted(item.tags))}")
        lines.append(f"- **Seen:** {item.seen_count}")
        if item.sources:
            source_bits = []
            for source in item.sources:
                bits = [b for b in (source.run_id, source.step_id, source.repo_url) if b]
                if bits:
                    source_bits.append(" / ".join(bits))
            if source_bits:
                lines.append(f"- **Sources:** {'; '.join(source_bits)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
