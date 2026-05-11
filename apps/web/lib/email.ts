/**
 * Email validation (cycle GG3, TS half).
 *
 * Pure stdlib RFC 5321 / 5322 structural validation. Today the
 * org-create owner-email field, the notification preference
 * editor, and the audit row's email-impact detector each
 * duplicate the regex inline with subtly different rules. This
 * module is the single source of truth.
 *
 *   parseEmail(input)       — lowercased canonical or null
 *   isValidEmail(input)     — bool
 *   emailDomain(input)      — lowercased domain part or null
 *   MAX_EMAIL_LENGTH        — 254 (RFC 5321)
 *   MAX_LOCAL_PART_LENGTH   — 64
 *
 * Storage convention: emails are stored lowercased (matches the
 * `services.audit_row` and org-membership tables). Pin so a
 * refactor that preserves user-typed case introduces a duplicate-
 * row risk.
 *
 * Out of scope: quoted local parts (`"a@b"@c.com`),
 * internationalized domains (`tên@miền.vn`), IP-literal hosts
 * (`user@[127.0.0.1]`). Pure ASCII.
 *
 * Pure TS, no React. Mirrors `apps/api/services/email.py`.
 */


/** RFC 5321 §4.5.3.1.3 max email length. */
export const MAX_EMAIL_LENGTH = 254;


/** RFC 5321 §4.5.3.1.1 max local-part length. */
export const MAX_LOCAL_PART_LENGTH = 64;


// Local part: alphanumeric + . _ % + - (no leading/trailing
// dot, no consecutive dots — enforced via segment grouping).
const _LOCAL_PART_RE = /^[a-zA-Z0-9_%+\-]+(?:\.[a-zA-Z0-9_%+\-]+)*$/;

// Domain label: alphanumeric + hyphen, NOT leading/trailing
// hyphen. RFC 1035 LDH ("letters, digits, hyphen").
const _DOMAIN_LABEL_RE = /^[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?$/;


/**
 * Parse and lowercase-canonicalize an email address.
 *
 * Returns canonical `local@domain` (lowercased) or `null`.
 *
 *   * parseEmail("USER@Example.COM")        → "user@example.com"
 *   * parseEmail("  user@example.com  ")    → "user@example.com"
 *   * parseEmail("user.name+tag@example.com") → "user.name+tag@example.com"
 *   * parseEmail("noatsign.com")            → null
 *   * parseEmail("user@example")            → null  (no TLD)
 *   * parseEmail("user@example.c")          → null  (TLD < 2 chars)
 */
export function parseEmail(input: string | null | undefined): string | null {
  if (input === null || input === undefined) return null;
  const s = input.trim();
  if (!s) return null;
  if (s.length > MAX_EMAIL_LENGTH) return null;

  const parts = s.split("@");
  if (parts.length !== 2) return null;
  const [local, domain] = parts;

  if (!local || local.length > MAX_LOCAL_PART_LENGTH) return null;
  if (!_LOCAL_PART_RE.test(local)) return null;

  if (!domain) return null;
  if (domain.startsWith(".") || domain.endsWith(".")) return null;
  if (domain.includes("..")) return null;
  if (!domain.includes(".")) return null;

  const labels = domain.split(".");
  for (const label of labels) {
    if (!_DOMAIN_LABEL_RE.test(label)) return null;
  }

  // TLD must be ≥2 chars (rules out single-letter "test" TLDs
  // and the bare hostname case).
  if ((labels[labels.length - 1] ?? "").length < 2) return null;

  return `${local.toLowerCase()}@${domain.toLowerCase()}`;
}


/** True iff `parseEmail(input)` returns non-null. */
export function isValidEmail(input: string | null | undefined): boolean {
  return parseEmail(input) !== null;
}


/** Return the lowercased domain part or null if invalid. Used
 *  by the audit row's domain-grouping aggregator. */
export function emailDomain(input: string | null | undefined): string | null {
  const parsed = parseEmail(input);
  if (parsed === null) return null;
  return parsed.split("@")[1] ?? null;
}
