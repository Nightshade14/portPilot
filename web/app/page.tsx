import Link from "next/link";
import { fixtures } from "@/lib/fixtures";
import { portpilot, isFixturesMode } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { NewRunForm } from "./new-run-form";
import styles from "./page.module.css";

async function loadRecentRuns(): Promise<RunSummary[]> {
  if (isFixturesMode()) return fixtures.listRuns(50);
  const { runs } = await portpilot.listRuns(50);
  return runs;
}

export default async function HomePage() {
  const runs = await loadRecentRuns();

  return (
    <main className={styles.main}>
      <h1>PortPilot</h1>
      <section aria-labelledby="new-run-heading">
        <h2 id="new-run-heading">Start a new run</h2>
        <NewRunForm />
      </section>

      <section aria-labelledby="recent-runs-heading">
        <h2 id="recent-runs-heading">Recent runs</h2>
        {runs.length === 0 ? (
          <p>No runs yet.</p>
        ) : (
          <table className={styles.table}>
            <caption className="visually-hidden">Recent PortPilot runs</caption>
            <thead>
              <tr>
                <th scope="col">Repo</th>
                <th scope="col">Goal</th>
                <th scope="col">Status</th>
                <th scope="col">Steps</th>
                <th scope="col">Updated</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td>{run.repo_url}</td>
                  <td>{run.goal}</td>
                  <td>
                    <span className={styles.statusCell}>
                      <span className={`${styles.dot} ${styles[`dot_${run.status}`] ?? ""}`} aria-hidden="true" />
                      {run.status}
                    </span>
                  </td>
                  <td>
                    {run.steps_done}/{run.steps_total}
                  </td>
                  <td>
                    <Link href={`/runs/${run.run_id}`}>{new Date(run.updated_at).toLocaleString()}</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
