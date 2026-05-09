"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { ArrowLeft, Camera, FileSignature, Plus, X } from "lucide-react";

import {
  useAddPunchItem,
  usePhotoHints,
  usePunchList,
  useSignOffPunchList,
  useUpdatePunchItem,
} from "@/hooks/punchlist";
import type { PunchItem } from "@/hooks/punchlist";
import { useUploadFieldPhoto } from "@/hooks/useUploadFieldPhoto";

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
        {/* Header stacks on mobile so the title gets full width and the
            sign-off button can take the full screen width below — easier to
            tap with a thumb than a 1.5-line button squeezed next to a long
            walkthrough name. */}
        <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{list.name}</h2>
            <p className="mt-1 text-sm text-slate-600">
              Khảo sát: {formatDate(list.walkthrough_date)}
              {list.owner_attendees && ` · ${list.owner_attendees}`}
              {list.signed_off_at && ` · Ký: ${formatDate(list.signed_off_at)}`}
            </p>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
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
                className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
              >
                <FileSignature size={16} />
                {signOff.isPending ? "Đang ký..." : "Ký bàn giao"}
              </button>
            )}
            <span
              className={`inline-flex items-center justify-center rounded-full px-3 py-1.5 text-xs font-medium ${
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
              className="inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              <Plus size={14} /> Thêm item
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
      {/* Title row stacks badges below the description on narrow screens
          so a long Vietnamese description doesn't wrap behind the
          severity/status pills. */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-slate-500">
            #{item.item_number}
          </span>
          <span className="font-medium text-slate-900">{item.description}</span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 text-xs">
          <span
            className={`rounded-full px-2 py-1 font-medium ${
              SEVERITY_BADGE[item.severity] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {item.severity}
          </span>
          <span
            className={`rounded-full px-2 py-1 font-medium ${
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
        // Status transitions are the most-tapped control on this page —
        // bump every button to >=44px tall (Apple's HIG floor) so a
        // gloved finger on site doesn't miss-fire the wrong status.
        <div className="mt-3 flex flex-wrap gap-2">
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
              className="inline-flex min-h-[44px] items-center rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
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
  const [photoId, setPhotoId] = useState<string | undefined>(undefined);
  // Local preview URL for a photo just captured this session — saves a
  // round-trip back to S3 for the thumbnail by reading the File directly
  // via createObjectURL. Cleaned up on unmount via the URL.revokeObjectURL
  // in the input handler.
  const [capturedPreview, setCapturedPreview] = useState<string | null>(null);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const add = useAddPunchItem(listId);
  const upload = useUploadFieldPhoto();
  // SiteEye photos taken near the walkthrough — surface as one-click attach
  // chips so the supervisor doesn't have to re-upload an image they already
  // captured during the walkthrough.
  const hints = usePhotoHints(listId);

  const onCapture = async (file: File) => {
    if (capturedPreview) URL.revokeObjectURL(capturedPreview);
    setCapturedPreview(URL.createObjectURL(file));
    // Upload immediately so the user can keep filling in the form while
    // the photo travels — by the time they hit "Thêm" the photo_id is
    // ready. If the upload fails we surface it via the mutation's
    // `isError` state and the form Save button stays usable (the user
    // can retry the photo or save without it).
    const uploaded = await upload.mutateAsync({
      file,
      source_module: "punchlist",
    });
    setPhotoId(uploaded.file_id);
  };

  const onSubmit = async () => {
    if (!description.trim()) return;
    await add.mutateAsync({
      description: description.trim(),
      location: location.trim() || undefined,
      trade: trade as Parameters<typeof add.mutateAsync>[0]["trade"],
      severity: severity as Parameters<typeof add.mutateAsync>[0]["severity"],
      due_date: dueDate || undefined,
      photo_id: photoId,
    });
    onClose();
  };

  return (
    // Full-screen on mobile, centered card on tablet+. The mobile version
    // gives the soft keyboard the whole viewport to push against without
    // squashing the form fields out of view. `safe-area-inset-bottom`
    // padding so the bottom button row clears the iOS home indicator.
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-slate-900/40 p-0 sm:items-center sm:p-4">
      <div className="flex w-full flex-col bg-white shadow-xl sm:max-w-lg sm:max-h-[90vh] sm:rounded-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 sm:border-0 sm:p-6 sm:pb-2">
          <h3 className="text-lg font-semibold text-slate-900">Thêm item</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Đóng"
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 sm:hidden"
          >
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 pb-4 sm:px-6">
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

        {/* Native camera capture — the `capture="environment"` hint
            makes mobile browsers open the rear camera directly instead
            of the gallery picker. On desktop it falls back to the file
            chooser, so this works everywhere without UA sniffing. */}
        <div className="mt-4">
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void onCapture(file);
              // Reset the input so the same file picked twice triggers
              // a fresh `change` event (browsers debounce identical
              // selections otherwise).
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => cameraInputRef.current?.click()}
            disabled={upload.isPending}
            className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-md border-2 border-dashed border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-800 hover:bg-blue-100 disabled:opacity-50 sm:w-auto"
          >
            <Camera size={18} />
            {upload.isPending ? "Đang tải lên..." : capturedPreview ? "Chụp lại" : "Chụp ảnh"}
          </button>
          {capturedPreview && (
            <div className="mt-3 flex items-center gap-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={capturedPreview}
                alt="Vừa chụp"
                className="h-20 w-20 rounded-md border border-slate-200 object-cover"
              />
              <div className="text-xs text-slate-600">
                Đã đính kèm ảnh vừa chụp.
                {upload.isError && (
                  <span className="block text-red-600">
                    Tải lên thất bại — chụp lại để thử lần nữa.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {hints.data && hints.data.results.length > 0 && (
          <div className="mt-4 rounded-md border border-blue-200 bg-blue-50/50 p-3">
            <p className="mb-2 text-xs font-medium text-blue-900">
              Ảnh từ SiteEye (chụp gần ngày khảo sát)
            </p>
            <div className="grid grid-cols-3 gap-2">
              {hints.data.results.slice(0, 6).map((p) => {
                const selected = photoId === p.photo_id;
                return (
                  <button
                    key={p.photo_id}
                    type="button"
                    onClick={() =>
                      setPhotoId(selected ? undefined : p.photo_id)
                    }
                    className={`relative aspect-square overflow-hidden rounded border-2 ${
                      selected
                        ? "border-blue-600 ring-2 ring-blue-300"
                        : "border-slate-200 hover:border-blue-300"
                    }`}
                    title={
                      p.taken_at
                        ? new Date(p.taken_at).toLocaleString("vi-VN")
                        : undefined
                    }
                  >
                    {p.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={p.thumbnail_url}
                        alt={p.tags.join(", ") || "site photo"}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-slate-100 text-[10px] text-slate-500">
                        no preview
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
            {photoId && (
              <p className="mt-2 text-[11px] text-blue-700">
                Đã chọn 1 ảnh — sẽ đính kèm với item.
              </p>
            )}
          </div>
        )}

        </div>
        {/* Sticky bottom action bar — stays visible above the soft keyboard
            on mobile so the user never loses sight of "Thêm". `pb` value
            includes safe-area inset for iOS home-indicator clearance. */}
        <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t border-slate-100 bg-white px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:rounded-b-xl sm:px-6">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-[44px] items-center rounded-md px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!description.trim() || add.isPending}
            className="inline-flex min-h-[44px] items-center rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {add.isPending ? "Đang thêm..." : "Thêm"}
          </button>
        </div>
      </div>
    </div>
  );
}
