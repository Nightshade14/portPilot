import { describe, expect, it } from "vitest";
import { isAllowed } from "@/lib/proxy-allowlist";

describe("proxy allow-list", () => {
  it("allows GET on every contract path", () => {
    const allowed = [
      "health",
      "runs",
      "runs/run_1",
      "runs/run_1/steps/step_1",
      "runs/run_1/events",
      "runs/run_1/artifacts",
      "runs/run_1/artifacts/art_1",
      "runs/run_1/download",
      "tools",
      "tools/port_route",
      "knowledge/search",
      "knowledge",
    ];
    for (const path of allowed) {
      expect(isAllowed("GET", path)).toBe(true);
    }
  });

  it("allows POST only on runs, and runs/*/pause|resume|cancel", () => {
    expect(isAllowed("POST", "runs")).toBe(true);
    expect(isAllowed("POST", "runs/run_1/pause")).toBe(true);
    expect(isAllowed("POST", "runs/run_1/resume")).toBe(true);
    expect(isAllowed("POST", "runs/run_1/cancel")).toBe(true);
  });

  it("rejects POST on GET-only contract paths", () => {
    expect(isAllowed("POST", "runs/run_1")).toBe(false);
    expect(isAllowed("POST", "runs/run_1/events")).toBe(false);
    expect(isAllowed("POST", "tools")).toBe(false);
    expect(isAllowed("POST", "runs/run_1/download")).toBe(false);
  });

  it("rejects paths not in the contract", () => {
    expect(isAllowed("GET", "admin/secrets")).toBe(false);
    expect(isAllowed("GET", "runs/run_1/nonexistent")).toBe(false);
    expect(isAllowed("DELETE", "runs")).toBe(false);
  });

  it("rejects a mutating action outside the explicit control allow-list", () => {
    expect(isAllowed("POST", "runs/run_1/steps/step_1")).toBe(false);
    expect(isAllowed("POST", "tools/port_route")).toBe(false);
  });
});
