import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  GitBranch,
  Cpu,
  MousePointerClick,
  Layers,
  Clock,
  KeyRound,
  Target,
} from "lucide-react";
import { getRunDetail } from "@/lib/portpilot";
import { RunStatusBadge } from "@/components/badges";
import { UsageBar } from "@/components/usage-bar";
import { StepList } from "@/components/step-list";
import { EventTimeline } from "@/components/event-timeline";
import {
  compactNumber,
  formatDateTime,
  relativeTime,
  repoName,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await getRunDetail(id);
  if (!data) notFound();

  const { run, plan, steps, events } = data;
  const totalTokens = run.usage.input_tokens + run.usage.output_tokens;
  const doneSteps = steps.filter((s) => s.status === "done").length;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-6 md:py-8">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Overview
      </Link>

      <header className="mt-4 rounded-xl border border-border bg-card p-5 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h1 className="truncate font-mono text-lg font-semibold tracking-tight md:text-xl">
                {repoName(run.repo_url)}
              </h1>
              <RunStatusBadge status={run.status} />
            </div>
            <p className="mt-2 flex items-start gap-2 text-pretty text-sm text-muted-foreground">
              <Target className="mt-0.5 size-4 shrink-0 text-primary" />
              {run.goal}
            </p>
            <a
              href={run.repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            >
              {run.repo_url}
            </a>
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <GitBranch className="size-3.5" /> Branch
            </dt>
            <dd className="mt-1 truncate font-mono text-xs">
              {run.workspace_branch}
            </dd>
          </div>
          <div>
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <KeyRound className="size-3.5" /> Lease
            </dt>
            <dd className="mt-1 truncate font-mono text-xs">
              {run.lease ? run.lease.owner : "released"}
            </dd>
          </div>
          <div>
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Layers className="size-3.5" /> Plan
            </dt>
            <dd className="mt-1 font-mono text-xs">v{run.ltp_version}</dd>
          </div>
          <div>
            <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-3.5" /> Updated
            </dt>
            <dd className="mt-1 font-mono text-xs">
              {relativeTime(run.updated_at)}
            </dd>
          </div>
        </dl>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="min-w-0 space-y-6">
          {plan && (
            <section>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Plan
              </h2>
              <div className="rounded-xl border border-border bg-card p-5">
                <p className="text-sm text-muted-foreground">{plan.rationale}</p>
                <ol className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-stretch">
                  {plan.phases.map((phase, i) => (
                    <li
                      key={phase.id}
                      className="flex flex-1 items-center gap-3 rounded-lg border border-border bg-secondary/40 p-3"
                    >
                      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-xs font-semibold text-primary">
                        {i + 1}
                      </span>
                      <span className="text-sm font-medium leading-tight">
                        {phase.title}
                      </span>
                    </li>
                  ))}
                </ol>
                {plan.assumptions?.length > 0 && (
                  <div className="mt-4 border-t border-border pt-4">
                    <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Assumptions
                    </p>
                    <ul className="space-y-1">
                      {plan.assumptions.map((a, i) => (
                        <li
                          key={i}
                          className="flex gap-2 text-sm text-muted-foreground"
                        >
                          <span className="text-primary">·</span>
                          {a}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Steps
              </h2>
              <span className="font-mono text-xs text-muted-foreground">
                {doneSteps}/{steps.length} done
              </span>
            </div>
            {steps.length > 0 ? (
              <StepList steps={steps} />
            ) : (
              <p className="rounded-xl border border-dashed border-border bg-card p-6 text-center text-sm text-muted-foreground">
                No steps recorded yet.
              </p>
            )}
          </section>
        </div>

        <aside className="min-w-0 space-y-6">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Budgets &amp; usage
            </h2>
            <div className="space-y-4 rounded-xl border border-border bg-card p-5">
              <UsageBar
                label="Tokens"
                value={totalTokens}
                max={run.budgets.max_tokens}
                format={compactNumber}
              />
              <UsageBar
                label="Steps"
                value={steps.length}
                max={run.budgets.max_steps}
              />
              <UsageBar
                label="Pinned tools"
                value={Object.keys(run.tool_pins).length}
                max={run.budgets.max_selected_tools}
              />
              <div className="grid grid-cols-2 gap-3 border-t border-border pt-4">
                <MiniStat
                  icon={Cpu}
                  label="Model calls"
                  value={run.usage.model_calls}
                />
                <MiniStat
                  icon={MousePointerClick}
                  label="Tool calls"
                  value={run.usage.tool_calls}
                />
              </div>
            </div>
          </section>

          {run.cli_manifest?.length > 0 && (
            <section>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                CLI manifest
              </h2>
              <div className="flex flex-wrap gap-1.5 rounded-xl border border-border bg-card p-4">
                {run.cli_manifest.map((cli) => (
                  <span
                    key={cli.name}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-secondary/60 px-2 py-1 font-mono text-[11px]"
                  >
                    {cli.name}
                    <span className="text-muted-foreground">{cli.version}</span>
                  </span>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Event log
            </h2>
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="mb-3 flex items-center justify-between">
                <span className="font-mono text-xs text-muted-foreground">
                  {events.length} events
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {events.length > 0 ? formatDateTime(events[0].ts) : ""}
                </span>
              </div>
              <div className="max-h-[560px] overflow-y-auto pr-1 scrollbar-thin">
                {events.length > 0 ? (
                  <EventTimeline events={events} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    No events recorded.
                  </p>
                )}
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-secondary/40 p-3">
      <Icon className="size-4 text-muted-foreground" />
      <p className="mt-2 font-mono text-lg font-semibold tabular-nums">
        {value}
      </p>
      <p className="text-[11px] text-muted-foreground">{label}</p>
    </div>
  );
}
