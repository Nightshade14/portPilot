import { type NextRequest, NextResponse } from "next/server";
import * as fx from "@/lib/data";

/**
 * PortPilot API proxy.
 *
 * The browser calls `/api/pp/<path>` and this route forwards allowlisted
 * paths to `${PORTPILOT_API_URL}/api/<path>`, attaching the bearer token
 * server-side so it is never exposed to the client. When no API URL is
 * configured it serves fixture data with the same response shapes, keeping
 * the console usable in local/preview environments.
 */

export const dynamic = "force-dynamic";

const GET_ALLOW: RegExp[] = [
  /^health$/,
  /^runs$/,
  /^runs\/[^/]+$/,
  /^runs\/[^/]+\/steps\/[^/]+$/,
  /^runs\/[^/]+\/events$/,
  /^runs\/[^/]+\/artifacts$/,
  /^runs\/[^/]+\/artifacts\/[^/]+$/,
  /^runs\/[^/]+\/download$/,
  /^tools$/,
  /^tools\/[^/]+$/,
  /^knowledge\/search$/,
  /^knowledge$/,
];

const POST_ALLOW: RegExp[] = [
  /^runs$/,
  /^runs\/[^/]+\/pause$/,
  /^runs\/[^/]+\/resume$/,
  /^runs\/[^/]+\/cancel$/,
];

function apiBase(): string | null {
  const base = process.env.PORTPILOT_API_URL;
  return base && base.length > 0 ? base.replace(/\/+$/, "") : null;
}

function err(status: number, code: string, message: string) {
  return NextResponse.json({ error: { code, message } }, { status });
}

async function forward(path: string, method: string, req: NextRequest) {
  const base = apiBase() as string;
  const token = process.env.PORTPILOT_API_TOKEN;

  const url = new URL(`${base}/api/${path}`);
  req.nextUrl.searchParams.forEach((value, key) =>
    url.searchParams.set(key, value),
  );

  const isDownload = /\/download$/.test(path);
  const body = method === "POST" ? await req.text() : undefined;

  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && body.length > 0) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url.toString(), {
    method,
    headers,
    body,
    cache: "no-store",
  });

  if (isDownload) {
    return new Response(res.body, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") ?? "application/gzip",
        "Content-Disposition":
          res.headers.get("Content-Disposition") ?? "attachment",
      },
    });
  }

  return new Response(await res.text(), {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("Content-Type") ?? "application/json",
    },
  });
}

async function fixtureFallback(
  path: string,
  method: string,
  req: NextRequest,
) {
  const params = req.nextUrl.searchParams;

  if (path === "health") {
    return NextResponse.json({ ok: true, version: "0.1.0-fixtures" });
  }

  if (path === "runs" && method === "GET") {
    const limit = Number(params.get("limit") ?? 50);
    return NextResponse.json({ runs: fx.fxListRuns(limit) });
  }

  if (path === "runs" && method === "POST") {
    const body = (await req.json().catch(() => ({}))) as {
      repo_url?: string;
      goal?: string;
    };
    if (!body.repo_url || !body.goal) {
      return err(400, "bad_request", "repo_url and goal are required.");
    }
    const runId = fx.fxCreateRun(body.repo_url, body.goal);
    return NextResponse.json({ run_id: runId }, { status: 201 });
  }

  let m = path.match(/^runs\/([^/]+)$/);
  if (m && method === "GET") {
    const bundle = fx.fxGetRunBundle(m[1]);
    return bundle ? NextResponse.json(bundle) : err(404, "not_found", "Run not found.");
  }

  m = path.match(/^runs\/([^/]+)\/steps\/([^/]+)$/);
  if (m && method === "GET") {
    const step = fx.fxGetStep(m[1], m[2]);
    return step
      ? NextResponse.json({ step })
      : err(404, "not_found", "Step not found.");
  }

  m = path.match(/^runs\/([^/]+)\/events$/);
  if (m && method === "GET") {
    const afterSeq = Number(params.get("after_seq") ?? 0);
    const limit = Number(params.get("limit") ?? 200);
    return NextResponse.json(fx.fxGetEvents(m[1], afterSeq, limit));
  }

  m = path.match(/^runs\/([^/]+)\/(pause|resume|cancel)$/);
  if (m && method === "POST") {
    const result = fx.fxControlRun(m[1], m[2]);
    return result
      ? NextResponse.json(result)
      : err(404, "not_found", "Run not found.");
  }

  m = path.match(/^runs\/([^/]+)\/artifacts$/);
  if (m && method === "GET") {
    return NextResponse.json({ artifacts: fx.fxGetArtifacts(m[1]) });
  }

  m = path.match(/^runs\/([^/]+)\/artifacts\/([^/]+)$/);
  if (m && method === "GET") {
    const artifact = fx.fxGetArtifact(m[1], m[2]);
    return artifact
      ? NextResponse.json({ artifact })
      : err(404, "not_found", "Artifact not found.");
  }

  m = path.match(/^runs\/([^/]+)\/download$/);
  if (m && method === "GET") {
    return new Response(`Fixture placeholder archive for ${m[1]}.\n`, {
      headers: {
        "Content-Type": "text/plain",
        "Content-Disposition": `attachment; filename="${m[1]}.txt"`,
      },
    });
  }

  if (path === "tools" && method === "GET") {
    const status = params.get("status") ?? undefined;
    return NextResponse.json({ tools: fx.fxListTools(status) });
  }

  m = path.match(/^tools\/([^/]+)$/);
  if (m && method === "GET") {
    const versions = fx.fxGetToolVersions(m[1]);
    return versions
      ? NextResponse.json({ name: m[1], versions })
      : err(404, "not_found", "Tool not found.");
  }

  if (path === "knowledge/search" && method === "GET") {
    const q = params.get("q") ?? "";
    const kinds = params.get("kinds") ?? undefined;
    const limit = Number(params.get("limit") ?? 10);
    return NextResponse.json({ hits: fx.fxSearchKnowledge(q, kinds, limit) });
  }

  if (path === "knowledge" && method === "GET") {
    const kinds = params.get("kinds") ?? undefined;
    const runId = params.get("run_id") ?? undefined;
    const limit = Number(params.get("limit") ?? 100);
    return NextResponse.json({ items: fx.fxListKnowledge(kinds, runId, limit) });
  }

  return err(404, "not_found", "No fixture for this path.");
}

async function handle(req: NextRequest, pathParts: string[], method: string) {
  const path = (pathParts ?? []).join("/");
  const allow = method === "GET" ? GET_ALLOW : method === "POST" ? POST_ALLOW : [];

  if (!allow.some((re) => re.test(path))) {
    return err(404, "not_found", "This path is not exposed by the proxy.");
  }

  return apiBase() === null
    ? fixtureFallback(path, method, req)
    : forward(path, method, req);
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return handle(req, path, "GET");
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return handle(req, path, "POST");
}
