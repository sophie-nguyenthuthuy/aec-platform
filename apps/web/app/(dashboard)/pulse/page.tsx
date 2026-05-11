"use client";

import Link from "next/link";
import { Building2, Plus, Search } from "lucide-react";
import { useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  Input,
  PageHeader,
  SkeletonLines,
  buttonStyles,
} from "@aec/ui/primitives";

import { useProjects } from "@/hooks/projects";

// Tone (semantic) per status. The Badge primitive only ships
// default / secondary / outline / destructive / success / warning, so
// project-status nuance still needs a small local map — but we now
// route it through the primitive instead of hardcoding Tailwind class
// strings on inline `<span>`s.
const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "outline" | "success" | "warning" | "destructive"
> = {
  active: "default",
  planning: "secondary",
  design: "secondary",
  bidding: "warning",
  construction: "default",
  handover: "secondary",
  completed: "success",
  on_hold: "warning",
  cancelled: "destructive",
};

const STATUS_LABEL: Record<string, string> = {
  active: "Đang hoạt động",
  planning: "Lập kế hoạch",
  design: "Thiết kế",
  bidding: "Đấu thầu",
  construction: "Thi công",
  handover: "Bàn giao",
  completed: "Hoàn thành",
  on_hold: "Tạm dừng",
  cancelled: "Huỷ",
};

export default function PulseIndexPage() {
  const [q, setQ] = useState("");
  const { data, isLoading } = useProjects({ per_page: 50, q: q || undefined });
  const projects = data?.data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="ProjectPulse"
        description="Dự án đang theo dõi của bạn."
        actions={
          <>
            <label htmlFor="pulse-search" className="sr-only">
              Tìm dự án
            </label>
            <div className="relative w-full sm:w-64">
              <Search
                size={14}
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="pulse-search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Tìm dự án..."
                className="pl-8"
              />
            </div>
            <Link href="/projects" className={buttonStyles({ size: "sm" })}>
              <Plus size={14} aria-hidden="true" />
              Dự án mới
            </Link>
          </>
        }
      />

      {isLoading ? (
        <div aria-busy="true" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rounded-xl border bg-card p-4">
              <SkeletonLines lines={3} />
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={<Building2 size={22} />}
          title={q ? "Không tìm thấy dự án phù hợp" : "Chưa có dự án nào"}
          description={
            q
              ? "Thử từ khoá khác hoặc xoá bộ lọc."
              : "Tạo dự án đầu tiên để bắt đầu theo dõi tiến độ."
          }
          action={
            !q && (
              <Button>
                <Plus size={14} aria-hidden="true" />
                Tạo dự án
              </Button>
            )
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/pulse/${p.id}/dashboard`}
                className="group flex h-full flex-col gap-2 rounded-xl border bg-card p-4 transition-colors hover:border-primary/30 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-semibold leading-tight text-foreground group-hover:text-primary">
                    {p.name}
                  </span>
                  <Badge variant={STATUS_VARIANT[p.status] ?? "secondary"}>
                    {STATUS_LABEL[p.status] ?? p.status}
                  </Badge>
                </div>
                {p.address &&
                  typeof p.address === "object" &&
                  (p.address as Record<string, string>).city && (
                    <p className="text-xs text-muted-foreground">
                      {(p.address as Record<string, string>).city}
                    </p>
                  )}
                <div className="mt-auto flex items-center gap-3 text-xs text-muted-foreground">
                  {p.open_tasks > 0 && <span>{p.open_tasks} công việc</span>}
                  {p.open_change_orders > 0 && <span>{p.open_change_orders} CO</span>}
                  {p.document_count > 0 && <span>{p.document_count} tài liệu</span>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
