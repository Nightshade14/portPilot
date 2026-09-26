import type { Event, EventType } from "./types";

/** Groups events by step_id (null key for run-level events), preserving seq order within each group. */
export function groupEventsByStep(events: Event[]): Map<string | null, Event[]> {
  const groups = new Map<string | null, Event[]>();
  for (const event of events) {
    const key = event.step_id;
    const list = groups.get(key);
    if (list) {
      list.push(event);
    } else {
      groups.set(key, [event]);
    }
  }
  return groups;
}

/** Filters events to the given set of types; pass null/undefined for no filter. */
export function filterEventsByType(events: Event[], types: EventType[] | null | undefined): Event[] {
  if (!types || types.length === 0) return events;
  const allow = new Set(types);
  return events.filter((e) => allow.has(e.type));
}

export interface ToolUsageMetric {
  name: string;
  createdCount: number;
  reusedCount: number;
}

/**
 * Derives created-vs-reused counts per tool from `tool_created` and
 * `tools_selected` events. A pick in `tools_selected` counts as "reused"
 * unless that exact name+version was created earlier in the same event
 * stream (in which case it's the tool's own first use, not a reuse).
 */
export function deriveToolUsage(events: Event[]): ToolUsageMetric[] {
  const created = new Set<string>(); // `${name}@${version}`
  const metrics = new Map<string, ToolUsageMetric>();

  const ensure = (name: string): ToolUsageMetric => {
    let m = metrics.get(name);
    if (!m) {
      m = { name, createdCount: 0, reusedCount: 0 };
      metrics.set(name, m);
    }
    return m;
  };

  for (const event of events) {
    if (event.type === "tool_created") {
      const payload = event.payload as { name: string; version: number };
      created.add(`${payload.name}@${payload.version}`);
      ensure(payload.name).createdCount += 1;
    } else if (event.type === "tools_selected") {
      const payload = event.payload as { picks: Array<{ name: string; version: number }> };
      for (const pick of payload.picks) {
        const key = `${pick.name}@${pick.version}`;
        if (!created.has(key)) {
          ensure(pick.name).reusedCount += 1;
        }
      }
    }
  }

  return [...metrics.values()];
}

export interface CompactionTotals {
  tokensBefore: number;
  tokensAfter: number;
  tokensSaved: number;
  count: number;
}

/** Sums tokens_before/tokens_after across all `compaction` events. */
export function deriveCompactionTotals(events: Event[]): CompactionTotals {
  let tokensBefore = 0;
  let tokensAfter = 0;
  let count = 0;
  for (const event of events) {
    if (event.type === "compaction") {
      const payload = event.payload as { tokens_before: number; tokens_after: number };
      tokensBefore += payload.tokens_before;
      tokensAfter += payload.tokens_after;
      count += 1;
    }
  }
  return { tokensBefore, tokensAfter, tokensSaved: tokensBefore - tokensAfter, count };
}
