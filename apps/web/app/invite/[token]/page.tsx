"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  EmptyState,
  FormField,
  Input,
  Spinner,
} from "@aec/ui/primitives";

import { AuthShell } from "@/components/AuthShell";
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
      <AuthShell title="Đang tải lời mời…">
        <div className="flex justify-center py-4">
          <Spinner size="lg" label="Đang tải lời mời" />
        </div>
      </AuthShell>
    );
  }

  if (loadError || !preview) {
    return (
      <AuthShell title="Lời mời không hợp lệ">
        <EmptyState
          variant="error"
          icon={<AlertCircle size={20} />}
          title="Không thể sử dụng lời mời này"
          description={loadError ?? "Lời mời này không tồn tại hoặc đã được sử dụng."}
          action={
            <Button onClick={() => router.push("/login")} variant="outline">
              Đến trang đăng nhập
            </Button>
          }
        />
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={`Tham gia ${preview.organization_name}`}
      description={
        <>
          Bạn được mời với vai trò{" "}
          <span className="font-medium text-foreground">{preview.role}</span>. Đặt mật khẩu
          cho <span className="font-mono text-xs">{preview.email}</span> để bắt đầu.
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormField label="Họ tên">
          <Input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            autoComplete="name"
          />
        </FormField>

        <FormField label="Mật khẩu" required help="Ít nhất 8 ký tự.">
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </FormField>

        {submitError && (
          <Alert variant="destructive">
            <AlertTitle>Lỗi</AlertTitle>
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          className="w-full"
          loading={submitting}
          loadingText="Đang xử lý"
        >
          {submitting ? "Đang xử lý…" : "Chấp nhận và tiếp tục"}
        </Button>
      </form>
    </AuthShell>
  );
}
