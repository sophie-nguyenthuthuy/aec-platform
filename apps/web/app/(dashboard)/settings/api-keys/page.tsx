"use client";

import { useCallback, useState } from "react";
import {
  AlertTriangle,
  Check,
  Clock,
  Copy,
  Key,
  Loader2,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import {
  type ApiKeyCreated,
  type ApiKeyRow,
  useApiKeyScopes,
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
} from "@/hooks/apiKeys";


// Group scopes by domain for the create-form checkbox grid. Splitting
// "projects:read" → "projects" + "read" lets us render rows like
// "Projects: ☐ read ☐ write" instead of one flat checklist of 14
// items.
function groupScopes(all: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {};
  for (const s of all) {
    if (s === "*") continue; // wildcard rendered separately
    const [domain, action] = s.split(":");
    // Defensive: scope strings should always be `domain:action`, but
    // `noUncheckedIndexedAccess` correctly flags the post-split tuple
    // as `(string | undefined)[]`. Skip malformed entries rather than
    // silently bucketing them under a phantom key.
    if (!domain || !action) continue;
    (groups[domain] ??= []).push(action);
  }
  for (const k of Object.keys(groups)) groups[k]!.sort();
  return groups;
}


function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 1) return "hôm nay";
  if (days < 30) return `${days} ngày trước`;
  if (days < 365) return `${Math.floor(days / 30)} tháng trước`;
  return `${Math.floor(days / 365)} năm trước`;
}


export default function ApiKeysPage() {
  const { data: keys, isLoading, isError, error } = useApiKeys();
  const { data: allScopes } = useApiKeyScopes();
  const [showCreate, setShowCreate] = useState(false);
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">API keys</h2>
          <p className="text-sm text-slate-600">
            Cấp quyền cho hệ thống của khách hàng gọi API của chúng ta.
            Xem{" "}
            <a href="/docs/api" className="text-blue-600 hover:underline">
              tài liệu API
            </a>{" "}
            để biết format header + scope. Webhooks (callback ngược lại tới
            khách hàng) được cấu hình tại{" "}
            <a href="/settings/webhooks" className="text-blue-600 hover:underline">
              /settings/webhooks
            </a>.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setJustCreated(null);
            setShowCreate(true);
          }}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={14} />
          Tạo key mới
        </button>
      </div>

      {/* The newly-minted key panel sits above the listing — the
          plaintext is shown EXACTLY ONCE so we want it impossible to
          miss. Dismissing it removes the only copy from memory. */}
      {justCreated && (
        <NewKeyBanner
          payload={justCreated}
          onDismiss={() => setJustCreated(null)}
        />
      )}

      {showCreate && (
        <CreateModal
          allScopes={allScopes ?? []}
          onClose={() => setShowCreate(false)}
          onCreated={(k) => {
            setShowCreate(false);
            setJustCreated(k);
          }}
        />
      )}

      {/* ---------- Listing ---------- */}
      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <ErrorPanel error={error as Error | null} />
      ) : !keys || keys.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Tên</th>
                <th className="px-4 py-2">Prefix</th>
                <th className="px-4 py-2">Scopes</th>
                <th className="px-4 py-2">RPM</th>
                <th className="px-4 py-2">Lần dùng cuối</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2 text-right">Hành động</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {keys.map((k) => (
                <KeyRow key={k.id} k={k} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ---------- Sub-components ----------


function NewKeyBanner({
  payload,
  onDismiss,
}: {
  payload: ApiKeyCreated;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(payload.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard might not be available (insecure context). Leave
      // the user to select-and-copy manually.
    }
  }, [payload.key]);
  return (
    <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
      <div className="flex items-start gap-2">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-amber-700" />
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-amber-900">
            Lưu key này NGAY — bạn sẽ không thấy lại nó
          </h3>
          <p className="mt-1 text-xs text-amber-800">
            Chúng ta lưu hash sha256, không lưu plaintext. Nếu mất key này, hãy
            revoke nó và tạo key mới.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white px-3 py-2 font-mono text-xs text-slate-900 ring-1 ring-amber-200">
              {payload.key}
            </code>
            <button
              type="button"
              onClick={copy}
              className="inline-flex shrink-0 items-center gap-1 rounded-md bg-amber-700 px-3 py-2 text-xs font-medium text-white hover:bg-amber-800"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Đã chép" : "Chép"}
            </button>
          </div>
          <button
            type="button"
            onClick={onDismiss}
            className="mt-3 text-xs text-amber-800 underline hover:text-amber-900"
          >
            Tôi đã lưu — đóng banner này
          </button>
        </div>
      </div>
    </section>
  );
}


function KeyRow({ k }: { k: ApiKeyRow }) {
  const revoke = useRevokeApiKey();
  const isRevoked = !!k.revoked_at;
  const isExpired = !!k.expires_at && new Date(k.expires_at) < new Date();
  return (
    <tr className={isRevoked || isExpired ? "bg-slate-50/40 text-slate-500" : ""}>
      <td className="px-4 py-3">
        <p className="font-medium">{k.name}</p>
        <p className="text-[10px] text-slate-400">
          tạo {formatRelative(k.created_at)}
        </p>
      </td>
      <td className="px-4 py-3 font-mono text-xs">aec_{k.prefix}…</td>
      <td className="px-4 py-3">
        {k.scopes.length === 0 ? (
          <span className="text-slate-400">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {k.scopes.map((s) => (
              <span
                key={s}
                className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                  s === "*"
                    ? "bg-rose-100 text-rose-800"
                    : s.endsWith(":write") || s.endsWith(":admin")
                      ? "bg-amber-100 text-amber-800"
                      : "bg-slate-100 text-slate-700"
                }`}
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="px-4 py-3 tabular-nums text-xs">
        {k.rate_limit_per_minute ?? "60 (mặc định)"}
      </td>
      <td className="px-4 py-3 text-xs">
        {k.last_used_at ? (
          <>
            <span>{formatRelative(k.last_used_at)}</span>
            {k.last_used_ip && (
              <span className="ml-1 text-[10px] text-slate-400">
                · {k.last_used_ip}
              </span>
            )}
          </>
        ) : (
          <span className="text-slate-400">chưa dùng</span>
        )}
      </td>
      <td className="px-4 py-3">
        {isRevoked ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-medium text-rose-800">
            <Trash2 size={10} /> revoked
          </span>
        ) : isExpired ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-700">
            <Clock size={10} /> expired
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
            <ShieldCheck size={10} /> active
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        {!isRevoked && (
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  `Revoke key "${k.name}"? Khách hàng dùng key này sẽ nhận 401 ngay lập tức.`,
                )
              ) {
                revoke.mutate(k.id);
              }
            }}
            disabled={revoke.isPending}
            className="rounded-md border border-rose-200 px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
          >
            Revoke
          </button>
        )}
      </td>
    </tr>
  );
}


function CreateModal({
  allScopes,
  onClose,
  onCreated,
}: {
  allScopes: string[];
  onClose: () => void;
  onCreated: (k: ApiKeyCreated) => void;
}) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rl, setRl] = useState<string>("");
  const create = useCreateApiKey();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const groups = groupScopes(allScopes);
  const hasWildcard = allScopes.includes("*");
  const wildcardSelected = selected.has("*");

  const toggle = (s: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      // Selecting `*` deselects everything else (it implies all);
      // selecting a specific scope deselects `*` (no longer all-access).
      if (s === "*" && next.has("*")) {
        return new Set(["*"]);
      }
      if (s !== "*" && next.has(s)) {
        next.delete("*");
      }
      return next;
    });
  };

  const submit = () => {
    setSubmitError(null);
    if (!name.trim()) {
      setSubmitError("Tên là bắt buộc.");
      return;
    }
    if (selected.size === 0) {
      setSubmitError("Chọn ít nhất một scope.");
      return;
    }
    create.mutate(
      {
        name: name.trim(),
        scopes: Array.from(selected),
        rate_limit_per_minute: rl ? Number(rl) : null,
      },
      {
        onSuccess: onCreated,
        onError: (err) =>
          setSubmitError(err instanceof Error ? err.message : "Tạo thất bại."),
      },
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 px-4 pt-16"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl space-y-4 rounded-xl bg-white p-6 shadow-2xl"
      >
        <div className="flex items-center gap-2">
          <Key size={16} className="text-blue-600" />
          <h3 className="text-lg font-semibold">Tạo API key mới</h3>
        </div>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Tên (cho admin nhận dạng)
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="VD: CRM tích hợp · Production"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Scopes
          </label>
          <div className="mt-2 space-y-2 rounded-lg border border-slate-200 p-3">
            {Object.entries(groups).map(([domain, actions]) => (
              <div key={domain} className="flex items-center gap-2">
                <span className="w-32 text-xs font-medium text-slate-700">
                  {domain}
                </span>
                <div className="flex gap-2">
                  {actions.map((action) => {
                    const full = `${domain}:${action}`;
                    return (
                      <label
                        key={action}
                        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs ${
                          selected.has(full)
                            ? "border-blue-500 bg-blue-50 text-blue-700"
                            : "border-slate-200 text-slate-700 hover:bg-slate-50"
                        } ${wildcardSelected ? "opacity-40" : ""}`}
                      >
                        <input
                          type="checkbox"
                          className="h-3 w-3"
                          checked={selected.has(full)}
                          disabled={wildcardSelected}
                          onChange={() => toggle(full)}
                        />
                        {action}
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
            {hasWildcard && (
              <label className="mt-2 flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-2">
                <input
                  type="checkbox"
                  className="mt-0.5 h-3 w-3"
                  checked={wildcardSelected}
                  onChange={() => toggle("*")}
                />
                <div className="text-xs">
                  <p className="font-medium text-rose-900">
                    <code>*</code> — toàn quyền tổ chức
                  </p>
                  <p className="text-rose-800">
                    Cho phép key thực hiện mọi hành động. Chỉ dùng cho ops
                    script một lần — KHÔNG dùng cho tích hợp lâu dài.
                  </p>
                </div>
              </label>
            )}
          </div>
        </div>

        <div>
          <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Giới hạn tốc độ (req / phút) — tuỳ chọn
          </label>
          <input
            type="number"
            min={1}
            max={10000}
            value={rl}
            onChange={(e) => setRl(e.target.value)}
            placeholder="60 (mặc định)"
            className="mt-1 w-40 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-slate-500">
            Để trống để dùng mặc định (60 rpm). Tối đa 10.000 cho đối tác cao
            tải.
          </p>
        </div>

        {submitError && (
          <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">
            {submitError}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={create.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Key size={14} />
            )}
            Tạo key
          </button>
        </div>
      </div>
    </div>
  );
}


function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
      <Key size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
      <p className="text-sm font-medium text-slate-700">Chưa có API key nào.</p>
      <p className="mt-1 text-xs text-slate-500">
        Tạo key đầu tiên để hệ thống của khách hàng có thể gọi API. Chỉ
        admin mới tạo được.
      </p>
    </div>
  );
}


function ErrorPanel({ error }: { error: Error | null }) {
  const msg = error?.message ?? "";
  const isForbidden = msg.includes("403") || /forbidden/i.test(msg);
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <ShieldAlert size={16} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium">Không thể tải danh sách key</p>
        <p className="mt-0.5 text-xs">
          {isForbidden
            ? "Bạn cần quyền admin để xem trang này. Liên hệ owner."
            : msg || "Vui lòng thử lại sau."}
        </p>
      </div>
    </div>
  );
}
