"use client";

import { useState } from "react";
import { FileCode2, FlaskConical } from "lucide-react";
import { CodeBlock } from "@/components/code-block";
import { cn } from "@/lib/format";

type FileMap = Record<string, string>;

export function ToolSource({
  files,
  tests,
}: {
  files: FileMap;
  tests: FileMap;
}) {
  const entries = [
    ...Object.entries(files).map(([path, code]) => ({
      path,
      code,
      kind: "file" as const,
    })),
    ...Object.entries(tests).map(([path, code]) => ({
      path,
      code,
      kind: "test" as const,
    })),
  ];

  const [active, setActive] = useState(0);
  if (entries.length === 0) return null;
  const current = entries[Math.min(active, entries.length - 1)];

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex gap-1 overflow-x-auto border-b border-border bg-secondary/40 p-1.5 scrollbar-thin">
        {entries.map((e, i) => (
          <button
            key={e.path}
            type="button"
            onClick={() => setActive(i)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-xs transition-colors",
              i === active
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {e.kind === "test" ? (
              <FlaskConical className="size-3.5 text-warning" />
            ) : (
              <FileCode2 className="size-3.5 text-primary" />
            )}
            {e.path}
          </button>
        ))}
      </div>
      <div className="p-3">
        <CodeBlock code={current.code} />
      </div>
    </div>
  );
}
