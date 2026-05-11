/**
 * Keyboard shortcut helper (cycle GG2).
 *
 * Pinned seams:
 *   1. MODIFIERS = ["mod", "shift", "alt"] (closed, ordered).
 *   2. `mod` → ⌘ on Mac, Ctrl elsewhere.
 *   3. Display order: mod → shift → alt → key (regardless of input).
 *   4. Mac display: no separator; other: "+"-separated.
 *   5. Single-char keys uppercase in display.
 *   6. matchShortcut: case-insensitive on key.
 *   7. matchShortcut: strict modifier check (extra modifiers fail match).
 */

import { describe, expect, it } from "vitest";

import {
  type KeyboardEventLike,
  MODIFIERS,
  formatShortcut,
  matchShortcut,
} from "../keyboard-shortcut";


function _ev(overrides: Partial<KeyboardEventLike> = {}): KeyboardEventLike {
  return {
    key: "",
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    ...overrides,
  };
}


// ---------- Constants ----------


describe("MODIFIERS", () => {
  it("is the canonical 3-modifier closed list in display order", () => {
    expect(MODIFIERS).toEqual(["mod", "shift", "alt"]);
  });

  it("does not include bare 'meta' or 'ctrl' (use 'mod' instead)", () => {
    // Pin: 'mod' is the cross-platform alias. A Mac-only 'cmd'
    // token would diverge between OSs.
    expect(MODIFIERS).not.toContain("meta" as never);
    expect(MODIFIERS).not.toContain("ctrl" as never);
  });
});


// ---------- formatShortcut — Mac ----------


describe("formatShortcut — Mac", () => {
  it("renders mod as ⌘", () => {
    expect(formatShortcut("mod+k", true)).toBe("⌘K");
  });

  it("renders shift as ⇧", () => {
    expect(formatShortcut("shift+k", true)).toBe("⇧K");
  });

  it("renders alt as ⌥", () => {
    expect(formatShortcut("alt+k", true)).toBe("⌥K");
  });

  it("combines modifiers in canonical order regardless of input order", () => {
    // Display order is always mod → shift → alt regardless of
    // how user typed them.
    expect(formatShortcut("mod+shift+k", true)).toBe("⌘⇧K");
    expect(formatShortcut("shift+mod+k", true)).toBe("⌘⇧K");
    expect(formatShortcut("alt+mod+shift+k", true)).toBe("⌘⇧⌥K");
  });

  it("uses no separator on Mac", () => {
    expect(formatShortcut("mod+shift+k", true)).not.toContain("+");
  });

  it("uppercases single-char keys", () => {
    expect(formatShortcut("mod+k", true)).toBe("⌘K");
    expect(formatShortcut("mod+a", true)).toBe("⌘A");
  });

  it("preserves multi-char key names", () => {
    expect(formatShortcut("mod+escape", true)).toBe("⌘escape");
    expect(formatShortcut("mod+enter", true)).toBe("⌘enter");
  });

  it("renders literal slash as '/' (not arrow)", () => {
    expect(formatShortcut("mod+/", true)).toBe("⌘/");
    expect(formatShortcut("/", true)).toBe("/");
  });
});


// ---------- formatShortcut — Windows / Linux ----------


describe("formatShortcut — non-Mac", () => {
  it("renders mod as Ctrl", () => {
    expect(formatShortcut("mod+k", false)).toBe("Ctrl+K");
  });

  it("renders shift as Shift", () => {
    expect(formatShortcut("shift+k", false)).toBe("Shift+K");
  });

  it("renders alt as Alt", () => {
    expect(formatShortcut("alt+k", false)).toBe("Alt+K");
  });

  it("combines modifiers with '+' separator", () => {
    expect(formatShortcut("mod+shift+k", false)).toBe("Ctrl+Shift+K");
    expect(formatShortcut("shift+mod+k", false)).toBe("Ctrl+Shift+K");
  });

  it("renders literal slash with '+' separator", () => {
    expect(formatShortcut("mod+/", false)).toBe("Ctrl+/");
  });
});


// ---------- matchShortcut — Mac vs non-Mac ----------


describe("matchShortcut — Mac mod resolves to metaKey", () => {
  it("matches when metaKey pressed", () => {
    const ev = _ev({ key: "k", metaKey: true });
    expect(matchShortcut(ev, "mod+k", true)).toBe(true);
  });

  it("does NOT match when only ctrlKey pressed (Mac)", () => {
    // Pin: on Mac, mod is metaKey. ctrlKey is not the alias.
    const ev = _ev({ key: "k", ctrlKey: true });
    expect(matchShortcut(ev, "mod+k", true)).toBe(false);
  });
});


describe("matchShortcut — non-Mac mod resolves to ctrlKey", () => {
  it("matches when ctrlKey pressed", () => {
    const ev = _ev({ key: "k", ctrlKey: true });
    expect(matchShortcut(ev, "mod+k", false)).toBe(true);
  });

  it("does NOT match when only metaKey pressed (non-Mac)", () => {
    const ev = _ev({ key: "k", metaKey: true });
    expect(matchShortcut(ev, "mod+k", false)).toBe(false);
  });
});


// ---------- matchShortcut — modifiers ----------


describe("matchShortcut — modifier strictness", () => {
  it("matches multi-modifier shortcut", () => {
    const ev = _ev({ key: "k", ctrlKey: true, shiftKey: true });
    expect(matchShortcut(ev, "mod+shift+k", false)).toBe(true);
  });

  it("does NOT match when extra modifier pressed", () => {
    // Pin strict: an unspecified modifier in the event fails
    // the match. Defends against accidental triggers when the
    // user is holding extra keys.
    const ev = _ev({ key: "k", ctrlKey: true, shiftKey: true });
    expect(matchShortcut(ev, "mod+k", false)).toBe(false);
  });

  it("does NOT match when missing required modifier", () => {
    const ev = _ev({ key: "k" });
    expect(matchShortcut(ev, "mod+k", false)).toBe(false);
  });

  it("matches plain key with no modifiers", () => {
    const ev = _ev({ key: "/" });
    expect(matchShortcut(ev, "/", false)).toBe(true);
  });
});


// ---------- matchShortcut — key comparison ----------


describe("matchShortcut — case-insensitive key", () => {
  it("matches uppercase event.key against lowercase shortcut", () => {
    // Shift+K produces event.key="K"; the shortcut is "mod+shift+k".
    const ev = _ev({ key: "K", ctrlKey: true, shiftKey: true });
    expect(matchShortcut(ev, "mod+shift+k", false)).toBe(true);
  });

  it("matches multi-char named keys", () => {
    const ev = _ev({ key: "Escape" });
    expect(matchShortcut(ev, "escape", false)).toBe(true);
  });

  it("does NOT match different key", () => {
    const ev = _ev({ key: "k", ctrlKey: true });
    expect(matchShortcut(ev, "mod+j", false)).toBe(false);
  });
});


// ---------- Round-trip: format vs match ----------


describe("matchShortcut — round-trip with format input", () => {
  it("the same shortcut string parses identically for both functions", () => {
    // A user-facing shortcut "mod+shift+k" should both display
    // correctly AND match the event the user produces by pressing
    // the displayed combo.
    const shortcut = "mod+shift+k";
    expect(formatShortcut(shortcut, false)).toBe("Ctrl+Shift+K");
    const ev = _ev({ key: "K", ctrlKey: true, shiftKey: true });
    expect(matchShortcut(ev, shortcut, false)).toBe(true);
  });
});
