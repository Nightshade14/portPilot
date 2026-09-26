import { describe, expect, it } from "vitest";
import { deriveCompactionTotals, deriveToolUsage, filterEventsByType, groupEventsByStep } from "@/lib/metrics";
import type { Event } from "@/lib/types";

function makeEvent(overrides: Partial<Event>): Event {
  return {
    run_id: "run_1",
    seq: 1,
    ts: "2026-09-26T00:00:00+00:00",
    type: "note",
    step_id: null,
    payload: {},
    ...overrides,
  };
}

describe("groupEventsByStep", () => {
  it("groups events by step_id, keeping null-step events under the null key", () => {
    const events = [
      makeEvent({ seq: 1, step_id: null }),
      makeEvent({ seq: 2, step_id: "step_a" }),
      makeEvent({ seq: 3, step_id: "step_a" }),
      makeEvent({ seq: 4, step_id: "step_b" }),
    ];
    const grouped = groupEventsByStep(events);
    expect(grouped.get(null)).toHaveLength(1);
    expect(grouped.get("step_a")).toHaveLength(2);
    expect(grouped.get("step_b")).toHaveLength(1);
  });

  it("preserves seq order within a group", () => {
    const events = [
      makeEvent({ seq: 5, step_id: "step_a" }),
      makeEvent({ seq: 2, step_id: "step_a" }),
    ];
    const grouped = groupEventsByStep(events);
    expect(grouped.get("step_a")?.map((e) => e.seq)).toEqual([5, 2]);
  });

  it("returns an empty map for no events", () => {
    expect(groupEventsByStep([]).size).toBe(0);
  });
});

describe("filterEventsByType", () => {
  const events = [
    makeEvent({ seq: 1, type: "run_created" }),
    makeEvent({ seq: 2, type: "tool_call" }),
    makeEvent({ seq: 3, type: "tool_result" }),
  ];

  it("returns all events when types is null/undefined/empty", () => {
    expect(filterEventsByType(events, null)).toHaveLength(3);
    expect(filterEventsByType(events, undefined)).toHaveLength(3);
    expect(filterEventsByType(events, [])).toHaveLength(3);
  });

  it("filters to only the requested types", () => {
    const result = filterEventsByType(events, ["tool_call"]);
    expect(result).toHaveLength(1);
    expect(result[0]?.seq).toBe(2);
  });
});

describe("deriveToolUsage", () => {
  it("counts a tool_created as created, not reused", () => {
    const events = [
      makeEvent({ seq: 1, type: "tool_created", payload: { name: "port_route", version: 1, purpose: "x" } }),
      makeEvent({
        seq: 2,
        type: "tools_selected",
        payload: {
          candidates: [],
          picks: [{ name: "port_route", version: 1, reason: "just made" }],
          missing: [],
          core_tools: [],
          tool_schema_tokens: 0,
        },
      }),
    ];
    const usage = deriveToolUsage(events);
    const entry = usage.find((u) => u.name === "port_route");
    expect(entry?.createdCount).toBe(1);
    expect(entry?.reusedCount).toBe(0);
  });

  it("counts a pick of a tool version not created in-stream as reused", () => {
    const events = [
      makeEvent({
        seq: 1,
        type: "tools_selected",
        payload: {
          candidates: [],
          picks: [{ name: "existing_tool", version: 3, reason: "from library" }],
          missing: [],
          core_tools: [],
          tool_schema_tokens: 0,
        },
      }),
    ];
    const usage = deriveToolUsage(events);
    const entry = usage.find((u) => u.name === "existing_tool");
    expect(entry?.createdCount).toBe(0);
    expect(entry?.reusedCount).toBe(1);
  });

  it("counts multiple reuses of the same tool across steps", () => {
    const pick = (stepSeq: number) =>
      makeEvent({
        seq: stepSeq,
        type: "tools_selected",
        payload: {
          candidates: [],
          picks: [{ name: "reused_tool", version: 1, reason: "again" }],
          missing: [],
          core_tools: [],
          tool_schema_tokens: 0,
        },
      });
    const usage = deriveToolUsage([pick(1), pick(2), pick(3)]);
    expect(usage.find((u) => u.name === "reused_tool")?.reusedCount).toBe(3);
  });
});

describe("deriveCompactionTotals", () => {
  it("sums tokens_before/after across all compaction events", () => {
    const events = [
      makeEvent({
        seq: 1,
        type: "compaction",
        payload: { tokens_before: 1000, tokens_after: 400, messages_before: 20, messages_after: 5 },
      }),
      makeEvent({
        seq: 2,
        type: "compaction",
        payload: { tokens_before: 2000, tokens_after: 600, messages_before: 30, messages_after: 8 },
      }),
    ];
    const totals = deriveCompactionTotals(events);
    expect(totals.tokensBefore).toBe(3000);
    expect(totals.tokensAfter).toBe(1000);
    expect(totals.tokensSaved).toBe(2000);
    expect(totals.count).toBe(2);
  });

  it("returns zeroes when there are no compaction events", () => {
    const totals = deriveCompactionTotals([makeEvent({ seq: 1, type: "run_created" })]);
    expect(totals).toEqual({ tokensBefore: 0, tokensAfter: 0, tokensSaved: 0, count: 0 });
  });
});
