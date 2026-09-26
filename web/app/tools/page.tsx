import Link from "next/link";
import { Wrench, ArrowUpRight, Terminal } from "lucide-react";
import { getTools } from "@/lib/portpilot";
import { ToolStatusBadge, Tag } from "@/components/badges";

export const metadata = {
  title: "Tools · PortPilot Console",
};

export const dynamic = "force-dynamic";

function successRate(uses: number, successes: number): number | null {
  if (uses === 0) return null;
  return Math.round((successes / uses) * 100);
}

export default async function ToolsPage() {
  const tools = await getTools();

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <header className="mb-8">
        <p className="font-mono text-xs uppercase tracking-widest text-primary">
          Agent-authored
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
          Tool registry
        </h1>
        <p className="mt-2 max-w-2xl text-pretty text-sm text-muted-foreground">
          Tools PortPilot wrote for itself while porting code — each versioned,
          tested, and promoted only after it proved useful in a real run.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tools.map(({ name, latest, versions, totalUses }) => {
          const rate = successRate(latest.stats.uses, latest.stats.successes);
          return (
            <Link
              key={name}
              href={`/tools/${encodeURIComponent(name)}`}
              className="group flex flex-col rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Wrench className="size-4.5" strokeWidth={2} />
                </span>
                <ToolStatusBadge status={latest.status} />
              </div>

              <div className="mt-3 flex items-center gap-1.5">
                <h2 className="truncate font-mono text-sm font-semibold">
                  {name}
                </h2>
                <span className="font-mono text-xs text-muted-foreground">
                  v{latest.version}
                </span>
                <ArrowUpRight className="ml-auto size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">
                {latest.description}
              </p>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {latest.tags.slice(0, 3).map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs">
                <span className="font-mono text-muted-foreground">
                  {totalUses} uses · {versions.length} ver
                </span>
                {rate !== null && (
                  <span
                    className={
                      rate >= 80
                        ? "font-mono font-medium text-success"
                        : rate >= 50
                          ? "font-mono font-medium text-warning"
                          : "font-mono font-medium text-danger"
                    }
                  >
                    {rate}% ok
                  </span>
                )}
              </div>

              {latest.requires_cli.length > 0 && (
                <div className="mt-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Terminal className="size-3" />
                  <span className="truncate font-mono">
                    {latest.requires_cli.join(", ")}
                  </span>
                </div>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
