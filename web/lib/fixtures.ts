import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type {
  ArtifactMeta,
  Event,
  Hit,
  KnowledgeItem,
  LongTermPlan,
  Run,
  RunSummary,
  ShortTermPlan,
  ToolRecord,
  ToolStatus,
  ToolSummary,
} from "./types";

/**
 * Fixtures-mode data source. Used by the API proxy when PORTPILOT_API_URL is
 * unset. Reads static JSON under web/fixtures/ so `npm run dev` renders every
 * page with no backend running.
 */

const FIXTURES_DIR = path.join(process.cwd(), "fixtures");

interface RunsFixture {
  runs: Record<string, Run>;
  plans: Record<string, LongTermPlan>;
  steps: Record<string, ShortTermPlan[]>;
}

let runsCache: RunsFixture | null = null;
let eventsCache: Record<string, Event[]> | null = null;
let toolsCache: Record<string, ToolRecord[]> | null = null;
let knowledgeCache: KnowledgeItem[] | null = null;

async function loadJson<T>(name: string): Promise<T> {
  const raw = await readFile(path.join(FIXTURES_DIR, name), "utf-8");
  return JSON.parse(raw) as T;
}

async function getRunsFixture(): Promise<RunsFixture> {
  if (!runsCache) runsCache = await loadJson<RunsFixture>("runs.json");
  return runsCache;
}

async function getEventsFixture(): Promise<Record<string, Event[]>> {
  if (!eventsCache) eventsCache = await loadJson<Record<string, Event[]>>("events.json");
  return eventsCache;
}

async function getToolsFixture(): Promise<Record<string, ToolRecord[]>> {
  if (!toolsCache) toolsCache = await loadJson<Record<string, ToolRecord[]>>("tools.json");
  return toolsCache;
}

async function getKnowledgeFixture(): Promise<KnowledgeItem[]> {
  if (!knowledgeCache) knowledgeCache = await loadJson<KnowledgeItem[]>("knowledge.json");
  return knowledgeCache;
}

function toSummary(run: Run, steps: ShortTermPlan[]): RunSummary {
  const done = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const current = steps.find((s) => s.step_id === run.current_step_id);
  return {
    run_id: run.run_id,
    repo_url: run.repo_url,
    goal: run.goal,
    status: run.status,
    created_at: run.created_at,
    updated_at: run.updated_at,
    steps_total: steps.length,
    steps_done: done,
    current_step_title: current?.title ?? null,
    usage: run.usage,
  };
}

export const fixtures = {
  async listRuns(limit = 50): Promise<RunSummary[]> {
    const { runs, steps } = await getRunsFixture();
    const summaries = Object.values(runs).map((run) => toSummary(run, steps[run.run_id] ?? []));
    summaries.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return summaries.slice(0, limit);
  },

  async createRun(repoUrl: string, goal: string): Promise<string> {
    // Fixtures mode always hands back the running fixture's id, per the lane brief.
    void repoUrl;
    void goal;
    return "run_running002";
  },

  async getRun(runId: string): Promise<{ run: Run; plan: LongTermPlan | null; steps: ShortTermPlan[] } | null> {
    const { runs, plans, steps } = await getRunsFixture();
    const run = runs[runId];
    if (!run) return null;
    return { run, plan: plans[runId] ?? null, steps: steps[runId] ?? [] };
  },

  async getStep(runId: string, stepId: string): Promise<ShortTermPlan | null> {
    const { steps } = await getRunsFixture();
    return (steps[runId] ?? []).find((s) => s.step_id === stepId) ?? null;
  },

  async getEvents(runId: string, afterSeq = 0, limit = 200): Promise<{ events: Event[]; next_after_seq: number }> {
    const all = (await getEventsFixture())[runId] ?? [];
    const filtered = all.filter((e) => e.seq > afterSeq).slice(0, limit);
    const nextAfterSeq = filtered.length > 0 ? filtered[filtered.length - 1]!.seq : afterSeq;
    return { events: filtered, next_after_seq: nextAfterSeq };
  },

  async controlRun(runId: string, action: "pause" | "resume" | "cancel"): Promise<{ ok: true; status: Run["status"] } | null> {
    const { runs } = await getRunsFixture();
    const run = runs[runId];
    if (!run) return null;
    const nextStatus: Run["status"] =
      action === "pause" ? "paused" : action === "cancel" ? "cancelled" : "queued";
    // Fixtures are read-only on disk; reflect the transition for this response only.
    return { ok: true, status: nextStatus };
  },

  async getArtifacts(runId: string): Promise<ArtifactMeta[]> {
    const events = (await getEventsFixture())[runId] ?? [];
    const metas: ArtifactMeta[] = [];
    for (const e of events) {
      const artifactId = (e.payload as { artifact_id?: string }).artifact_id;
      if (artifactId) {
        metas.push({
          artifact_id: artifactId,
          run_id: runId,
          step_id: e.step_id,
          kind: e.type,
          name: artifactId,
          created_at: e.ts,
        });
      }
    }
    return metas;
  },

  async getArtifact(runId: string, artifactId: string): Promise<{ artifact_id: string; run_id: string; step_id: string | null; kind: string; name: string; created_at: string; content: string } | null> {
    const metas = await fixtures.getArtifacts(runId);
    const meta = metas.find((m) => m.artifact_id === artifactId);
    if (!meta) return null;
    return { ...meta, content: `Fixture placeholder content for ${artifactId}.` };
  },

  async listTools(status?: ToolStatus): Promise<ToolSummary[]> {
    const byName = await getToolsFixture();
    const summaries: ToolSummary[] = [];
    for (const versions of Object.values(byName)) {
      const active = [...versions].reverse().find((v) => (status ? v.status === status : true)) ?? versions[versions.length - 1];
      if (!active) continue;
      if (status && !versions.some((v) => v.status === status)) continue;
      summaries.push({
        name: active.name,
        version: active.version,
        status: active.status,
        description: active.description,
        when_to_use: active.when_to_use,
        tags: active.tags,
        requires_cli: active.requires_cli,
        stats: active.stats,
        provenance: active.provenance,
        created_at: active.created_at,
        versions_count: versions.length,
      });
    }
    return summaries;
  },

  async getTool(name: string): Promise<ToolRecord[] | null> {
    const byName = await getToolsFixture();
    return byName[name] ?? null;
  },

  async searchKnowledge(q: string, kinds?: string, limit = 10): Promise<Hit[]> {
    const items = await getKnowledgeFixture();
    const kindList = kinds ? kinds.split(",") : null;
    const needle = q.trim().toLowerCase();
    const hits: Hit[] = [];
    for (const item of items) {
      if (kindList && !kindList.includes(item.kind)) continue;
      const haystack = `${item.title} ${item.body} ${item.tags.join(" ")}`.toLowerCase();
      if (!needle || haystack.includes(needle)) {
        const score = needle ? (haystack.split(needle).length - 1) / haystack.length + 0.5 : 0.5;
        hits.push({ item, score, via: "text" });
      }
    }
    hits.sort((a, b) => b.score - a.score);
    return hits.slice(0, limit);
  },

  async listKnowledge(kinds?: string, runId?: string, limit = 100): Promise<KnowledgeItem[]> {
    const items = await getKnowledgeFixture();
    const kindList = kinds ? kinds.split(",") : null;
    return items
      .filter((item) => (kindList ? kindList.includes(item.kind) : true))
      .filter((item) => (runId ? item.sources.some((s) => s.run_id === runId) : true))
      .slice(0, limit);
  },
};
