"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { ppFetch } from "@/lib/client";
import { isRunTerminal, usePolling } from "@/lib/use-polling";
import { deriveCompactionTotals, deriveToolUsage, groupEventsByStep } from "@/lib/metrics";
import type {
  Event,
  EventType,
  GetEventsResponse,
  GetRunResponse,
  RunControlResponse,
} from "@/lib/types";
import styles from "./run-view.module.css";

interface RunViewProps {
  runId: string;
  initial: GetRunResponse;
}

const EVENT_TYPE_OPTIONS: EventType[] = [
  "run_created",
  "survey_done",
  "plan_created",
  "plan_revised",
  "step_planned",
  "step_started",
  "tools_selected",
  "tool_loaded",
  "tool_call",
  "tool_result",
  "tool_error",
  "tool_created",
  "tool_validated",
  "tool_promoted",
  "tool_rejected",
  "cli_checked",
  "cli_installed",
  "cli_refused",
  "compaction",
  "checkpoint",
  "step_verified",
  "step_failed",
  "lesson_recorded",
  "gotcha_recorded",
  "budget_exceeded",
  "completed",
  "failed",
  "cancelled",
  "paused",
  "resumed",
];

export function RunView({ runId, initial }: RunViewProps) {
  const fetchRun = useCallback(() => ppFetch<GetRunResponse>(`runs/${runId}`), [runId]);
  const { data, error } = usePolling<GetRunResponse>(
    fetchRun,
    (d) => isRunTerminal(d?.run.status),
    2000,
  );
  const runData = data ?? initial;

  const fetchEvents = useCallback(
    () => ppFetch<GetEventsResponse>(`runs/${runId}/events?after_seq=0&limit=200`),
    [runId],
  );
  const { data: eventsData } = usePolling<GetEventsResponse>(
    fetchEvents,
    () => isRunTerminal(runData.run.status),
    2000,
  );
  const stableEvents = useMemo(() => eventsData?.events ?? [], [eventsData]);

  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<EventType | "all">("all");
  const [controlError, setControlError] = useState<string | null>(null);
  const [controlPending, setControlPending] = useState(false);

  const { run, plan, steps } = runData;
  const selectedStep = steps.find((s) => s.step_id === selectedStepId) ?? null;

  const groupedEvents = useMemo(() => groupEventsByStep(stableEvents), [stableEvents]);
  const filteredEvents = useMemo(
    () => (typeFilter === "all" ? stableEvents : stableEvents.filter((e) => e.type === typeFilter)),
    [stableEvents, typeFilter],
  );

  const toolUsage = useMemo(() => deriveToolUsage(stableEvents), [stableEvents]);
  const compaction = useMemo(() => deriveCompactionTotals(stableEvents), [stableEvents]);

  const cliEvents = useMemo(
    () => stableEvents.filter((e) => e.type === "cli_checked" || e.type === "cli_installed" || e.type === "cli_refused"),
    [stableEvents],
  );
  const knowledgeEvents = useMemo(
    () => stableEvents.filter((e) => e.type === "lesson_recorded" || e.type === "gotcha_recorded"),
    [stableEvents],
  );

  async function runControl(action: "pause" | "resume" | "cancel") {
    setControlPending(true);
    setControlError(null);
    try {
      await ppFetch<RunControlResponse>(`runs/${runId}/${action}`, { method: "POST" });
    } catch (err) {
      setControlError(err instanceof Error ? err.message : `Failed to ${action} run.`);
    } finally {
      setControlPending(false);
    }
  }

  const isTerminal = isRunTerminal(run.status);

  return (
    <main className={styles.main}>
      <p>
        <Link href="/">&larr; Back to runs</Link>
      </p>

      <header className={styles.header}>
        <h1>{run.goal}</h1>
        <dl className={styles.headerMeta}>
          <div>
            <dt>Status</dt>
            <dd>
              <span className={styles.statusCell}>
                <span className={`${styles.dot} ${styles[`dot_${run.status}`] ?? ""}`} aria-hidden="true" />
                {run.status}
              </span>
            </dd>
          </div>
          <div>
            <dt>Repo</dt>
            <dd>{run.repo_url}</dd>
          </div>
          <div>
            <dt>Usage</dt>
            <dd>
              {run.usage.input_tokens + run.usage.output_tokens} tokens · {run.usage.model_calls} model calls ·{" "}
              {run.usage.tool_calls} tool calls
            </dd>
          </div>
        </dl>

        <div className={styles.controls} role="group" aria-label="Run controls">
          <button type="button" onClick={() => runControl("pause")} disabled={isTerminal || controlPending}>
            Pause
          </button>
          <button type="button" onClick={() => runControl("resume")} disabled={isTerminal || controlPending}>
            Resume
          </button>
          <button type="button" onClick={() => runControl("cancel")} disabled={isTerminal || controlPending}>
            Cancel
          </button>
          <a className={styles.downloadLink} href={`/api/pp/runs/${runId}/download`}>
            Download workspace
          </a>
        </div>
        {controlError ? (
          <p role="alert" className={styles.errorText}>
            {controlError}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className={styles.errorText}>
            Live updates paused: {error}
          </p>
        ) : null}
      </header>

      <section aria-labelledby="plan-heading" className={styles.section}>
        <h2 id="plan-heading">Plan</h2>
        {plan ? (
          <ol className={styles.phaseList}>
            {plan.phases.map((phase) => {
              const phaseSteps = steps.filter((s) => s.phase_id === phase.id);
              return (
                <li key={phase.id} className={styles.phaseItem}>
                  <h3>{phase.title}</h3>
                  <ul className={styles.stepList}>
                    {phaseSteps.map((step) => (
                      <li key={step.step_id}>
                        <button
                          type="button"
                          className={styles.stepButton}
                          onClick={() => setSelectedStepId(step.step_id)}
                          aria-pressed={selectedStepId === step.step_id}
                        >
                          <span
                            className={`${styles.badge} ${styles[`badge_${step.status}`] ?? ""}`}
                          >
                            {step.status}
                          </span>{" "}
                          {step.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ol>
        ) : (
          <p>No plan yet.</p>
        )}
      </section>

      {selectedStep ? (
        <section aria-labelledby="step-detail-heading" className={styles.section}>
          <h2 id="step-detail-heading">Step: {selectedStep.title}</h2>
          <p>{selectedStep.objective}</p>
          <h3>Selected tools</h3>
          {selectedStep.selected_tools.length === 0 ? (
            <p>None.</p>
          ) : (
            <ul>
              {selectedStep.selected_tools.map((pick) => (
                <li key={`${pick.name}@${pick.version}`}>
                  <Link href={`/tools/${pick.name}`}>
                    {pick.name}@{pick.version}
                  </Link>{" "}
                  &mdash; {pick.reason}
                </li>
              ))}
            </ul>
          )}
          {selectedStep.missing_capabilities.length > 0 ? (
            <>
              <h3>Missing capabilities</h3>
              <ul>
                {selectedStep.missing_capabilities.map((cap) => (
                  <li key={cap}>{cap}</li>
                ))}
              </ul>
            </>
          ) : null}
          <h3>Tokens used</h3>
          <p>
            {selectedStep.usage.input_tokens + selectedStep.usage.output_tokens} tokens across{" "}
            {selectedStep.usage.model_calls} model calls.
          </p>
          <h3>Acceptance checks</h3>
          {selectedStep.acceptance.length === 0 ? (
            <p>None.</p>
          ) : (
            <ul>
              {selectedStep.acceptance.map((check) => (
                <li key={check.name}>{check.name}</li>
              ))}
            </ul>
          )}
          <h3>Commit</h3>
          <p>{selectedStep.commit_sha ?? "Not yet committed."}</p>
        </section>
      ) : null}

      <section aria-labelledby="timeline-heading" className={styles.section}>
        <h2 id="timeline-heading">Timeline</h2>
        <div className={styles.field}>
          <label htmlFor="event-type-filter">Filter by type</label>
          <select
            id="event-type-filter"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as EventType | "all")}
          >
            <option value="all">All types</option>
            {EVENT_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <ol className={styles.timeline} aria-live="polite">
          {filteredEvents.map((event) => (
            <li key={event.seq} className={styles.timelineItem}>
              <span className={styles.timelineSeq}>#{event.seq}</span>{" "}
              <span className={styles.timelineType}>{event.type}</span>{" "}
              <span className={styles.timelineTs}>{new Date(event.ts).toLocaleTimeString()}</span>
              {event.step_id ? <span className={styles.timelineStep}> step: {event.step_id}</span> : null}
            </li>
          ))}
        </ol>
        <p className={styles.groupCount}>{groupedEvents.size} step groups in this timeline.</p>
      </section>

      <section aria-labelledby="env-heading" className={styles.section}>
        <h2 id="env-heading">Environment panel</h2>
        {cliEvents.length === 0 ? (
          <p>No CLI activity yet.</p>
        ) : (
          <ul>
            {cliEvents.map((event) => (
              <li key={event.seq}>
                <CliEventLine event={event} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="tools-panel-heading" className={styles.section}>
        <h2 id="tools-panel-heading">Tools panel</h2>
        {toolUsage.length === 0 ? (
          <p>No tools used yet.</p>
        ) : (
          <table className={styles.table}>
            <caption className="visually-hidden">Tools created and reused this run</caption>
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Created</th>
                <th scope="col">Reused</th>
              </tr>
            </thead>
            <tbody>
              {toolUsage.map((tool) => (
                <tr key={tool.name}>
                  <td>
                    <Link href={`/tools/${tool.name}`}>{tool.name}</Link>
                  </td>
                  <td>{tool.createdCount}</td>
                  <td>{tool.reusedCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="knowledge-panel-heading" className={styles.section}>
        <h2 id="knowledge-panel-heading">Knowledge panel</h2>
        {knowledgeEvents.length === 0 ? (
          <p>No lessons or gotchas recorded yet.</p>
        ) : (
          <ul>
            {knowledgeEvents.map((event) => {
              const payload = event.payload as { title: string; merged: boolean };
              return (
                <li key={event.seq}>
                  <strong>{event.type === "lesson_recorded" ? "Lesson" : "Gotcha"}:</strong> {payload.title}{" "}
                  {payload.merged ? "(merged into an existing item)" : "(new item)"}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="compaction-heading" className={styles.section}>
        <h2 id="compaction-heading">Compaction</h2>
        {compaction.count === 0 ? (
          <p>No compactions yet.</p>
        ) : (
          <p>
            {compaction.count} compaction{compaction.count === 1 ? "" : "s"}: {compaction.tokensBefore} tokens
            before &rarr; {compaction.tokensAfter} tokens after (saved {compaction.tokensSaved} tokens).
          </p>
        )}
      </section>
    </main>
  );
}

function CliEventLine({ event }: { event: Event }) {
  if (event.type === "cli_checked") {
    const payload = event.payload as { installed: Record<string, string>; arch: string };
    const installed = Object.entries(payload.installed)
      .map(([name, version]) => `${name}@${version}`)
      .join(", ");
    return <span>Checked ({payload.arch}): {installed || "none installed"}</span>;
  }
  if (event.type === "cli_installed") {
    const payload = event.payload as { name: string; version: string; already_installed: boolean };
    return (
      <span>
        Installed {payload.name}@{payload.version}
        {payload.already_installed ? " (already present)" : ""}
      </span>
    );
  }
  const payload = event.payload as { name: string; reason: string };
  return (
    <span className={styles.refused}>
      Refused {payload.name}: {payload.reason}
    </span>
  );
}
