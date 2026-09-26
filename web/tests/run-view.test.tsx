import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RunView } from "@/app/runs/[id]/run-view";
import type { Event, GetEventsResponse, GetRunResponse } from "@/lib/types";
import runsFixture from "../fixtures/runs.json";
import eventsFixture from "../fixtures/events.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const RUN_ID = "run_completed001";

function buildInitial(): GetRunResponse {
  const runs = runsFixture as unknown as {
    runs: Record<string, GetRunResponse["run"]>;
    plans: Record<string, GetRunResponse["plan"]>;
    steps: Record<string, GetRunResponse["steps"]>;
  };
  return {
    run: runs.runs[RUN_ID]!,
    plan: runs.plans[RUN_ID] ?? null,
    steps: runs.steps[RUN_ID] ?? [],
  };
}

function eventsForRun(): Event[] {
  const events = eventsFixture as unknown as Record<string, Event[]>;
  return events[RUN_ID] ?? [];
}

describe("RunView (rendered from fixtures)", () => {
  beforeEach(() => {
    const initial = buildInitial();
    const events = eventsForRun();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes("/events")) {
          const body: GetEventsResponse = { events, next_after_seq: events.at(-1)?.seq ?? 0 };
          return new Response(JSON.stringify(body), { status: 200 });
        }
        if (url.includes(`/runs/${RUN_ID}`)) {
          return new Response(JSON.stringify(initial), { status: 200 });
        }
        return new Response(JSON.stringify({ error: { code: "not_found", message: "no fixture" } }), {
          status: 404,
        });
      }),
    );
  });

  it("renders the run header, plan phases and steps", async () => {
    render(<RunView runId={RUN_ID} initial={buildInitial()} />);

    expect(screen.getByRole("heading", { level: 1, name: /Port Flask service to TypeScript\/Hono/ })).toBeInTheDocument();
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    expect(screen.getByText("Survey the Flask app")).toBeInTheDocument();
    expect(screen.getByText(/Survey routes and models/)).toBeInTheDocument();
  });

  it("renders the timeline once events load", async () => {
    render(<RunView runId={RUN_ID} initial={buildInitial()} />);

    await waitFor(() => {
      expect(screen.getByText("run_created")).toBeInTheDocument();
    });
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("renders the tools panel with created/reused counts", async () => {
    render(<RunView runId={RUN_ID} initial={buildInitial()} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Tools panel" })).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByText("port_flask_route")).toBeInTheDocument();
    });
  });

  it("disables run controls once the run is terminal", async () => {
    render(<RunView runId={RUN_ID} initial={buildInitial()} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: "Resume" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
