# CODEGUARD — Regulatory & Compliance Intelligence

CODEGUARD is the AEC Platform's RAG-backed compliance assistant for
Vietnamese building codes (QCVN, TCVN, zoning law). It answers natural-
language questions, auto-scans project parameters against the relevant
code categories, and generates permit-application checklists. This doc is
the map for everything that makes that work.

If you are coming to the code cold, read this first. The architecture has
non-obvious choices (halfvec generated columns, two separate hallucination
guards, the dim-cap workaround) that are difficult to re-derive from the
code alone.

---

## 1. What it does (three product surfaces)

| Endpoint | What it does | LLM calls per request |
|----------|--------------|-----------------------|
| `POST /api/v1/codeguard/query` | Free-text Q&A over the indexed corpus, returns answer + grounded citations + related questions. | 1 HyDE expansion (cached) + 1 generation = 1–2 |
| `POST /api/v1/codeguard/query/stream` | SSE-streamed Q&A — token deltas as the LLM generates, terminal `done` event with grounded response. Same pipeline as `/query`. See §6. | 1–2 |
| `POST /api/v1/codeguard/scan`  | Audits a project against fire-safety / accessibility / structure / zoning / energy categories, returns FAIL/WARN/PASS findings with citations. | 1 generation per category (up to 5) |
| `POST /api/v1/codeguard/scan/stream` | SSE-streamed scan — per-category `category_start`/`category_done` events, terminal `done` with aggregate counts. See §6. | up to 5 |
| `POST /api/v1/codeguard/permit-checklist` | Generates a jurisdiction-specific checklist of permit documents the applicant must prepare. | 1 generation |
| `GET /api/v1/codeguard/regulations[/{id}]` | List + detail views of the indexed corpus. | 0 (DB only) |
| `GET /api/v1/codeguard/checks/{project_id}` | Audit history of `query` + `scan` calls for a project. | 0 |
| `POST /api/v1/codeguard/checks/{check_id}/mark-item` | Update a checklist item's status (done / in_progress / not_applicable). | 0 |
| `GET /api/v1/codeguard/health` | Unauthenticated dependency probe for ops tooling. Per-dep `{status, latency_ms, message}` + aggregate `ok` / `degraded` / `down`. See §7. | 0 |

Every call that produces findings or answers persists a `ComplianceCheck`
row keyed on `(organization_id, project_id)` so the audit trail is
queryable. The `regulations_referenced` array on that row links back to
every regulation cited in the response. Both the streaming and non-
streaming variants of `/query` and `/scan` write the same row shape, so
audit consumers (the history page, `GET /checks/{id}`) treat both paths
identically.

The frontend exposes five pages — query, scan, checklist, regulations,
history — all under `/codeguard/*`. See `apps/web/app/(dashboard)/codeguard/`.

Every LLM-invoking route gates on per-org token quotas (see §13). Over-
limit orgs get a structured 429 before any LLM work starts; both
`/query` and the streaming `/query/stream` (and same for scan +
permit-checklist) share the gate via `_check_quota_or_raise`. After
the LLM call succeeds, accumulated token counts are drained into the
`codeguard_org_usage` row so the next request's pre-flight check sees
real spend.

`QueryRequest` and `ScanRequest` accept an optional `as_of_date` field
(ISO date string). When supplied, retrieval is restricted to
regulations whose `effective_date <= as_of_date` and whose
`expiry_date IS NULL OR expiry_date > as_of_date` — the binding
correctness contract for compliance audits ("this 2022 project must
not be evaluated against a 2024 revision"). Default is today.

---

## 2. Data model

Five tables, all created in migration `0005_codeguard.py`:

```
regulations          ← canonical record per code (e.g. QCVN 06:2022/BXD)
  └── regulation_chunks   ← embedded sections, one row per ~1200-char chunk
                            (FK ON DELETE CASCADE — re-ingest deletes + re-embeds)

compliance_checks    ← audit row per /query or /scan call
permit_checklists    ← one row per /permit-checklist call,
                       items[] is JSONB so the UI can mark items done in place
```

Tenant-scoped tables (`compliance_checks`, `permit_checklists`) carry
`organization_id`; RLS enforces isolation — see §8.

### regulation_chunks columns of note

| Column | Type | Notes |
|--------|------|-------|
| `embedding` | `vector(3072)` | text-embedding-3-large output. Written by ingest. |
| `embedding_half` | `halfvec(3072)` | `GENERATED ALWAYS AS (embedding::halfvec) STORED`. **The HNSW index lives on this column, not `embedding`.** See §3 for why. |
| `section_ref` | `text` | e.g. "3.2.1" — the heading hierarchy from the source. |
| `content` | `text` | Verbatim chunk text. The grounding guard treats this as authoritative source. |

---

## 3. The 3072-dim halfvec workaround

pgvector's `vector` type supports any dim, but its IVFFlat and HNSW indexes
only work up to **2000 dims**. text-embedding-3-large is 3072 dims, so a
naive HNSW index on `embedding` fails to create.

The fix (migration `0009_codeguard_hnsw.py`):

```sql
-- Generated halfvec mirror — automatically populated from `embedding`.
ALTER TABLE regulation_chunks
ADD COLUMN embedding_half halfvec(3072)
GENERATED ALWAYS AS (embedding::halfvec(3072)) STORED;

-- HNSW supports halfvec up to 4000 dims (pgvector 0.7.0+).
CREATE INDEX ix_regulation_chunks_embedding_half_hnsw
ON regulation_chunks USING hnsw (embedding_half halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

`_dense_search` in `apps/ml/pipelines/codeguard.py` queries the halfvec
column via `c.embedding_half <=> CAST(:vec AS halfvec)` so the index is
hit. Querying the `vector` column instead is a sequential scan and
collapses at >5k chunks. **Never query `embedding` directly in retrieval
code.**

Mirror pattern for other modules indexing >2k-dim embeddings:
DRAWBRIDGE (`0007_drawbridge_hnsw`) does the same thing.

Requires:
- Postgres 15+
- `vector` extension at 0.7.0+ (the dev container sets this up).

---

## 4. Retrieval flow

```
                ┌─────────────────────────────────────────────┐
question  ─────▶│ _hyde_expand   (Anthropic, ~200-800ms)      │
                │   TTL-cached on (question, language).       │
                │   Cache hit → ~0ms, cache miss → LLM call.  │
                └─────────────────────────────────────────────┘
                         │  question + hyde_text
                         ▼
                ┌─────────────────────────────────────────────┐
                │ _hybrid_search                              │
                │   ├── _dense_search (pgvector HNSW halfvec) │ ─┐
                │   │     filter: r.effective_date <= as_of   │  │
                │   │     AND (r.expiry_date IS NULL          │  │
                │   │          OR r.expiry_date > as_of)      │  │
                │   └── _sparse_search (Elasticsearch BM25)   │ ─┤ asyncio.gather
                │   → _reciprocal_rank_fusion (k=60)          │ ─┘
                └─────────────────────────────────────────────┘
                         │  fused list (top_k * 3 candidates)
                         ▼
                ┌─────────────────────────────────────────────┐
                │ _rerank (cross-encoder, optional)           │
                │   bge-reranker-v2-m3 if RERANKER_ENDPOINT   │
                │   set; otherwise pass-through.              │
                └─────────────────────────────────────────────┘
                         │  top_k candidates
                         ▼
                ┌─────────────────────────────────────────────┐
                │ node_generate / streaming generator         │
                │   if candidates == [] → ABSTAIN (§5.2)      │
                │   else: Claude returns JSON →               │
                │         _ground_citations (§5.1)            │
                │   Streaming variant: yield token deltas as  │
                │   the JSON `answer` field grows; final      │
                │   `done` event carries grounded citations.  │
                └─────────────────────────────────────────────┘
                         │
                         ▼   QueryResponse
```

### HyDE cache

`_hyde_expand` is wrapped in a per-process `cachetools.TTLCache` keyed on
`(question, language)`. Defaults: 10000 entries, 1h TTL. Override via:

- `CODEGUARD_HYDE_CACHE_MAX` — max entries (LRU eviction past)
- `CODEGUARD_HYDE_CACHE_TTL_SEC` — TTL in seconds

A cache hit skips the Anthropic round-trip entirely (typically 500–800ms
saved, which is exactly the gap users see between submit and first
streamed token). Failures don't poison the cache — exceptions propagate
before the cache write.

The cache is **per-process**: multi-worker production gets N independent
caches. A shared Redis cache is a worthwhile follow-up but not required
for dev/staging or single-worker deployments. Tests use `_hyde_clear_cache()`
between cases to keep state isolated.

Sparse search returns `[]` if Elasticsearch is unreachable — the WARNING
log fires but the pipeline degrades gracefully to dense-only (RRF of
`(dense, [])` is `dense` order). For the Q&A path, dense gets the
HyDE-expanded prose for semantic surface area, but sparse gets the raw
question only — HyDE prose dilutes BM25 term signal.

### Effective-date filter

`QueryRequest.as_of_date` and `ScanRequest.as_of_date` flow through to
`_dense_search`'s WHERE clause:

```sql
AND (r.effective_date IS NULL OR r.effective_date <= :as_of)
AND (r.expiry_date IS NULL OR r.expiry_date > :as_of)
```

Default when the client omits the field: `date.today()`. NULL effective
or expiry dates are treated as "always in effect" — legacy rows without
known issue dates aren't excluded just because they pre-date the
metadata.

The sparse path doesn't currently filter by date — ES doesn't carry the
same column structure, and a stale BM25 hit on an out-of-date regulation
is naturally outranked by the dense path's fresh hits via RRF. Tightening
the sparse filter is a follow-up once the ES index mapping carries
`effective_date`.

Test coverage: `apps/ml/tests/test_codeguard_as_of_date.py` (3 Tier 1
tests pinning the SQL clause shape, default behaviour, and `_hybrid_search`
forwarding; 1 Tier 3 integration test against real Postgres seeding two
regs at different effective dates).

---

## 5. Hallucination guards

CODEGUARD has **two** distinct hallucination guards, addressing two
different failure modes. Both live in `apps/ml/pipelines/codeguard.py`.

### 5.1 Citation grounding — `_ground_citations`

**Problem:** the LLM invents authoritative-looking section refs ("QCVN
06:2022/BXD §7.4") that don't exist in the retrieved chunks, or quotes
text that doesn't appear in the source. For a compliance tool this is
the worst class of failure: the user sees a fabricated quote rendered as
authoritative.

**Solution:** every Citation is shaped from the *retrieved DB row* —
`regulation_id`, `regulation` (code_name), `section` (section_ref), and
`source_url` come from the chunk that retrieval returned. The LLM's only
provenance influence is `chunk_index`, which selects which retrieved
chunk to cite. It cannot fabricate a code name or section that wasn't
retrieved.

**Excerpt validation:** the LLM-supplied excerpt is accepted only if it's
a whitespace-collapsed, case-folded substring of the chunk content. If
not, it falls back to the chunk's first 300 chars. This preserves the UX
benefit of a focused highlight while guaranteeing the displayed quote
actually appears in the source.

**Index validation:** `chunk_index` must be a non-negative `int` (no
strings, no floats, no booleans, no negatives, no out-of-range). All
drops are logged at WARNING.

**Inline `[N]` markers (Q&A):** the prompt (`_QA_SYSTEM`) instructs the
model to emit 1-indexed `[N]` markers in the `answer` text immediately
after each factual claim, where `[N]` refers to the N-th entry of the
`citations` array. The frontend's `<AnswerWithCitations>` component (in
`packages/ui/codeguard/`) parses those markers and substitutes them with
hover-expanded chips. Out-of-range markers (LLM mis-numbered) render as
literal text, so the worst-case is "ugly bracket in the answer" — never
a popover pointing at undefined data.

**Inline `[1]` marker (scan):** the same convention applies to scan
finding descriptions, with one simplification — each `Finding` has at
most one citation, so the marker is always `[1]` referring to that
finding's own citation. The `_SCAN_SYSTEM` prompt instructs the model
to skip the marker entirely when `citation_chunk_index` is null (PASS
findings without a source). `<FindingItem>` reuses
`<AnswerWithCitations>` with `citations={citation ? [citation] : []}`,
so the same out-of-range-fallback behaviour applies — a stray `[1]` in
a citation-less finding renders as literal text.

Tests:
- `apps/ml/tests/test_codeguard_citation_grounding.py` (14 cases — guard logic)
- `apps/web/tests/e2e/codeguard-citation-markers.spec.ts` (3 cases — Q&A side)
- `apps/web/tests/e2e/codeguard-scan-markers.spec.ts` (2 cases — scan side: hover chip + no-citation literal fallback).

### 5.2 Zero-retrieval abstain — `_abstain_response`

**Problem:** when `_hybrid_search` returns `[]` (question outside the
indexed corpus, filters match nothing), the prior implementation sent an
empty `context` field to Claude, which reliably produces a confident-
sounding hallucination of an entirely fictional regulation.

**Solution:** `node_generate` checks `state.candidates` first; if empty,
returns the canned `_abstain_response(language)` without invoking the LLM
at all. Saves ~2 API calls (HyDE + generation) and ~1s of latency per
out-of-corpus query, and prevents fabrication.

**Localised messages** (`_ABSTAIN_MESSAGES`):
- `vi`: "Không tìm thấy quy định liên quan trong cơ sở tri thức CODEGUARD."
- `en`: "No relevant regulations were found in the CODEGUARD knowledge base for this question."

**UI contract:** `confidence === 0 && citations.length === 0` is the
load-bearing signal — the frontend `query/page.tsx` switches to a
distinct amber "Không có kết quả phù hợp" card on this shape.

Tests: `apps/ml/tests/test_codeguard_abstain.py` (6 cases including a
test that monkeypatches `_llm` to raise on construction, proving the
abstain path never invokes the LLM).

---

## 6. Streaming endpoints

Two streaming variants exist alongside the JSON endpoints. Both return
`text/event-stream` with `Cache-Control: no-cache` + `X-Accel-Buffering: no`
(the latter is critical for nginx; without it the proxy buffers the
whole stream and the streaming UX collapses).

### 6.1 `POST /query/stream`

Wire format:

```
event: token
data: {"delta": "<incremental text>"}

event: done
data: {"answer": "...", "confidence": 0.88, "citations": [...],
       "related_questions": [...], "check_id": "<uuid>"}

event: error
data: {"message": "..."}
```

`done` is terminal and only fires on success — the `check_id` is
populated only after the `ComplianceCheck` row is persisted, which
can't happen until the LLM finishes. `error` is also terminal; once
fired, no further events follow.

Token deltas come from `JsonOutputParser.astream()` — the parser yields
incremental dicts as the JSON parses, and we extract the `answer` field's
prefix-delta. The `citations` and `related_questions` arrive in the
`done` event so they can be grounded against the retrieved chunks
*before* shipping to the client (citation grounding can only run on a
fully-parsed citation array, not on partials).

Backend helper: `pipelines.codeguard.answer_regulation_query_stream`.
Frontend hook: `apps/web/hooks/codeguard/useQueryStream.ts`.

### 6.2 `POST /scan/stream`

Wire format:

```
event: category_start
data: {"category": "fire_safety"}

event: category_done
data: {"category": "fire_safety", "findings": [{...}, ...]}

event: done
data: {"check_id": "<uuid>", "total": N,
       "pass_count": ..., "warn_count": ..., "fail_count": ...}

event: error
data: {"message": "..."}
```

Categories yield in input order. Each category emits exactly one
`category_start` and one `category_done` regardless of retrieval/LLM
outcomes. **Per-category LLM exceptions are swallowed** — the failing
category yields zero findings rather than aborting the scan; only hard
pipeline failures surface as `error` events.

Backend helper: `pipelines.codeguard.auto_scan_project_stream`.
Frontend hook: `apps/web/hooks/codeguard/useScanStream.ts`.

### 6.3 Why the non-streaming endpoints stay

`POST /query` and `POST /scan` are kept alongside the streaming variants:
the existing router-level mock tests use them, and clients without
SSE-friendly transports (server-side rendering, batch jobs) still need
the JSON endpoints. Both paths share the same retrieval, grounding,
abstain, and persistence helpers — anything you change in those flows
lands in both surfaces simultaneously.

---

## 7. Health endpoint

`GET /api/v1/codeguard/health` is an unauthenticated dependency probe for
ops tooling — Kubernetes readiness/liveness checks, dashboards,
deployment smoke tests. Crucially does **not** call any LLM or burn any
tokens, so it's safe to probe at any frequency.

### Response shape

```json
{
  "data": {
    "status": "ok" | "degraded" | "down",
    "deps": [
      {"name": "postgres",      "status": "ok",          "latency_ms": 5,  "message": "halfvec column present"},
      {"name": "openai_key",    "status": "ok",          "latency_ms": 0,  "message": "OPENAI_API_KEY configured"},
      {"name": "anthropic_key", "status": "ok",          "latency_ms": 0,  "message": "ANTHROPIC_API_KEY configured"},
      {"name": "elasticsearch", "status": "unavailable", "latency_ms": 0,  "message": "ELASTICSEARCH_URL not configured (dense-only mode)"}
    ]
  },
  "meta": null,
  "errors": null
}
```

### Aggregate status rules

- `ok` — every required dep is `ok`. Optional deps may be `unavailable`
  (intentionally off) without changing this.
- `degraded` — required deps are `ok`, but a configured optional dep is
  `down`. Service still answers, just with reduced capability (e.g.
  ES-down means dense-only retrieval — answers degrade in quality but
  the pipeline doesn't fail).
- `down` — at least one required dep is `down`. Service should not
  answer queries; load balancers should pull this pod out of rotation.

Required deps: `postgres`, `openai_key`, `anthropic_key`. Everything else
is optional.

### What's checked

- **Postgres:** SELECTs against `information_schema.columns` for the
  presence of `regulation_chunks.embedding_half`. This is the cheapest
  proof that migration `0009_codeguard_hnsw` is applied — cheaper than
  parsing alembic state. If the column is missing, `_dense_search`
  raises on every query, so this is a real "service is broken" signal.
- **API keys:** env-var presence only. Deliberately NOT a live ping —
  pinging Anthropic/OpenAI on every probe would burn tokens proportional
  to `probe_frequency × pod_count`. Invalid-key failures surface in the
  LLM call telemetry (§10) instead.
- **Elasticsearch:** `await es.ping()` if `ELASTICSEARCH_URL` is set
  and the package is installed. `unavailable` (intentionally off) is
  distinct from `down` (configured but unreachable).

### Why no auth

Kubernetes liveness probes don't carry auth headers; forcing them
would either require a static probe token (operational drag) or
break the probe entirely. The route is intentionally outside
`require_auth`.

Tests: `apps/api/tests/test_codeguard_health.py` (6 cases — aggregate
rules, per-dep shape contract, unauthenticated route).

---

## 8. Tenant isolation (RLS)

`compliance_checks` and `permit_checklists` are tenant-scoped. Migration
`0008_codeguard_rls.py` enables RLS with `tenant_isolation_*` policies
matching the pattern used by sibling modules (pulse, costpulse, winwork,
bidradar):

```sql
CREATE POLICY tenant_isolation_compliance_checks ON compliance_checks
  USING (organization_id = current_setting('app.current_org_id', true)::uuid);
```

`TenantAwareSession` (in `apps/api/db/session.py`) sets
`app.current_org_id` per request via `SET LOCAL`. The router already
filters by `organization_id` in WHERE clauses, but RLS is defense-in-
depth — a missed filter or a future SELECT that forgets the predicate
still returns zero rows from the wrong org.

`regulations` and `regulation_chunks` are **not** tenant-scoped — they're
global reference data. All organisations share the same corpus.

---

## 9. Ingest pipeline

`apps/ml/pipelines/codeguard_ingest.py` parses PDF / TXT / MD, splits by
heading hierarchy, embeds with `text-embedding-3-large` in batches of 64,
upserts into `regulations` + `regulation_chunks`, optionally mirrors to
Elasticsearch.

### Heuristics worth knowing

- `_HEADING_RE` matches lines like `"3.2.1 Title"` or `"Điều 12. Title"`.
- `_looks_like_heading` rejects body-text false positives (lines ending
  in punctuation, lines containing commas, numeric prose like
  `"200 m², cho phép bố trí..."`).
- `_CHUNK_MIN_CHARS = 50` — sections shorter than this are dropped. Lower
  values let real but terse subsections through (§3.2.2 of the QCVN
  fixture is ~70 chars); higher values filter out incidental fragments.
- `_CHUNK_TARGET_CHARS = 1200`, `_CHUNK_MAX_CHARS = 1800` — sections
  longer than max are split along paragraph boundaries.

Tests: `apps/ml/tests/test_codeguard_ingest_parser.py` (15 cases:
parametrised heading accept/reject, fixture round-trip).

### Seeding the dev corpus

```bash
make seed-codeguard
# expands to:
# PYTHONPATH=apps/api:apps/ml python -m pipelines.codeguard_ingest \
#   --source apps/ml/fixtures/codeguard/qcvn_06_2022_excerpt.md \
#   --code "QCVN 06:2022/BXD" \
#   --country VN --jurisdiction national \
#   --category fire_safety --effective 2022-10-25 --language vi
```

`PYTHONPATH=apps/api:apps/ml` is required because the CLI imports
`db.session` (lives in apps/api) but the CLI itself is in apps/ml.

### Dry-run validation

Before burning OpenAI credits on a new PDF, validate parse quality:

```bash
PYTHONPATH=apps/api:apps/ml python -m pipelines.codeguard_ingest \
  --source path/to/new_code.pdf --code "QCVN XX:YYYY" --dry-run
```

Prints per-section `§ref lvl=N body=N chunks=M title` lines and total
chunk count. No embeddings, no DB writes, no Anthropic/OpenAI calls.

---

## 10. Test tiers

CODEGUARD has four distinct test tiers, each with different deps. Run
the right tier for the change you're making.

### Tier 1 — Unit tests (no deps)

Run on every CI commit. No Postgres, no API keys, no network.

```bash
python -m pytest \
  apps/ml/tests/test_codeguard_ingest_parser.py \
  apps/ml/tests/test_codeguard_citation_grounding.py \
  apps/ml/tests/test_codeguard_hybrid_search.py \
  apps/ml/tests/test_codeguard_abstain.py \
  apps/ml/tests/test_codeguard_hyde_cache.py \
  apps/ml/tests/test_codeguard_query_stream.py \
  apps/ml/tests/test_codeguard_scan_stream.py \
  apps/ml/tests/test_codeguard_telemetry.py
```

### Tier 2 — Router tests (no external deps)

Mock the LLM via the `mock_llm` fixture in `apps/api/tests/conftest.py`,
mock the DB via `FakeAsyncSession`. Tests HTTP wiring + persistence
shape, not pipeline internals.

```bash
python -m pytest \
  apps/api/tests/test_codeguard_query.py \
  apps/api/tests/test_codeguard_scan.py \
  apps/api/tests/test_codeguard_checklist.py \
  apps/api/tests/test_codeguard_health.py
```

### Tier 3 — Integration tests (real Postgres, no API keys)

Gated on `TEST_DATABASE_URL`. Stub the LLM via `FakeListChatModel` from
LangChain. Exercises the full pipeline against a real DB with the
halfvec column + HNSW index.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5437/aec \
  python -m pytest \
    apps/ml/tests/test_codeguard_retrieval_integration.py \
    apps/ml/tests/test_codeguard_query_pipeline_integration.py \
    apps/ml/tests/test_codeguard_scan_pipeline_integration.py
```

The dev compose stack publishes Postgres on port 5437 (not 5432) — see
`docker-compose.yml`. Apply migrations with
`docker exec aec-platform-api-1 alembic upgrade head` before first run.

### Tier 4 — Quality eval (real LLM, costs money)

Hand-curated Q&A pairs. Gated on `OPENAI_API_KEY` + `ANTHROPIC_API_KEY`
+ `TEST_DATABASE_URL`. Runs the real pipeline end-to-end against the
seeded fixture and asserts answer correctness. Catches prompt drift and
model-version regressions that mechanical tests miss. **Not** for
per-commit CI — gate on a manual or nightly job.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://aec:aec@localhost:5437/aec \
  OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... \
  python -m pytest apps/ml/tests/test_codeguard_quality_eval.py -v
```

Requires `make seed-codeguard` to have been run against the same DB.

### Tier 5 — Frontend E2E (Playwright, no API server required)

Mock the API endpoints (including SSE streams) via `page.route()`. No
real backend, no API keys. Covers query / scan / checklist / history /
inline-citation-markers flows end-to-end at the rendered-DOM level.

```bash
cd apps/web && pnpm exec playwright test tests/e2e/codeguard-*.spec.ts
```

The webServer block in `playwright.config.ts` boots `next dev` on port
3101 once per test run, so a clean clone with deps installed needs
nothing extra to run these.

---

## 11. Operational notes

- **HyDE cache:** `_hyde_expand` is wrapped in a per-process
  `cachetools.TTLCache` keyed on `(question, language)`. Defaults: 10000
  entries, 1h TTL. Override via `CODEGUARD_HYDE_CACHE_MAX` and
  `CODEGUARD_HYDE_CACHE_TTL_SEC`. Cuts Anthropic spend on repeat
  questions and trims ~500–800ms off perceived first-token latency in
  the streaming path. Per-process; multi-worker production gets N
  independent caches.
- **Reranker:** `_RERANKER_ENDPOINT` env var enables cross-encoder
  re-ranking. Without it the pipeline uses raw RRF order. For Vietnamese
  the reranker matters — bge-reranker-v2-m3 is the recommended model.
- **Elasticsearch index `regulation_chunks`:** auto-created with the
  default analyzer on first `es.index()` call. For better Vietnamese
  recall an explicit mapping with `icu_analyzer` is worth adding (out of
  scope for current work).
- **Streaming + nginx:** SSE responses set `X-Accel-Buffering: no` so
  intermediate proxies don't buffer the stream. Without it the client
  receives the entire response in one chunk and the streaming UX
  collapses. If you front the API with a different proxy, configure the
  equivalent flag.
- **Cost telemetry:** every LLM and embedding call goes through the
  `_record_llm_call` async context manager and emits a structured log
  on the `codeguard.telemetry` logger. Stable shape: `call`, `model`,
  `latency_ms`, `input_chars`, `output_chars`, `input_tokens`,
  `output_tokens`, `status`, `error`. Failures still emit (with
  `status="error"`) — a misconfigured API key shows up in the spend
  rollup, not just the error path. HyDE cache hits emit NO record
  (call didn't happen).

  Token counts come from a `_UsageCaptureHandler` (a LangChain
  `BaseCallbackHandler`) that hooks `on_llm_end` and reads
  `usage_metadata` off the AIMessage *before* the JsonOutputParser
  strips it. Each call site threads `config={"callbacks":
  rec["callbacks"]}` into `chain.ainvoke(...)` to wire it through.
  Token fields stay None for embedding calls (OpenAIEmbeddings isn't
  a chat model and doesn't fire `on_llm_end`) and for fake test
  models without `usage_metadata` — both are documented "no usage
  available" states, not bugs.

  Character counts are populated alongside as a sanity check and as
  the primary spend dimension for embeddings.

  See `docs/codeguard-telemetry.md` for the operating guide: how to
  configure JSON formatting, how to use `scripts/codeguard_spend_report.py`
  for tail-and-script rollups, and sample LogQL queries for spend +
  latency + cache hit rate dashboards.

---

## 12. Reference index

| Concern | File |
|---------|------|
| API router | `apps/api/routers/codeguard.py` |
| API schemas | `apps/api/schemas/codeguard.py` |
| ORM models | `apps/api/models/codeguard.py` |
| Pipeline (Q&A, scan, checklist) | `apps/ml/pipelines/codeguard.py` |
| Streaming pipeline helpers | Same file: `answer_regulation_query_stream`, `auto_scan_project_stream` |
| HyDE cache | Same file: `_hyde_cache`, `_hyde_clear_cache` |
| Citation grounding guard | Same file: `_ground_citations`, `_abstain_response` |
| Cost telemetry helper | Same file: `_record_llm_call`, `_UsageCaptureHandler`, `telemetry_logger` |
| Per-request accumulator | Same file: `TelemetryAccumulator`, `set_telemetry_accumulator`, `clear_telemetry_accumulator`, `get_telemetry_accumulator` |
| Quota service | `apps/api/services/codeguard_quotas.py` (`check_org_quota`, `record_org_usage`, `QuotaCheckResult`) |
| Quota wiring | `apps/api/routers/codeguard.py` (`_check_quota_or_raise`, `_with_usage_recording`) |
| Quota migration | `apps/api/alembic/versions/0023_codeguard_quotas.py` (`codeguard_org_quotas`, `codeguard_org_usage`) |
| PDF Unicode shim | `apps/api/services/_pdf_fonts.py` (`ensure_unicode_fonts`) |
| Health probe | `apps/api/routers/codeguard.py` (`_check_postgres`, `_check_api_key_env`, `_check_elasticsearch`, `_aggregate_status`) |
| Ingest CLI | `apps/ml/pipelines/codeguard_ingest.py` |
| Migrations | `apps/api/alembic/versions/0005_codeguard.py`, `0008_codeguard_rls.py`, `0009_codeguard_hnsw.py` |
| Fixture | `apps/ml/fixtures/codeguard/qcvn_06_2022_excerpt.md` |
| Frontend pages | `apps/web/app/(dashboard)/codeguard/{query,scan,checklist,regulations,history}/page.tsx` |
| Frontend hooks | `apps/web/hooks/codeguard/{useQuery,useQueryStream,useScan,useScanStream,useChecklist,useRegulations,keys}.ts` |
| UI components | `packages/ui/codeguard/{CitationCard,AnswerWithCitations,FindingItem,ChecklistItem,ComplianceScore,RegulationSearch}.tsx` |
| Shared types | `packages/ui/codeguard/types.ts` |
| Frontend E2E specs | `apps/web/tests/e2e/codeguard-{query,scan,scan-markers,checklist,history,regulations,citation-markers}.spec.ts` |
| Backend tests | `apps/ml/tests/test_codeguard_*.py` (parser, grounding, abstain, hybrid, hyde-cache, query-stream, scan-stream, telemetry, retrieval-integration, query-pipeline-integration, scan-pipeline-integration, quality-eval) + `apps/api/tests/test_codeguard_health.py` |
| Make targets | `Makefile` (`seed-codeguard`, `eval-codeguard`) |
| Spend rollup script | `scripts/codeguard_spend_report.py` |
| Telemetry operating guide | `docs/codeguard-telemetry.md` |

---

## 13. Per-org token quotas

Every LLM-invoking codeguard route (`/query`, `/query/stream`, `/scan`,
`/scan/stream`, `/permit-checklist`, `/permit-checklist/stream`) gates
on a per-org monthly cap. The story has three pieces — pre-flight
check, post-call drain, and the schema both read from.

### Schema (migration `0023_codeguard_quotas.py`)

- `codeguard_org_quotas(organization_id, monthly_input_token_limit,
  monthly_output_token_limit)` — opt-in. Missing row → unlimited.
  NULL on either dimension → unlimited on that dimension only (org pins
  on the dimension that has a number).
- `codeguard_org_usage(organization_id, period_start, input_tokens,
  output_tokens)` — running per-month counters. PK
  `(organization_id, period_start)` for clean UPSERT. `period_start` is
  the first day of the calendar month (computed server-side via
  `date_trunc('month', NOW())::date` to avoid clock-skew row splits).

### Pre-flight check — `_check_quota_or_raise`

Single LEFT JOIN against the two tables (`services.codeguard_quotas.
check_org_quota`). Each LLM-invoking route calls
`_check_quota_or_raise(db, auth.organization_id)` at entry; over-limit
orgs get a structured 429 with the binding-dimension message ("Monthly
output-token quota exceeded (210,000 / 200,000). Contact admin to
raise the cap.") before any LLM work starts. Streaming routes call it
*before* constructing the StreamingResponse so the 429 is a clean
HTTP response, not an SSE error frame.

### Post-call drain — `_with_usage_recording`

The pre-flight check is only useful if the usage table actually fills.
Every LLM-invoking route wraps its pipeline call (or its SSE generator
body) in `_with_usage_recording(db, organization_id)` — an async
context manager that:

1. Allocates a `TelemetryAccumulator` and binds it via the pipeline's
   `set_telemetry_accumulator` contextvar. The accumulator propagates
   through all `await` boundaries the pipeline uses, including async
   generators for SSE.
2. Lets the pipeline run. Every successful `_record_llm_call` site
   (HyDE, generation, scan-per-category, checklist generation) feeds
   `handler.input_tokens` / `handler.output_tokens` into the bound
   accumulator.
3. On exit, persists the accumulated totals via
   `services.codeguard_quotas.record_org_usage` — a single UPSERT
   against `(org_id, period_start)`. The next request's pre-flight
   check sees the increment.

Best-effort write: a transient DB hiccup during `record_org_usage` is
logged at WARNING and swallowed. Failing the user's already-served
response because bookkeeping failed would be the wrong tradeoff —
worst case is one request's worth of under-counted spend.

### Why not a FastAPI dependency

Streaming routes return a `StreamingResponse` whose generator runs
*after* a `dependencies=[Depends(...)]` would yield. The accumulator
drain has to happen after the generator finishes (the LLM calls happen
inside the generator), which means the route owns the `async with`.
Putting it in a dep would drain too early — every streaming request's
counter would be 0.

### Test coverage

`apps/api/tests/test_codeguard_quotas.py`:

- Tier 1: 8 tests for `check_org_quota` (NULL semantics, both-dimension
  binding, no-row → unlimited, no-usage-row → 0 used) + 2 for
  `record_org_usage` (zero-token short-circuit, UPSERT param shape).
- Tier 2 route: 1 dedicated `/query` 429 test, 1 parametrised
  cross-route test that asserts every other LLM-invoking surface also
  gates on the same 429 — pin the cross-route contract so a regression
  dropping `_check_quota_or_raise` from one route is caught by name.
- Tier 2 drain: 1 test that proves
  `_with_usage_recording` actually fires `record_org_usage` with
  non-zero tokens (the contract that was silently broken before this
  round — the previous wiring called `record_org_usage(in_tok=...,
  out_tok=...)` with kwarg names that didn't match the function's
  signature, so every call raised `TypeError` and got swallowed).

## 14. Quotas — Operations runbook

This section is the operator's surface for the quota story. Sections
1–13 above describe what's there and why; this one is "you got paged
at 2am, what do you do."

### 14.1 The CLI: `scripts/codeguard_quotas.py`

Five subcommands. All read `DATABASE_URL` (asyncpg form) — the same
env var the API server uses, so running locally hits the same DB the
API pod will read.

```bash
# Set or update an org's monthly cap. Either limit can be omitted
# (NULL = unlimited on that dimension); both omitted = unlimited.
python scripts/codeguard_quotas.py set <org-uuid> \
  --input-limit 5000000 --output-limit 1000000 \
  --actor "$USER"

# Show one org's quota row + current-month usage with %-of-cap.
python scripts/codeguard_quotas.py get <org-uuid>

# List all orgs with quotas, sorted by binding %. `--over-pct 80`
# filters to the at-risk cohort (the ops dashboard view).
python scripts/codeguard_quotas.py list --over-pct 80

# Zero an org's current-month usage row. Use for billing disputes
# or cleanup after a load test. The QUOTA itself is untouched —
# only the running totals are reset. Requires `--confirm` so a
# fat-fingered command in shell history can't zero a customer's
# spend by accident.
python scripts/codeguard_quotas.py reset <org-uuid> --confirm \
  --actor "$USER"

# Read the audit log for one org, most-recent first. `--since`
# filters to a date range, `--action` to one mutation type.
python scripts/codeguard_quotas.py audit <org-uuid> \
  --since 2026-04-01 --action quota_set --limit 50
```

Mutating subcommands (`set`, `reset`) write to
`codeguard_quota_audit_log` in the same transaction as the
operation. The `actor` field defaults to `$USER`; override with
`--actor` for service-account runs (CI bots, shared ops boxes).
`--json` (top-level flag, before the subcommand) flips every
subcommand to machine-readable output for piping into `jq`.

`set` ALSO fires `check_and_notify_thresholds` after commit — covers
the "ops lowers a cap below current usage and nobody hits an LLM
route to trigger the usage-side check" edge case. The dedupe table
prevents a double-fire if the org happens to also cross via usage in
the same period.

### 14.2 Threshold notifications (80% / 95%)

When an org's monthly usage crosses 80% (warn) or 95% (critical) on
either dimension, every user opted into `notification_preferences.
key='quota_warn'` for that org gets pinged — once per `(org,
dimension, threshold, period)` thanks to the dedupe table at
`codeguard_quota_threshold_notifications` (added in migration
`0030_codeguard_quota_thresholds`).

Per-channel intent:

- `email_enabled=TRUE` → email via `services.mailer.send_mail`
  (vi-VN copy, absolute URL pointing at `<WEB_BASE_URL>/codeguard/quota`).
- `slack_enabled=TRUE` → POST to `OPS_SLACK_WEBHOOK_URL` via
  `services.slack.send_slack`. Currently fires AT MOST ONCE per
  event regardless of how many users opted in (single global
  webhook). Per-user Slack DMs are a future feature.
- both flags TRUE → both channels fire.
- both flags FALSE → user filtered out at the SQL level.

Opt a user in:

```sql
INSERT INTO notification_preferences
  (user_id, organization_id, key, email_enabled, slack_enabled)
VALUES
  ('<user-uuid>', '<org-uuid>', 'quota_warn', TRUE, TRUE);
```

Or via the UI: `/settings/notifications` → CODEGUARD section
(once that page surfaces the `quota_warn` row).

If finance complains "I'm not getting the alerts": (1) confirm a
row exists with `key='quota_warn'` and at least one channel
enabled, (2) confirm `OPS_SLACK_WEBHOOK_URL` is set if they
expected Slack, (3) check the dedupe table — they may have
already received the alert this period:

```sql
SELECT * FROM codeguard_quota_threshold_notifications
WHERE organization_id = '<org-uuid>'
  AND period_start = date_trunc('month', NOW())::date;
```

### 14.3 The `/metrics` series

Two cap-check metrics flow through the existing `/metrics` scrape
(stdlib renderer in `core.metrics`, not the `prometheus_client`
SDK). Both have bounded label cardinality — safe to leave on
every LLM route.

- **`codeguard_quota_429_total{limit_kind}`** — counter, ticks once
  per cap-check refusal labelled by binding dimension (`input` |
  `output`). Use this to answer "how often are we capping out
  tenants today" without grepping logs.

  ```promql
  # Refusals per minute, broken out by dimension:
  sum by (limit_kind) (rate(codeguard_quota_429_total[1m]))
  ```

- **`codeguard_quota_check_duration_seconds`** — histogram, observes
  the pre-flight SELECT on every cap-check (allow OR refuse). Use
  this to answer "is the cap-check inflating p95 on LLM routes?"

  ```promql
  # p99 cap-check latency:
  histogram_quantile(0.99,
    rate(codeguard_quota_check_duration_seconds_bucket[5m]))
  ```

Neither metric carries an `org_id` label — per-org cardinality
would explode the series count once the platform scales. For "which
orgs cap most," query the audit log (`scripts/codeguard_quotas.py
audit ...`), not Prometheus.

### 14.4 The 429 client contract

Every LLM-invoking route returns this error envelope on cap-out:

```json
{
  "data": null,
  "meta": null,
  "errors": [{
    "code": "429",
    "message": "Đã vượt hạn mức token output tháng này (210.000 / 200.000). Liên hệ quản trị để tăng hạn mức.",
    "field": null,
    "details_url": "/codeguard/quota"
  }]
}
```

Notes:

- Copy is Vietnamese, numbers use vi-VN dot grouping. Matches
  what the `<QuotaStatusBanner>` and `/codeguard/quota` page
  surface in the surrounding UI.
- `details_url` is what the frontend reads to render a "Xem hạn
  mức" CTA on the toast / inline error. The CTA is a relative
  link inside the app — do NOT hardcode the host on the client
  side; the field is structured precisely so the API owns this.
- The dimension label (`input` / `output`) is rendered as-is, not
  translated, so it matches the banner copy elsewhere ("hạn mức
  input").

### 14.5 Billing-dispute runbook (3 steps)

Customer claims they were charged for traffic that never reached
their endpoint. Walk through the audit + reset path:

1. **Audit-log lookup** — confirm what happened on their org:

   ```bash
   python scripts/codeguard_quotas.py audit <org-uuid> \
     --since 2026-05-01 --json | jq .
   ```

   Look for unexpected `quota_set` events (someone raised the cap
   without notice?) or anomalous `quota_reset` events.

2. **Reset usage** — zero the running counters for the current
   period. The QUOTA stays put; only `codeguard_org_usage` for the
   current month is affected:

   ```bash
   python scripts/codeguard_quotas.py reset <org-uuid> --confirm \
     --actor "ops-billing-dispute-${TICKET_ID}"
   ```

   The `--actor` field is free-text — use it to pin the audit-log
   trail to a specific support ticket so compliance can answer "why
   did we zero this org" later.

3. **Verify in the audit log** — confirm the reset row appears:

   ```bash
   python scripts/codeguard_quotas.py audit <org-uuid> \
     --action quota_reset --limit 5
   ```

   Should show your reset event at the top, with `before` capturing
   the pre-zero totals (the evidence the customer was charged for)
   and `after` showing zeros.

If the customer also wants the cap raised: chain `set` after the
reset, with a separate `--actor` so the two events are attributable
independently.

### 14.6 Migration index

| Migration | Adds |
| --- | --- |
| `0023_codeguard_quotas` | `codeguard_org_quotas` + `codeguard_org_usage` |
| `0026_codeguard_quota_audit_log` | `codeguard_quota_audit_log` (JSONB before/after, FK SET NULL) |
| `0030_codeguard_quota_thresholds` | `codeguard_quota_threshold_notifications` (dedupe, FK CASCADE) |

All three use FK relationships with `organizations.id` but with
intentionally different deletion behaviour: usage CASCADE (clean up
running counters), audit log SET NULL (preserve paper trail),
notification dedupe CASCADE (operational state only).
