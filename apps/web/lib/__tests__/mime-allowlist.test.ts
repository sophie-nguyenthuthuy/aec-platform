/**
 * File MIME type allowlist (cycle II2).
 *
 * Pinned seams:
 *   1. MIME_CATEGORIES = [photo, document, cad, archive].
 *   2. SVG NOT in photo (XSS guard).
 *   3. application/octet-stream rejected for ALL categories.
 *   4. HEIC accepted in photo (iPhone uploads).
 *   5. Comparison case-insensitive on type.
 *   6. MIME parameters stripped before comparison.
 *   7. null / empty → false.
 */

import { describe, expect, it } from "vitest";

import {
  MIME_ALLOWLIST,
  MIME_CATEGORIES,
  acceptedExtensions,
  isAllowedMime,
} from "../mime-allowlist";


// ---------- MIME_CATEGORIES ----------


describe("MIME_CATEGORIES", () => {
  it("is the canonical 4-category closed list", () => {
    expect(MIME_CATEGORIES).toEqual(["photo", "document", "cad", "archive"]);
  });
});


// ---------- photo category ----------


describe("isAllowedMime — photo", () => {
  it("accepts JPEG", () => {
    expect(isAllowedMime("image/jpeg", "photo")).toBe(true);
  });

  it("accepts PNG", () => {
    expect(isAllowedMime("image/png", "photo")).toBe(true);
  });

  it("accepts HEIC (iPhone uploads dominant in VN)", () => {
    // Cardinal pin: HEIC is iPhone's default photo format.
    // Rejecting it would block VN's iPhone-heavy user base.
    expect(isAllowedMime("image/heic", "photo")).toBe(true);
  });

  it("accepts WebP", () => {
    expect(isAllowedMime("image/webp", "photo")).toBe(true);
  });

  it("REJECTS SVG (XSS vector via embedded <script>)", () => {
    // Cardinal pin: SVG can carry executable JS. A refactor that
    // re-adds it would silently re-introduce an XSS path through
    // the avatar uploader.
    expect(isAllowedMime("image/svg+xml", "photo")).toBe(false);
  });

  it("REJECTS bitmap (BMP)", () => {
    expect(isAllowedMime("image/bmp", "photo")).toBe(false);
  });

  it("REJECTS GIF (out of allowlist)", () => {
    expect(isAllowedMime("image/gif", "photo")).toBe(false);
  });
});


// ---------- document category ----------


describe("isAllowedMime — document", () => {
  it("accepts PDF", () => {
    expect(isAllowedMime("application/pdf", "document")).toBe(true);
  });

  it("REJECTS Word docs (out of allowlist for now)", () => {
    expect(
      isAllowedMime("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
    ).toBe(false);
  });

  it("REJECTS plain text", () => {
    expect(isAllowedMime("text/plain", "document")).toBe(false);
  });
});


// ---------- cad category ----------


describe("isAllowedMime — cad", () => {
  it("accepts AutoCAD .dwg via application/acad", () => {
    expect(isAllowedMime("application/acad", "cad")).toBe(true);
  });

  it("accepts AutoCAD .dwg via image/vnd.dwg", () => {
    expect(isAllowedMime("image/vnd.dwg", "cad")).toBe(true);
  });

  it("accepts .dxf via application/vnd.dxf", () => {
    expect(isAllowedMime("application/vnd.dxf", "cad")).toBe(true);
  });
});


// ---------- archive category ----------


describe("isAllowedMime — archive", () => {
  it("accepts zip", () => {
    expect(isAllowedMime("application/zip", "archive")).toBe(true);
  });

  it("REJECTS rar (out of allowlist)", () => {
    expect(isAllowedMime("application/vnd.rar", "archive")).toBe(false);
  });
});


// ---------- octet-stream defense ----------


describe("isAllowedMime — octet-stream rejected universally", () => {
  it("REJECTS application/octet-stream for photo", () => {
    // Cardinal pin: type-confusion guard. A spoofed MIME of
    // `application/octet-stream` could let a malicious file
    // bypass type validation.
    expect(isAllowedMime("application/octet-stream", "photo")).toBe(false);
  });

  it("REJECTS application/octet-stream for document", () => {
    expect(isAllowedMime("application/octet-stream", "document")).toBe(false);
  });

  it("REJECTS application/octet-stream for cad", () => {
    expect(isAllowedMime("application/octet-stream", "cad")).toBe(false);
  });

  it("REJECTS application/octet-stream for archive", () => {
    expect(isAllowedMime("application/octet-stream", "archive")).toBe(false);
  });
});


// ---------- Cross-category isolation ----------


describe("isAllowedMime — cross-category isolation", () => {
  it("PDF is allowed for document but NOT photo", () => {
    expect(isAllowedMime("application/pdf", "document")).toBe(true);
    expect(isAllowedMime("application/pdf", "photo")).toBe(false);
  });

  it("JPEG is allowed for photo but NOT document", () => {
    expect(isAllowedMime("image/jpeg", "photo")).toBe(true);
    expect(isAllowedMime("image/jpeg", "document")).toBe(false);
  });
});


// ---------- Normalisation ----------


describe("isAllowedMime — normalisation", () => {
  it("is case-insensitive on type", () => {
    expect(isAllowedMime("IMAGE/JPEG", "photo")).toBe(true);
    expect(isAllowedMime("Image/Jpeg", "photo")).toBe(true);
  });

  it("strips MIME parameters", () => {
    expect(isAllowedMime("image/jpeg; charset=binary", "photo")).toBe(true);
    expect(isAllowedMime("image/jpeg;name=foo.jpg", "photo")).toBe(true);
  });

  it("strips surrounding whitespace", () => {
    expect(isAllowedMime("  image/jpeg  ", "photo")).toBe(true);
  });
});


// ---------- Defensive ----------


describe("isAllowedMime — defensive", () => {
  it("returns false for null / undefined / empty", () => {
    expect(isAllowedMime(null, "photo")).toBe(false);
    expect(isAllowedMime(undefined, "photo")).toBe(false);
    expect(isAllowedMime("", "photo")).toBe(false);
  });
});


// ---------- acceptedExtensions ----------


describe("acceptedExtensions", () => {
  it("returns photo extensions", () => {
    expect(acceptedExtensions("photo")).toEqual([
      ".jpg", ".jpeg", ".png", ".heic", ".webp",
    ]);
  });

  it("returns document extensions", () => {
    expect(acceptedExtensions("document")).toEqual([".pdf"]);
  });

  it("returns cad extensions", () => {
    expect(acceptedExtensions("cad")).toEqual([".dwg", ".dxf"]);
  });

  it("returns archive extensions", () => {
    expect(acceptedExtensions("archive")).toEqual([".zip"]);
  });
});


// ---------- Allowlist invariants ----------


describe("MIME_ALLOWLIST invariants", () => {
  it("covers every category", () => {
    for (const category of MIME_CATEGORIES) {
      expect(MIME_ALLOWLIST[category]).toBeDefined();
    }
  });

  it("photo has 4 entries", () => {
    expect(MIME_ALLOWLIST.photo.size).toBe(4);
  });

  it("no octet-stream in any category", () => {
    for (const category of MIME_CATEGORIES) {
      expect(MIME_ALLOWLIST[category].has("application/octet-stream")).toBe(false);
    }
  });

  it("no SVG in any category", () => {
    for (const category of MIME_CATEGORIES) {
      expect(MIME_ALLOWLIST[category].has("image/svg+xml")).toBe(false);
    }
  });
});
