"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * Where Supabase's "reset password" email lands. Supabase appends a
 * recovery token to the URL fragment which `@supabase/ssr` exchanges
 * for a session automatically (`supabase.auth.onAuthStateChange` fires
 * "PASSWORD_RECOVERY"). Once we have a session, the user can call
 * `updateUser({ password })` to set a new one.
 *
 * If the user lands here without a recovery token (e.g. they bookmarked
 * the URL), redirect them back to /forgot-password.
 */
export default function ResetPasswordPage() {
  const router = useRouter();
  const supabase = supabaseBrowser();

  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [password, setPassword] = useState("");

  useEffect(() => {
    // The recovery flow puts the access_token in the URL fragment.
    // @supabase/ssr's createBrowserClient handles the exchange itself
    // — we just need to wait for the session to materialize.
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") {
        setReady(true);
      }
    });

    // Race: also try `getSession` in case the auth state already
    // settled before we subscribed.
    void supabase.auth.getSession().then(({ data }) => {
      if (data.session) setReady(true);
    });

    return () => sub.subscription.unsubscribe();
  }, [supabase]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const { error: updateError } = await supabase.auth.updateUser({ password });
    setSubmitting(false);

    if (updateError) {
      setError(updateError.message);
      return;
    }
    router.replace("/");
    router.refresh();
  }

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm space-y-3 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-900">Đang xác thực…</h1>
          <p className="text-sm text-slate-600">
            Nếu liên kết không tự kích hoạt, mở lại email và bấm vào liên kết
            đặt lại mật khẩu một lần nữa.
          </p>
          <Link
            href="/forgot-password"
            className="block rounded-md border border-slate-300 px-3 py-2 text-center text-sm text-slate-700 hover:bg-slate-50"
          >
            Yêu cầu liên kết mới
          </Link>
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
          <h1 className="text-xl font-semibold text-slate-900">Đặt lại mật khẩu</h1>
          <p className="text-sm text-slate-600">Nhập mật khẩu mới (≥ 8 ký tự).</p>
        </div>

        <label className="block">
          <span className="block text-xs font-medium text-slate-700">Mật khẩu mới</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            autoFocus
          />
        </label>

        {error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
        ) : null}

        <button
          type="submit"
          disabled={submitting || password.length < 8}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Đang lưu…" : "Đặt lại mật khẩu"}
        </button>
      </form>
    </div>
  );
}
