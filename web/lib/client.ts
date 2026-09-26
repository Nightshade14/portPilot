"use client";

import type { ApiErrorBody } from "./types";

/** Browser-side fetch against our own /api/pp proxy (never the upstream API directly). */
export async function ppFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/pp/${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      body = null;
    }
    throw new Error(body?.error?.message ?? `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}
