"use client";

/**
 * Admin-only CRUD UI for `normalizer_rules`.
 *
 * Pairs with the API in `apps/api/routers/admin.py`. The DB rules
 * are merged on top of the in-code `_RULES` in
 * `services.price_scrapers.normalizer` — see migration
 * `0028_normalizer_rules.py`. Any mutation here busts the in-process
 * rule cache server-side via `refresh_db_rules()`, so a freshly-saved
 * rule takes effect on the next scrape without a redeploy.
 *
 * Two affordances besides plain CRUD:
 *
 *   1. A "test sample" input at the top — when non-empty, each rule
 *      row is dimmed unless its regex matches the sample. Lets ops
 *      paste a problem material name and visually see which rule
 *      will fire (or that none does — that's the "we need a new rule"
 *      signal).
 *
 *   2. The create/edit form catches the API's 400-on-bad-regex and
 *      surfaces it inline. The server-side validator is the source
 *      of truth (`re.compile(..., re.IGNORECASE)` in
 *      `create_normalizer_rule`); duplicating it client-side would
 *      silently diverge, so we just display whatever it returns.
 */

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import {
  type NormalizerRule,
  type NormalizerRuleCreatePayload,
  useCreateNormalizerRule,
  useDeleteNormalizerRule,
  useNormalizerRules,
  useUpdateNormalizerRule,
} from "@/hooks/admin";
import { ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth-context";

import { TesterResults } from "./_components/TesterResults";


export default function NormalizerRulesPage(): JSX.Element {
  const t = useTranslations("admin_normalizer_rules");
  const session = useSession();
  const isAdmin = session.orgs.find((o) => o.id === session.orgId)?.role === "admin";

  const rules = useNormalizerRules();
  const [sample, setSample] = useState("");
  const [editing, setEditing] = useState<NormalizerRule | "new" | null>(null);

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          {t("non_admin_message")}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("title")}</h1>
          <p className="text-sm text-slate-500">{t("description")}</p>
        </div>
        <button
          type="button"
          onClick={() => setEditing("new")}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          {t("button_new_rule")}
        </button>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600">
          {t("tester_label")}
        </label>
        {/* Textarea instead of an <input> so ops can paste a list of
            unmatched material names from telemetry — the typical
            workflow after a drift alert is "I have N orphan strings;
            which rules cover which?", not "test one name." */}
        <textarea
          value={sample}
          onChange={(e) => setSample(e.target.value)}
          placeholder={t("tester_placeholder")}
          rows={4}
          className="mt-2 w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm focus:border-slate-400 focus:outline-none"
        />
        <p className="mt-1 text-xs text-slate-500">{t("tester_help")}</p>
      </section>

      <TesterResults sample={sample} rules={rules.data ?? []} t={t} />

      <RulesTable
        rules={rules.data ?? []}
        isLoading={rules.isLoading}
        sample={sample}
        onEdit={setEditing}
        t={t}
      />

      {editing !== null && (
        <RuleFormModal rule={editing === "new" ? null : editing} onClose={() => setEditing(null)} t={t} />
      )}
    </div>
  );
}


// ---------- Table ----------


function RulesTable({
  rules,
  isLoading,
  sample,
  onEdit,
  t,
}: {
  rules: NormalizerRule[];
  isLoading: boolean;
  sample: string;
  onEdit: (r: NormalizerRule) => void;
  t: ReturnType<typeof useTranslations<"admin_normalizer_rules">>;
}): JSX.Element {
  // Build a per-rule "matches sample?" lookup once per render so each
  // row's badge is O(1). We compile each pattern with the same flag
  // (`i`) the server uses; pattern compile errors surface as a falsy
  // match (the rule wouldn't fire in production either).
  //
  // Multi-line semantics: when the textarea contains multiple lines,
  // a rule "matches" if its pattern hits AT LEAST ONE input line.
  // Rationale: ops paste a batch of unmatched names; "this rule covers
  // anything in the list" is the actionable question. Single-line
  // mode reduces to the obvious "does this rule fire on this string."
  const matches = useMemo(() => {
    const out = new Map<string, boolean>();
    if (!sample) return out;
    const lines = sample
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (lines.length === 0) return out;
    for (const r of rules) {
      try {
        const re = new RegExp(r.pattern, "i");
        out.set(r.id, lines.some((line) => re.test(line)));
      } catch {
        out.set(r.id, false);
      }
    }
    return out;
  }, [rules, sample]);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        {t("loading")}
      </div>
    );
  }
  if (rules.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        {t("empty_state")}
      </div>
    );
  }

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {t("table_heading")}
        </h2>
        <p className="text-xs text-slate-500">{t("table_subheading", { count: rules.length })}</p>
      </header>
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2 text-right">{t("col_priority")}</th>
            <th className="px-3 py-2">{t("col_pattern")}</th>
            <th className="px-3 py-2">{t("col_material_code")}</th>
            <th className="px-3 py-2">{t("col_canonical_name")}</th>
            <th className="px-3 py-2">{t("col_category")}</th>
            <th className="px-3 py-2">{t("col_preferred_units")}</th>
            <th className="px-3 py-2 text-center">{t("col_enabled")}</th>
            <th className="px-3 py-2 text-right">{t("col_actions")}</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              matches={matches.get(rule.id)}
              sampleActive={Boolean(sample)}
              onEdit={onEdit}
              t={t}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}


function RuleRow({
  rule,
  matches,
  sampleActive,
  onEdit,
  t,
}: {
  rule: NormalizerRule;
  matches: boolean | undefined;
  sampleActive: boolean;
  onEdit: (r: NormalizerRule) => void;
  t: ReturnType<typeof useTranslations<"admin_normalizer_rules">>;
}): JSX.Element {
  const update = useUpdateNormalizerRule();
  const del = useDeleteNormalizerRule();

  // Dim non-matching rules when a sample is active so the eye lands
  // on the row(s) that would actually fire. Use opacity rather than
  // hiding so the priority order remains visible — sometimes "rule X
  // matches but rule Y has higher priority" is the actual bug.
  const dim = sampleActive && matches === false;

  return (
    <tr className={`border-t border-slate-100 ${dim ? "opacity-40" : ""} ${rule.enabled ? "" : "bg-slate-50"}`}>
      <td className="px-3 py-2 text-right font-mono text-slate-700">{rule.priority}</td>
      <td className="px-3 py-2 font-mono text-xs">
        <div className="flex items-center gap-2">
          {sampleActive && matches === true && (
            <span
              className="inline-block h-2 w-2 rounded-full bg-emerald-500"
              title={t("matches_sample")}
              aria-label={t("matches_sample")}
            />
          )}
          <span className="break-all">{rule.pattern}</span>
        </div>
      </td>
      <td className="px-3 py-2 font-mono text-xs text-slate-700">{rule.material_code}</td>
      <td className="px-3 py-2 text-slate-700">{rule.canonical_name}</td>
      <td className="px-3 py-2 text-slate-600">{rule.category ?? "—"}</td>
      <td className="px-3 py-2 font-mono text-xs text-slate-600">{rule.preferred_units || "—"}</td>
      <td className="px-3 py-2 text-center">
        <button
          type="button"
          disabled={update.isPending}
          onClick={() => update.mutate({ id: rule.id, enabled: !rule.enabled })}
          className={`rounded-full px-2 py-0.5 text-xs ${
            rule.enabled
              ? "bg-emerald-100 text-emerald-800 hover:bg-emerald-200"
              : "bg-slate-200 text-slate-700 hover:bg-slate-300"
          } disabled:opacity-50`}
        >
          {rule.enabled ? t("toggle_on") : t("toggle_off")}
        </button>
      </td>
      <td className="px-3 py-2 text-right">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onEdit(rule)}
            className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-100"
          >
            {t("button_edit")}
          </button>
          <button
            type="button"
            disabled={del.isPending}
            onClick={() => {
              if (confirm(t("confirm_delete", { code: rule.material_code }))) {
                del.mutate(rule.id);
              }
            }}
            className="rounded border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            {t("button_delete")}
          </button>
        </div>
      </td>
    </tr>
  );
}


// ---------- Create / edit modal ----------


function RuleFormModal({
  rule,
  onClose,
  t,
}: {
  rule: NormalizerRule | null;
  onClose: () => void;
  t: ReturnType<typeof useTranslations<"admin_normalizer_rules">>;
}): JSX.Element {
  const create = useCreateNormalizerRule();
  const update = useUpdateNormalizerRule();
  const isNew = rule === null;

  const [form, setForm] = useState<NormalizerRuleCreatePayload>({
    priority: rule?.priority ?? 50,
    pattern: rule?.pattern ?? "",
    material_code: rule?.material_code ?? "",
    category: rule?.category ?? null,
    canonical_name: rule?.canonical_name ?? "",
    preferred_units: rule?.preferred_units ?? "",
    enabled: rule?.enabled ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const isSubmitting = create.isPending || update.isPending;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (isNew) {
        await create.mutateAsync(form);
      } else {
        // PATCH-shaped: send the full form. The server handles
        // partial-update semantics — undefined fields are skipped.
        await update.mutateAsync({ id: rule!.id, ...form });
      }
      onClose();
    } catch (err) {
      // The API returns 400 with a `re.error` message for invalid
      // regex — surface it verbatim so the admin can fix the typo
      // without context-switching to docs.
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(String(err));
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold text-slate-900">
          {isNew ? t("modal_title_new") : t("modal_title_edit")}
        </h2>
        <form onSubmit={submit} className="space-y-4">
          <Field label={t("field_pattern")} hint={t("field_pattern_hint")}>
            <input
              type="text"
              required
              value={form.pattern}
              onChange={(e) => setForm({ ...form, pattern: e.target.value })}
              className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm focus:border-slate-400 focus:outline-none"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("field_material_code")}>
              <input
                type="text"
                required
                value={form.material_code}
                onChange={(e) => setForm({ ...form, material_code: e.target.value })}
                className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm focus:border-slate-400 focus:outline-none"
              />
            </Field>
            <Field label={t("field_canonical_name")}>
              <input
                type="text"
                required
                value={form.canonical_name}
                onChange={(e) => setForm({ ...form, canonical_name: e.target.value })}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
              />
            </Field>
            <Field label={t("field_category")}>
              <input
                type="text"
                value={form.category ?? ""}
                onChange={(e) => setForm({ ...form, category: e.target.value || null })}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
              />
            </Field>
            <Field label={t("field_preferred_units")} hint={t("field_preferred_units_hint")}>
              <input
                type="text"
                value={form.preferred_units ?? ""}
                onChange={(e) => setForm({ ...form, preferred_units: e.target.value })}
                className="w-full rounded-md border border-slate-200 px-3 py-2 font-mono text-sm focus:border-slate-400 focus:outline-none"
              />
            </Field>
            <Field label={t("field_priority")} hint={t("field_priority_hint")}>
              <input
                type="number"
                min={0}
                max={10000}
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: Number(e.target.value) || 0 })}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
              />
            </Field>
            <Field label={t("field_enabled")}>
              <label className="mt-2 inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.enabled ?? true}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                {form.enabled ? t("toggle_on") : t("toggle_off")}
              </label>
            </Field>
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
            >
              {t("button_cancel")}
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {isSubmitting ? t("button_saving") : t("button_save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <label className="block">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </label>
  );
}
