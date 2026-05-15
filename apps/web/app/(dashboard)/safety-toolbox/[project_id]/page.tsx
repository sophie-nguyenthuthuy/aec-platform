"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ClipboardList,
  HardHat,
  Loader2,
  Plus,
  Shield,
  Users,
  X,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Safety Toolbox Talks dashboard — Báo cáo họp an toàn đầu ca.
 *
 * Mandated by Nghị định 06/2021 + Thông tư 04/2017. This page makes
 * the compliance record real:
 *   * Coverage KPI ("% of working days with a briefing") = the
 *     metric Sở Xây dựng inspectors actually check.
 *   * Missing-dates list = auditor's "show me your gaps" view.
 *   * Quick "Ghi nhận buổi họp" form for HSE officers on mobile.
 *   * Talk history with attendee count + signed%.
 */

interface ToolboxTalk {
  id: string;
  held_on: string;
  shift: "morning" | "afternoon" | "night";
  topic: string;
  content_notes: string | null;
  presenter_name: string;
  presenter_role: string | null;
  ppe_checks: Record<string, string> | null;
  attendee_count: number;
  signed_count: number;
  created_at: string;
}

interface ComplianceResponse {
  window: { since: string; until: string; days: number };
  working_days: number;
  days_with_talks: number;
  coverage_pct: number;
  missing_dates: string[];
  missing_dates_total: number;
  avg_attendees: number;
}


const SHIFT_LABEL = { morning: "Ca sáng", afternoon: "Ca chiều", night: "Ca đêm" };


export default function SafetyToolboxPage() {
  const { token, orgId } = useSession();
  const params = useParams<{ project_id: string }>();
  const projectId = params?.project_id;

  const [talks, setTalks] = useState<ToolboxTalk[]>([]);
  const [compliance, setCompliance] = useState<ComplianceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!token || !orgId || !projectId) return;
    setLoading(true);
    try {
      const [t, c] = await Promise.all([
        apiFetch<{ talks: ToolboxTalk[] }>(
          "/api/v1/safety-toolbox/projects/" + projectId + "/talks",
          { token, orgId },
        ),
        apiFetch<ComplianceResponse>(
          "/api/v1/safety-toolbox/projects/" + projectId + "/compliance?days=30",
          { token, orgId },
        ),
      ]);
      setTalks(t.data!.talks);
      setCompliance(c.data!);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, orgId, projectId]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  const coverageColour = useMemo(() => {
    if (!compliance) return "text-slate-700";
    const pct = compliance.coverage_pct;
    if (pct >= 95) return "text-emerald-700";
    if (pct >= 80) return "text-amber-700";
    return "text-rose-700";
  }, [compliance]);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/pulse/${projectId}` as never}
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Quay lại dự án
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
              <HardHat size={22} className="text-amber-600" />
              Họp an toàn đầu ca
            </h2>
            <p className="text-xs text-slate-500">
              Báo cáo BHLĐ theo Nghị định 06/2021 — bắt buộc lưu hồ sơ
              cho Sở Xây dựng kiểm tra.
            </p>
          </div>
          <button
            onClick={() => setShowAdd((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={14} />
            Ghi nhận buổi họp
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}

      {showAdd && projectId && (
        <AddTalkForm
          projectId={projectId}
          token={token ?? ""}
          orgId={orgId ?? ""}
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            void fetchAll();
          }}
        />
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : compliance ? (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile
              icon={<Shield size={14} />}
              label="Coverage 30 ngày"
              value={`${compliance.coverage_pct}%`}
              valueClass={coverageColour}
            />
            <KpiTile
              icon={<CheckCircle2 size={14} />}
              label="Ngày có họp"
              value={`${compliance.days_with_talks} / ${compliance.working_days}`}
            />
            <KpiTile
              icon={<AlertTriangle size={14} />}
              label="Ngày bỏ trống"
              value={String(compliance.missing_dates_total)}
              valueClass={
                compliance.missing_dates_total > 0
                  ? "text-rose-700"
                  : "text-emerald-700"
              }
            />
            <KpiTile
              icon={<Users size={14} />}
              label="TB người tham dự"
              value={compliance.avg_attendees.toFixed(1)}
            />
          </div>

          {/* Compliance status banner */}
          {compliance.coverage_pct < 95 && compliance.missing_dates.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="flex items-center gap-1.5 text-sm font-medium text-amber-900">
                <AlertTriangle size={14} />
                Cần ghi nhận họp an toàn cho các ngày sau (theo Nghị định 06/2021):
              </p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {compliance.missing_dates.map((d) => (
                  <li
                    key={d}
                    className="rounded-full bg-white px-2 py-0.5 text-xs text-amber-900 ring-1 ring-amber-300"
                  >
                    {formatVnDate(d)}
                  </li>
                ))}
                {compliance.missing_dates_total > compliance.missing_dates.length && (
                  <li className="text-xs text-amber-700">
                    + {compliance.missing_dates_total - compliance.missing_dates.length} ngày khác
                  </li>
                )}
              </ul>
            </div>
          )}

          {/* Talk history */}
          <section className="rounded-xl border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Lịch sử ({talks.length} buổi)
              </h3>
            </header>
            {talks.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-slate-500">
                Chưa có buổi họp nào được ghi nhận.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {talks.map((t) => (
                  <TalkRow key={t.id} talk={t} />
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}


function KpiTile({
  icon,
  label,
  value,
  valueClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-xl font-bold ${valueClass ?? "text-slate-900"}`}>
        {value}
      </p>
    </div>
  );
}


function TalkRow({ talk }: { talk: ToolboxTalk }) {
  const signedPct =
    talk.attendee_count > 0
      ? Math.round((talk.signed_count / talk.attendee_count) * 100)
      : 0;
  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        <ClipboardList size={16} className="mt-0.5 text-slate-400" />
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            <p className="text-sm font-medium text-slate-900">{talk.topic}</p>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
              {SHIFT_LABEL[talk.shift]}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
            <span>
              <Calendar size={10} className="mr-1 inline" />
              {formatVnDate(talk.held_on)}
            </span>
            <span>
              <Users size={10} className="mr-1 inline" />
              {talk.attendee_count} người ({signedPct}% có ký)
            </span>
            <span>Trình bày: {talk.presenter_name}</span>
          </div>
          {talk.content_notes && (
            <p className="mt-1 text-xs text-slate-600">{talk.content_notes}</p>
          )}
        </div>
      </div>
    </li>
  );
}


function AddTalkForm({
  projectId,
  token,
  orgId,
  onClose,
  onAdded,
}: {
  projectId: string;
  token: string;
  orgId: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [heldOn, setHeldOn] = useState(new Date().toISOString().slice(0, 10));
  const [shift, setShift] = useState<"morning" | "afternoon" | "night">("morning");
  const [topic, setTopic] = useState("");
  const [presenter, setPresenter] = useState("");
  const [attendeesRaw, setAttendeesRaw] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const attendees = useMemo(
    () =>
      attendeesRaw
        .split(/\n+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
        .map((line) => {
          // Format: "Name | Phone | Role" or just "Name"
          const parts = line.split("|").map((p) => p.trim());
          return {
            worker_name: parts[0] || "",
            worker_phone: parts[1] || null,
            worker_role: parts[2] || null,
            signed: true,
          };
        }),
    [attendeesRaw],
  );

  async function submit() {
    setErr(null);
    if (!topic.trim() || !presenter.trim()) {
      setErr("Nhập chủ đề + tên người trình bày.");
      return;
    }
    if (attendees.length === 0) {
      setErr("Nhập ít nhất 1 người tham dự.");
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch(
        "/api/v1/safety-toolbox/projects/" + projectId + "/talks",
        {
          method: "POST",
          token,
          orgId,
          body: {
            held_on: heldOn,
            shift,
            topic: topic.trim(),
            presenter_name: presenter.trim(),
            content_notes: notes.trim() || null,
            attendees,
          },
        },
      );
      onAdded();
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.toLowerCase().includes("talk_already_exists")) {
        setErr("Đã có buổi họp được ghi cho ngày + ca này.");
      } else {
        setErr(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Ghi nhận buổi họp an toàn</h3>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
          <X size={16} />
        </button>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs text-slate-600">Ngày</label>
          <input
            type="date"
            value={heldOn}
            onChange={(e) => setHeldOn(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Ca</label>
          <select
            value={shift}
            onChange={(e) => setShift(e.target.value as typeof shift)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            <option value="morning">Ca sáng</option>
            <option value="afternoon">Ca chiều</option>
            <option value="night">Ca đêm</option>
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Chủ đề an toàn</label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="vd: Sử dụng dây an toàn khi làm việc trên cao"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Người trình bày</label>
          <input
            type="text"
            value={presenter}
            onChange={(e) => setPresenter(e.target.value)}
            placeholder="vd: Nguyễn Văn A — Chỉ huy trưởng"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">
            Danh sách người tham dự ({attendees.length})
          </label>
          <textarea
            value={attendeesRaw}
            onChange={(e) => setAttendeesRaw(e.target.value)}
            rows={4}
            placeholder={`Nguyễn Văn A | 0987654321 | thợ hồ\nTrần Thị B | 0912345678 | thợ sắt\nLê C\n(Mỗi dòng 1 người: Tên | SĐT | Vai trò)`}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm font-mono"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Nội dung họp (tuỳ chọn)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="vd: Nhắc nhở đội thi công tầng 5 phải đeo dây an toàn..."
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm text-slate-700"
        >
          Huỷ
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
          Ghi nhận
        </button>
      </div>
    </div>
  );
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
