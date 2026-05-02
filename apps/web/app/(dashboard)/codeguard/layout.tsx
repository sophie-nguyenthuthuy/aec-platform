import Link from "next/link";
import type { ReactNode } from "react";

import { QuotaStatusBanner } from "./QuotaStatusBanner";

// `as const` keeps each `href` as its literal type so it satisfies the
// typedRoutes `Route` union (next.config: experimental.typedRoutes = true).
const NAV = [
  { href: "/codeguard/query", label: "Hỏi quy chuẩn" },
  { href: "/codeguard/scan", label: "Quét tuân thủ" },
  { href: "/codeguard/checklist", label: "Checklist cấp phép" },
  { href: "/codeguard/regulations", label: "Thư viện quy chuẩn" },
  { href: "/codeguard/history", label: "Lịch sử kiểm tra" },
  { href: "/codeguard/quota", label: "Hạn mức" },
] as const;

export default function CodeguardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
          <h1 className="text-lg font-bold text-slate-900">CODEGUARD</h1>
          <nav className="flex gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className="rounded-md px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
              >
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      {/* Renders inline above the page content when usage exceeds 80%
          on either dimension; hidden under that or for unlimited orgs.
          Closes the loop so users see "approaching cap" before they
          hit the 429 from the route layer. */}
      <QuotaStatusBanner />
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
    </div>
  );
}
