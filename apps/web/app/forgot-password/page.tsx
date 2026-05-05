"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * "Send me a reset link" form. Calls Supabase's built-in
 * `resetPasswordForEmail` which mails a one-time link that lands at
 * `/reset-password` (the `redirectTo` below). Whether the email actually
 * goes out depends on the Supabase project's SMTP config — until that's
 * wired in the dashboard, dev users have to use the Supabase admin API
 * to reset.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const supabase = supabaseBrowser();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
      // Build the absolute URL on the fly — we can't hardcode the host
      // because it differs across dev/staging/prod.
      redirectTo: `${window.location.origin}/reset-password`,
    });

    setSubmitting(false);

    // Per Supabase recommendation: don't surface "user not found" — show
    // the success state regardless to avoid email enumeration. The
    // catch is for actual transport errors (rate-limit, invalid email
    // format Supabase rejected).
    if (resetError && !resetError.message.toLowerCase().includes("user")) {
      setError(resetError.message);
      return;
    }

    setSent(true);
  }

  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm space-y-3 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">Kiểm tra email</h1>
          <p className="text-sm text-slate-600">
            Nếu <span className="font-mono text-xs">{email}</span> tồn tại trong
            hệ thống, bạn sẽ nhận được liên kết đặt lại mật khẩu trong vài phút.
          </p>
          <Link
            href="/login"
            className="block rounded-md border border-slate-300 px-3 py-2 text-center text-sm text-slate-700 hover:bg-slate-50"
          >
            Quay lại đăng nhập
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
          <h1 className="text-xl font-semibold text-slate-900">Quên mật khẩu?</h1>
          <p className="text-sm text-slate-600">
            Nhập email và chúng tôi sẽ gửi liên kết đặt lại mật khẩu.
          </p>
        </div>

        <label className="block">
          <span className="block text-xs font-medium text-slate-700">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </label>

        {error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Đang gửi…" : "Gửi liên kết"}
        </button>

        <p className="text-center text-xs text-slate-500">
          <Link href="/login" className="hover:underline">
            Quay lại đăng nhập
          </Link>
        </p>
      </form>
    </div>
  );
}
