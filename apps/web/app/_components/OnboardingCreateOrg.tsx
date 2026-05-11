"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Two-step first-run wizard, shown by `app/layout.tsx` when the
 * authenticated user has zero org memberships.
 *
 *   Step 1 — `create_org`: creates the org via `POST /api/v1/orgs`
 *     (caller becomes `owner`). Form is blocking — without an org
 *     the dashboard has nowhere to load tenant data from.
 *
 *   Step 2 — `seed_choice`: offers a one-click "Load demo data"
 *     CTA (POST `/api/v1/onboarding/seed-demo` — the same endpoint
 *     the projects-page empty state hits) OR "Skip, I'll start
 *     blank." Either choice leads to `/winwork`. Optional: a fresh
 *     org with zero projects lands on a wall of empty dashboards;
 *     seed-demo populates one project across every module so the
 *     evaluator immediately sees what the platform does.
 *
 * Why two steps in one component (not two routes):
 *   * The transition between steps doesn't need a URL change — the
 *     user is in a single linear flow. A separate `/onboarding/seed`
 *     route would mean either an extra middleware bypass entry or
 *     another auth-gating decision.
 *   * Both steps share the `email` and `token` props — passing them
 *     through a route change would mean re-fetching the session.
 *
 * The token comes from the Server Component layout via prop drilling
 * — no extra Supabase round-trip in the browser.
 */
export function OnboardingCreateOrg({ token, email }: { token: string; email: string }) {
  const router = useRouter();
  const [step, setStep] = useState<"create_org" | "seed_choice">("create_org");
  const [name, setName] = useState("");
  const [orgId, setOrgId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onCreateOrg(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/orgs`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: name.trim() }),
      });
      const env = (await res.json()) as {
        data: { id: string } | null;
        errors: { code: string; message: string }[] | null;
      };
      if (!res.ok || !env.data) {
        setError(env.errors?.[0]?.message ?? "Không thể tạo tổ chức.");
        setSubmitting(false);
        return;
      }
      // Step 1 → 2. Stash the new org's id so the seed-demo CTA can
      // include it in the X-Org-ID header (the auto-provisioner sets
      // the active-org cookie eventually but we want to act
      // immediately — header is the synchronous path).
      setOrgId(env.data.id);
      setStep("seed_choice");
      setSubmitting(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi không xác định.");
      setSubmitting(false);
    }
  }

  async function onSeedDemo() {
    if (!orgId) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/onboarding/seed-demo`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Org-ID": orgId,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) {
        // 403 / 500 — fall through to the dashboard anyway. The org
        // was created successfully; failed seed isn't a blocker.
        // Show the error briefly, then let the user choose Skip.
        const env = (await res.json().catch(() => null)) as
          | { errors?: { message: string }[] | null }
          | null;
        setError(
          env?.errors?.[0]?.message ?? "Không thể nạp demo data — bạn có thể bỏ qua.",
        );
        setSubmitting(false);
        return;
      }
      // Success — land on /winwork (the dashboard's default home).
      // `refresh()` so the layout re-runs against the now-populated
      // /me/orgs and seed-demo data renders on first paint.
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi không xác định.");
      setSubmitting(false);
    }
  }

  function onSkipSeed() {
    // No-op apart from the redirect — the org exists, the user just
    // chose to start with no demo data. Layout re-renders, finds
    // the org, dashboard loads with empty-state panels.
    router.replace("/");
    router.refresh();
  }

  if (step === "seed_choice") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-md space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">
              ✓ Tổ chức đã tạo
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Bạn đã sẵn sàng bắt đầu. Một bước cuối: bạn có muốn nạp dữ liệu
              mẫu để xem nền tảng hoạt động không?
            </p>
          </div>

          <div className="space-y-3 rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
            <p className="font-semibold">Nạp dữ liệu demo (khuyến nghị)</p>
            <p className="text-xs leading-relaxed">
              Tạo 1 dự án mẫu với đề xuất, dự toán, change orders, RFI,
              defects, và 5 visit + ảnh SiteEye. An toàn để chạy lại — idempotent.
              Bạn sẽ thấy ngay nền tảng hoạt động ra sao trên 14 mô-đun.
            </p>
            <button
              type="button"
              onClick={onSeedDemo}
              disabled={submitting}
              className="w-full rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Đang nạp…" : "Nạp demo + vào dashboard"}
            </button>
          </div>

          {error ? (
            <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          ) : null}

          <div className="space-y-2">
            <button
              type="button"
              onClick={onSkipSeed}
              disabled={submitting}
              className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Bỏ qua — bắt đầu với dashboard trống
            </button>
            <p className="text-center text-[11px] text-slate-500">
              Bạn vẫn có thể nạp demo sau từ trang Dự án.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Step 1 — create org.
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={onCreateOrg}
        className="w-full max-w-md space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Tạo tổ chức của bạn</h1>
          <p className="mt-1 text-sm text-slate-600">
            Bạn đang đăng nhập với <span className="font-mono text-xs">{email}</span>{" "}
            nhưng chưa thuộc tổ chức nào. Tạo một tổ chức để bắt đầu.
          </p>
          <p className="mt-2 text-[11px] text-slate-500">Bước 1 / 2</p>
        </div>

        <label className="block">
          <span className="block text-xs font-medium text-slate-700">Tên tổ chức</span>
          <input
            type="text"
            required
            minLength={2}
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ví dụ: Kiến Trúc XYZ"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            autoFocus
          />
          <span className="mt-1 block text-[11px] text-slate-500">
            Bạn sẽ là chủ sở hữu (owner). Có thể mời thành viên khác sau.
          </span>
        </label>

        {error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
        ) : null}

        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Đang tạo…" : "Tiếp tục →"}
        </button>
      </form>
    </div>
  );
}
