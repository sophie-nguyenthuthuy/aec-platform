/**
 * "Per-input results" panel for the normaliser-rules admin page.
 *
 * Computes the winning rule for each pasted input line. The "winner"
 * is the first rule whose pattern matches — same first-match
 * semantics the server uses. The incoming `rules` list is sorted by
 * priority ASC (server default), so the order matches production.
 *
 * Extracted into its own module so vitest can exercise the regex
 * matching, multi-line gating, and orphan-flag branches without
 * mounting the whole admin page.
 *
 * `t` is structurally typed instead of bound to the next-intl
 * `useTranslations(...)` return so tests can pass a plain stub. The
 * production caller satisfies the structural contract trivially.
 */

import { useMemo } from "react";

import type { NormalizerRule } from "@/hooks/admin";


/**
 * Minimal translator-shape the panel needs. The next-intl
 * `useTranslations(...)` return matches this structurally.
 */
export type Translator = (key: string, params?: Record<string, string | number>) => string;


export function TesterResults({
  sample,
  rules,
  t,
}: {
  sample: string;
  rules: NormalizerRule[];
  t: Translator;
}): JSX.Element | null {
  // Split on newlines, drop blank lines. Trim each so trailing
  // whitespace from a paste doesn't accidentally make a rule fail to
  // match (regexes are anchorless but trailing spaces still matter
  // when a pattern has `$` at the end).
  const inputs = useMemo(
    () =>
      sample
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    [sample],
  );

  // Pre-compile rule patterns once. Bad patterns are stored as null —
  // they're effectively dead in production too.
  const compiled = useMemo(
    () =>
      rules.map((r) => {
        try {
          return { rule: r, regex: new RegExp(r.pattern, "i") };
        } catch {
          return { rule: r, regex: null as RegExp | null };
        }
      }),
    [rules],
  );

  if (inputs.length <= 1) {
    // Single-line mode — the per-rule green-dot highlight in the
    // outer rules table already conveys the answer; an extra
    // results panel would just duplicate. Hide.
    return null;
  }

  const results = inputs.map((input) => {
    const winner = compiled.find(({ regex }) => regex && regex.test(input));
    return { input, winner: winner?.rule ?? null };
  });
  const matchedCount = results.filter((r) => r.winner !== null).length;
  const unmatchedCount = results.length - matchedCount;

  return (
    <section
      className="overflow-hidden rounded-lg border border-slate-200 bg-white"
      data-testid="tester-results"
    >
      <header className="flex items-baseline justify-between border-b border-slate-100 px-4 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {t("results_heading")}
        </h2>
        <p className="text-xs text-slate-500">
          {t("results_summary", { matched: matchedCount, unmatched: unmatchedCount })}
        </p>
      </header>
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th className="px-3 py-2">{t("col_input")}</th>
            <th className="px-3 py-2">{t("col_winning_rule")}</th>
          </tr>
        </thead>
        <tbody>
          {results.map((row, idx) => (
            <tr
              key={`${idx}-${row.input}`}
              className="border-t border-slate-100"
              data-testid="tester-result-row"
              data-input={row.input}
              data-winner={row.winner?.material_code ?? ""}
            >
              <td className="px-3 py-2 font-mono text-xs break-all">{row.input}</td>
              <td className="px-3 py-2">
                {row.winner ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-slate-700">
                    <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
                    <span className="font-mono">{row.winner.material_code}</span>
                    <span className="text-slate-500">— {row.winner.canonical_name}</span>
                    <span className="text-slate-400">
                      {t("priority_label", { priority: row.winner.priority })}
                    </span>
                  </span>
                ) : (
                  // Pink-flag: this is the actionable signal — paste
                  // your unmatched-list from telemetry, the lines that
                  // light up red here are the ones that need a new rule.
                  <span
                    className="inline-flex items-center gap-1.5 rounded bg-rose-50 px-2 py-0.5 text-xs text-rose-700"
                    data-testid="tester-result-no-match"
                  >
                    {t("no_match")}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
