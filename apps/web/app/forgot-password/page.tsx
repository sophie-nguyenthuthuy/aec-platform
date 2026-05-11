"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, FormField, Input } from "@aec/ui/primitives";

import { AuthShell } from "@/components/AuthShell";
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
  const router = useRouter();
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
      <AuthShell
        title="Kiểm tra email"
        description={
          <>
            Nếu <span className="font-mono text-xs text-foreground">{email}</span>{" "}
            tồn tại trong hệ thống, bạn sẽ nhận được liên kết đặt lại mật khẩu trong
            vài phút.
          </>
        }
      >
        <Button
          variant="outline"
          className="w-full"
          onClick={() => router.push("/login")}
        >
          Quay lại đăng nhập
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Quên mật khẩu?"
      description="Nhập email và chúng tôi sẽ gửi liên kết đặt lại mật khẩu."
      footer={
        <Link
          href="/login"
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          Quay lại đăng nhập
        </Link>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormField label="Email" required>
          <Input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </FormField>

        {error && (
          <Alert variant="destructive">
            <p>{error}</p>
          </Alert>
        )}

        <Button
          type="submit"
          className="w-full"
          loading={submitting}
          loadingText="Đang gửi"
        >
          {submitting ? "Đang gửi…" : "Gửi liên kết"}
        </Button>
      </form>
    </AuthShell>
  );
}
