"use client";

import { useMemo, useState } from "react";
import { Search, Lightbulb, Bug, IdCard, FileText, Eye } from "lucide-react";
import type { KnowledgeItem } from "@/lib/data";
import { Tag } from "@/components/badges";
import { cn, relativeTime } from "@/lib/format";

const kindMeta: Record<
  string,
  { label: string; cls: string; icon: typeof Lightbulb }
> = {
  lesson: {
    label: "Lesson",
    cls: "border-primary/30 bg-primary/10 text-primary",
    icon: Lightbulb,
  },
  gotcha: {
    label: "Gotcha",
    cls: "border-warning/40 bg-warning/10 text-warning",
    icon: Bug,
  },
  tool_card: {
    label: "Tool card",
    cls: "border-success/30 bg-success/10 text-success",
    icon: IdCard,
  },
  run_digest: {
    label: "Run digest",
    cls: "border-border bg-secondary text-muted-foreground",
    icon: FileText,
  },
};

const filters = [
  { id: "all", label: "All" },
  { id: "lesson", label: "Lessons" },
  { id: "gotcha", label: "Gotchas" },
  { id: "tool_card", label: "Tool cards" },
  { id: "run_digest", label: "Digests" },
];

export function KnowledgeBrowser({ items }: { items: KnowledgeItem[] }) {
  const [kind, setKind] = useState("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: items.length };
    for (const it of items) c[it.kind] = (c[it.kind] ?? 0) + 1;
    return c;
  }, [items]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((it) => {
      if (kind !== "all" && it.kind !== kind) return false;
      if (!q) return true;
      return (
        it.title.toLowerCase().includes(q) ||
        it.body.toLowerCase().includes(q) ||
        it.tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  }, [items, kind, query]);

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setKind(f.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                kind === f.id
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label}
              <span className="font-mono text-[11px] opacity-70">
                {counts[f.id] ?? 0}
              </span>
            </button>
          ))}
        </div>

        <div className="relative sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search knowledge…"
            className="w-full rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/50 focus:ring-2 focus:ring-primary/20"
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="mt-8 rounded-xl border border-dashed border-border bg-card p-10 text-center text-sm text-muted-foreground">
          No knowledge items match your filters.
        </p>
      ) : (
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {filtered.map((item) => {
            const cfg = kindMeta[item.kind] ?? kindMeta.run_digest;
            const Icon = cfg.icon;
            return (
              <article
                key={item.id}
                className="flex flex-col rounded-xl border border-border bg-card p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      cfg.cls,
                    )}
                  >
                    <Icon className="size-3" />
                    {cfg.label}
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                    <Eye className="size-3" />
                    {item.seen_count}
                  </span>
                </div>

                <h2 className="mt-3 text-pretty text-sm font-semibold leading-snug">
                  {item.title}
                </h2>
                <p className="mt-1.5 line-clamp-3 flex-1 text-sm text-muted-foreground">
                  {item.body}
                </p>

                {item.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {item.tags.slice(0, 4).map((t) => (
                      <Tag key={t}>{t}</Tag>
                    ))}
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px] text-muted-foreground">
                  <span className="font-mono">
                    {item.sources.length} source
                    {item.sources.length === 1 ? "" : "s"}
                  </span>
                  <span className="font-mono">
                    {relativeTime(item.updated_at)}
                  </span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
