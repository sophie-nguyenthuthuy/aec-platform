/**
 * OpenAPI ↔ hand-written TS types drift check.
 *
 * The bug class
 * -------------
 * `apps/api/tests/openapi.snapshot.json` is the source of truth for
 * the API contract. The TS types in `packages/types/*.ts` are
 * hand-written. Today there's no test that they match — someone can
 * add a column to a Pydantic model, regenerate the OpenAPI snapshot,
 * and forget to update the TS side. Runtime tests pass because the
 * new field just shows up as `undefined` on the client; the bug
 * surfaces weeks later when somebody references `task.foo` and gets
 * a confusing "Property 'foo' does not exist on type 'Task'" error
 * the TS server stubbornly insists on, even though the API has been
 * sending `foo` the whole time.
 *
 * Mechanism
 * ---------
 * For a curated set of `(OpenAPI schema name, TS interface name)`
 * pairs, compare the property-name SETS. We don't compare types —
 * Pydantic's `int | None` ↔ TS `number | null` ↔ `nullable: true`
 * has too many false-positive shapes (`anyOf` vs `oneOf`, `format:
 * uuid` vs `string`, etc.) to be useful at this granularity. Type
 * comparison is the next ratchet — start with field-name parity,
 * which already kills the 80% bug case ("you forgot to add the
 * column to TS").
 *
 * Why a curated list rather than every-schema-checked
 * ---------------------------------------------------
 * The OpenAPI snapshot has 253 schemas; our TS types cover ~50.
 * The remaining 200+ are request/response shapes that the
 * Pydantic-on-the-wire side owns and the TS side doesn't model
 * (e.g. internal admin endpoints, idempotency wrappers, validation
 * envelopes that the TS client unwraps before the user-facing
 * code sees them). Checking all 253 would force us to either:
 *   * Stub out 200+ TS interfaces we don't need, OR
 *   * Allowlist 200+ schemas, which is the same as not checking.
 *
 * The curated list is the schemas where the TS side IS the client
 * model: domain entities (Task, ChangeOrder, MeetingNote, …) and
 * their request bodies (TaskCreate, ProposalGenerateRequest, …).
 * Add new entries here as new domain modules ship TS types.
 *
 * Allowed asymmetries
 * -------------------
 * `extra_ts_fields` per pair: TS-side fields that aren't in the
 * OpenAPI schema. Used for client-only convenience properties
 * (e.g. derived flags computed on render). Empty by default —
 * the common case is exact parity.
 *
 * `extra_openapi_fields`: OpenAPI fields that aren't in the TS
 * interface. Used for fields the TS client deliberately doesn't
 * surface (e.g. internal bookkeeping fields the API returns but
 * the UI ignores). Also empty by default.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as ts from "typescript";
import { describe, expect, test } from "vitest";

interface SchemaPair {
  /** Key in `components.schemas` of the OpenAPI snapshot. */
  openapi: string;
  /** Path to the TS file (from repo root) and interface name. */
  ts_file: string;
  ts_interface: string;
  /** Field names that legitimately exist on the TS side but not in OpenAPI. */
  extra_ts_fields?: string[];
  /** Field names that legitimately exist in OpenAPI but not on the TS side. */
  extra_openapi_fields?: string[];
}

/**
 * The pairs to check. Keep this list ordered by domain module —
 * makes it easy to spot when a new module's TS types went un-pinned.
 */
const PAIRS: SchemaPair[] = [
  // ---------- pulse ----------
  { openapi: "Task", ts_file: "packages/types/pulse.ts", ts_interface: "Task" },
  {
    openapi: "TaskCreate",
    ts_file: "packages/types/pulse.ts",
    ts_interface: "TaskCreate",
  },
  {
    openapi: "ChangeOrder",
    ts_file: "packages/types/pulse.ts",
    ts_interface: "ChangeOrder",
  },
  {
    openapi: "MeetingNote",
    ts_file: "packages/types/pulse.ts",
    ts_interface: "MeetingNote",
  },
  // ---------- winwork ----------
  {
    openapi: "ProposalGenerateRequest",
    ts_file: "packages/types/winwork.ts",
    ts_interface: "ProposalGenerateRequest",
  },
];

const REPO_ROOT = resolve(__dirname, "../../../..");
const SNAPSHOT_PATH = resolve(
  REPO_ROOT,
  "apps/api/tests/openapi.snapshot.json",
);

interface OpenAPISnapshot {
  components: { schemas: Record<string, OpenAPISchema> };
}
interface OpenAPISchema {
  properties?: Record<string, unknown>;
}

function loadSnapshot(): OpenAPISnapshot {
  const raw = readFileSync(SNAPSHOT_PATH, "utf-8");
  return JSON.parse(raw) as OpenAPISnapshot;
}

/**
 * Extract property names from a TS interface declaration via the
 * official compiler API. Robust against:
 *   * Multi-line property types (`foo:\n  | "a"\n  | "b";`)
 *   * Index signatures (skipped — they're not "fields")
 *   * Nested object types (we only collect TOP-level property names)
 *   * Method signatures (these don't appear in our type files but
 *     the visitor handles them gracefully if they do)
 *
 * Throws if the interface isn't found — the test reports that as a
 * concrete failure, which is the right signal (someone renamed the
 * interface but didn't update PAIRS).
 */
function tsInterfaceFieldNames(filePath: string, name: string): Set<string> {
  const src = readFileSync(filePath, "utf-8");
  const sf = ts.createSourceFile(
    filePath,
    src,
    ts.ScriptTarget.ES2022,
    /* setParentNodes */ true,
    ts.ScriptKind.TS,
  );

  const fields = new Set<string>();
  let found = false;

  function visit(node: ts.Node) {
    if (ts.isInterfaceDeclaration(node) && node.name.text === name) {
      found = true;
      for (const member of node.members) {
        if (ts.isPropertySignature(member) && ts.isIdentifier(member.name)) {
          fields.add(member.name.text);
        }
      }
      return; // Don't recurse into the interface body.
    }
    ts.forEachChild(node, visit);
  }
  ts.forEachChild(sf, visit);

  if (!found) {
    throw new Error(
      `Interface '${name}' not found in ${filePath}. ` +
        "Did someone rename it? Update the entry in PAIRS.",
    );
  }
  return fields;
}

describe("OpenAPI ↔ TS types drift", () => {
  const snapshot = loadSnapshot();

  for (const pair of PAIRS) {
    test(`${pair.openapi} ↔ ${pair.ts_interface}`, () => {
      const oaSchema = snapshot.components.schemas[pair.openapi];
      if (!oaSchema) {
        throw new Error(
          `OpenAPI schema '${pair.openapi}' not found in snapshot. ` +
            "Either the schema was renamed in apps/api/, or the snapshot " +
            "needs regeneration (SNAPSHOT_UPDATE=1 pytest tests/test_openapi_snapshot.py).",
        );
      }
      const oaFields = new Set(Object.keys(oaSchema.properties ?? {}));

      const tsFields = tsInterfaceFieldNames(
        resolve(REPO_ROOT, pair.ts_file),
        pair.ts_interface,
      );

      // Apply allowlists.
      const allowedTSExtras = new Set(pair.extra_ts_fields ?? []);
      const allowedOAExtras = new Set(pair.extra_openapi_fields ?? []);

      const onlyInTS = [...tsFields].filter(
        (f) => !oaFields.has(f) && !allowedTSExtras.has(f),
      );
      const onlyInOA = [...oaFields].filter(
        (f) => !tsFields.has(f) && !allowedOAExtras.has(f),
      );

      // Format failures with concrete remediation hints. The drift
      // direction matters — the fix is different in each case.
      const errors: string[] = [];
      if (onlyInTS.length > 0) {
        errors.push(
          `TS interface '${pair.ts_interface}' has fields the OpenAPI schema doesn't: ${onlyInTS.join(", ")}.\n` +
            "  → Either remove them from the TS interface (the API isn't sending them), " +
            "or add them to `extra_ts_fields` if they're computed client-side.",
        );
      }
      if (onlyInOA.length > 0) {
        errors.push(
          `OpenAPI schema '${pair.openapi}' has fields the TS interface doesn't: ${onlyInOA.join(", ")}.\n` +
            "  → Either add them to the TS interface (the API IS sending them and the UI is ignoring them), " +
            "or add them to `extra_openapi_fields` if the UI deliberately doesn't surface them.",
        );
      }

      expect(errors, errors.join("\n\n")).toEqual([]);
    });
  }

  test("snapshot file exists and is loadable", () => {
    // Defensive: if the snapshot file moved or got truncated by a
    // botched merge, the per-pair tests would all fail with the
    // same "not found" message, which is noisy. This single test
    // surfaces the root cause.
    expect(snapshot.components.schemas).toBeDefined();
    expect(Object.keys(snapshot.components.schemas).length).toBeGreaterThan(50);
  });
});
