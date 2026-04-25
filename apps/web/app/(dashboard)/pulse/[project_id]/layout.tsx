import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

const NAV = [
  { slug: "dashboard", label: "Dashboard" },
  { slug: "tasks", label: "Tasks" },
  { slug: "schedule", label: "Schedule" },
  { slug: "change-orders", label: "Change Orders" },
  { slug: "meetings", label: "Meetings" },
  { slug: "reports", label: "Reports" },
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
      <nav className="mb-6 flex gap-4 border-b border-gray-200 pb-2 text-sm">
        {NAV.map((n) => (
          <Link
            key={n.slug}
            href={`${base}/${n.slug}` as Route}
            className="rounded px-2 py-1 text-gray-600 hover:bg-gray-100 hover:text-gray-900"
          >
            {n.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
