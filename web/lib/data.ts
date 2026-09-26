import runsFixture from "@/fixtures/runs.json";
import eventsFixture from "@/fixtures/events.json";
import toolsFixture from "@/fixtures/tools.json";
import knowledgeFixture from "@/fixtures/knowledge.json";

export type RunStatus = "completed" | "running" | "failed" | "queued";

export type Budgets = {
  max_steps: number;
  max_tokens: number;
  max_minutes: number;
  max_tools_created: number;
  max_selected_tools: number;
  max_mid_step_loads: number;
};

export type Usage = {
  input_tokens: number;
  output_tokens: number;
  model_calls: number;
  tool_calls: number;
  compactions: number;
};

export type Run = {
  run_id: string;
  repo_url: string;
  goal: string;
  status: RunStatus;
  current_step_id: string | null;
  ltp_version: number;
  lease: { owner: string; expires_at: string } | null;
  budgets: Budgets;
  usage: Usage;
  cli_manifest: { name: string; version: string }[];
  tool_pins: Record<string, number>;
  control: unknown;
  error: unknown;
  workspace_branch: string;
  created_at: string;
  updated_at: string;
};

export type Phase = {
  id: string;
  title: string;
  goal?: string;
  exit_criteria?: string[];
  modules?: string[];
};

export type Plan = {
  run_id: string;
  version: number;
  goal: string;
  phases: Phase[];
  assumptions: string[];
  rationale: string;
  created_at: string;
};

export type SelectedTool = {
  name: string;
  version: number;
  reason: string;
  used: boolean;
  helpful: boolean | null;
};

export type Step = {
  step_id: string;
  run_id: string;
  seq: number;
  phase_id: string;
  title: string;
  objective: string;
  inputs: string[];
  acceptance: {
    name: string;
    command: string;
    expect_exit: number;
    timeout_s: number;
  }[];
  capability_hints: string[];
  budget: { max_turns: number; max_tokens: number; max_minutes: number };
  status: "done" | "running" | "failed" | "queued";
  selected_tools: SelectedTool[];
  missing_capabilities: string[];
  attempts: number;
  commit_sha: string | null;
  outcome: string | null;
  usage: Usage;
  started_at: string | null;
  ended_at: string | null;
};

export type RunEvent = {
  run_id: string;
  seq: number;
  ts: string;
  type: string;
  step_id: string | null;
  payload: Record<string, unknown>;
};

export type ToolVersion = {
  name: string;
  version: number;
  description: string;
  when_to_use: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  files: Record<string, string>;
  tests: Record<string, string>;
  requires_cli: string[];
  tags: string[];
  status: "active" | "deprecated";
  provenance: {
    run_id: string | null;
    step_id: string | null;
    repo_url: string | null;
    parent_version: number | null;
    author: string;
  };
  stats: {
    uses: number;
    successes: number;
    failures: number;
    runs_used_in: string[];
  };
  created_at: string;
};

export type KnowledgeItem = {
  id: string;
  kind: "lesson" | "gotcha" | "tool_card" | "run_digest";
  title: string;
  body: string;
  tags: string[];
  facets: Record<string, string>;
  sources: { run_id: string; step_id: string | null; repo_url: string | null }[];
  seen_count: number;
  status: string;
  ref: string | null;
  created_at: string;
  updated_at: string;
};

export type RunBundle = { run: Run; plan: Plan | null; steps: Step[] };
export type RunDetail = RunBundle & { events: RunEvent[] };

export type ToolSummary = {
  name: string;
  latest: ToolVersion;
  versions: ToolVersion[];
  totalUses: number;
};

const runs = runsFixture as unknown as {
  runs: Record<string, Run>;
  plans: Record<string, Plan>;
  steps: Record<string, Step[]>;
};
const events = eventsFixture as unknown as Record<string, RunEvent[]>;
const tools = toolsFixture as unknown as Record<string, ToolVersion[]>;
const knowledge = knowledgeFixture as unknown as KnowledgeItem[];

/**
 * Fixture-backed data functions. These mirror the PortPilot API response
 * shapes exactly and are used both by the `/api/pp` proxy fallback (when no
 * PORTPILOT_API_URL is configured) and by `lib/portpilot.ts` as a fallback
 * when a live request fails. They are pure and safe to import anywhere.
 */

export function fxListRuns(limit = 50): Run[] {
  return Object.values(runs.runs)
    .sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    .slice(0, limit);
}

export function fxGetRunBundle(id: string): RunBundle | null {
  const run = runs.runs[id];
  if (!run) return null;
  return { run, plan: runs.plans[id] ?? null, steps: runs.steps[id] ?? [] };
}

export function fxGetRunDetail(id: string): RunDetail | null {
  const bundle = fxGetRunBundle(id);
  if (!bundle) return null;
  return { ...bundle, events: events[id] ?? [] };
}

export function fxGetEvents(
  id: string,
  afterSeq = 0,
  limit = 200,
): { run_id: string; events: RunEvent[]; next_seq: number } {
  const matched = (events[id] ?? [])
    .filter((e) => e.seq > afterSeq)
    .slice(0, limit);
  const next = matched.length ? matched[matched.length - 1].seq : afterSeq;
  return { run_id: id, events: matched, next_seq: next };
}

export function fxGetStep(id: string, stepId: string): Step | null {
  return (runs.steps[id] ?? []).find((s) => s.step_id === stepId) ?? null;
}

export function fxControlRun(
  id: string,
  action: string,
): { run_id: string; control: string; status: RunStatus } | null {
  if (!runs.runs[id]) return null;
  const status: RunStatus =
    action === "cancel" ? "failed" : action === "pause" ? "queued" : "running";
  return { run_id: id, control: action, status };
}

export function fxGetArtifacts(_id: string): unknown[] {
  return [];
}

export function fxGetArtifact(_id: string, _artId: string): unknown | null {
  return null;
}

export function fxListTools(status?: string): ToolVersion[] {
  const all = Object.values(tools).flat();
  return status ? all.filter((t) => t.status === status) : all;
}

export function fxGetToolVersions(name: string): ToolVersion[] | null {
  const versions = tools[name];
  if (!versions) return null;
  return [...versions].sort((a, b) => b.version - a.version);
}

export function fxSearchKnowledge(
  q: string,
  kinds?: string,
  limit = 10,
): KnowledgeItem[] {
  const kindSet = kinds ? new Set(kinds.split(",")) : null;
  const query = q.trim().toLowerCase();
  return knowledge
    .filter((k) => {
      if (kindSet && !kindSet.has(k.kind)) return false;
      if (!query) return true;
      return (
        k.title.toLowerCase().includes(query) ||
        k.body.toLowerCase().includes(query) ||
        k.tags.some((t) => t.toLowerCase().includes(query))
      );
    })
    .slice(0, limit);
}

export function fxListKnowledge(
  kinds?: string,
  runId?: string,
  limit = 100,
): KnowledgeItem[] {
  const kindSet = kinds ? new Set(kinds.split(",")) : null;
  return [...knowledge]
    .filter((k) => {
      if (kindSet && !kindSet.has(k.kind)) return false;
      if (runId && !k.sources.some((s) => s.run_id === runId)) return false;
      return true;
    })
    .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at))
    .slice(0, limit);
}

export function fxCreateRun(_repoUrl: string, _goal: string): string {
  return `run_${Math.random().toString(36).slice(2, 10)}`;
}

/** Shape helpers shared between the live layer and fixtures. */

export function toToolSummary(name: string, versions: ToolVersion[]): ToolSummary {
  const sorted = [...versions].sort((a, b) => b.version - a.version);
  const active = sorted.find((v) => v.status === "active") ?? sorted[0];
  return {
    name,
    latest: active,
    versions: sorted,
    totalUses: versions.reduce((sum, v) => sum + (v.stats?.uses ?? 0), 0),
  };
}

export function groupToolSummaries(list: ToolVersion[]): ToolSummary[] {
  const byName = new Map<string, ToolVersion[]>();
  for (const v of list) {
    const arr = byName.get(v.name) ?? [];
    arr.push(v);
    byName.set(v.name, arr);
  }
  return [...byName.entries()]
    .map(([name, versions]) => toToolSummary(name, versions))
    .sort((a, b) => b.totalUses - a.totalUses);
}
