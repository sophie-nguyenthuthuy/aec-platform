import type { ReactNode } from "react";
import Link from "next/link";

export default function BidRadarLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">BidRadar</h1>
            <p className="text-xs text-slate-500">Tender intelligence across Vietnam & ASEAN</p>
          </div>
          <nav className="flex gap-1 text-sm">
            <Link
              href="/bidradar"
              className="rounded-md px-3 py-1.5 text-slate-700 hover:bg-slate-100"
            >
              Matches
            </Link>
            <Link
              href="/bidradar/tenders"
              className="rounded-md px-3 py-1.5 text-slate-700 hover:bg-slate-100"
            >
              All tenders
            </Link>
            <Link
              href="/bidradar/profile"
              className="rounded-md px-3 py-1.5 text-slate-700 hover:bg-slate-100"
            >
              Firm profile
            </Link>
            <Link
              href="/bidradar/digests"
              className="rounded-md px-3 py-1.5 text-slate-700 hover:bg-slate-100"
            >
              Digests
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
    </div>
  );
}
