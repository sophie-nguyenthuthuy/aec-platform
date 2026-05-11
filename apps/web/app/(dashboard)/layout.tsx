import type { Route } from "next";
import type { ReactNode } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { MobileNavShell } from "@/components/MobileNavShell";
import { SidebarNav, type NavItem } from "@/components/SidebarNav";

import { OrgSwitcher } from "./_components/OrgSwitcher";
import { SearchTrigger } from "./_components/SearchTrigger";
import { QuotaStatusBanner } from "./codeguard/QuotaStatusBanner";

const NAV: NavItem[] = [
  { section: "Tổng quan", href: "/inbox" as Route, label: "Hôm nay" },
  { href: "/projects" as Route, label: "Dự án" },
  { href: "/activity" as Route, label: "Hoạt động" },
  { section: "Giai đoạn thiết kế", href: "/codeguard" as Route, label: "CodeGuard" },
  { href: "/drawbridge" as Route, label: "Drawbridge" },
  { section: "Giai đoạn đấu thầu", href: "/bidradar" as Route, label: "BidRadar" },
  { href: "/winwork" as Route, label: "WinWork" },
  { href: "/costpulse" as Route, label: "CostPulse" },
  { section: "Giai đoạn thi công", href: "/pulse" as Route, label: "Pulse" },
  { href: "/siteeye" as Route, label: "SiteEye" },
  { href: "/schedule" as Route, label: "SchedulePilot" },
  { href: "/submittals" as Route, label: "Submittals" },
  { href: "/dailylog" as Route, label: "Nhật ký" },
  { href: "/changeorder" as Route, label: "Change orders" },
  { section: "Bàn giao", href: "/handover" as Route, label: "Handover" },
  { href: "/punchlist" as Route, label: "Punch list" },
  { section: "Cài đặt", href: "/settings/members" as Route, label: "Thành viên" },
  { href: "/settings/notifications" as Route, label: "Thông báo" },
  { href: "/settings/audit" as Route, label: "Nhật ký kiểm tra" },
  { href: "/settings/webhooks" as Route, label: "Webhooks" },
  { href: "/settings/search-analytics" as Route, label: "Phân tích tìm kiếm" },
  { href: "/settings/import" as Route, label: "Nhập dữ liệu" },
  { href: "/settings/export" as Route, label: "Xuất dữ liệu" },
  { href: "/settings/retention" as Route, label: "Retention" },
  { href: "/settings/api-keys" as Route, label: "API keys" },
  { section: "Tài liệu", href: "/docs/webhooks" as Route, label: "Webhooks" },
  { href: "/docs/api" as Route, label: "API reference" },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  // SidebarNav is a client component (needs usePathname for active-state
  // highlighting). We pass the route data in serialised form so the
  // server-rendered shell stays cheap.
  const navContent = (
    <>
      <SearchTrigger />
      <SidebarNav items={NAV} />
    </>
  );

  return (
    <>
      {/* Cmd+K command palette — global, mounted once at the dashboard
          shell so the shortcut works from any sub-page. */}
      <CommandPalette />
      <MobileNavShell nav={navContent} footer={<OrgSwitcher />}>
        {/* Quota banner is dashboard-wide, not codeguard-only. Codeguard
            owns the cap, but the cap applies to LLM calls from every
            surface (drawbridge, costpulse, winwork, etc.). Rendering
            the banner only inside `/codeguard/*` meant a user pushing
            usage from drawbridge would hit a 429 mid-conversation
            with no prior warning. The banner self-hides for unlimited
            orgs and on fetch errors, so the spillover cost on
            quota-irrelevant pages (settings, docs) is zero pixels. */}
        <QuotaStatusBanner />
        {children}
      </MobileNavShell>
    </>
  );
}
