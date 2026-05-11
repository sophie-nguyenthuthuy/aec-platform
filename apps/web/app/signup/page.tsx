"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { MailCheck } from "lucide-react";

import { Alert, Button, FormField, Input } from "@aec/ui/primitives";

import { AuthShell } from "@/components/AuthShell";
import { supabaseBrowser } from "@/lib/supabase-browser";

/**
 * Self-serve signup. Calls `supabase.auth.signUp` which:
 *
 *  * If "Confirm email" is OFF in the Supabase project (dev default),
 *    returns a populated `session` immediately — we redirect to `/`,
 *    where the layout sees the new user has no orgs and renders the
 *    onboarding "create your org" pane.
 *
 *  * If "Confirm email" is ON (prod default), `session` is null until
 *    the user clicks the link in the verification email. Show a
 *    "check your email" message and stop.
 *
 *  Either way, the new local DB rows (`users`, `org_members`) are
 *  created on first authenticated `/me/orgs` call by the auto-provisioner —
 *  signup itself only touches Supabase.
 */
export default function SignupPage() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [needsConfirmation, setNeedsConfirmation] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const supabase = supabaseBrowser();
    const { data, error: signUpError } = await supabase.auth.signUp({
      email,
      password,
    });
    setSubmitting(false);

    if (signUpError) {
      setError(signUpError.message);
      return;
    }

    if (data.session) {
      // Auto-confirmed — go to /, layout will detect no orgs and render
      // the onboarding form.
      router.replace(next);
      router.refresh();
      return;
    }

    // Email confirmation required. Show the "check your inbox" state.
    setNeedsConfirmation(true);
  }

  if (needsConfirmation) {
    return (
      <AuthShell
        title="Kiểm tra email"
        description={
          <>
            Chúng tôi vừa gửi một liên kết xác nhận đến{" "}
            <span className="font-mono text-xs text-foreground">{email}</span>.
            Mở liên kết và quay lại đây để đăng nhập.
          </>
        }
      >
        <div className="flex items-start gap-3 rounded-md bg-muted/60 p-3 text-sm text-muted-foreground">
          <MailCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <p>Không nhận được email? Kiểm tra thư mục spam hoặc thử đăng ký lại với địa chỉ khác.</p>
        </div>
        <Button
          variant="outline"
          className="mt-4 w-full"
          onClick={() => router.push("/login")}
        >
          Quay lại đăng nhập
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="AEC Platform"
      description="Đăng ký tài khoản miễn phí"
      footer={
        <>
          Đã có tài khoản?{" "}
          <Link
            href="/login"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Đăng nhập
          </Link>
        </>
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

        <FormField
          label="Mật khẩu"
          required
          help="Ít nhất 8 ký tự."
        >
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
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
          loadingText="Đang đăng ký"
        >
          {submitting ? "Đang đăng ký…" : "Đăng ký"}
        </Button>
      </form>
    </AuthShell>
  );
}
