"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Plug,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";

import {
  type CreateWebhookRequest,
  type WebhookCreated,
  type WebhookDelivery,
  type WebhookSubscription,
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useUpdateWebhook,
  useWebhookDeliveries,
  useWebhooks,
} from "@/hooks/webhooks";


// Closed registry of event types — must stay in sync with
// `services/webhooks._KNOWN_EVENT_TYPES`. Grouped by module for the
// checkbox UI; an empty selection on the form means "subscribe to all
// events" which the API encodes as an empty array.
const EVENT_GROUPS: Array<{ label: string; events: Array<[string, string]> }> = [
  {
    label: "CostPulse",
    events: [["costpulse.estimate.approve", "Duyệt dự toán"]],
  },
  {
    label: "ProjectPulse",
    events: [
      ["pulse.change_order.approve", "Duyệt change order"],
      ["pulse.change_order.reject", "Từ chối change order"],
    ],
  },
  {
    label: "Tổ chức",
    events: [
      ["org.member.role_change", "Đổi vai trò thành viên"],
      ["org.member.remove", "Xóa thành viên"],
      ["org.invitation.create", "Tạo lời mời"],
      ["org.invitation.revoke", "Thu hồi lời mời"],
      ["org.invitation.accept", "Chấp nhận lời mời"],
    ],
  },
  {
    label: "Handover",
    events: [
      ["handover.package.deliver", "Bàn giao gói"],
      ["handover.defect.reported", "Báo lỗi mới"],
    ],
  },
  {
    label: "SiteEye",
    events: [["siteeye.safety_incident.detected", "Phát hiện sự cố ATLĐ"]],
  },
];


export default function WebhooksSettingsPage() {
  const { data: subs, isLoading, isError, error } = useWebhooks();
  const [showCreate, setShowCreate] = useState(false);

  if (isError) {
    // The API gates on Role.ADMIN — show a friendly hint rather than
    // a stack trace if the caller is a member/viewer that wandered in.
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-semibold">Webhooks</h1>
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <p>
            Bạn cần quyền <span className="font-semibold">admin</span> để quản
            lý webhooks. Liên hệ owner của tổ chức.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Webhooks</h1>
          <p className="mt-1 text-sm text-slate-600">
            Đăng ký URL nhận sự kiện từ AEC Platform — change order, RFI, lỗi
            mới, sự cố ATLĐ, v.v. Mỗi delivery được ký HMAC-SHA256 với secret
            của subscription (header <code>X-AEC-Signature</code>).
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plug size={14} /> Đăng ký webhook
        </button>
      </div>

      {showCreate && (
        <CreateWebhookForm onClose={() => setShowCreate(false)} />
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : !subs?.length ? (
        <EmptyState onCreate={() => setShowCreate(true)} />
      ) : (
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {subs.map((sub) => (
            <SubscriptionRow key={sub.id} sub={sub} />
          ))}
        </ul>
      )}
    </div>
  );
}


// ---------- Create form ----------


function CreateWebhookForm({ onClose }: { onClose: () => void }) {
  const create = useCreateWebhook();
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [created, setCreated] = useState<WebhookCreated | null>(null);

  if (created) {
    return <SecretReveal created={created} onDone={onClose} />;
  }

  function toggle(event: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(event)) next.delete(event);
      else next.add(event);
      return next;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const req: CreateWebhookRequest = {
      url,
      event_types: Array.from(selected),
    };
    const res = await create.mutateAsync(req);
    setCreated(res);
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded-xl border border-slate-200 bg-white p-5"
    >
      <div>
        <label className="mb-1 block text-xs font-medium text-slate-700">
          Receiver URL
        </label>
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-app.com/webhooks/aec"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <p className="mt-1 text-xs text-slate-500">
          Phải là HTTPS để chúng tôi có thể tin tưởng việc giao payload.
        </p>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-slate-700">
          Event types <span className="text-slate-400">(để trống = tất cả)</span>
        </p>
        <div className="space-y-3">
          {EVENT_GROUPS.map((group) => (
            <fieldset key={group.label}>
              <legend className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {group.label}
              </legend>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {group.events.map(([slug, label]) => (
                  <label
                    key={slug}
                    className="flex items-center gap-2 rounded border border-slate-200 px-2 py-1 text-xs hover:bg-slate-50"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(slug)}
                      onChange={() => toggle(slug)}
                    />
                    <span className="font-medium text-slate-800">{label}</span>
                    <span className="ml-auto truncate text-[10px] text-slate-400">
                      {slug}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
      </div>

      {create.isError && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {(create.error as Error)?.message ?? "Đăng ký thất bại."}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
        >
          Hủy
        </button>
        <button
          type="submit"
          disabled={!url || create.isPending}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {create.isPending ? "Đang tạo..." : "Tạo subscription"}
        </button>
      </div>
    </form>
  );
}


// ---------- Secret one-time disclosure ----------


function SecretReveal({
  created,
  onDone,
}: {
  created: WebhookCreated;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(created.secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-4 rounded-xl border border-emerald-200 bg-emerald-50 p-5">
      <div className="flex items-start gap-2">
        <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-700" />
        <div>
          <p className="font-semibold text-emerald-900">Webhook đã tạo</p>
          <p className="mt-1 text-sm text-emerald-800">
            Đây là <strong>lần duy nhất</strong> bạn nhìn thấy secret. Lưu nó
            an toàn vào hệ thống nhận của bạn — nếu mất, bạn sẽ phải xóa
            subscription này và tạo lại.
          </p>
        </div>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-emerald-900">URL</p>
        <p className="rounded bg-white px-3 py-1.5 font-mono text-xs">
          {created.url}
        </p>
      </div>

      <div>
        <p className="mb-1 text-xs font-medium text-emerald-900">Secret</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 break-all rounded bg-white px-3 py-1.5 font-mono text-xs">
            {created.secret}
          </code>
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-300 hover:bg-emerald-100"
          >
            <Copy size={12} />
            {copied ? "Đã copy" : "Copy"}
          </button>
        </div>
      </div>

      <p className="rounded bg-white px-3 py-2 text-xs text-slate-700">
        <span className="font-medium">Verify trong receiver:</span>{" "}
        <code className="font-mono">
          hmac.compare_digest(`sha256=${`{}`}`.format(local_hmac(body)),
          headers["X-AEC-Signature"])
        </code>
      </p>

      <button
        type="button"
        onClick={onDone}
        className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
      >
        Xong
      </button>
    </div>
  );
}


// ---------- Subscription row ----------


function SubscriptionRow({ sub }: { sub: WebhookSubscription }) {
  const [open, setOpen] = useState(false);
  const update = useUpdateWebhook(sub.id);
  const del = useDeleteWebhook();
  const test = useTestWebhook();

  return (
    <li className="px-5 py-3">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-center gap-2 text-left"
        >
          {open ? (
            <ChevronDown size={14} className="text-slate-400" />
          ) : (
            <ChevronRight size={14} className="text-slate-400" />
          )}
          <span className="truncate font-mono text-xs text-slate-800">
            {sub.url}
          </span>
          {sub.enabled ? (
            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
              hoạt động
            </span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
              tắt
            </span>
          )}
          {sub.failure_count > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
              {sub.failure_count} lỗi liên tiếp
            </span>
          )}
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => test.mutate(sub.id)}
            disabled={test.isPending}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
            title="Gửi sự kiện test"
          >
            <Send size={11} /> Test
          </button>
          <button
            type="button"
            onClick={() => update.mutate({ enabled: !sub.enabled })}
            disabled={update.isPending}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
          >
            {sub.enabled ? "Tắt" : "Bật"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm("Xóa webhook này? Không thể hoàn tác.")) {
                del.mutate(sub.id);
              }
            }}
            disabled={del.isPending}
            className="inline-flex items-center gap-1 rounded border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            <Trash2 size={11} /> Xóa
          </button>
        </div>
      </div>

      <p className="mt-1 ml-6 text-[11px] text-slate-500">
        {sub.event_types.length === 0
          ? "Mọi sự kiện"
          : `${sub.event_types.length} loại sự kiện`}
        {sub.last_delivery_at && (
          <>
            {" "}
            · Lần cuối: {new Date(sub.last_delivery_at).toLocaleString("vi-VN")}
          </>
        )}
      </p>

      {open && <DeliveriesPanel id={sub.id} />}
    </li>
  );
}


// ---------- Recent deliveries panel ----------


function DeliveriesPanel({ id }: { id: string }) {
  const { data, isLoading, isError } = useWebhookDeliveries(id);
  if (isLoading) return <p className="ml-6 mt-2 text-xs text-slate-500">Đang tải...</p>;
  if (isError) return <p className="ml-6 mt-2 text-xs text-red-700">Không thể tải deliveries.</p>;
  if (!data?.length)
    return <p className="ml-6 mt-2 text-xs text-slate-500">Chưa có delivery nào.</p>;

  return (
    <ul className="ml-6 mt-3 space-y-1.5">
      {data.map((d) => (
        <DeliveryRow key={d.id} delivery={d} />
      ))}
    </ul>
  );
}


function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const ok = delivery.status === "delivered";
  const failed = delivery.status === "failed";
  const Icon = ok ? CheckCircle2 : failed ? XCircle : AlertTriangle;
  const tone = ok
    ? "text-emerald-700"
    : failed
      ? "text-red-700"
      : "text-amber-700";

  return (
    <li className="flex items-start gap-2 rounded border border-slate-100 bg-slate-50/50 px-2 py-1.5 text-[11px]">
      <Icon size={12} className={`mt-0.5 shrink-0 ${tone}`} />
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-mono font-medium text-slate-800">
            {delivery.event_type}
          </span>
          <span className="text-slate-500">
            attempt {delivery.attempt_count} ·{" "}
            {new Date(delivery.created_at).toLocaleString("vi-VN")}
          </span>
          {delivery.response_status != null && (
            <span className="text-slate-700">HTTP {delivery.response_status}</span>
          )}
        </div>
        {delivery.error_message && (
          <p className="mt-0.5 truncate text-red-700">{delivery.error_message}</p>
        )}
      </div>
    </li>
  );
}


// ---------- Empty state ----------


function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center">
      <Plug size={28} className="text-slate-400" />
      <p className="text-sm font-medium text-slate-800">
        Chưa có webhook nào
      </p>
      <p className="max-w-md text-xs text-slate-600">
        Đăng ký một URL để nhận sự kiện thời gian thực — change order
        approval, lỗi mới, sự cố ATLĐ, v.v. Mỗi delivery được ký
        HMAC-SHA256 với secret riêng để bạn xác minh.
      </p>
      <button
        type="button"
        onClick={onCreate}
        className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
      >
        Đăng ký webhook đầu tiên
      </button>
    </div>
  );
}
