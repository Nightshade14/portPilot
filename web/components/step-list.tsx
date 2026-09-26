"use client";

import { useState } from "react";
import {
  ChevronRight,
  TerminalSquare,
  Wrench,
  GitCommitHorizontal,
  Clock,
} from "lucide-react";
import type { Step } from "@/lib/data";
import { StepStatusBadge } from "@/components/badges";
import { cn, durationBetween, compactNumber } from "@/lib/format";

export function StepList({ steps }: { steps: Step[] }) {
  const firstOpen = steps.find(
    (s) => s.status === "running" || s.status === "failed",
  );
  const [open, setOpen] = useState<string | null>(
    firstOpen?.step_id ?? steps[0]?.step_id ?? null,
  );

  return (
    <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
      {steps.map((step) => {
        const expanded = open === step.step_id;
        return (
          <div key={step.step_id}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : step.step_id)}
              className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/30"
              aria-expanded={expanded}
            >
              <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-secondary font-mono text-xs font-medium tabular-nums text-muted-foreground">
                {step.seq}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {step.title}
                </span>
              </span>
              <StepStatusBadge status={step.status} />
              <ChevronRight
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-transform",
                  expanded && "rotate-90",
                )}
              />
            </button>

            {expanded && (
              <div className="border-t border-border bg-secondary/30 px-4 py-4">
                <p className="text-sm text-muted-foreground">
                  {step.objective}
                </p>

                <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <Clock className="size-3.5" />
                    {durationBetween(step.started_at, step.ended_at)}
                  </span>
                  <span className="inline-flex items-center gap-1.5 font-mono">
                    {compactNumber(
                      step.usage.input_tokens + step.usage.output_tokens,
                    )}{" "}
                    tokens
                  </span>
                  <span className="font-mono">
                    attempt {step.attempts}
                  </span>
                  {step.commit_sha && (
                    <span className="inline-flex items-center gap-1.5 font-mono">
                      <GitCommitHorizontal className="size-3.5" />
                      {step.commit_sha.slice(0, 10)}
                    </span>
                  )}
                </div>

                {step.selected_tools.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <Wrench className="size-3.5" /> Selected tools
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {step.selected_tools.map((t) => (
                        <span
                          key={t.name}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11px]",
                            t.helpful
                              ? "border-success/30 bg-success/10 text-success"
                              : t.used
                                ? "border-border bg-card text-foreground"
                                : "border-border bg-secondary text-muted-foreground",
                          )}
                          title={t.reason}
                        >
                          {t.name} v{t.version}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {step.acceptance.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <TerminalSquare className="size-3.5" /> Acceptance checks
                    </p>
                    <div className="space-y-1.5">
                      {step.acceptance.map((a) => (
                        <div
                          key={a.name}
                          className="overflow-x-auto rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground scrollbar-thin"
                        >
                          <span className="text-muted-foreground">$ </span>
                          {a.command}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {step.outcome && (
                  <p className="mt-4 rounded-md border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
                    {step.outcome}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
