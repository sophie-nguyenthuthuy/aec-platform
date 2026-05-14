"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import {
  Building2,
  Check,
  ChevronRight,
  Loader2,
  Plus,
  Sparkles,
  Users,
  X,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import { AuthShell } from "@/components/AuthShell";


/**
 * Four-step new-user onboarding flow. Mounted at `/onboarding`.
 *
 * The wizard runs OUTSIDE the dashboard shell (no sidebar, no nav)
 * because new users need a focused single-task surface — dropping
 * them into a navless modal lowers abandonment vs surfacing a
 * full dashboard with empty states.
 *
 * Steps:
 *   1. Tạo tổ chức — org name + country + slug (auto-generated,
 *      revealed only on conflict).
 *   2. Chọn module quan tâm — checkbox grid of the 14 modules.
 *      Stored on `organizations.modules` JSONB. Pure preference signal:
 *      every module endpoint still works regardless of selection
 *      (gating happens via plan, not this list). Used only by the
 *      sidebar's "highlighted" + "recommended" sections later.
 *   3. Mời thành viên — comma-separated emails. Skippable.
 *   4. Seed demo project — one-click populate a sample project so
 *      the user lands on a non-empty dashboard.
 *
 * Each step's state lives on this component (no global store). The
 * back button stays available so a user who realises they mistyped
 * the org name can fix it without restarting.
 */
const MODULE_OPTIONS: Array<{ value: string; label: string; description: string }> = [
  { value: "winwork", label: "WinWork", description: "Đề xuất & báo giá" },
  { value: "costpulse", label: "CostPulse", description: "Dự toán + RFQ vật tư" },
  { value: "pulse", label: "Pulse", description: "Điều phối dự án" },
  { value: "siteeye", label: "SiteEye", description: "Giám sát công trường AI" },
  { value: "bidradar", label: "BidRadar", description: "Săn gói thầu nhà nước" },
  { value: "codeguard", label: "CodeGuard", description: "Đối chiếu QCVN/TCVN" },
  { value: "drawbridge", label: "Drawbridge", description: "Q&A bản vẽ" },
  { value: "handover", label: "Handover", description: "Bàn giao + nghiệm thu" },
  { value: "schedulepilot", label: "Tiến độ dự án", description: "Gantt + đường găng + AI rủi ro" },
  { value: "permitflow", label: "PermitFlow", description: "Giấy phép xây dựng" },
  { value: "pccc", label: "PCCC", description: "Phòng cháy chữa cháy" },
  { value: "dailylog", label: "Nhật ký", description: "Báo cáo nhật trình ngày" },
  { value: "changeorder", label: "Lệnh thay đổi", description: "Quản lý CO + rollup tiến độ" },
  { value: "punchlist", label: "Punch list", description: "Danh mục tồn đọng bàn giao" },
];


export default function OnboardingPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { token } = useSession();

  // Step state. `step` is 1-indexed for human-readable URLs in the
  // URL bar (?step=2). Bypass query-string sync for now — it's a single
  // session anyway.
  const [step, setStep] = useState(1);

  // Step 1: org
  const [orgName, setOrgName] = useState("");
  const [orgCountry, setOrgCountry] = useState("VN");
  const [orgId, setOrgId] = useState<string | null>(null);

  // Step 2: modules
  const [modules, setModules] = useState<Set<string>>(
    () => new Set(["pulse", "costpulse", "siteeye", "schedulepilot"]),
  );

  // Step 3: invites
  const [invitesRaw, setInvitesRaw] = useState("");
  const invites = useMemo(
    () =>
      invitesRaw
        .split(/[\s,;]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0 && /@/.test(s)),
    [invitesRaw],
  );

  // Step 4: seed
  const [seeding, setSeeding] = useState(false);

  // Shared
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- Step 1: create org ----
  const submitOrg = useCallback(async () => {
    if (!orgName.trim()) {
      setError("Tên tổ chức không được để trống");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const res = await apiFetch<{ id: string; name: string; slug: string }>(
        "/api/v1/orgs",
        {
          method: "POST",
          token: token ?? "",
          orgId: "", // creating an org → no active orgId yet
          body: { name: orgName.trim(), country_code: orgCountry },
        },
      );
      setOrgId(res.data!.id);
      setStep(2);
      // Force a reload of the session-bearing layout so the new org
      // shows up in OrgSwitcher when the wizard finishes.
      router.refresh();
    } catch (e) {
      setError((e as Error).message ?? "Không tạo được tổ chức");
    } finally {
      setSubmitting(false);
    }
  }, [orgName, orgCountry, token, router]);

  // ---- Step 2: save modules ----
  const submitModules = useCallback(async () => {
    if (!orgId) return;
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/orgs/${orgId}/modules`, {
        method: "PATCH",
        token: token ?? "",
        orgId,
        body: { modules: Array.from(modules) },
      });
      setStep(3);
    } catch (e) {
      setError((e as Error).message ?? "Không lưu được lựa chọn module");
    } finally {
      setSubmitting(false);
    }
  }, [orgId, modules, token]);

  // ---- Step 3: send invitations ----
  const submitInvites = useCallback(async () => {
    if (!orgId) return;
    setError(null);
    setSubmitting(true);
    try {
      // Fan out one POST per email. Errors per-email aren't fatal —
      // we still advance to step 4 because the user can resend from
      // Settings → Thành viên later.
      const results = await Promise.allSettled(
        invites.map((email) =>
          apiFetch(`/api/v1/orgs/${orgId}/invitations`, {
            method: "POST",
            token: token ?? "",
            orgId,
            body: { email, role: "member" },
          }),
        ),
      );
      const failed = results.filter((r) => r.status === "rejected");
      if (failed.length > 0 && failed.length === invites.length) {
        setError(`Không gửi được lời mời nào (${failed.length} email)`);
        return;
      }
      setStep(4);
    } finally {
      setSubmitting(false);
    }
  }, [orgId, invites, token]);

  // ---- Step 4: seed demo + finish ----
  const seedAndFinish = useCallback(async () => {
    if (!orgId) return;
    setSeeding(true);
    setError(null);
    try {
      await apiFetch<{ project_id: string }>("/api/v1/onboarding/seed-demo", {
        method: "POST",
        token: token ?? "",
        orgId,
      });
      router.push("/");
      router.refresh();
    } catch (e) {
      // Even if seeding fails, land on the dashboard — the user can
      // create projects manually. Surface the error briefly first.
      setError((e as Error).message ?? "Tạo dữ liệu mẫu thất bại");
      setSeeding(false);
    }
  }, [orgId, token, router]);

  const finishWithoutSeed = useCallback(() => {
    router.push("/");
    router.refresh();
  }, [router]);

  return (
    <AuthShell
      title="Chào mừng đến AEC Platform"
      description="4 bước nhanh để bắt đầu"
    >
      <Stepper current={step} total={4} />

      <div className="mt-6">
        {step === 1 && (
          <StepOrg
            name={orgName}
            country={orgCountry}
            error={error}
            submitting={submitting}
            onNameChange={setOrgName}
            onCountryChange={setOrgCountry}
            onSubmit={submitOrg}
          />
        )}
        {step === 2 && (
          <StepModules
            selected={modules}
            onToggle={(v) => {
              const next = new Set(modules);
              if (next.has(v)) next.delete(v);
              else next.add(v);
              setModules(next);
            }}
            error={error}
            submitting={submitting}
            onBack={() => setStep(1)}
            onSubmit={submitModules}
          />
        )}
        {step === 3 && (
          <StepInvites
            invitesRaw={invitesRaw}
            parsed={invites}
            onChange={setInvitesRaw}
            error={error}
            submitting={submitting}
            onBack={() => setStep(2)}
            onSubmit={submitInvites}
            onSkip={() => setStep(4)}
          />
        )}
        {step === 4 && (
          <StepSeed
            seeding={seeding}
            error={error}
            onSeed={seedAndFinish}
            onSkip={finishWithoutSeed}
          />
        )}
      </div>
    </AuthShell>
  );
}


// ---------- Subcomponents ----------


function Stepper({ current, total }: { current: number; total: number }) {
  return (
    <ol className="flex items-center justify-center gap-2">
      {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
        <li key={n} className="flex items-center gap-2">
          <div
            className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
              n < current
                ? "bg-emerald-500 text-white"
                : n === current
                ? "bg-blue-600 text-white"
                : "bg-slate-200 text-slate-500"
            }`}
            aria-current={n === current ? "step" : undefined}
          >
            {n < current ? <Check size={14} /> : n}
          </div>
          {n < total && (
            <ChevronRight size={14} className="text-slate-300" aria-hidden />
          )}
        </li>
      ))}
    </ol>
  );
}


function StepOrg({
  name,
  country,
  error,
  submitting,
  onNameChange,
  onCountryChange,
  onSubmit,
}: {
  name: string;
  country: string;
  error: string | null;
  submitting: boolean;
  onNameChange: (v: string) => void;
  onCountryChange: (v: string) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="space-y-4"
    >
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Building2 size={18} />
          Tạo tổ chức
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Đây là không gian làm việc của công ty bạn. Có thể đổi tên sau ở
          phần Cài đặt.
        </p>
      </div>

      <div>
        <label className="text-sm font-medium text-slate-700">Tên công ty</label>
        <input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          required
          placeholder="VD: Công ty Xây dựng ABC"
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="text-sm font-medium text-slate-700">Quốc gia</label>
        <select
          value={country}
          onChange={(e) => onCountryChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="VN">Việt Nam</option>
          <option value="LA">Lào</option>
          <option value="KH">Campuchia</option>
          <option value="SG">Singapore</option>
        </select>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
          Tiếp tục
        </button>
      </div>
    </form>
  );
}


function StepModules({
  selected,
  onToggle,
  error,
  submitting,
  onBack,
  onSubmit,
}: {
  selected: Set<string>;
  onToggle: (v: string) => void;
  error: string | null;
  submitting: boolean;
  onBack: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Sparkles size={18} />
          Chọn module sẽ dùng
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Tất cả module luôn sẵn sàng. Lựa chọn này chỉ giúp ưu tiên hiển
          thị trên dashboard. Có thể đổi sau.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 max-h-80 overflow-y-auto pr-1">
        {MODULE_OPTIONS.map((m) => {
          const checked = selected.has(m.value);
          return (
            <label
              key={m.value}
              className={`flex cursor-pointer items-start gap-2 rounded-md border p-2.5 text-sm transition-colors ${
                checked
                  ? "border-blue-500 bg-blue-50"
                  : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(m.value)}
                className="mt-0.5"
              />
              <div className="flex-1">
                <p className="font-medium text-slate-900">{m.label}</p>
                <p className="text-xs text-slate-500">{m.description}</p>
              </div>
            </label>
          );
        })}
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-slate-600 underline-offset-4 hover:underline"
        >
          ← Quay lại
        </button>
        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
          Tiếp tục ({selected.size} module)
        </button>
      </div>
    </div>
  );
}


function StepInvites({
  invitesRaw,
  parsed,
  onChange,
  error,
  submitting,
  onBack,
  onSubmit,
  onSkip,
}: {
  invitesRaw: string;
  parsed: string[];
  onChange: (v: string) => void;
  error: string | null;
  submitting: boolean;
  onBack: () => void;
  onSubmit: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Users size={18} />
          Mời thành viên
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Dán email các thành viên (cách nhau bằng dấu phẩy hoặc xuống dòng).
          Họ sẽ nhận lời mời qua email và được gán role <b>thành viên</b>.
          Bỏ qua bước này nếu chưa cần.
        </p>
      </div>

      <textarea
        value={invitesRaw}
        onChange={(e) => onChange(e.target.value)}
        placeholder="vd: nam@cty.vn, hoa@cty.vn"
        rows={4}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />

      {parsed.length > 0 && (
        <p className="text-xs text-slate-500">
          Sẽ gửi đến: <b>{parsed.length}</b> email
        </p>
      )}

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-slate-600 underline-offset-4 hover:underline"
        >
          ← Quay lại
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            Bỏ qua
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={submitting || parsed.length === 0}
            className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
            Gửi {parsed.length} lời mời
          </button>
        </div>
      </div>
    </div>
  );
}


function StepSeed({
  seeding,
  error,
  onSeed,
  onSkip,
}: {
  seeding: boolean;
  error: string | null;
  onSeed: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Plus size={18} />
          Tạo dữ liệu mẫu?
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Một dự án mẫu cùng đề xuất, dự toán, RFI, ảnh công trường — để
          bạn click thử trước khi nhập dự án thật. Có thể xoá hoặc giữ
          tuỳ ý sau.
        </p>
      </div>

      <ul className="grid grid-cols-2 gap-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <li>· 1 dự án mẫu</li>
        <li>· 1 đề xuất (WinWork)</li>
        <li>· 1 dự toán (CostPulse)</li>
        <li>· 2 lệnh thay đổi</li>
        <li>· 2 RFI</li>
        <li>· 2 lỗi tồn đọng</li>
        <li>· 5 lượt giám sát + ảnh</li>
        <li>· Báo cáo tiến độ</li>
      </ul>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex flex-col gap-2 pt-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={onSkip}
          disabled={seeding}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          Để sau
        </button>
        <button
          type="button"
          onClick={onSeed}
          disabled={seeding}
          className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {seeding ? <Loader2 size={14} className="animate-spin" /> : null}
          {seeding ? "Đang tạo dữ liệu mẫu…" : "Tạo dữ liệu mẫu + xong"}
        </button>
      </div>
    </div>
  );
}
