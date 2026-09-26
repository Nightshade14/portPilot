import { Activity, CheckCircle2, Cpu, Layers } from "lucide-react";
import { getRuns, getTools, getKnowledge } from "@/lib/portpilot";
import { StatCard } from "@/components/stat-card";
import { RunCard } from "@/components/run-card";
import { RunStatusBadge } from "@/components/badges";
import { compactNumber, repoName, relativeTime } from "@/lib/format";
import { StartRunForm } from "@/components/start-run-form";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [runs, tools, knowledge] = await Promise.all([
    getRuns(),
    getTools(),
    getKnowledge(),
  ]);

  const active = runs.filter((r) => r.status === "running").length;
  const completed = runs.filter((r) => r.status === "completed").length;
  const totalTokens = runs.reduce(
    (sum, r) => sum + r.usage.input_tokens + r.usage.output_tokens,
    0,
  );
  const successRate =
    runs.length > 0 ? Math.round((completed / runs.length) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <header className="mb-8">
        <p className="font-mono text-xs uppercase tracking-widest text-primary">
          Mission control
        </p>
        <h1 className="mt-2 text-balance text-2xl font-semibold tracking-tight md:text-3xl">
          Autonomous porting runs
        </h1>
        <p className="mt-2 max-w-2xl text-pretty text-sm text-muted-foreground">
          PortPilot plans, writes its own tools, and ports repositories step by
          step. Track every run, budget, and lesson it learns along the way.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Active runs"
          value={active}
          sub={`${runs.length} total runs`}
          icon={Activity}
          accent="warning"
        />
        <StatCard
          label="Completed"
          value={completed}
          sub={`${successRate}% success rate`}
          icon={CheckCircle2}
          accent="success"
        />
        <StatCard
          label="Tokens used"
          value={compactNumber(totalTokens)}
          sub="across all runs"
          icon={Cpu}
        />
        <StatCard
          label="Tools authored"
          value={tools.length}
          sub={`${knowledge.length} knowledge items`}
          icon={Layers}
        />
      </section>

      <section className="mt-10 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Recent runs
            </h2>
            <span className="font-mono text-xs text-muted-foreground">
              {runs.length} shown
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {runs.map((run) => (
              <RunCard key={run.run_id} run={run} />
            ))}
          </div>
        </div>

        <aside className="grid gap-6 lg:sticky lg:top-20 lg:self-start">
          <StartRunForm />
          <div className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Run activity</h2>
            </div>
            <ul className="divide-y divide-border">
              {runs.slice(0, 6).map((run) => (
                <li key={run.run_id}>
                  <Link
                    href={`/runs/${run.run_id}`}
                    className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent/40"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-xs font-medium">
                        {repoName(run.repo_url)}
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                        {relativeTime(run.updated_at)}
                      </p>
                    </div>
                    <RunStatusBadge status={run.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </section>
    </div>
  );
}
