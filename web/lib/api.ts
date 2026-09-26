import "server-only";
import type {
  ApiErrorBody,
  CreateRunRequest,
  CreateRunResponse,
  GetArtifactResponse,
  GetArtifactsResponse,
  GetEventsResponse,
  GetRunResponse,
  GetStepResponse,
  GetToolResponse,
  ListKnowledgeResponse,
  ListRunsResponse,
  ListToolsResponse,
  RunControlResponse,
  SearchKnowledgeResponse,
} from "./types";

/**
 * Server-only PortPilot API client. Talks to PORTPILOT_API_URL with the bearer
 * token from PORTPILOT_API_TOKEN. Both are server-side env vars -- never
 * expose them to the browser (no NEXT_PUBLIC_ prefix, never returned in a
 * response body).
 */

export class PortPilotApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.error?.message ?? `PortPilot API error (${status})`);
    this.name = "PortPilotApiError";
    this.status = status;
    this.code = body?.error?.code ?? "unknown";
  }
}

export function getApiBaseUrl(): string | null {
  const url = process.env.PORTPILOT_API_URL;
  return url && url.length > 0 ? url.replace(/\/+$/, "") : null;
}

function getApiToken(): string | undefined {
  return process.env.PORTPILOT_API_TOKEN;
}

/** True when no upstream API is configured and the proxy should serve fixtures. */
export function isFixturesMode(): boolean {
  return getApiBaseUrl() === null;
}

interface RequestOptions {
  method?: string;
  path: string;
  query?: Record<string, string | number | undefined>;
  body?: unknown;
}

async function request<T>(opts: RequestOptions): Promise<T> {
  const base = getApiBaseUrl();
  if (!base) {
    throw new Error("PORTPILOT_API_URL is not configured; use fixtures mode instead.");
  }
  const token = getApiToken();
  const url = new URL(base + opts.path);
  if (opts.query) {
    for (const [key, value] of Object.entries(opts.query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url.toString(), {
    method: opts.method ?? "GET",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let errBody: ApiErrorBody | null = null;
    try {
      errBody = (await res.json()) as ApiErrorBody;
    } catch {
      errBody = null;
    }
    throw new PortPilotApiError(res.status, errBody);
  }
  return (await res.json()) as T;
}

export const portpilot = {
  health(): Promise<{ ok: true; version: string }> {
    return request({ path: "/api/health" });
  },
  createRun(body: CreateRunRequest): Promise<CreateRunResponse> {
    return request({ method: "POST", path: "/api/runs", body });
  },
  listRuns(limit = 50): Promise<ListRunsResponse> {
    return request({ path: "/api/runs", query: { limit } });
  },
  getRun(runId: string): Promise<GetRunResponse> {
    return request({ path: `/api/runs/${encodeURIComponent(runId)}` });
  },
  getStep(runId: string, stepId: string): Promise<GetStepResponse> {
    return request({
      path: `/api/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}`,
    });
  },
  getEvents(runId: string, afterSeq = 0, limit = 200): Promise<GetEventsResponse> {
    return request({
      path: `/api/runs/${encodeURIComponent(runId)}/events`,
      query: { after_seq: afterSeq, limit },
    });
  },
  pauseRun(runId: string): Promise<RunControlResponse> {
    return request({ method: "POST", path: `/api/runs/${encodeURIComponent(runId)}/pause` });
  },
  resumeRun(runId: string): Promise<RunControlResponse> {
    return request({ method: "POST", path: `/api/runs/${encodeURIComponent(runId)}/resume` });
  },
  cancelRun(runId: string): Promise<RunControlResponse> {
    return request({ method: "POST", path: `/api/runs/${encodeURIComponent(runId)}/cancel` });
  },
  getArtifacts(runId: string): Promise<GetArtifactsResponse> {
    return request({ path: `/api/runs/${encodeURIComponent(runId)}/artifacts` });
  },
  getArtifact(runId: string, artifactId: string): Promise<GetArtifactResponse> {
    return request({
      path: `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
    });
  },
  listTools(status?: string): Promise<ListToolsResponse> {
    return request({ path: "/api/tools", query: { status } });
  },
  getTool(name: string): Promise<GetToolResponse> {
    return request({ path: `/api/tools/${encodeURIComponent(name)}` });
  },
  searchKnowledge(params: {
    q: string;
    kinds?: string;
    mode?: string;
    limit?: number;
  }): Promise<SearchKnowledgeResponse> {
    return request({ path: "/api/knowledge/search", query: params });
  },
  listKnowledge(params: { kinds?: string; run_id?: string; limit?: number }): Promise<ListKnowledgeResponse> {
    return request({ path: "/api/knowledge", query: params });
  },
};
