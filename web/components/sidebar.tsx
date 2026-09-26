"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Wrench, BookOpen, Plane } from "lucide-react";
import { cn } from "@/lib/format";

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard, match: (p: string) => p === "/" || p.startsWith("/runs") },
  { href: "/tools", label: "Tools", icon: Wrench, match: (p: string) => p.startsWith("/tools") },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen, match: (p: string) => p.startsWith("/knowledge") },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-card md:flex">
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-5">
        <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Plane className="size-4 -rotate-45" strokeWidth={2.25} />
        </span>
        <span className="text-[15px] font-semibold tracking-tight">
          PortPilot
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 p-3">
        <p className="px-3 pb-2 pt-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Console
        </p>
        {nav.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              <Icon className="size-[18px]" strokeWidth={2} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-4">
        <div className="rounded-lg border border-border bg-secondary/60 p-3">
          <p className="text-xs font-medium text-foreground">Worker pool</p>
          <div className="mt-2 flex items-center gap-2">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-success" />
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              worker-1 online
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
