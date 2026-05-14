import type { Route } from "next";
import type { ReactNode } from "react";

import { CommandPalette } from "@/components/CommandPalette";
import { MobileNavShell } from "@/components/MobileNavShell";
import { SidebarNav, type NavItem } from "@/components/SidebarNav";

import { OrgSwitcher } from "./_components/OrgSwitcher";
import { SearchTrigger } from "./_components/SearchTrigger";
import { QuotaStatusBanner } from "./codeguard/QuotaStatusBanner";

// Sidebar nav. Labels are Vietnamese-first; English module brand names
// (CodeGuard, Drawbridge, BidRadar, etc.) are kept as the product name
// but get a Vietnamese description in the page header to anchor users.
//
// Section headers walk a Vietnamese construction project's actual
// lifecycle: Tổng quan → Pháp lý → Thiết kế → Đấu thầu → Thi công →
// Bàn giao → Cài đặt. New users self-orient by phase.
const NAV: NavItem[] = [
  { section: "Tổng quan", href: "/inbox" as Route, label: "Hôm nay" },
  { href: "/my-work" as Route, label: "Công việc của tôi" },
  { href: "/projects" as Route, label: "Dự án" },
  { href: "/activity" as Route, label: "Hoạt động" },
  { section: "Pháp lý", href: "/permitflow" as Route, label: "Giấy phép xây dựng" },
  { href: "/pccc" as Route, label: "Phòng cháy chữa cháy" },
  { section: "Giai đoạn thiết kế", href: "/codeguard" as Route, label: "CodeGuard — Đối chiếu QCVN" },
  { href: "/drawbridge" as Route, label: "Drawbridge — Bản vẽ thiết kế" },
  { section: "Giai đoạn đấu thầu", href: "/bidradar" as Route, label: "BidRadar — Săn gói thầu" },
  { href: "/winwork" as Route, label: "WinWork — Đề xuất & Báo giá" },
  { href: "/costpulse" as Route, label: "CostPulse — Dự toán & Vật tư" },
  { section: "Giai đoạn thi công", href: "/pulse" as Route, label: "Pulse — Điều phối dự án" },
  { href: "/siteeye" as Route, label: "SiteEye — Giám sát công trường" },
  { href: "/schedule" as Route, label: "Tiến độ dự án" },
  { href: "/submittals" as Route, label: "Tài liệu trình duyệt" },
  { href: "/dailylog" as Route, label: "Nhật ký công trình" },
  { href: "/changeorder" as Route, label: "Lệnh thay đổi" },
  { href: "/nghiemthu" as Route, label: "Nghiệm thu" },
  { href: "/thanhtoan" as Route, label: "Thanh toán" },
  { href: "/einvoice" as Route, label: "Hoá đơn điện tử" },
  { href: "/greenmark" as Route, label: "LOTUS / EDGE (chứng chỉ xanh)" },
  { href: "/bondline" as Route, label: "Bảo lãnh ngân hàng" },
  { href: "/workforce" as Route, label: "Quản lý nhân công" },
  { section: "Bàn giao", href: "/handover" as Route, label: "Bàn giao công trình" },
  { href: "/punchlist" as Route, label: "Danh mục tồn đọng" },
  { section: "Cài đặt", href: "/settings/members" as Route, label: "Thành viên" },
  { href: "/settings/notifications" as Route, label: "Thông báo" },
  { href: "/settings/audit" as Route, label: "Nhật ký kiểm tra" },
  { href: "/settings/webhooks" as Route, label: "Webhooks" },
  { href: "/settings/search-analytics" as Route, label: "Phân tích tìm kiếm" },
  { href: "/settings/import" as Route, label: "Nhập dữ liệu" },
  { href: "/settings/export" as Route, label: "Xuất dữ liệu" },
  { href: "/settings/retention" as Route, label: "Lưu trữ dữ liệu" },
  { href: "/settings/api-keys" as Route, label: "Khoá API" },
  { section: "Tài liệu", href: "/docs/webhooks" as Route, label: "Webhooks" },
  { href: "/docs/api" as Route, label: "Tham chiếu API" },
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
