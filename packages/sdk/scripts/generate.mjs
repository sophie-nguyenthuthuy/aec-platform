#!/usr/bin/env node
// SDK code-generator. Fetches /openapi.json from the configured backend
// (env: AEC_OPENAPI_URL, defaults to a running local API) and emits
// `src/generated.ts` with one method per operation + types for path
// params and response envelopes.
//
// Why not `openapi-typescript-codegen`:
//   * Zero new dependencies — vanilla node, runs in CI without an
//     install step.
//   * The output we need is small (one method-per-route, no advanced
//     features like polymorphic unions). A 200-line generator that's
//     easy to read beats a black-box dependency.
//   * Drift between our envelope shape and the codegen's idea of a
//     response is easier to handle when we control the emitter.
//
// Limitations (intentional, can extend later):
//   * Body schemas: emitted as `Record<string, unknown>` since our
//     OpenAPI uses Pydantic-generated $refs that bloat the output if
//     followed. Partners writing TS will hand-shape the body — same
//     posture as the audit-log type.
//   * Path params only — no query-string typing yet.
//
// Usage:
//   AEC_OPENAPI_URL=https://api.aec-platform.vn/openapi.json node scripts/generate.mjs
//   pnpm --filter @aec/sdk run generate

import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const OUT_DIR = resolve(__dirname, "../src");
const OUT_FILE = resolve(OUT_DIR, "generated.ts");

const URL_FROM_ENV =
  process.env.AEC_OPENAPI_URL ?? "http://localhost:8000/openapi.json";


// ---------- Fetch + parse ----------

async function loadSpec() {
  // file:// + bare paths read from disk so CI can dump the spec
  // from a unit-test FastAPI app and regenerate without spinning a
  // server.
  if (URL_FROM_ENV.startsWith("file://")) {
    return JSON.parse(readFileSync(fileURLToPath(URL_FROM_ENV), "utf8"));
  }
  if (URL_FROM_ENV.startsWith("/") || URL_FROM_ENV.startsWith("./")) {
    return JSON.parse(readFileSync(URL_FROM_ENV, "utf8"));
  }
  const res = await fetch(URL_FROM_ENV);
  if (!res.ok) {
    throw new Error(`failed to fetch ${URL_FROM_ENV}: ${res.status} ${res.statusText}`);
  }
  return await res.json();
}


// ---------- Helpers ----------

function methodNameFor(method, path, operationId) {
  // Prefer FastAPI's `operationId` (auto-generated, e.g.
  // "list_api_keys_api_v1_api_keys_get"). Fall back to verb+path
  // when missing.
  if (operationId) {
    // FastAPI suffixes with the route shape — strip the verb tail
    // and underscores around the path segments, leave the verb
    // prefix.
    return operationId.replace(/[^a-zA-Z0-9_]/g, "_");
  }
  const cleanedPath = path
    .replace(/^\/api\/v1\//, "")
    .replace(/\{[^}]+\}/g, "by_param")
    .replace(/[/-]/g, "_");
  return `${method.toLowerCase()}_${cleanedPath}`;
}

function pathParamNamesIn(path) {
  return [...path.matchAll(/\{([^}]+)\}/g)].map((m) => m[1]);
}

function buildPathExpression(path) {
  // `/foo/{id}` → "`/foo/${params.id}`" (template literal body).
  return path.replace(/\{([^}]+)\}/g, "${params.$1}");
}


// ---------- Emit ----------

function emit(spec) {
  const lines = [];
  lines.push("/* eslint-disable */");
  lines.push("/**");
  lines.push(" * Auto-generated. DO NOT EDIT — re-run `pnpm --filter @aec/sdk run generate`");
  lines.push(" * after backend deploys.");
  lines.push(" *");
  // Stable source identifier — NOT the runtime AEC_OPENAPI_URL, which
  // varies between local-dev / CI / committed-snapshot invocations and
  // would cause the drift-check (`scripts/drift-check.mjs`) to fail
  // purely on the header line whenever the env differs across runs.
  // The committed file is the canonical artefact; the URL it was last
  // generated from is operational, not part of the contract.
  lines.push(" * Source: AEC Platform OpenAPI snapshot");
  lines.push(` * API title: ${spec.info?.title ?? "(unknown)"}`);
  lines.push(` * API version: ${spec.info?.version ?? "(unknown)"}`);
  lines.push(" */");
  lines.push("");
  lines.push("import type { AecClientCore } from \"./client\";");
  lines.push("");
  lines.push("export interface Operations {");
  // Pre-declare the method registry so call sites can typecheck
  // method names without running the SDK.

  const methods = [];
  const paths = spec.paths ?? {};
  for (const [path, item] of Object.entries(paths)) {
    for (const method of ["get", "post", "patch", "delete", "put"]) {
      const op = item[method];
      if (!op) continue;
      const name = methodNameFor(method, path, op.operationId);
      const pathParams = pathParamNamesIn(path);
      const summary = (op.summary ?? "").replace(/\*\//g, "*\\/");
      methods.push({ name, method: method.toUpperCase(), path, pathParams, summary });
    }
  }

  for (const m of methods) {
    const paramsType = m.pathParams.length > 0
      ? `{ ${m.pathParams.map((p) => `${p}: string | number`).join("; ")} }`
      : "Record<string, never>";
    lines.push(`  /** ${m.summary || `${m.method} ${m.path}`} */`);
    lines.push(`  ${m.name}: { params: ${paramsType}; method: "${m.method}"; path: string };`);
  }
  lines.push("}");
  lines.push("");

  // Emit one method per operation. Each is a thin wrapper around the
  // shared `AecClientCore.request` so retry / auth / error mapping
  // live in ONE place — the operations are just typed shells.
  lines.push("export function bindOperations(core: AecClientCore) {");
  lines.push("  return {");
  for (const m of methods) {
    const paramsType = m.pathParams.length > 0
      ? `{ ${m.pathParams.map((p) => `${p}: string | number`).join("; ")} }`
      : "Record<string, never>";
    const pathExpr = m.pathParams.length > 0
      ? `\`${buildPathExpression(m.path)}\``
      : `"${m.path}"`;
    const bodyArg = ["POST", "PATCH", "PUT"].includes(m.method)
      ? ", body?: unknown"
      : "";
    const bodyForward = ["POST", "PATCH", "PUT"].includes(m.method)
      ? ", body"
      : "";
    lines.push(`    /** ${m.summary || `${m.method} ${m.path}`} */`);
    lines.push(
      `    ${m.name}: (params: ${paramsType}, query?: Record<string, string | number | boolean | undefined>${bodyArg}) =>`,
    );
    lines.push(
      `      core.request<unknown>("${m.method}", ${pathExpr}, query${bodyForward}),`,
    );
  }
  lines.push("  };");
  lines.push("}");
  lines.push("");
  lines.push(`export const OPERATION_COUNT = ${methods.length};`);

  return lines.join("\n") + "\n";
}


// ---------- Main ----------

(async () => {
  console.log(`[sdk-gen] fetching ${URL_FROM_ENV}`);
  const spec = await loadSpec();
  mkdirSync(OUT_DIR, { recursive: true });
  const out = emit(spec);
  writeFileSync(OUT_FILE, out, "utf8");
  console.log(`[sdk-gen] wrote ${OUT_FILE} (${out.length} bytes)`);
})().catch((err) => {
  console.error("[sdk-gen] failed:", err);
  process.exit(1);
});
