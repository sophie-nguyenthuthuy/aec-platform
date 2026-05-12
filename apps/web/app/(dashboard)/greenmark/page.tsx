"use client";

import { useState } from "react";
import { Plus, Sprout } from "lucide-react";
import { CertCard, CERT_SYSTEM_LABEL, TARGET_LEVEL_LABEL } from "@aec/ui/greenmark";
import type { CertStatus, CertSystem, TargetLevel } from "@aec/ui/greenmark";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useCerts, useCreateCert } from "@/hooks/greenmark";

const SYSTEM_OPTIONS: CertSystem[] = [
  "lotus_nr",
  "lotus_homes",
  "lotus_bio",
  "lotus_intl",
  "edge",
];

const LOTUS_LEVELS: TargetLevel[] = ["certified", "silver", "gold", "platinum"];
const EDGE_LEVELS: TargetLevel[] = ["edge_certified", "edge_advanced", "edge_zero"];

const STATUS_FILTERS: Array<{ value: CertStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "planning", label: "Lập kế hoạch" },
  { value: "self_assessment", label: "Tự đánh giá" },
  { value: "submitted", label: "Đã nộp" },
  { value: "final_cert", label: "Đã chứng nhận" },
];

export default function GreenmarkPage() {
  const [statusFilter, setStatusFilter] = useState<CertStatus | "all">("all");
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useCerts({
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chứng nhận xanh (LOTUS / EDGE)"
        description="Theo dõi mục tiêu LOTUS của VGBC và EDGE của IFC. Tính điểm tự động theo nhóm credits, gợi ý credits nên ưu tiên để nâng cấp mức chứng nhận."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo mục tiêu chứng nhận
          </Button>
        }
      />

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            size="sm"
            variant={statusFilter === f.value ? "default" : "outline"}
            onClick={() => setStatusFilter(f.value)}
            className="rounded-full"
          >
            {f.label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<Sprout size={20} />}
          title="Chưa có mục tiêu chứng nhận xanh nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((c) => (
            <CertCard key={c.id} cert={c} href={`/greenmark/${c.id}`} />
          ))}
        </div>
      )}

      {creating && <CreateCertDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateCertDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [system, setSystem] = useState<CertSystem>("lotus_nr");
  const [level, setLevel] = useState<TargetLevel>("gold");
  const create = useCreateCert();

  const isEdge = system === "edge";
  const validLevels = isEdge ? EDGE_LEVELS : LOTUS_LEVELS;

  const onSubmit = async () => {
    if (!projectId) return;
    const effectiveLevel = validLevels.includes(level)
      ? level
      : (validLevels[0] as TargetLevel);
    await create.mutateAsync({
      project_id: projectId,
      system,
      target_level: effectiveLevel,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">
          Tạo mục tiêu chứng nhận xanh
        </h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mã dự án
            </span>
            <Input
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Hệ thống chứng nhận
            </span>
            <select
              value={system}
              onChange={(e) => {
                const next = e.target.value as CertSystem;
                setSystem(next);
                setLevel(next === "edge" ? "edge_certified" : "gold");
              }}
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {SYSTEM_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {CERT_SYSTEM_LABEL[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mục tiêu
            </span>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value as TargetLevel)}
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {validLevels.map((lv) => (
                <option key={lv} value={lv}>
                  {TARGET_LEVEL_LABEL[lv]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button onClick={onSubmit} disabled={!projectId} loading={create.isPending}>
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
