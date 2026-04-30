"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Full-page fallback shown by `app/layout.tsx` when the authenticated
 * user has zero org memberships. Creates an org via `POST /api/v1/orgs`
 * which makes the caller `owner`; after success the layout re-runs
 * (via `router.refresh()`) and the dashboard renders normally.
 *
 * The token is passed in from the Server Component layout so we don't
 * need a Supabase round-trip in the browser just to read it.
 */
export function OnboardingCreateOrg({ token, email }: { token: string; email: string }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
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
      // Layout re-renders against fresh /me/orgs, finds the new org,
      // and the dashboard mounts normally. router.replace("/") ensures
      // we land on the home redirect (/winwork) rather than a
      // potentially deep URL the user typed.
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi không xác định.");
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Tạo tổ chức của bạn</h1>
          <p className="mt-1 text-sm text-slate-600">
            Bạn đang đăng nhập với <span className="font-mono text-xs">{email}</span>{" "}
            nhưng chưa thuộc tổ chức nào. Tạo một tổ chức để bắt đầu.
          </p>
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
          {submitting ? "Đang tạo…" : "Tạo tổ chức"}
        </button>
      </form>
    </div>
  );
}
