"use client";
import Link from "next/link";
import { useState } from "react";
import type { ProposalStatus } from "@aec/types/winwork";

import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
  buttonStyles,
} from "@aec/ui/primitives";
import { ProposalCard } from "@aec/ui/winwork/ProposalCard";
import { useProposals } from "@/hooks/winwork/useProposals";

const STATUSES: Array<{ value: ProposalStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "sent", label: "Đã gửi" },
  { value: "won", label: "Thắng" },
  { value: "lost", label: "Thua" },
  { value: "expired", label: "Hết hạn" },
];

export default function WinWorkListPage() {
  const [status, setStatus] = useState<ProposalStatus | "all">("all");
  const [q, setQ] = useState("");

  const { data, isLoading } = useProposals({
    status: status === "all" ? undefined : status,
    q: q || undefined,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Đề xuất"
        description="Theo dõi và quản lý đề xuất dự án với khách hàng"
        actions={
          <Link href="/winwork/proposals/new" className={buttonStyles({})}>
            Đề xuất mới
          </Link>
        }
      />

      <div className="flex flex-wrap gap-2">
        <div className="flex flex-wrap gap-1">
          {STATUSES.map((s) => (
            <Button
              key={s.value}
              variant={status === s.value ? "default" : "outline"}
              size="sm"
              onClick={() => setStatus(s.value)}
            >
              {s.label}
            </Button>
          ))}
        </div>
        <Input
          className="ml-auto w-64"
          placeholder="Tìm tiêu đề hoặc khách hàng..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState title="Chưa có đề xuất nào." />
      ) : (
        <div className="grid gap-3">
          {(data?.items ?? []).map((p) => (
            <ProposalCard key={p.id} proposal={p} />
          ))}
        </div>
      )}
    </div>
  );
}
