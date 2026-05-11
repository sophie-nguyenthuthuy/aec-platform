"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Button,
  FormField,
  Input,
  Spinner,
} from "@aec/ui/primitives";

import { AuthShell } from "@/components/AuthShell";
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
      <AuthShell
        title="Đang xác thực…"
        description="Nếu liên kết không tự kích hoạt, mở lại email và bấm vào liên kết đặt lại mật khẩu một lần nữa."
      >
        <div className="flex justify-center py-2">
          <Spinner size="lg" label="Đang xác thực" />
        </div>
        <Button
          variant="outline"
          className="mt-4 w-full"
          onClick={() => router.push("/forgot-password")}
        >
          Yêu cầu liên kết mới
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Đặt lại mật khẩu"
      description="Nhập mật khẩu mới (≥ 8 ký tự)."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormField label="Mật khẩu mới" required>
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
            autoFocus
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
          disabled={password.length < 8}
          loading={submitting}
          loadingText="Đang lưu"
        >
          {submitting ? "Đang lưu…" : "Đặt lại mật khẩu"}
        </Button>
      </form>
    </AuthShell>
  );
}
