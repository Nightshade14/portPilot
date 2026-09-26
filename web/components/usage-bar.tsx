import { cn } from "@/lib/format";

export function UsageBar({
  label,
  value,
  max,
  unit,
  format,
}: {
  label: string;
  value: number;
  max: number;
  unit?: string;
  format?: (n: number) => string;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const near = pct >= 80;
  const fmt = format ?? ((n: number) => n.toLocaleString());

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className="font-mono text-xs tabular-nums text-foreground">
          {fmt(value)}
          <span className="text-muted-foreground">
            {" / "}
            {fmt(max)}
            {unit ? ` ${unit}` : ""}
          </span>
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            near ? "bg-warning" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
