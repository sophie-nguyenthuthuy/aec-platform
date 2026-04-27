"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, FileSignature, Plus } from "lucide-react";

import {
  useAddPunchItem,
  usePunchList,
  useSignOffPunchList,
  useUpdatePunchItem,
} from "@/hooks/punchlist";
import type { PunchItem } from "@/hooks/punchlist";

const STATUS_BADGE: Record<string, string> = {
  open: "bg-amber-100 text-amber-700",
  in_progress: "bg-blue-100 text-blue-700",
  fixed: "bg-indigo-100 text-indigo-700",
  verified: "bg-emerald-100 text-emerald-700",
  waived: "bg-zinc-100 text-zinc-600",
};

const SEVERITY_BADGE: Record<string, string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-100 text-amber-700",
  high: "bg-red-100 text-red-700",
};

const TRADES = [
  { value: "architectural", label: "Kiến trúc" },
  { value: "mep", label: "MEP" },
  { value: "structural", label: "Kết cấu" },
  { value: "civil", label: "Hạ tầng" },
  { value: "landscape", label: "Cảnh quan" },
  { value: "other", label: "Khác" },
];

const SEVERITIES = [
  { value: "low", label: "Thấp" },
  { value: "medium", label: "Trung bình" },
  { value: "high", label: "Cao" },
];

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function PunchListDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = usePunchList(id);
  const signOff = useSignOffPunchList(id ?? "");
  const [adding, setAdding] = useState(false);

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link href="/punchlist" className="text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} className="mr-1 inline" /> Quay lại
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy punch list.</p>
      </div>
    );
  }

  const { list, items } = data;
  const sortedItems = [...items].sort((a, b) => a.item_number - b.item_number);
  const allDone = items.every((i) => ["verified", "waived"].includes(i.status));

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/punchlist"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả punch list
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{list.name}</h2>
            <p className="mt-1 text-sm text-slate-600">
              Khảo sát: {formatDate(list.walkthrough_date)}
              {list.owner_attendees && ` · ${list.owner_attendees}`}
              {list.signed_off_at && ` · Ký: ${formatDate(list.signed_off_at)}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {list.status !== "signed_off" && list.status !== "cancelled" && (
              <button
                type="button"
                onClick={() => signOff.mutate(undefined)}
                disabled={signOff.isPending || !allDone || items.length === 0}
                title={
                  !allDone
                    ? "Cần xác minh hoặc miễn trừ tất cả mục trước khi ký"
                    : ""
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
              >
                <FileSignature size={14} />
                {signOff.isPending ? "Đang ký..." : "Ký bàn giao"}
              </button>
            )}
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                {
                  open: "bg-amber-100 text-amber-700",
                  in_review: "bg-blue-100 text-blue-700",
                  signed_off: "bg-emerald-100 text-emerald-700",
                  cancelled: "bg-zinc-100 text-zinc-600",
                }[list.status] ?? "bg-slate-100 text-slate-700"
              }`}
            >
              {list.status}
            </span>
          </div>
        </div>
      </div>

      {list.notes && (
        <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
          {list.notes}
        </p>
      )}

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-baseline justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Items ({list.total_items} · đã xác minh {list.verified_items})
          </h3>
          {list.status !== "signed_off" && list.status !== "cancelled" && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              <Plus size={12} /> Thêm item
            </button>
          )}
        </div>
        {sortedItems.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Chưa có item nào.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {sortedItems.map((item) => (
              <ItemRow key={item.id} item={item} listId={list.id} />
            ))}
          </ul>
        )}
      </div>

      {adding && id && (
        <AddItemDialog listId={id} onClose={() => setAdding(false)} />
      )}
    </div>
  );
}

function ItemRow({ item, listId }: { item: PunchItem; listId: string }) {
  const update = useUpdatePunchItem(listId);
  return (
    <li className="px-4 py-3 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-slate-500">
            #{item.item_number}
          </span>
          <span className="font-medium text-slate-900">{item.description}</span>
        </div>
        <div className="flex items-center gap-1.5 text-[10px]">
          <span
            className={`rounded-full px-2 py-0.5 font-medium ${
              SEVERITY_BADGE[item.severity] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {item.severity}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 font-medium ${
              STATUS_BADGE[item.status] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {item.status}
          </span>
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-600">
        {item.location ?? "—"} · {item.trade}
        {item.due_date && ` · Hạn ${item.due_date}`}
      </p>
      {item.status !== "verified" && item.status !== "waived" && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[
            { value: "in_progress", label: "Đang xử lý" },
            { value: "fixed", label: "Đã sửa" },
            { value: "verified", label: "Xác minh" },
            { value: "waived", label: "Miễn trừ" },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              disabled={update.isPending}
              onClick={() =>
                update.mutate({
                  itemId: item.id,
                  payload: {
                    status: opt.value as Parameters<
                      typeof update.mutate
                    >[0]["payload"]["status"],
                  },
                })
              }
              className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              → {opt.label}
            </button>
          ))}
        </div>
      )}
    </li>
  );
}

function AddItemDialog({
  listId,
  onClose,
}: {
  listId: string;
  onClose: () => void;
}) {
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [trade, setTrade] = useState("architectural");
  const [severity, setSeverity] = useState("medium");
  const [dueDate, setDueDate] = useState("");
  const add = useAddPunchItem(listId);

  const onSubmit = async () => {
    if (!description.trim()) return;
    await add.mutateAsync({
      description: description.trim(),
      location: location.trim() || undefined,
      trade: trade as Parameters<typeof add.mutateAsync>[0]["trade"],
      severity: severity as Parameters<typeof add.mutateAsync>[0]["severity"],
      due_date: dueDate || undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Thêm item</h3>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Mô tả
            </span>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="vd: Vết sơn ở sảnh tầng 1"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Vị trí</span>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Sảnh / Tầng 1"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Hạn</span>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Hạng mục</span>
            <select
              value={trade}
              onChange={(e) => setTrade(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {TRADES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mức độ</span>
            <select
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {SEVERITIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!description.trim() || add.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {add.isPending ? "Đang thêm..." : "Thêm"}
          </button>
        </div>
      </div>
    </div>
  );
}
