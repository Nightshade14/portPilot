"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { ppFetch } from "@/lib/client";
import type { CreateRunResponse } from "@/lib/types";
import styles from "./page.module.css";

const REPO_URL_PATTERN = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(\.git)?\/?$/;

const GOAL_PRESETS = [
  "Port Flask service to TypeScript/Hono",
  "Optimize the Dockerfile (size, CVEs, layers)",
];

export function NewRunForm() {
  const router = useRouter();
  const repoId = useId();
  const goalId = useId();
  const [repoUrl, setRepoUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [repoError, setRepoError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function validateRepoUrl(value: string): boolean {
    if (value.length > 0 && !REPO_URL_PATTERN.test(value)) {
      setRepoError("Must be a GitHub URL like https://github.com/owner/repo");
      return false;
    }
    setRepoError(null);
    return true;
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!validateRepoUrl(repoUrl) || repoUrl.length === 0) return;
    if (goal.trim().length < 3) {
      setSubmitError("Goal must be at least 3 characters.");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await ppFetch<CreateRunResponse>("runs", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl, goal }),
      });
      router.push(`/runs/${result.run_id}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start run.");
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label htmlFor={repoId}>Repository URL</label>
        <input
          id={repoId}
          name="repo_url"
          type="text"
          required
          value={repoUrl}
          onChange={(e) => {
            setRepoUrl(e.target.value);
            validateRepoUrl(e.target.value);
          }}
          placeholder="https://github.com/owner/repo"
          aria-describedby={repoError ? `${repoId}-error` : undefined}
          aria-invalid={repoError ? true : undefined}
        />
        {repoError ? (
          <p id={`${repoId}-error`} role="alert" className={styles.fieldError}>
            {repoError}
          </p>
        ) : null}
      </div>

      <div className={styles.field}>
        <label htmlFor={goalId}>Goal</label>
        <textarea
          id={goalId}
          name="goal"
          required
          minLength={3}
          maxLength={2000}
          rows={3}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <div className={styles.presets}>
          {GOAL_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className={styles.presetButton}
              onClick={() => setGoal(preset)}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>

      {submitError ? (
        <p role="alert" className={styles.fieldError}>
          {submitError}
        </p>
      ) : null}

      <button type="submit" disabled={submitting}>
        {submitting ? "Starting…" : "Start run"}
      </button>
    </form>
  );
}
