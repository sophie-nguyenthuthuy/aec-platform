"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, Button, FormField, Input } from "@aec/ui/primitives";

import { AuthShell } from "@/components/AuthShell";
import { SsoButtons } from "@/components/SsoButtons";
import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * Email/password sign-in. Minimal form; no signup flow yet — dev users are
 * provisioned via the Supabase dashboard or admin API. After a successful
 * sign-in the middleware sees the freshly-set cookie and lets the user
 * through to whatever URL was queued via `?next=`.
 */
export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  // `?error=` is set by /auth/callback when an OAuth round-trip fails
  // (expired code, user denied consent, etc.). Seed local state from it
  // so the user sees a recoverable message after redirect, not a silent
  // re-render of an empty form.
  const [error, setError] = useState<string | null>(params.get("error"));
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const supabase = supabaseBrowser();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    setSubmitting(false);
    if (signInError) {
      setError(signInError.message);
      return;
    }
    // Use `replace` so the back button doesn't return to /login.
    router.replace(next);
    // `refresh` so the server components re-run with the new auth cookie.
    router.refresh();
  }

  return (
    <AuthShell
      title="AEC Platform"
      description="Đăng nhập để tiếp tục"
      footer={
        <>
          Chưa có tài khoản?{" "}
          <Link
            href="/signup"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Đăng ký
          </Link>
        </>
      }
    >
      <SsoButtons next={next} />

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

        <FormField
          label="Mật khẩu"
          required
          help={
            <Link
              href="/forgot-password"
              className="text-primary underline-offset-4 hover:underline"
            >
              Quên mật khẩu?
            </Link>
          }
        >
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
          loadingText="Đang đăng nhập"
        >
          {submitting ? "Đang đăng nhập…" : "Đăng nhập"}
        </Button>
      </form>
    </AuthShell>
  );
}
