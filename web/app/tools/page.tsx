import Link from "next/link";
import { fixtures } from "@/lib/fixtures";
import { portpilot, isFixturesMode } from "@/lib/api";
import type { ToolSummary } from "@/lib/types";
import styles from "../page.module.css";

async function loadTools(): Promise<ToolSummary[]> {
  if (isFixturesMode()) return fixtures.listTools();
  const { tools } = await portpilot.listTools();
  return tools;
}

export default async function ToolsPage() {
  const tools = await loadTools();

  return (
    <main className={styles.main}>
      <h1>Tool library</h1>
      {tools.length === 0 ? (
        <p>No tools yet.</p>
      ) : (
        <table className={styles.table}>
          <caption className="visually-hidden">Tool library</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Version</th>
              <th scope="col">Status</th>
              <th scope="col">Uses</th>
              <th scope="col">Failure rate</th>
              <th scope="col">Runs used in</th>
              <th scope="col">Created by run</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr key={tool.name}>
                <td>
                  <Link href={`/tools/${tool.name}`}>{tool.name}</Link>
                </td>
                <td>{tool.version}</td>
                <td>{tool.status}</td>
                <td>{tool.stats.uses}</td>
                <td>{(tool.stats.uses ? tool.stats.failures / tool.stats.uses : 0).toFixed(2)}</td>
                <td>{tool.stats.runs_used_in.length}</td>
                <td>{tool.provenance.run_id ?? "seed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
