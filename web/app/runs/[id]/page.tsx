import { fixtures } from "@/lib/fixtures";
import { portpilot, isFixturesMode } from "@/lib/api";
import { notFound } from "next/navigation";
import { RunView } from "./run-view";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const initial = isFixturesMode() ? await fixtures.getRun(id) : await safeGetRun(id);
  if (!initial) notFound();

  return <RunView runId={id} initial={initial} />;
}

async function safeGetRun(id: string) {
  try {
    return await portpilot.getRun(id);
  } catch {
    return null;
  }
}
