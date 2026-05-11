"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Building2, Search } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { useProjects } from "@/hooks/projects";
import type { ProjectListFilters } from "@/hooks/projects";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "planning", label: "Lập kế hoạch" },
  { value: "design", label: "Thiết kế" },
  { value: "bidding", label: "Đấu thầu" },
  { value: "construction", label: "Thi công" },
  { value: "handover", label: "Bàn giao" },
  { value: "completed", label: "Hoàn thành" },
];

const STATUS_BADGE: Record<string, string> = {
  planning: "bg-muted text-muted-foreground",
  design: "bg-indigo-100 text-indigo-700",
  bidding: "bg-amber-100 text-amber-700",
  construction: "bg-blue-100 text-blue-700",
  handover: "bg-purple-100 text-purple-700",
  completed: "bg-emerald-100 text-emerald-700",
  on_hold: "bg-yellow-100 text-yellow-700",
  cancelled: "bg-red-100 text-red-700",
};

function formatVnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B ₫`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  return `${n.toLocaleString("vi-VN")} ₫`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function ProjectsPage() {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const filters: ProjectListFilters = {
    status: statusFilter === "all" ? undefined : statusFilter,
    q: q || undefined,
    page,
  };

  const { data, isLoading, isError } = useProjects(filters);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dự án"
        description="Tổng quan toàn bộ dự án — nhấn vào một dự án để xem trạng thái từng module (CodeGuard, Drawbridge, CostPulse, Pulse, Handover, ...)."
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Tìm theo tên dự án..."
            className="pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={statusFilter === f.value ? "default" : "outline"}
              className="rounded-full"
              onClick={() => {
                setStatusFilter(f.value);
                setPage(1);
              }}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : isError ? (
        <Alert variant="destructive">
          Không thể tải danh sách dự án. Vui lòng thử lại.
        </Alert>
      ) : !data?.data.length ? (
        <EmptyProjectsState />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.data.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="block rounded-xl border bg-card p-5 transition hover:border-primary/40 hover:shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-foreground">
                      {p.name}
                    </h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {p.type ?? "—"} ·{" "}
                      {[p.address?.district, p.address?.city]
                        .filter(Boolean)
                        .join(", ") || "—"}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      STATUS_BADGE[p.status] ?? "bg-muted text-muted-foreground"
                    }`}
                  >
                    {p.status}
                  </span>
                </div>

                <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt className="text-muted-foreground">Ngân sách</dt>
                    <dd className="mt-0.5 font-medium text-foreground">
                      {formatVnd(p.budget_vnd)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Khởi công</dt>
                    <dd className="mt-0.5 font-medium text-foreground">
                      {formatDate(p.start_date)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Diện tích</dt>
                    <dd className="mt-0.5 font-medium text-foreground">
                      {p.area_sqm ? `${p.area_sqm.toLocaleString("vi-VN")} m²` : "—"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-4 flex items-center gap-3 border-t pt-3 text-[11px]">
                  <CounterPill label="Tasks mở" value={p.open_tasks} tone="blue" />
                  <CounterPill
                    label="CO mở"
                    value={p.open_change_orders}
                    tone="amber"
                  />
                  <CounterPill label="Tài liệu" value={p.document_count} tone="slate" />
                </div>
              </Link>
            ))}
          </div>

          {data.meta && data.meta.total != null && data.meta.per_page != null && (
            <Pagination
              page={page}
              perPage={data.meta.per_page}
              total={data.meta.total}
              onPageChange={setPage}
            />
          )}
        </>
      )}
    </div>
  );
}

function CounterPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "blue" | "amber" | "slate";
}) {
  const colors: Record<typeof tone, string> = {
    blue: "text-blue-700 bg-blue-50",
    amber: "text-amber-700 bg-amber-50",
    slate: "text-foreground bg-muted/40",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 ${colors[tone]}`}>
      <span className="font-semibold">{value}</span>
      <span>{label}</span>
    </span>
  );
}

function Pagination({
  page,
  perPage,
  total,
  onPageChange,
}: {
  page: number;
  perPage: number;
  total: number;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between border-t pt-4 text-xs text-muted-foreground">
      <span>
        Trang {page} / {totalPages} · {total} dự án
      </span>
      <div className="flex gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          Trước
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Sau
        </Button>
      </div>
    </div>
  );
}


// ---------- Empty-state with seed-demo CTA ----------


/**
 * First-run nudge: when the org has zero projects, instead of a dead
 * "no data" panel, offer a single-click button that loads a sample
 * project across every module. Hits `POST /api/v1/onboarding/seed-demo`
 * which is admin-gated; we render the CTA for everyone but the
 * server returns 403 for non-admin clicks (caught + shown inline).
 */
function EmptyProjectsState() {
  const { token, orgId } = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const seed = useMutation({
    mutationFn: async () => {
      const res = await apiFetch<{ project_id: string; status: string }>(
        "/api/v1/onboarding/seed-demo",
        { method: "POST", token, orgId },
      );
      return res.data as { project_id: string; status: string };
    },
    onSuccess: (data) => {
      // Refetch the project list so the user sees the new row even if
      // they navigate "back" to /projects later.
      qc.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${data.project_id}`);
    },
    onError: (err) => {
      // Most likely cause: caller is `member`/`viewer`. Surface a
      // friendly hint instead of the raw "Forbidden" error.
      const msg =
        err instanceof Error
          ? err.message.includes("403")
            ? "Bạn cần quyền admin để load demo data. Liên hệ owner."
            : err.message
          : "Không thể load demo data.";
      setError(msg);
    },
  });

  return (
    <EmptyState
      icon={<Building2 size={20} />}
      title="Chưa có dự án nào."
      description="Dự án thường được tạo từ một đề xuất đã trúng (WinWork) hoặc nhập trực tiếp qua API. Nếu bạn đang đánh giá nền tảng, có thể nạp dữ liệu mẫu:"
      action={
        <div className="flex flex-col items-center gap-2">
          <Button
            onClick={() => {
              setError(null);
              seed.mutate();
            }}
            loading={seed.isPending}
          >
            {seed.isPending ? "Đang nạp..." : "Nạp dữ liệu demo"}
          </Button>
          <p className="text-[11px] text-muted-foreground">
            Tạo 1 dự án mẫu với đề xuất, dự toán, change orders, RFI, defects,
            và 5 visit + ảnh SiteEye. An toàn để chạy lại — idempotent.
          </p>
          {error && (
            <p className="mt-1 max-w-md text-xs text-destructive">{error}</p>
          )}
        </div>
      }
    />
  );
}
