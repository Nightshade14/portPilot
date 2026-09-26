import { NextResponse, type NextRequest } from "next/server";
import { fixtures } from "@/lib/fixtures";
import { getApiBaseUrl, isFixturesMode } from "@/lib/api";
import { isAllowed } from "@/lib/proxy-allowlist";

/**
 * Proxies /api/pp/* to the PortPilot API (PORTPILOT_API_URL), attaching the
 * server-side bearer token. Falls back to fixtures when no API URL is
 * configured. Only forwards GETs on contract paths, plus POST on
 * runs, runs/*\/pause, runs/*\/resume and runs/*\/cancel. Streams downloads.
 */

function errorResponse(status: number, code: string, message: string) {
  return NextResponse.json({ error: { code, message } }, { status });
}

async function handle(request: NextRequest, path: string[], method: "GET" | "POST"): Promise<Response> {
  const joinedPath = path.join("/");

  if (!isAllowed(method, joinedPath)) {
    return errorResponse(404, "not_found", "This path is not exposed by the proxy.");
  }

  if (isFixturesMode()) {
    return handleFixtures(joinedPath, method, request);
  }

  return handleUpstream(joinedPath, method, request);
}

async function handleUpstream(joinedPath: string, method: "GET" | "POST", request: NextRequest): Promise<Response> {
  const base = getApiBaseUrl();
  const token = process.env.PORTPILOT_API_TOKEN;
  const url = new URL(`${base}/api/${joinedPath}`);
  request.nextUrl.searchParams.forEach((value, key) => url.searchParams.set(key, value));

  const isDownload = /\/download$/.test(joinedPath);
  const body = method === "POST" ? await request.text() : undefined;

  const upstream = await fetch(url.toString(), {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body,
    cache: "no-store",
  });

  if (isDownload) {
    // Stream the tar.gz through without buffering it in memory.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/gzip",
        "Content-Disposition": upstream.headers.get("Content-Disposition") ?? "attachment",
      },
    });
  }

  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}

async function handleFixtures(joinedPath: string, method: "GET" | "POST", request: NextRequest): Promise<Response> {
  const q = request.nextUrl.searchParams;

  if (joinedPath === "health") {
    return NextResponse.json({ ok: true, version: "0.1.0-fixtures" });
  }

  if (joinedPath === "runs" && method === "GET") {
    const limit = Number(q.get("limit") ?? 50);
    return NextResponse.json({ runs: await fixtures.listRuns(limit) });
  }

  if (joinedPath === "runs" && method === "POST") {
    const body = (await request.json()) as { repo_url?: string; goal?: string };
    if (!body.repo_url || !body.goal) {
      return errorResponse(400, "bad_request", "repo_url and goal are required.");
    }
    const runId = await fixtures.createRun(body.repo_url, body.goal);
    return NextResponse.json({ run_id: runId }, { status: 201 });
  }

  const runMatch = joinedPath.match(/^runs\/([^/]+)$/);
  if (runMatch && method === "GET") {
    const result = await fixtures.getRun(runMatch[1]!);
    if (!result) return errorResponse(404, "not_found", "Run not found.");
    return NextResponse.json(result);
  }

  const stepMatch = joinedPath.match(/^runs\/([^/]+)\/steps\/([^/]+)$/);
  if (stepMatch && method === "GET") {
    const step = await fixtures.getStep(stepMatch[1]!, stepMatch[2]!);
    if (!step) return errorResponse(404, "not_found", "Step not found.");
    return NextResponse.json({ step });
  }

  const eventsMatch = joinedPath.match(/^runs\/([^/]+)\/events$/);
  if (eventsMatch && method === "GET") {
    const afterSeq = Number(q.get("after_seq") ?? 0);
    const limit = Number(q.get("limit") ?? 200);
    return NextResponse.json(await fixtures.getEvents(eventsMatch[1]!, afterSeq, limit));
  }

  const controlMatch = joinedPath.match(/^runs\/([^/]+)\/(pause|resume|cancel)$/);
  if (controlMatch && method === "POST") {
    const result = await fixtures.controlRun(controlMatch[1]!, controlMatch[2] as "pause" | "resume" | "cancel");
    if (!result) return errorResponse(404, "not_found", "Run not found.");
    return NextResponse.json(result);
  }

  const artifactsMatch = joinedPath.match(/^runs\/([^/]+)\/artifacts$/);
  if (artifactsMatch && method === "GET") {
    return NextResponse.json({ artifacts: await fixtures.getArtifacts(artifactsMatch[1]!) });
  }

  const artifactMatch = joinedPath.match(/^runs\/([^/]+)\/artifacts\/([^/]+)$/);
  if (artifactMatch && method === "GET") {
    const artifact = await fixtures.getArtifact(artifactMatch[1]!, artifactMatch[2]!);
    if (!artifact) return errorResponse(404, "not_found", "Artifact not found.");
    return NextResponse.json({ artifact });
  }

  const downloadMatch = joinedPath.match(/^runs\/([^/]+)\/download$/);
  if (downloadMatch && method === "GET") {
    const body = `Fixture placeholder archive for ${downloadMatch[1]}.\n`;
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "application/gzip",
        "Content-Disposition": `attachment; filename="${downloadMatch[1]}.tar.gz"`,
      },
    });
  }

  if (joinedPath === "tools" && method === "GET") {
    const status = q.get("status") ?? undefined;
    return NextResponse.json({ tools: await fixtures.listTools(status as never) });
  }

  const toolMatch = joinedPath.match(/^tools\/([^/]+)$/);
  if (toolMatch && method === "GET") {
    const versions = await fixtures.getTool(toolMatch[1]!);
    if (!versions) return errorResponse(404, "not_found", "Tool not found.");
    return NextResponse.json({ name: toolMatch[1], versions });
  }

  if (joinedPath === "knowledge/search" && method === "GET") {
    const query = q.get("q") ?? "";
    const kinds = q.get("kinds") ?? undefined;
    const limit = Number(q.get("limit") ?? 10);
    return NextResponse.json({ hits: await fixtures.searchKnowledge(query, kinds, limit) });
  }

  if (joinedPath === "knowledge" && method === "GET") {
    const kinds = q.get("kinds") ?? undefined;
    const runId = q.get("run_id") ?? undefined;
    const limit = Number(q.get("limit") ?? 100);
    return NextResponse.json({ items: await fixtures.listKnowledge(kinds, runId, limit) });
  }

  return errorResponse(404, "not_found", "No fixture for this path.");
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return handle(request, path, "GET");
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return handle(request, path, "POST");
}
