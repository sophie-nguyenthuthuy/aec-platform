import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { MobileNavShell } from "@/components/MobileNavShell";

import { OrgSwitcher } from "./_components/OrgSwitcher";
import { SearchTrigger } from "./_components/SearchTrigger";

const NAV: Array<{ href: Route; label: string; section?: string }> = [
  { section: "Tổng quan", href: "/inbox", label: "Hôm nay" },
  { href: "/projects", label: "Dự án" },
  { href: "/activity", label: "Hoạt động" },
  { section: "Giai đoạn thiết kế", href: "/codeguard", label: "CodeGuard" },
  { href: "/drawbridge", label: "Drawbridge" },
  { section: "Giai đoạn đấu thầu", href: "/bidradar", label: "BidRadar" },
  { href: "/winwork", label: "WinWork" },
  { href: "/costpulse", label: "CostPulse" },
  { section: "Giai đoạn thi công", href: "/pulse", label: "Pulse" },
  { href: "/siteeye", label: "SiteEye" },
  { href: "/schedule", label: "SchedulePilot" },
  { href: "/submittals", label: "Submittals" },
  { href: "/dailylog", label: "Nhật ký" },
  { href: "/changeorder", label: "Change orders" },
  { section: "Bàn giao", href: "/handover", label: "Handover" },
  { href: "/punchlist", label: "Punch list" },
  { section: "Cài đặt", href: "/settings/members", label: "Thành viên" },
  { href: "/settings/notifications", label: "Thông báo" },
  { href: "/settings/audit", label: "Nhật ký kiểm tra" },
  { href: "/settings/webhooks", label: "Webhooks" },
  { href: "/settings/search-analytics", label: "Phân tích tìm kiếm" },
  { href: "/settings/import", label: "Nhập dữ liệu" },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  // Build the nav once here (server-side) and hand it to MobileNavShell
  // (client) — keeps the route data on the server and the open/close
  // state on the client.
  const navContent = (
    <>
      <SearchTrigger />
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {NAV.map((item) => (
          <div key={item.href}>
            {item.section && (
              <div className="mt-3 mb-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {item.section}
              </div>
            )}
            <Link
              href={item.href}
              className="block rounded px-3 py-2 text-sm hover:bg-muted"
            >
              {item.label}
            </Link>
          </div>
        ))}
      </nav>
    </>
  );

  return (
    <>
      {/* Cmd+K command palette — global, mounted once at the dashboard
          shell so the shortcut works from any sub-page. */}
      <CommandPalette />
      <MobileNavShell nav={navContent} footer={<OrgSwitcher />}>
        {children}
      </MobileNavShell>
    </>
  );
}


// `SearchTrigger` lives in `_components/SearchTrigger.tsx` (client component).
// Defining it inline here failed at runtime with "Event handlers cannot
// be passed to Client Component props" because the layout is server-
// rendered and onClick can't cross the boundary.
