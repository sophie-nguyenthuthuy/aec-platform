/**
 * File MIME type allowlist (cycle II2, TS half).
 *
 * Closed allowlist of MIME types per upload category. Today the
 * upload widget, the avatar uploader, and the audit-evidence
 * attach button each duplicate the type list inline with subtly
 * different MIME entries. This module is the single source of truth.
 *
 *   isAllowedMime(type, category)   — bool
 *   acceptedExtensions(category)    — for input `accept=` attribute
 *   MIME_CATEGORIES                 — closed list
 *   MIME_ALLOWLIST                  — frozen category → set of MIMEs
 *
 * Categories:
 *   * photo    — image/jpeg, image/png, image/heic, image/webp
 *   * document — application/pdf
 *   * cad      — application/acad, image/vnd.dwg, application/vnd.dxf
 *   * archive  — application/zip
 *
 * Pinned defenses:
 *   * SVG explicitly NOT in `photo` — the `image/svg+xml` MIME
 *     allows embedded `<script>` (XSS vector). Pin so a refactor
 *     that re-adds it surfaces in review.
 *   * `application/octet-stream` rejected for ALL categories —
 *     type-confusion guard against malicious uploads with a
 *     spoofed MIME.
 *   * HEIC accepted in `photo` — iPhone uploads dominant in VN.
 *
 * Pure TS. Mirrors `apps/api/services/mime_allowlist.py`.
 */


export type MimeCategory = "photo" | "document" | "cad" | "archive";


/** Closed list of upload categories. Pin via test. */
export const MIME_CATEGORIES: readonly MimeCategory[] = [
  "photo",
  "document",
  "cad",
  "archive",
];


/** Closed allowlist: category → set of accepted MIME types
 *  (lowercased). All comparisons happen against the lowercased
 *  base type (parameters stripped). */
export const MIME_ALLOWLIST: Readonly<Record<MimeCategory, ReadonlySet<string>>> = {
  photo: new Set([
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/webp",
  ]),
  document: new Set([
    "application/pdf",
  ]),
  cad: new Set([
    "application/acad",
    "image/vnd.dwg",
    "application/vnd.dxf",
  ]),
  archive: new Set([
    "application/zip",
  ]),
};


/** Accepted file extensions per category. Used for the upload
 *  widget's `accept=` attribute (which accepts both MIME types
 *  and extensions). */
const _ACCEPTED_EXTENSIONS: Readonly<Record<MimeCategory, readonly string[]>> = {
  photo: [".jpg", ".jpeg", ".png", ".heic", ".webp"],
  document: [".pdf"],
  cad: [".dwg", ".dxf"],
  archive: [".zip"],
};


/**
 * True iff the MIME type is in the allowlist for `category`.
 *
 * Defensive normalisation:
 *   * Lowercased on comparison.
 *   * Whitespace stripped.
 *   * MIME parameters stripped (`image/jpeg; charset=binary` →
 *     `image/jpeg`).
 *   * Empty / null / undefined → false.
 */
export function isAllowedMime(
  mimeType: string | null | undefined,
  category: MimeCategory,
): boolean {
  if (!mimeType) return false;
  const lower = mimeType.toLowerCase().trim();
  // Strip parameters: take only the part before any `;`.
  const baseType = (lower.split(";")[0] ?? "").trim();
  return MIME_ALLOWLIST[category].has(baseType);
}


/** File extensions accepted by `category`. Used as the
 *  `<input type="file" accept="...">` attribute value. */
export function acceptedExtensions(
  category: MimeCategory,
): readonly string[] {
  return _ACCEPTED_EXTENSIONS[category];
}
