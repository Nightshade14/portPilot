import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/format";

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: LucideIcon;
  accent?: "primary" | "success" | "warning" | "danger";
}) {
  const accentCls = {
    primary: "text-primary",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
  }[accent ?? "primary"];

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <Icon className={cn("size-4", accentCls)} strokeWidth={2} />
      </div>
      <p className="mt-3 font-mono text-2xl font-semibold tracking-tight tabular-nums">
        {value}
      </p>
      {sub ? (
        <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
      ) : null}
    </div>
  );
}
