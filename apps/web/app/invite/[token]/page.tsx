"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { supabaseBrowser } from "@/lib/supabase-browser";

interface InvitationPreview {
  email: string;
  role: string;
  organization_name: string;
  expires_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Set-password form for an invitee. The token in the URL is the bearer
 *  credential for both the GET (preview) and POST (accept) calls — no
 *  user is logged in yet. After a successful accept we sign the user in
 *  with the password they just set, which puts them in the standard
 *  cookie-authed flow.
 *
 *  Next.js 14 contract: `params` arrives as a plain object, NOT a
 *  Promise. Earlier this file used `params: Promise<{token}>` + `use()`
 *  (the Next 15 pattern); on 14 that throws "unsupported type passed
 *  to use()" at first render and the entire page crashes — see the
 *  Playwright trace from the real-auth invitation suite. */
export default function AcceptInvitePage({
  params,
}: {
  params: { token: string };
}) {
  const { token } = params;
  const router = useRouter();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/invitations/${token}`, {
          cache: "no-store",
        });
        const env = (await res.json()) as {
          data: InvitationPreview | null;
          errors: { code: string; message: string }[] | null;
        };
        if (cancelled) return;
        if (!res.ok) {
          setLoadError(env.errors?.[0]?.message ?? "Lời mời không hợp lệ.");
        } else if (env.data) {
          setPreview(env.data);
        }
      } catch {
        if (!cancelled) setLoadError("Không thể tải lời mời. Vui lòng thử lại.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!preview) return;
    setSubmitError(null);
    setSubmitting(true);

    try {
      const acceptRes = await fetch(`${API_BASE}/api/v1/invitations/${token}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, full_name: fullName || null }),
      });
      const env = (await acceptRes.json()) as {
        errors: { code: string; message: string }[] | null;
      };
      if (!acceptRes.ok) {
        setSubmitError(env.errors?.[0]?.message ?? "Không thể chấp nhận lời mời.");
        setSubmitting(false);
        return;
      }

      // Auto-sign-in with the just-set password so the user lands in
      // the dashboard with a populated session cookie. If sign-in fails
      // (e.g. unconfirmed email mode), fall back to the login form
      // pre-filled with their email.
      const supabase = supabaseBrowser();
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: preview.email,
        password,
      });
      if (signInError) {
        router.replace(`/login?email=${encodeURIComponent(preview.email)}`);
        return;
      }
      router.replace("/");
      router.refresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Lỗi không xác định.");
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <p className="text-sm text-slate-600">Đang tải lời mời…</p>
      </div>
    );
  }

  if (loadError || !preview) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm rounded-lg border border-red-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-red-700">Lời mời không hợp lệ</h1>
          <p className="mt-2 text-sm text-slate-600">
            {loadError ?? "Lời mời này không tồn tại hoặc đã được sử dụng."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            Tham gia {preview.organization_name}
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Bạn được mời với vai trò <span className="font-medium">{preview.role}</span>. Đặt mật
            khẩu cho{" "}
            <span className="font-mono text-xs">{preview.email}</span> để bắt đầu.
          </p>
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="block text-xs font-medium text-slate-700">Họ tên</span>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-slate-700">
              Mật khẩu (≥ 8 ký tự)
            </span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </label>
        </div>

        {submitError ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{submitError}</div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Đang xử lý…" : "Chấp nhận và tiếp tục"}
        </button>
      </form>
    </div>
  );
}
