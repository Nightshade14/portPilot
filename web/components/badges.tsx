import { cn } from "@/lib/format";

const dot = "size-1.5 rounded-full";

export function RunStatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const map: Record<string, { label: string; cls: string; dot: string; pulse?: boolean }> = {
    completed: {
      label: "Completed",
      cls: "border-success/30 bg-success/10 text-success",
      dot: "bg-success",
    },
    running: {
      label: "Running",
      cls: "border-warning/40 bg-warning/10 text-warning",
      dot: "bg-warning",
      pulse: true,
    },
    failed: {
      label: "Failed",
      cls: "border-danger/30 bg-danger/10 text-danger",
      dot: "bg-danger",
    },
    cancelled: {
      label: "Cancelled",
      cls: "border-border bg-secondary text-muted-foreground",
      dot: "bg-muted-foreground",
    },
    queued: {
      label: "Queued",
      cls: "border-border bg-secondary text-muted-foreground",
      dot: "bg-muted-foreground",
    },
  };
  const cfg = map[status] ?? map.queued;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        cfg.cls,
        className,
      )}
    >
      {cfg.pulse ? (
        <span className="relative flex size-1.5">
          <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-70", cfg.dot)} />
          <span className={cn(dot, cfg.dot)} />
        </span>
      ) : (
        <span className={cn(dot, cfg.dot)} />
      )}
      {cfg.label}
    </span>
  );
}

export function StepStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: "border-success/30 bg-success/10 text-success",
    running: "border-warning/40 bg-warning/10 text-warning",
    failed: "border-danger/30 bg-danger/10 text-danger",
    queued: "border-border bg-secondary text-muted-foreground",
  };
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        map[status] ?? map.queued,
      )}
    >
      {label}
    </span>
  );
}

export function ToolStatusBadge({ status }: { status: string }) {
  const active = status === "active";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        active
          ? "border-success/30 bg-success/10 text-success"
          : "border-border bg-secondary text-muted-foreground",
      )}
    >
      <span className={cn(dot, active ? "bg-success" : "bg-muted-foreground")} />
      {active ? "Active" : "Deprecated"}
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-secondary/60 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
      {children}
    </span>
  );
}
