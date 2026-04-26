"use client";

/**
 * Public supplier RFQ-response page.
 *
 * Lives outside the `(dashboard)` route group on purpose — the supplier
 * has no AEC Platform login, no org, no JWT. The token in `?t=` IS the
 * authn; both the GET context fetch and the POST submit pass it through
 * to /api/v1/public/rfq/{context,respond}. This page never reads from
 * the dashboard session context.
 *
 * UX shape:
 *  - Loading state on first context fetch.
 *  - 401/expired → friendly error page with "request a new link" copy.
 *  - 404 (RFQ withdrawn) → matching error variant.
 *  - 200 + submission_status="submitted" → confirmation page (no form).
 *  - 200 + submission_status="pending" → the response form.
 */

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface PublicBoqLine {
  description: string;
  material_code: string | null;
  quantity: number | null;
  unit: string | null;
}

interface PublicRfqContext {
  organization_name: string;
  project_name: string | null;
  estimate_name: string | null;
  deadline: string | null;
  message: string | null;
  boq_digest: PublicBoqLine[];
  submission_status: "pending" | "submitted";
  submitted_quote: PublicQuote | null;
}

interface PublicQuote {
  total_vnd: string | null;
  lead_time_days: number | null;
  valid_until: string | null;
  notes: string | null;
  line_items: PublicQuoteLine[];
}

interface PublicQuoteLine {
  material_code: string | null;
  description: string;
  quantity: number | null;
  unit: string | null;
  unit_price_vnd: string | null;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "no-token" }
  | { kind: "error"; status: number; message: string }
  | { kind: "ready"; context: PublicRfqContext };

export default function RfqRespondPage(): JSX.Element {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  // Read `?t=` directly from window.location instead of `useSearchParams`
  // so we can render a sensible no-token state without pulling in the
  // suspense boundary the App Router expects around `useSearchParams`.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const t = params.get("t");
    if (!t) {
      setState({ kind: "no-token" });
      return;
    }
    setToken(t);
    void fetchContext(t).then(setState);
  }, []);

  if (state.kind === "loading") {
    return <CenteredCard>Loading your RFQ…</CenteredCard>;
  }
  if (state.kind === "no-token") {
    return (
      <ErrorCard title="Missing link token">
        This page expects a secure link from your RFQ email. If you copied
        the URL by hand, please use the original link from the email
        instead — the token after <code>?t=</code> is required.
      </ErrorCard>
    );
  }
  if (state.kind === "error") {
    return (
      <ErrorCard title={state.status === 401 ? "Link expired or invalid" : "RFQ unavailable"}>
        {state.status === 401
          ? "The link in your email may have expired or been replaced by a newer one. Please reply to the original email asking for a fresh link."
          : state.message}
      </ErrorCard>
    );
  }

  const ctx = state.context;
  if (ctx.submission_status === "submitted") {
    return <SubmittedConfirmation context={ctx} />;
  }
  return <RespondForm context={ctx} token={token!} />;
}


// ---------- Network ----------

async function fetchContext(token: string): Promise<LoadState> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/rfq/context?t=${encodeURIComponent(token)}`,
      { cache: "no-store" },
    );
    const json = (await res.json().catch(() => ({}))) as {
      data?: PublicRfqContext;
      errors?: Array<{ message: string }>;
    };
    if (!res.ok) {
      return {
        kind: "error",
        status: res.status,
        message: json.errors?.[0]?.message ?? "Could not load this RFQ.",
      };
    }
    if (!json.data) {
      return { kind: "error", status: 500, message: "Empty response from server." };
    }
    return { kind: "ready", context: json.data };
  } catch (e: unknown) {
    return {
      kind: "error",
      status: 0,
      message: e instanceof Error ? e.message : "Network error",
    };
  }
}

async function postQuote(token: string, payload: PublicQuote): Promise<{ ok: true } | { ok: false; message: string }> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/public/rfq/respond?t=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!res.ok) {
      const json = (await res.json().catch(() => ({}))) as {
        errors?: Array<{ message: string }>;
      };
      return { ok: false, message: json.errors?.[0]?.message ?? `HTTP ${res.status}` };
    }
    return { ok: true };
  } catch (e: unknown) {
    return { ok: false, message: e instanceof Error ? e.message : "Network error" };
  }
}


// ---------- Layout helpers ----------

function CenteredCard({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto mt-12 max-w-2xl rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        {children}
      </div>
    </main>
  );
}

function ErrorCard({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <CenteredCard>
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      <p className="mt-3 text-sm text-slate-600">{children}</p>
    </CenteredCard>
  );
}

function ContextHeader({ context }: { context: PublicRfqContext }): JSX.Element {
  return (
    <header className="border-b border-slate-200 pb-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">Request for Quotation</div>
      <h1 className="mt-1 text-2xl font-bold text-slate-900">{context.organization_name}</h1>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {context.project_name ? (
          <Field label="Project">{context.project_name}</Field>
        ) : null}
        {context.estimate_name ? (
          <Field label="Estimate">{context.estimate_name}</Field>
        ) : null}
        {context.deadline ? (
          <Field label="Response deadline">{context.deadline}</Field>
        ) : null}
      </dl>
      {context.message ? (
        <p className="mt-4 whitespace-pre-wrap text-sm text-slate-700">{context.message}</p>
      ) : null}
    </header>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{children}</dd>
    </div>
  );
}

function BoqDigestList({ lines }: { lines: PublicBoqLine[] }): JSX.Element | null {
  if (lines.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">Indicative scope</h2>
      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
            <tr>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2">Code</th>
              <th className="px-3 py-2 text-right">Quantity</th>
              <th className="px-3 py-2">Unit</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-3 py-2">{l.description}</td>
                <td className="px-3 py-2 font-mono text-xs text-slate-500">
                  {l.material_code ?? "—"}
                </td>
                <td className="px-3 py-2 text-right">{l.quantity ?? "—"}</td>
                <td className="px-3 py-2">{l.unit ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}


// ---------- Submitted state ----------

function SubmittedConfirmation({ context }: { context: PublicRfqContext }): JSX.Element {
  const q = context.submitted_quote;
  return (
    <CenteredCard>
      <ContextHeader context={context} />
      <div className="mt-6 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
        <strong>Your quote has been received.</strong> Thanks — the buyer
        will reach out if they need follow-up. You can close this page.
      </div>
      {q ? (
        <section className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">What you submitted</h2>
          <dl className="grid grid-cols-1 gap-y-1 text-sm sm:grid-cols-2">
            {q.total_vnd ? <Field label="Total (VND)">{q.total_vnd}</Field> : null}
            {q.lead_time_days != null ? (
              <Field label="Lead time">{q.lead_time_days} days</Field>
            ) : null}
            {q.valid_until ? <Field label="Valid until">{q.valid_until}</Field> : null}
          </dl>
          {q.notes ? (
            <p className="mt-3 whitespace-pre-wrap text-sm text-slate-600">{q.notes}</p>
          ) : null}
        </section>
      ) : null}
    </CenteredCard>
  );
}


// ---------- Form ----------

function RespondForm({
  context,
  token,
}: {
  context: PublicRfqContext;
  token: string;
}): JSX.Element {
  // Seed line items from the buyer's BOQ so the supplier can edit prices
  // in place rather than retyping descriptions. They can still add/remove
  // rows below.
  const [lineItems, setLineItems] = useState<PublicQuoteLine[]>(() =>
    context.boq_digest.map((l) => ({
      material_code: l.material_code,
      description: l.description,
      quantity: l.quantity,
      unit: l.unit,
      unit_price_vnd: null,
    })),
  );
  const [totalVnd, setTotalVnd] = useState<string>("");
  const [leadTimeDays, setLeadTimeDays] = useState<string>("");
  const [validUntil, setValidUntil] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (submitted) {
    // Re-render with the same data the supplier just sent, surfaced as
    // submitted_quote — saves a refetch.
    return (
      <SubmittedConfirmation
        context={{
          ...context,
          submission_status: "submitted",
          submitted_quote: {
            total_vnd: totalVnd || null,
            lead_time_days: leadTimeDays ? parseInt(leadTimeDays, 10) : null,
            valid_until: validUntil || null,
            notes: notes || null,
            line_items: lineItems,
          },
        }}
      />
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const payload: PublicQuote = {
      total_vnd: totalVnd || null,
      lead_time_days: leadTimeDays ? parseInt(leadTimeDays, 10) : null,
      valid_until: validUntil || null,
      notes: notes || null,
      // Strip lines the supplier left fully blank — keeps the buyer's
      // dashboard view clean.
      line_items: lineItems.filter(
        (l) => l.description || l.unit_price_vnd || l.quantity != null,
      ),
    };
    const res = await postQuote(token, payload);
    setBusy(false);
    if (res.ok) {
      setSubmitted(true);
    } else {
      setError(res.message);
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto mt-6 max-w-3xl space-y-4">
        <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <ContextHeader context={context} />
          <BoqDigestList lines={context.boq_digest} />
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
        >
          <h2 className="text-lg font-semibold text-slate-900">Submit your quote</h2>
          <p className="mt-1 text-sm text-slate-500">
            Fill in either a top-line total or per-line prices below — both is
            fine too. All fields are optional.
          </p>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FormField label="Total quote (VND)">
              <input
                inputMode="numeric"
                value={totalVnd}
                onChange={(e) => setTotalVnd(e.target.value)}
                placeholder="e.g. 12500000"
                className={inputClass}
              />
            </FormField>
            <FormField label="Lead time (days)">
              <input
                type="number"
                min={0}
                max={365}
                value={leadTimeDays}
                onChange={(e) => setLeadTimeDays(e.target.value)}
                className={inputClass}
              />
            </FormField>
            <FormField label="Quote valid until">
              <input
                type="date"
                value={validUntil}
                onChange={(e) => setValidUntil(e.target.value)}
                className={inputClass}
              />
            </FormField>
          </div>

          <FormField label="Notes (delivery terms, payment terms, exclusions…)" className="mt-4">
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={2000}
              className={inputClass}
            />
          </FormField>

          {lineItems.length > 0 ? (
            <section className="mt-6">
              <h3 className="mb-2 text-sm font-semibold text-slate-700">Line-item pricing</h3>
              <div className="overflow-hidden rounded-md border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
                    <tr>
                      <th className="px-3 py-2">Item</th>
                      <th className="px-3 py-2 text-right">Quantity</th>
                      <th className="px-3 py-2">Unit</th>
                      <th className="px-3 py-2 text-right">Unit price (VND)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lineItems.map((line, idx) => (
                      <tr key={idx} className="border-t border-slate-100">
                        <td className="px-3 py-2">
                          <div className="font-medium text-slate-900">{line.description}</div>
                          {line.material_code ? (
                            <div className="font-mono text-xs text-slate-500">
                              {line.material_code}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2 text-right">{line.quantity ?? "—"}</td>
                        <td className="px-3 py-2">{line.unit ?? "—"}</td>
                        <td className="px-3 py-2">
                          <input
                            inputMode="numeric"
                            value={line.unit_price_vnd ?? ""}
                            onChange={(e) =>
                              setLineItems((prev) =>
                                prev.map((p, i) =>
                                  i === idx ? { ...p, unit_price_vnd: e.target.value || null } : p,
                                ),
                              )
                            }
                            placeholder="0"
                            className={`${inputClass} text-right`}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {error ? (
            <p className="mt-4 text-sm text-red-600" role="alert">
              {error}
            </p>
          ) : null}

          <div className="mt-6 flex items-center justify-end gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {busy ? "Sending…" : "Submit quote"}
            </button>
          </div>
        </form>
      </div>
    </main>
  );
}

function FormField({
  label,
  children,
  className = "",
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600">
        {label}
      </span>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none";
