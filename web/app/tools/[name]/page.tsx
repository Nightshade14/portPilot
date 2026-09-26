import { notFound } from "next/navigation";
import Link from "next/link";
import { fixtures } from "@/lib/fixtures";
import { portpilot, isFixturesMode } from "@/lib/api";
import type { ToolRecord } from "@/lib/types";
import styles from "../../page.module.css";
import detailStyles from "./tool-detail.module.css";

async function loadVersions(name: string): Promise<ToolRecord[] | null> {
  if (isFixturesMode()) return fixtures.getTool(name);
  try {
    const { versions } = await portpilot.getTool(name);
    return versions;
  } catch {
    return null;
  }
}

export default async function ToolDetailPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const versions = await loadVersions(name);
  if (!versions) notFound();

  return (
    <main className={styles.main}>
      <p>
        <Link href="/tools">&larr; Back to tools</Link>
      </p>
      <h1>{name}</h1>
      {versions.map((version) => (
        <section key={version.version} className={detailStyles.version}>
          <h2>
            v{version.version} &mdash; {version.status}
          </h2>
          <p>{version.description}</p>
          <p>
            <strong>When to use:</strong> {version.when_to_use}
          </p>
          {version.requires_cli.length > 0 ? (
            <p>
              <strong>Requires CLI:</strong> {version.requires_cli.join(", ")}
            </p>
          ) : null}
          <h3>Files</h3>
          {Object.entries(version.files).map(([path, content]) => (
            <pre key={path} className={detailStyles.code}>
              <code>
                {path}
                {"\n\n"}
                {content}
              </code>
            </pre>
          ))}
          <h3>Tests</h3>
          {Object.keys(version.tests).length === 0 ? (
            <p>None.</p>
          ) : (
            Object.entries(version.tests).map(([path, content]) => (
              <pre key={path} className={detailStyles.code}>
                <code>
                  {path}
                  {"\n\n"}
                  {content}
                </code>
              </pre>
            ))
          )}
        </section>
      ))}
    </main>
  );
}
