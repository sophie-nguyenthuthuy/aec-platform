/**
 * Keyboard shortcut helper (cycle GG2, TS-only).
 *
 * Cross-platform shortcut formatter + key-event matcher. Today
 * the audit search trigger, the command palette, the audit row
 * export shortcut, and the deliveries retry-all-stuck shortcut
 * each duplicate the platform-detection logic inline. This
 * module is the single source of truth.
 *
 *   formatShortcut(shortcut, isMac)    — display string
 *   matchShortcut(event, shortcut, isMac) — bool
 *   MODIFIERS                          — closed modifier list
 *
 * Closed modifier set: `mod` (cross-platform alias for ⌘ on Mac,
 * Ctrl elsewhere), `shift`, `alt`. NO bare `meta` or `ctrl` —
 * pin the cross-platform alias `mod` so a refactor that adds a
 * Mac-only `cmd` token doesn't slip past.
 *
 * Frontend-only — no Python counterpart since shortcuts are a
 * pure DOM concern.
 *
 * Pinned invariants (see test):
 *   * `mod` resolves to `metaKey` on Mac, `ctrlKey` elsewhere.
 *   * Modifier display order: mod → shift → alt → key (regardless
 *     of input order).
 *   * Single-char keys uppercase in display ("k" → "K").
 *   * Multi-char keys preserved as-is in display ("escape" → "escape").
 *   * Mac display: no separator ("⌘⇧K"); other: "+"-separated ("Ctrl+Shift+K").
 *   * `matchShortcut` is case-insensitive on the key segment.
 */


export type Modifier = "mod" | "shift" | "alt";


/** Closed modifier list. Order is the canonical display order:
 *  mod → shift → alt → key. Pin so a refactor that re-orders
 *  doesn't surface different shortcut strings on different pages. */
export const MODIFIERS: readonly Modifier[] = ["mod", "shift", "alt"];


/** Duck-typed KeyboardEvent for testability. The standard
 *  KeyboardEvent has these properties; tests can pass plain
 *  objects without constructing real events. */
export interface KeyboardEventLike {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}


interface ParsedShortcut {
  modifiers: Set<Modifier>;
  key: string; // lowercased
}


function _parse(shortcut: string): ParsedShortcut {
  const parts = shortcut.toLowerCase().split("+").map((p) => p.trim());
  const modifiers = new Set<Modifier>();
  let key = "";
  for (const part of parts) {
    if (part === "mod" || part === "shift" || part === "alt") {
      modifiers.add(part);
    } else if (part) {
      // The non-modifier part is the key. Last one wins if
      // multiple appear (defensive — caller bug, but don't crash).
      key = part;
    }
  }
  return { modifiers, key };
}


/**
 * Format a shortcut for display in a tooltip / menu.
 *
 *   * formatShortcut("mod+k", true)        → "⌘K"
 *   * formatShortcut("mod+k", false)       → "Ctrl+K"
 *   * formatShortcut("mod+shift+k", true)  → "⌘⇧K"
 *   * formatShortcut("mod+shift+k", false) → "Ctrl+Shift+K"
 *   * formatShortcut("shift+mod+k", true)  → "⌘⇧K"  (order normalized)
 *   * formatShortcut("/", false)           → "/"
 *   * formatShortcut("mod+/", false)       → "Ctrl+/"
 */
export function formatShortcut(shortcut: string, isMac: boolean): string {
  const parsed = _parse(shortcut);
  const parts: string[] = [];

  if (parsed.modifiers.has("mod")) {
    parts.push(isMac ? "⌘" : "Ctrl");
  }
  if (parsed.modifiers.has("shift")) {
    parts.push(isMac ? "⇧" : "Shift");
  }
  if (parsed.modifiers.has("alt")) {
    parts.push(isMac ? "⌥" : "Alt");
  }

  // Display key: single chars uppercase; multi-char preserved.
  const displayKey =
    parsed.key.length === 1 ? parsed.key.toUpperCase() : parsed.key;
  parts.push(displayKey);

  // Mac display: glyphs without separator. Other: "+"-separated.
  return isMac ? parts.join("") : parts.join("+");
}


/**
 * Return true iff the given keyboard event matches the shortcut.
 *
 * Comparison rules:
 *   * `mod` matches `metaKey` on Mac, `ctrlKey` elsewhere.
 *   * Other modifiers must match exactly (event.shiftKey,
 *     event.altKey).
 *   * Key comparison is case-insensitive on `event.key`.
 *
 * Defensive: the modifier check is strict — if shortcut requires
 * `mod` but the event has `shift` too without it being declared,
 * the match returns false. This prevents accidental triggers
 * when extra modifiers are held.
 */
export function matchShortcut(
  event: KeyboardEventLike,
  shortcut: string,
  isMac: boolean = false,
): boolean {
  const parsed = _parse(shortcut);
  const modPressed = isMac ? event.metaKey : event.ctrlKey;

  if (parsed.modifiers.has("mod") !== modPressed) return false;
  if (parsed.modifiers.has("shift") !== event.shiftKey) return false;
  if (parsed.modifiers.has("alt") !== event.altKey) return false;

  return event.key.toLowerCase() === parsed.key;
}
