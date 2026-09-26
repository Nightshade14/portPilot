"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Moon, Sun, Plane } from "lucide-react";
import { cn } from "@/lib/format";

const mobileNav = [
  { href: "/", label: "Overview" },
  { href: "/tools", label: "Tools" },
  { href: "/knowledge", label: "Knowledge" },
];

export function Topbar() {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const isDark = document.documentElement.classList.contains("dark");
    setDark(isDark);
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
  }

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-md md:px-6">
      <div className="flex items-center gap-4">
        <Link href="/" className="flex items-center gap-2 md:hidden">
          <span className="flex size-6 items-center justify-center rounded bg-primary text-primary-foreground">
            <Plane className="size-3.5 -rotate-45" strokeWidth={2.25} />
          </span>
          <span className="text-sm font-semibold">PortPilot</span>
        </Link>
        <nav className="flex items-center gap-1 md:hidden">
          {mobileNav.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/" || pathname.startsWith("/runs")
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-xs font-medium",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <span className="flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground">
            <span className="size-1.5 rounded-full bg-success" />
            <span className="font-mono">api healthy</span>
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="hidden font-mono text-xs text-muted-foreground sm:inline">
          agent build 2.4.1
        </span>
        <button
          type="button"
          onClick={toggle}
          aria-label="Toggle color theme"
          className="flex size-8 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
        >
          {dark ? (
            <Sun className="size-4" />
          ) : (
            <Moon className="size-4" />
          )}
        </button>
      </div>
    </header>
  );
}
