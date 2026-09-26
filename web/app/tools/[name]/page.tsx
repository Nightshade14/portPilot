import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Wrench,
  Terminal,
  Lightbulb,
  GitBranch,
  History,
} from "lucide-react";
import { getToolSummary } from "@/lib/portpilot";
import { ToolStatusBadge, Tag } from "@/components/badges";
import { ToolSource } from "@/components/tool-source";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ToolDetailPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  const tool = await getToolSummary(decodeURIComponent(name));
  if (!tool) notFound();

  const { latest, versions, totalUses } = tool;
  const successes = versions.reduce((s, v) => s + v.stats.successes, 0);
  const failures = versions.reduce((s, v) => s + v.stats.failures, 0);
  const rate = totalUses > 0 ? Math.round((successes / totalUses) * 100) : null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-6 md:py-8">
      <Link
        href="/tools"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Tools
      </Link>

      <header className="mt-4 rounded-xl border border-border bg-card p-5 md:p-6">
        <div className="flex items-start gap-4">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Wrench className="size-5.5" strokeWidth={2} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="font-mono text-lg font-semibold tracking-tight md:text-xl">
                {tool.name}
              </h1>
              <span className="font-mono text-sm text-muted-foreground">
                v{latest.version}
              </span>
              <ToolStatusBadge status={latest.status} />
            </div>
            <p className="mt-2 text-pretty text-sm text-muted-foreground">
              {latest.description}
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {latest.tags.map((t) => (
                <Tag key={t}>{t}</Tag>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-4 sm:grid-cols-4">
          <Metric label="Total uses" value={totalUses} />
          <Metric
            label="Success rate"
            value={rate !== null ? `${rate}%` : "—"}
            tone={rate !== null && rate >= 80 ? "success" : rate !== null && rate < 50 ? "danger" : undefined}
          />
          <Metric label="Failures" value={failures} />
          <Metric label="Versions" value={versions.length} />
        </div>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="min-w-0 space-y-6">
          {latest.when_to_use && (
            <section className="rounded-xl border border-border bg-card p-5">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Lightbulb className="size-4 text-primary" />
                When to use
              </h2>
              <p className="mt-2 text-pretty text-sm text-muted-foreground">
                {latest.when_to_use}
              </p>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Source
            </h2>
            <ToolSource files={latest.files} tests={latest.tests} />
          </section>

          <div className="grid gap-6 sm:grid-cols-2">
            <SchemaCard title="Input schema" schema={latest.input_schema} />
            <SchemaCard title="Output schema" schema={latest.output_schema} />
          </div>
        </div>

        <aside className="min-w-0 space-y-6">
          {latest.requires_cli.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Requires CLI
              </h2>
              <div className="flex flex-wrap gap-1.5 rounded-xl border border-border bg-card p-4">
                {latest.requires_cli.map((c) => (
                  <span
                    key={c}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-secondary/60 px-2 py-1 font-mono text-[11px]"
                  >
                    <Terminal className="size-3" />
                    {c}
                  </span>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              <History className="size-3.5" /> Version history
            </h2>
            <ol className="space-y-2">
              {versions.map((v) => (
                <li
                  key={v.version}
                  className="rounded-lg border border-border bg-card p-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium">
                      v{v.version}
                    </span>
                    <ToolStatusBadge status={v.status} />
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                    {formatDate(v.created_at)} · {v.stats.uses} uses
                  </p>
                  {v.provenance.parent_version && (
                    <p className="mt-1 flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                      <GitBranch className="size-3" />
                      forked from v{v.provenance.parent_version}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Provenance
            </h2>
            <div className="space-y-2 rounded-xl border border-border bg-card p-4 text-xs">
              <ProvRow label="Author" value={latest.provenance.author} />
              {latest.provenance.run_id && (
                <ProvRow
                  label="Origin run"
                  value={
                    <Link
                      href={`/runs/${latest.provenance.run_id}`}
                      className="font-mono text-primary hover:underline"
                    >
                      {latest.provenance.run_id}
                    </Link>
                  }
                />
              )}
              <ProvRow
                label="Used in"
                value={`${latest.stats.runs_used_in.length} run(s)`}
              />
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "success" | "danger";
}) {
  const toneCls =
    tone === "success"
      ? "text-success"
      : tone === "danger"
        ? "text-danger"
        : "text-foreground";
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 font-mono text-xl font-semibold tabular-nums ${toneCls}`}>
        {value}
      </p>
    </div>
  );
}

function ProvRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-foreground">{value}</span>
    </div>
  );
}

function SchemaCard({
  title,
  schema,
}: {
  title: string;
  schema: Record<string, unknown>;
}) {
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed text-foreground scrollbar-thin">
          {JSON.stringify(schema, null, 2)}
        </pre>
      </div>
    </section>
  );
}
