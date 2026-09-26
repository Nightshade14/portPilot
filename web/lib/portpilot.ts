import "server-only";

import * as fx from "@/lib/data";
import type {
  KnowledgeItem,
  Plan,
  Run,
  RunDetail,
  RunEvent,
  Step,
  ToolSummary,
  ToolVersion,
} from "@/lib/data";

/**
 * Server-side access to the PortPilot backend.
 *
 * When PORTPILOT_API_URL is configured, RSC pages read live data directly
 * from `${PORTPILOT_API_URL}/api/{path}` using the bearer token. If the URL is
 * absent, or a live request fails, we fall back to the bundled fixtures so the
 * console still renders. Client-side calls go through the `/api/pp` proxy
 * instead, which enforces the same contract without exposing the token.
 */

export function apiBase(): string | null {
  const base = process.env.PORTPILOT_API_URL;
  return base && base.length > 0 ? base.replace(/\/+$/, "") : null;
}

async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const base = apiBase();
  if (!base) throw new Error("PORTPILOT_API_URL is not configured");

  const url = new URL(`${base}/api/${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const token = process.env.PORTPILOT_API_TOKEN;
  const res = await fetch(url.toString(), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`PortPilot API responded ${res.status} for /api/${path}`);
  }
  return (await res.json()) as T;
}

export async function getRuns(): Promise<Run[]> {
  if (!apiBase()) return fx.fxListRuns();
  try {
    const data = await apiGet<{ runs: Run[] }>("runs", { limit: 50 });
    return Array.isArray(data.runs) ? data.runs : fx.fxListRuns();
  } catch {
    return fx.fxListRuns();
  }
}

export async function getRunDetail(id: string): Promise<RunDetail | null> {
  if (!apiBase()) return fx.fxGetRunDetail(id);
  try {
    const raw = await apiGet<
      Partial<RunDetail> & Run & { run?: Run; plan?: Plan; steps?: Step[] }
    >(`runs/${encodeURIComponent(id)}`);

    // The detail endpoint may nest under `run` or return the run flat.
    const run = (raw.run ?? (raw as unknown as Run)) as Run;
    if (!run || !run.run_id) return fx.fxGetRunDetail(id);

    const plan = raw.plan ?? null;
    const steps = Array.isArray(raw.steps) ? raw.steps : [];

    let events: RunEvent[] = [];
    try {
      const ev = await apiGet<{ events: RunEvent[] }>(
        `runs/${encodeURIComponent(id)}/events`,
        { after_seq: 0, limit: 200 },
      );
      events = Array.isArray(ev.events) ? ev.events : [];
    } catch {
      events = fx.fxGetRunDetail(id)?.events ?? [];
    }

    return { run, plan, steps, events };
  } catch {
    return fx.fxGetRunDetail(id);
  }
}

export async function getTools(): Promise<ToolSummary[]> {
  if (!apiBase()) return fx.groupToolSummaries(fx.fxListTools());
  try {
    const data = await apiGet<{ tools: ToolVersion[] }>("tools");
    const list = Array.isArray(data.tools) ? data.tools : [];
    const summaries = fx.groupToolSummaries(list);
    return summaries.length > 0
      ? summaries
      : fx.groupToolSummaries(fx.fxListTools());
  } catch {
    return fx.groupToolSummaries(fx.fxListTools());
  }
}

export async function getToolSummary(name: string): Promise<ToolSummary | null> {
  const fromFixtures = () => {
    const versions = fx.fxGetToolVersions(name);
    return versions ? fx.toToolSummary(name, versions) : null;
  };

  if (!apiBase()) return fromFixtures();
  try {
    const data = await apiGet<{ name: string; versions: ToolVersion[] }>(
      `tools/${encodeURIComponent(name)}`,
    );
    if (!Array.isArray(data.versions) || data.versions.length === 0) {
      return fromFixtures();
    }
    return fx.toToolSummary(data.name ?? name, data.versions);
  } catch {
    return fromFixtures();
  }
}

export async function getKnowledge(): Promise<KnowledgeItem[]> {
  if (!apiBase()) return fx.fxListKnowledge();
  try {
    const data = await apiGet<{ items: KnowledgeItem[] }>("knowledge", {
      limit: 100,
    });
    return Array.isArray(data.items) ? data.items : fx.fxListKnowledge();
  } catch {
    return fx.fxListKnowledge();
  }
}
