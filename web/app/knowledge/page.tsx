import { getKnowledge } from "@/lib/portpilot";
import { KnowledgeBrowser } from "@/components/knowledge-browser";

export const metadata = {
  title: "Knowledge · PortPilot Console",
};

export const dynamic = "force-dynamic";

export default async function KnowledgePage() {
  const items = await getKnowledge();

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <header className="mb-8">
        <p className="font-mono text-xs uppercase tracking-widest text-primary">
          Learned memory
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">
          Knowledge base
        </h1>
        <p className="mt-2 max-w-2xl text-pretty text-sm text-muted-foreground">
          Lessons, gotchas, and digests PortPilot distilled from past runs — the
          memory it consults before touching a new repository.
        </p>
      </header>

      <KnowledgeBrowser items={items} />
    </div>
  );
}
