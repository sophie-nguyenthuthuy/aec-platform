import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

const NAV = [
  { slug: "dashboard", label: "Tổng quan" },
  { slug: "tasks", label: "Công việc" },
  { slug: "schedule", label: "Tiến độ" },
  { slug: "change-orders", label: "Lệnh thay đổi" },
  { slug: "meetings", label: "Cuộc họp" },
  { slug: "reports", label: "Báo cáo" },
];

export default function PulseProjectLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: { project_id: string };
}) {
  const base = `/pulse/${params.project_id}`;
  return (
    <div className="mx-auto w-full max-w-7xl p-4">
      <nav className="mb-6 flex flex-wrap items-center gap-4 border-b border-gray-200 pb-2 text-sm">
        {NAV.map((n) => (
          <Link
            key={n.slug}
            href={`${base}/${n.slug}` as Route}
            className="rounded px-2 py-1 text-gray-600 hover:bg-gray-100 hover:text-gray-900"
          >
            {n.label}
          </Link>
        ))}
        {/* Cross-link to the cashflow module which lives outside the
            pulse route tree but is naturally discovered from here. */}
        <Link
          href={`/cashflow/${params.project_id}` as Route}
          className="rounded px-2 py-1 text-blue-600 hover:bg-blue-50"
        >
          Dòng tiền ↗
        </Link>
      </nav>
      {children}
    </div>
  );
}
