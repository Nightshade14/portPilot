import Link from "next/link";
import { GitBranch, ArrowUpRight } from "lucide-react";
import type { Run } from "@/lib/data";
import { RunStatusBadge } from "@/components/badges";
import { UsageBar } from "@/components/usage-bar";
import { compactNumber, relativeTime, repoName } from "@/lib/format";

type RunCardRun = Run & {
  steps_done?: number;
  steps_total?: number;
};

export function RunCard({ run }: { run: RunCardRun }) {
  const totalTokens = run.usage.input_tokens + run.usage.output_tokens;
  // The list endpoint intentionally returns a compact run summary. Detailed
  // budget data is available only from /runs/:id, so do not assume it exists.
  const stepValue = run.steps_done ?? run.usage.tool_calls;
  const stepMax = run.steps_total ?? run.budgets?.max_steps;
  const tokenMax = run.budgets?.max_tokens;
  return (
    <Link
      href={`/runs/${run.run_id}`}
      className="group flex flex-col rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate font-mono text-sm font-medium text-foreground">
              {repoName(run.repo_url)}
            </span>
            <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
            {run.goal}
          </p>
        </div>
        <RunStatusBadge status={run.status} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3">
        {stepMax !== undefined ? (
          <UsageBar label="Steps" value={stepValue} max={stepMax} />
        ) : null}
        {tokenMax !== undefined ? (
          <UsageBar
            label="Tokens"
            value={totalTokens}
            max={tokenMax}
            format={compactNumber}
          />
        ) : (
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              Tokens used
            </p>
            <p className="mt-1 font-mono text-xs tabular-nums text-foreground">
              {compactNumber(totalTokens)}
            </p>
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5 font-mono">
          <GitBranch className="size-3.5" />
          {run.workspace_branch}
        </span>
        <span className="font-mono">{relativeTime(run.updated_at)}</span>
      </div>
    </Link>
  );
}
