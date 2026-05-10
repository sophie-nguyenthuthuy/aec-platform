/**
 * Email validation (cycle GG3, TS half).
 *
 * Pinned seams:
 *   1. MAX_EMAIL_LENGTH = 254 (RFC 5321).
 *   2. MAX_LOCAL_PART_LENGTH = 64.
 *   3. Lowercased canonical (storage convention).
 *   4. Whitespace stripped on parse.
 *   5. Exactly one '@' separator.
 *   6. No leading/trailing dot in local or domain.
 *   7. No consecutive dots anywhere.
 *   8. TLD must be ≥2 chars.
 *   9. Domain labels: LDH (letters, digits, hyphen, no leading/trailing hyphen).
 *  10. null / undefined / empty → null.
 */

import { describe, expect, it } from "vitest";

import {
  MAX_EMAIL_LENGTH,
  MAX_LOCAL_PART_LENGTH,
  emailDomain,
  isValidEmail,
  parseEmail,
} from "../email";


// ---------- Constants ----------


describe("limits", () => {
  it("MAX_EMAIL_LENGTH is RFC 5321 254", () => {
    expect(MAX_EMAIL_LENGTH).toBe(254);
  });

  it("MAX_LOCAL_PART_LENGTH is 64", () => {
    expect(MAX_LOCAL_PART_LENGTH).toBe(64);
  });
});


// ---------- Canonical valid emails ----------


describe("parseEmail — canonical valid", () => {
  it("parses simple email", () => {
    expect(parseEmail("user@example.com")).toBe("user@example.com");
  });

  it("parses email with dots in local part", () => {
    expect(parseEmail("user.name@example.com")).toBe("user.name@example.com");
  });

  it("parses email with plus-tag in local part", () => {
    expect(parseEmail("user+tag@example.com")).toBe("user+tag@example.com");
  });

  it("parses email with subdomain", () => {
    expect(parseEmail("user@sub.example.com")).toBe("user@sub.example.com");
  });

  it("parses VN ccTLD", () => {
    expect(parseEmail("nguyen@vnpt.vn")).toBe("nguyen@vnpt.vn");
  });

  it("parses email with hyphen in domain", () => {
    expect(parseEmail("user@my-company.com")).toBe("user@my-company.com");
  });
});


// ---------- Canonicalization ----------


describe("parseEmail — canonicalization", () => {
  it("lowercases local part and domain", () => {
    expect(parseEmail("USER@EXAMPLE.COM")).toBe("user@example.com");
  });

  it("strips leading and trailing whitespace", () => {
    expect(parseEmail("  user@example.com  ")).toBe("user@example.com");
    expect(parseEmail("\tuser@example.com\n")).toBe("user@example.com");
  });

  it("preserves internal dots and special chars after lowercasing", () => {
    expect(parseEmail("USER.NAME+TAG@example.com")).toBe(
      "user.name+tag@example.com",
    );
  });
});


// ---------- Structural rejection ----------


describe("parseEmail — structural rejection", () => {
  it("rejects missing @", () => {
    expect(parseEmail("noatsign.com")).toBeNull();
  });

  it("rejects multiple @", () => {
    expect(parseEmail("a@b@c.com")).toBeNull();
  });

  it("rejects empty local part", () => {
    expect(parseEmail("@example.com")).toBeNull();
  });

  it("rejects empty domain", () => {
    expect(parseEmail("user@")).toBeNull();
  });
});


// ---------- Local part rules ----------


describe("parseEmail — local part rules", () => {
  it("rejects leading dot in local part", () => {
    expect(parseEmail(".user@example.com")).toBeNull();
  });

  it("rejects trailing dot in local part", () => {
    expect(parseEmail("user.@example.com")).toBeNull();
  });

  it("rejects consecutive dots in local part", () => {
    expect(parseEmail("us..er@example.com")).toBeNull();
  });

  it("rejects local part over 64 chars", () => {
    const longLocal = "a".repeat(65);
    expect(parseEmail(`${longLocal}@example.com`)).toBeNull();
  });

  it("accepts local part at exactly 64 chars", () => {
    const localAt64 = "a".repeat(64);
    expect(parseEmail(`${localAt64}@example.com`)).toBe(`${localAt64}@example.com`);
  });
});


// ---------- Domain rules ----------


describe("parseEmail — domain rules", () => {
  it("rejects domain without dot (no TLD)", () => {
    expect(parseEmail("user@example")).toBeNull();
  });

  it("rejects leading dot in domain", () => {
    expect(parseEmail("user@.example.com")).toBeNull();
  });

  it("rejects trailing dot in domain", () => {
    expect(parseEmail("user@example.com.")).toBeNull();
  });

  it("rejects consecutive dots in domain", () => {
    expect(parseEmail("user@example..com")).toBeNull();
  });

  it("rejects single-char TLD", () => {
    // TLD must be ≥2 chars per RFC + ICANN policy.
    expect(parseEmail("user@example.c")).toBeNull();
  });

  it("rejects leading hyphen in domain label", () => {
    expect(parseEmail("user@-example.com")).toBeNull();
  });

  it("rejects trailing hyphen in domain label", () => {
    expect(parseEmail("user@example-.com")).toBeNull();
  });

  it("accepts hyphen in middle of domain label", () => {
    expect(parseEmail("user@my-company.com")).toBe("user@my-company.com");
  });
});


// ---------- Total length ----------


describe("parseEmail — total length", () => {
  it("rejects email over 254 chars", () => {
    // Build a 255-char email.
    const local = "a".repeat(60);
    const domain = "b".repeat(190) + ".com";
    const email = `${local}@${domain}`;
    if (email.length > MAX_EMAIL_LENGTH) {
      expect(parseEmail(email)).toBeNull();
    }
  });
});


// ---------- Defensive ----------


describe("parseEmail — defensive", () => {
  it("returns null for null / undefined / empty", () => {
    expect(parseEmail(null)).toBeNull();
    expect(parseEmail(undefined)).toBeNull();
    expect(parseEmail("")).toBeNull();
    expect(parseEmail("   ")).toBeNull();
  });
});


// ---------- isValidEmail ----------


describe("isValidEmail", () => {
  it("returns true for valid", () => {
    expect(isValidEmail("user@example.com")).toBe(true);
  });

  it("returns false for invalid", () => {
    expect(isValidEmail("invalid")).toBe(false);
    expect(isValidEmail(null)).toBe(false);
  });
});


// ---------- emailDomain ----------


describe("emailDomain", () => {
  it("extracts the domain from a valid email", () => {
    expect(emailDomain("user@example.com")).toBe("example.com");
  });

  it("lowercases the returned domain", () => {
    expect(emailDomain("user@EXAMPLE.COM")).toBe("example.com");
  });

  it("returns null for invalid input", () => {
    expect(emailDomain(null)).toBeNull();
    expect(emailDomain("invalid")).toBeNull();
  });
});
