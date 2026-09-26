import {
  Rocket,
  KeyRound,
  ScanSearch,
  ListTree,
  Play,
  CheckCircle2,
  Terminal,
  MousePointerClick,
  CornerDownRight,
  GitCommitHorizontal,
  Wrench,
  ShieldCheck,
  ArrowUpCircle,
  AlertTriangle,
  XCircle,
  Download,
  Ban,
  Minimize2,
  Lightbulb,
  Bug,
  Flag,
  Circle,
  type LucideIcon,
} from "lucide-react";
import type { RunEvent } from "@/lib/data";
import { formatTime } from "@/lib/format";

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "accent";

const meta: Record<string, { label: string; tone: Tone; icon: LucideIcon }> = {
  run_created: { label: "Run created", tone: "primary", icon: Rocket },
  lease_acquired: { label: "Lease acquired", tone: "neutral", icon: KeyRound },
  survey_done: { label: "Survey complete", tone: "primary", icon: ScanSearch },
  plan_created: { label: "Plan created", tone: "primary", icon: ListTree },
  step_planned: { label: "Step planned", tone: "neutral", icon: ListTree },
  step_started: { label: "Step started", tone: "primary", icon: Play },
  cli_checked: { label: "CLI checked", tone: "neutral", icon: Terminal },
  tools_selected: { label: "Tools selected", tone: "accent", icon: Wrench },
  tool_call: { label: "Tool call", tone: "neutral", icon: MousePointerClick },
  tool_result: { label: "Tool result", tone: "neutral", icon: CornerDownRight },
  checkpoint: { label: "Checkpoint", tone: "neutral", icon: GitCommitHorizontal },
  step_verified: { label: "Step verified", tone: "success", icon: CheckCircle2 },
  tool_created: { label: "Tool created", tone: "accent", icon: Wrench },
  tool_validated: { label: "Tool validated", tone: "success", icon: ShieldCheck },
  tool_promoted: { label: "Tool promoted", tone: "success", icon: ArrowUpCircle },
  tool_error: { label: "Tool error", tone: "danger", icon: AlertTriangle },
  step_failed: { label: "Step failed", tone: "danger", icon: XCircle },
  tool_loaded: { label: "Tool loaded", tone: "neutral", icon: Download },
  compaction: { label: "Context compaction", tone: "warning", icon: Minimize2 },
  cli_installed: { label: "CLI installed", tone: "neutral", icon: Download },
  cli_refused: { label: "CLI refused", tone: "danger", icon: Ban },
  lesson_recorded: { label: "Lesson recorded", tone: "accent", icon: Lightbulb },
  gotcha_recorded: { label: "Gotcha recorded", tone: "warning", icon: Bug },
  completed: { label: "Run completed", tone: "success", icon: Flag },
  budget_exceeded: { label: "Budget exceeded", tone: "danger", icon: AlertTriangle },
};

const toneNode: Record<Tone, string> = {
  neutral: "border-border bg-secondary text-muted-foreground",
  primary: "border-primary/30 bg-primary/10 text-primary",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
  accent: "border-primary/30 bg-accent text-accent-foreground",
};

function summarize(type: string, payload: Record<string, unknown>): string | null {
  const p = payload as Record<string, any>;
  switch (type) {
    case "run_created":
      return p.goal ?? null;
    case "lease_acquired":
      return p.owner ? `owner ${p.owner}` : null;
    case "survey_done":
      return `${p.files ?? "?"} files · ${Object.keys(p.languages ?? {}).join(", ")}`;
    case "plan_created":
      return `v${p.version} · ${p.phases?.length ?? 0} phases`;
    case "step_planned":
    case "step_started":
      return p.title ?? null;
    case "tools_selected":
      return Array.isArray(p.tools)
        ? p.tools.map((t: any) => (typeof t === "string" ? t : t.name)).join(", ")
        : null;
    case "tool_call":
    case "tool_loaded":
    case "tool_created":
    case "tool_validated":
    case "tool_promoted":
      return p.name ? `${p.name}${p.version ? ` v${p.version}` : ""}` : null;
    case "tool_result":
      return p.ok === false ? "failed" : p.ok === true ? "ok" : (p.status ?? null);
    case "checkpoint":
      return p.commit_sha ? `commit ${String(p.commit_sha).slice(0, 10)}` : null;
    case "tool_error":
    case "step_failed":
    case "cli_refused":
      return p.error ?? p.reason ?? p.message ?? null;
    case "compaction":
      return p.saved_tokens ? `saved ${p.saved_tokens} tokens` : "context compacted";
    case "cli_installed":
    case "cli_checked":
      return p.name ? `${p.name}${p.version ? ` ${p.version}` : ""}` : null;
    case "lesson_recorded":
    case "gotcha_recorded":
      return p.title ?? null;
    case "budget_exceeded":
      return p.dimension ?? p.kind ?? null;
    case "completed":
      return p.outcome ?? "finished";
    default:
      return null;
  }
}

export function EventTimeline({ events }: { events: RunEvent[] }) {
  return (
    <ol className="relative">
      {events.map((ev, i) => {
        const cfg = meta[ev.type] ?? {
          label: ev.type,
          tone: "neutral" as Tone,
          icon: Circle,
        };
        const Icon = cfg.icon;
        const summary = summarize(ev.type, ev.payload);
        const last = i === events.length - 1;
        return (
          <li key={ev.seq} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && (
              <span
                className="absolute left-[15px] top-8 h-[calc(100%-1rem)] w-px bg-border"
                aria-hidden
              />
            )}
            <span
              className={`z-10 flex size-8 shrink-0 items-center justify-center rounded-full border ${toneNode[cfg.tone]}`}
            >
              <Icon className="size-4" strokeWidth={2} />
            </span>
            <div className="min-w-0 flex-1 pt-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-sm font-medium text-foreground">
                  {cfg.label}
                </span>
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {formatTime(ev.ts)}
                </span>
                {ev.step_id && (
                  <span className="font-mono text-[11px] text-muted-foreground/70">
                    {ev.step_id.split("_").slice(-1)[0]}
                  </span>
                )}
              </div>
              {summary && (
                <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">
                  {summary}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
