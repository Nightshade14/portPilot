"use client";

import { useId, useState } from "react";
import { ppFetch } from "@/lib/client";
import type { Hit, KnowledgeKind, SearchMode, SearchKnowledgeResponse } from "@/lib/types";
import styles from "./knowledge.module.css";

const KINDS: KnowledgeKind[] = ["lesson", "gotcha", "memory", "tool_card", "run_digest"];
const MODES: SearchMode[] = ["hybrid", "vector", "text"];

export default function KnowledgePage() {
  const queryId = useId();
  const [query, setQuery] = useState("");
  const [selectedKinds, setSelectedKinds] = useState<Set<KnowledgeKind>>(new Set());
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [hits, setHits] = useState<Hit[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  function toggleKind(kind: KnowledgeKind) {
    setSelectedKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  async function runSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSearching(true);
    setError(null);
    setHasSearched(true);
    try {
      const params = new URLSearchParams({ q: query, mode, limit: "10" });
      if (selectedKinds.size > 0) params.set("kinds", [...selectedKinds].join(","));
      const result = await ppFetch<SearchKnowledgeResponse>(`knowledge/search?${params.toString()}`);
      setHits(result.hits);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <main className={styles.main}>
      <h1>Knowledge</h1>
      <form onSubmit={runSearch} className={styles.form}>
        <div className={styles.field}>
          <label htmlFor={queryId}>Search</label>
          <input
            id={queryId}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. validation parity"
          />
        </div>

        <fieldset className={styles.fieldset}>
          <legend>Kind filters</legend>
          {KINDS.map((kind) => (
            <label key={kind} className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={selectedKinds.has(kind)}
                onChange={() => toggleKind(kind)}
              />
              {kind}
            </label>
          ))}
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>Mode</legend>
          {MODES.map((m) => (
            <label key={m} className={styles.radioLabel}>
              <input
                type="radio"
                name="mode"
                value={m}
                checked={mode === m}
                onChange={() => setMode(m)}
              />
              {m}
            </label>
          ))}
        </fieldset>

        <button type="submit" disabled={searching}>
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {error ? (
        <p role="alert" className={styles.errorText}>
          {error}
        </p>
      ) : null}

      <section aria-live="polite">
        {hasSearched && hits.length === 0 && !searching ? <p>No results.</p> : null}
        <ul className={styles.results}>
          {hits.map((hit) => (
            <li key={hit.item.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <span className={styles.kindBadge}>{hit.item.kind}</span>
                <h2>{hit.item.title}</h2>
              </div>
              <p>{hit.item.body}</p>
              <p className={styles.cardMeta}>
                score {hit.score.toFixed(2)} &middot; via {hit.via}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
