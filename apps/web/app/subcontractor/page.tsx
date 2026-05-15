"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Hammer,
  Loader2,
  MapPin,
  Save,
} from "lucide-react";


/**
 * Public Subcontractor Portal — token-auth, no Supabase login.
 *
 * URL: /subcontractor?t=<token>
 *
 * Renders the sub's project context + their assignments. Each
 * assignment row has an inline progress form (percent + status + note).
 *
 * No Supabase client — talks to /api/v1/public/sub/* directly with
 * the token forwarded in every request. Token never leaves the URL +
 * its in-memory state in this component.
 */

interface Assignment {
  id: string;
  title: string;
  description: string | null;
  contract_value_vnd: number | null;
  planned_start: string | null;
  planned_finish: string | null;
  percent_complete: number;
  status: string;
  sub_last_update_at: string | null;
}

interface DashboardData {
  organization: { name: string };
  project: {
    id: string;
    name: string;
    address: Record<string, unknown> | null;
    type: string | null;
    status: string;
  };
  subcontractor_email: string;
  assignments: Assignment[];
}


const STATUS_LABEL: Record<string, string> = {
  not_started: "Chưa bắt đầu",
  in_progress: "Đang thi công",
  review_needed: "Chờ chủ đầu tư duyệt",
  complete: "Hoàn thành",
  blocked: "Bị chặn",
};


export default function SubcontractorPortalPage() {
  const params = useSearchParams();
  const token = params.get("t");

  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(
        `${apiUrl}/api/v1/public/sub?t=${encodeURIComponent(token)}`,
      );
      if (res.status === 401) {
        setError(
          "Liên kết không hợp lệ hoặc đã hết hạn. Vui lòng yêu cầu link mới từ tổng thầu.",
        );
        return;
      }
      if (!res.ok) {
        setError(`Lỗi tải dữ liệu (${res.status})`);
        return;
      }
      const env = (await res.json()) as { data: DashboardData };
      setData(env.data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  if (!token) {
    return (
      <ErrorShell
        title="Liên kết không hợp lệ"
        body="Vui lòng dùng đúng URL có tham số ?t= trong tin nhắn của tổng thầu."
      />
    );
  }
  if (loading) {
    return (
      <ErrorShell
        title="Đang tải dữ liệu…"
        body="Vui lòng chờ trong giây lát."
        icon={<Loader2 className="animate-spin" size={32} />}
      />
    );
  }
  if (error) {
    return <ErrorShell title="Đã có lỗi" body={error} />;
  }
  if (!data) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-4 py-4">
          <p className="text-xs uppercase tracking-wider text-slate-500">
            {data.organization.name}
          </p>
          <div className="mt-1 flex items-baseline justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-slate-900">
                {data.project.name}
              </h1>
              <p className="mt-0.5 text-xs text-slate-500">
                {data.project.type ?? "Dự án xây dựng"} ·{" "}
                <MapPin size={11} className="inline" />{" "}
                {(data.project.address as { city?: string } | null)?.city ?? "—"}
              </p>
            </div>
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
              {data.subcontractor_email}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-4 px-4 py-6">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-500">
            <Hammer size={14} />
            Nhiệm vụ của tôi ({data.assignments.length})
          </h2>
        </div>

        {data.assignments.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
            <ClipboardCheck size={32} className="mx-auto text-slate-400" />
            <p className="mt-3 text-sm text-slate-600">
              Tổng thầu chưa gán nhiệm vụ cụ thể cho bạn. Liên hệ tổng thầu
              để bổ sung scope of work.
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {data.assignments.map((a) => (
              <AssignmentCard
                key={a.id}
                assignment={a}
                token={token}
                onUpdated={fetchData}
              />
            ))}
          </ul>
        )}

        <footer className="mt-12 border-t border-slate-200 pt-4 text-xs text-slate-500">
          <p>Cổng nhà thầu phụ — AEC Platform</p>
          <p className="mt-1">
            Mọi cập nhật được ghi log + tổng thầu nhìn thấy ngay. Câu hỏi:
            liên hệ tổng thầu qua Zalo / điện thoại.
          </p>
        </footer>
      </main>
    </div>
  );
}


function AssignmentCard({
  assignment,
  token,
  onUpdated,
}: {
  assignment: Assignment;
  token: string;
  onUpdated: () => void;
}) {
  const [pct, setPct] = useState(assignment.percent_complete);
  const [status, setStatus] = useState(assignment.status);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    setSaving(true);
    try {
      const apiUrl =
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(
        `${apiUrl}/api/v1/public/sub/assignments/${assignment.id}/progress?t=${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            percent_complete: pct,
            status,
            note: note.trim() || null,
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const msg =
          (body as { errors?: Array<{ message?: string }> }).errors?.[0]
            ?.message ?? `Lỗi ${res.status}`;
        setErr(msg);
        return;
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      setNote("");
      onUpdated();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold text-slate-900">{assignment.title}</h3>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
            status === "complete"
              ? "bg-emerald-100 text-emerald-700"
              : status === "blocked"
              ? "bg-rose-100 text-rose-700"
              : status === "review_needed"
              ? "bg-amber-100 text-amber-700"
              : status === "in_progress"
              ? "bg-blue-100 text-blue-700"
              : "bg-slate-100 text-slate-700"
          }`}
        >
          {STATUS_LABEL[status] || status}
        </span>
      </div>
      {assignment.description && (
        <p className="mt-1 text-sm text-slate-600">{assignment.description}</p>
      )}
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
        {assignment.contract_value_vnd != null && (
          <span>
            Giá trị: {assignment.contract_value_vnd.toLocaleString("vi-VN")} ₫
          </span>
        )}
        {assignment.planned_start && (
          <span>Bắt đầu: {formatVnDate(assignment.planned_start)}</span>
        )}
        {assignment.planned_finish && (
          <span>Kết thúc: {formatVnDate(assignment.planned_finish)}</span>
        )}
        {assignment.sub_last_update_at && (
          <span>
            Lần cập nhật cuối: {formatVnDateTime(assignment.sub_last_update_at)}
          </span>
        )}
      </div>

      {/* Progress update form */}
      <div className="mt-3 rounded-lg bg-slate-50 p-3">
        <div className="flex items-center justify-between gap-3">
          <label className="text-xs text-slate-600">
            % Hoàn thành: <b>{pct}%</b>
          </label>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle2 size={12} />
              Đã lưu
            </span>
          )}
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={pct}
          onChange={(e) => setPct(parseInt(e.target.value, 10))}
          className="mt-1 w-full"
        />

        <div className="mt-3">
          <label className="text-xs text-slate-600">Trạng thái</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            <option value="not_started">Chưa bắt đầu</option>
            <option value="in_progress">Đang thi công</option>
            <option value="review_needed">Chờ chủ đầu tư duyệt</option>
            <option value="complete">Hoàn thành</option>
            <option value="blocked">Bị chặn</option>
          </select>
        </div>

        <div className="mt-3">
          <label className="text-xs text-slate-600">Ghi chú (tuỳ chọn)</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="vd: Đã hoàn thành tầng 3, đang chờ vật tư cho tầng 4…"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>

        {err && (
          <p className="mt-2 text-xs text-rose-600">
            <AlertTriangle size={11} className="mr-1 inline" />
            {err}
          </p>
        )}

        <button
          onClick={submit}
          disabled={saving}
          className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {saving ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Save size={14} />
          )}
          Lưu cập nhật
        </button>
      </div>
    </li>
  );
}


function ErrorShell({
  title,
  body,
  icon,
}: {
  title: string;
  body: string;
  icon?: React.ReactNode;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-amber-100 text-amber-700">
          {icon ?? <AlertTriangle size={24} />}
        </div>
        <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
        <p className="mt-2 text-sm text-slate-600">{body}</p>
      </div>
    </main>
  );
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}


function formatVnDateTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} ${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}
