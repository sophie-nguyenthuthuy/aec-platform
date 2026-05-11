"use client";

import { useMemo } from "react";
import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";


export interface NavItem {
  href: Route;
  label: string;
  /** Section heading rendered above this item (only on the first item of each section). */
  section?: string;
}


/**
 * Sidebar nav with active-state highlighting + aria-current. Items are
 * grouped under their `section` header; the active link gets a tinted
 * background and `aria-current="page"` so screen readers announce it.
 *
 * Server components can't call `usePathname`, so the layout passes the
 * raw NAV array (serializable) and we render it on the client.
 */
export function SidebarNav({ items }: { items: NavItem[] }) {
  const pathname = usePathname();

  // Group items by section so we can render a single <ul> per group with
  // a proper <h2> heading — better semantics than flat <div>s.
  const groups = useMemo(() => groupBySection(items), [items]);

  return (
    <nav
      aria-label="Điều hướng chính"
      className="flex flex-1 flex-col gap-4 overflow-y-auto"
    >
      {groups.map((group) => (
        <div key={group.section ?? "_"}>
          {group.section && (
            <h2 className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {group.section}
            </h2>
          )}
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={
                      active
                        ? "block rounded-md bg-primary/10 px-3 py-2 text-sm font-medium text-primary"
                        : "block rounded-md px-3 py-2 text-sm text-foreground/80 transition-colors hover:bg-accent hover:text-accent-foreground"
                    }
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}


/**
 * Active when the current pathname is exactly the item's href OR starts
 * with `${item.href}/` (so /pulse/123 lights up the Pulse nav item).
 * Special-cased so `/` doesn't match every page.
 */
function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}


function groupBySection(items: NavItem[]): Array<{ section?: string; items: NavItem[] }> {
  const groups: Array<{ section?: string; items: NavItem[] }> = [];
  let current: { section?: string; items: NavItem[] } | null = null;
  for (const item of items) {
    if (item.section || current === null) {
      current = { section: item.section, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }
  return groups;
}
