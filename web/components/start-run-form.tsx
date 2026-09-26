"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, GitBranch, Loader2, Sparkles } from "lucide-react";

const EXAMPLE_REPOS = [
  "https://github.com/vercel/next.js",
  "https://github.com/facebook/react",
  "https://github.com/honojs/hono",
];

export function StartRunForm() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function isValidRepo(url: string) {
    return /^https?:\/\/github\.com\/[\w.-]+\/[\w.-]+/.test(url.trim());
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    const trimmedRepo = repoUrl.trim();
    if (!isValidRepo(trimmedRepo)) {
      setError("Enter a valid GitHub repository URL.");
      return;
    }
    const trimmedGoal = goal.trim();
    if (trimmedGoal.length < 8) {
      setError("Describe the goal in a little more detail.");
      return;
    }
    setError(null);
    setSubmitting(true);

    try {
      const res = await fetch("/api/pp/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: trimmedRepo, goal: trimmedGoal }),
      });
      const data = (await res.json().catch(() => null)) as
        | { run_id?: string; error?: { message?: string } }
        | null;

      if (!res.ok) {
        setError(data?.error?.message ?? "Failed to start the run.");
        setSubmitting(false);
        return;
      }

      if (data?.run_id) {
        router.push(`/runs/${data.run_id}`);
        router.refresh();
      } else {
        router.refresh();
        setSubmitting(false);
      }
    } catch {
      setError("Could not reach the PortPilot API.");
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Sparkles className="size-4 text-primary" aria-hidden="true" />
        <h2 className="text-sm font-semibold">Start a run</h2>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4 p-4">
        <div className="grid gap-1.5">
          <label
            htmlFor="repo-url"
            className="text-xs font-medium text-muted-foreground"
          >
            Repository
          </label>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-primary/30">
            <GitBranch
              className="size-4 shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              id="repo-url"
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="w-full bg-transparent py-2.5 font-mono text-sm outline-none placeholder:text-muted-foreground/60"
            />
          </div>
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {EXAMPLE_REPOS.map((repo) => (
              <button
                key={repo}
                type="button"
                onClick={() => setRepoUrl(repo)}
                className="rounded-md border border-border bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {repo.replace("https://github.com/", "")}
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-1.5">
          <label
            htmlFor="goal"
            className="text-xs font-medium text-muted-foreground"
          >
            Prompt
          </label>
          <textarea
            id="goal"
            rows={3}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Port this project to the App Router and migrate the test suite to Vitest."
            className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2.5 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
          />
        </div>

        {error ? (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {submitting ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Starting run…
            </>
          ) : (
            <>
              Start run
              <ArrowRight className="size-4" aria-hidden="true" />
            </>
          )}
        </button>
      </form>
    </div>
  );
}
