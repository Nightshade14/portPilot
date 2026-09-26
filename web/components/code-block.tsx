export function CodeBlock({ code }: { code: string }) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-background">
      <pre className="overflow-x-auto py-3 text-xs leading-relaxed scrollbar-thin">
        <code className="block font-mono">
          {lines.map((line, i) => (
            <span key={i} className="flex">
              <span className="w-10 shrink-0 select-none pr-3 text-right text-muted-foreground/40">
                {i + 1}
              </span>
              <span className="flex-1 whitespace-pre pr-4 text-foreground">
                {line || " "}
              </span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
