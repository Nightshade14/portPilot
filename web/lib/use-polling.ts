"use client";

import { useEffect, useRef, useState } from "react";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * Polls `fetchFn` every 2s while `isTerminal(data)` is false. Stops polling
 * once terminal (or on unmount). `fetchFn` should be stable-ish (e.g. wrap
 * with useCallback) since it re-runs on every poll tick.
 */
export function usePolling<T>(
  fetchFn: () => Promise<T>,
  isTerminal: (data: T | null) => boolean,
  intervalMs = 2000,
): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetchRef = useRef(fetchFn);

  useEffect(() => {
    fetchRef.current = fetchFn;
  }, [fetchFn]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const result = await fetchRef.current();
        if (cancelled) return;
        setData(result);
        setError(null);
        setLoading(false);
        if (!isTerminal(result)) {
          timer = setTimeout(tick, intervalMs);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Unknown error");
        setLoading(false);
        timer = setTimeout(tick, intervalMs);
      }
    }

    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetchFn read via ref
  }, [intervalMs]);

  return { data, error, loading };
}

export function isRunTerminal(status: string | undefined | null): boolean {
  return status ? TERMINAL_STATUSES.has(status) : false;
}
