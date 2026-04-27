# Public Supplier RFQ-Response Portal

When CostPulse dispatches an RFQ, each supplier gets an email with a
**unique signed link** that opens a no-auth response page. They never log
into the platform — the token in `?t=` is the entire authn surface.

This doc covers the trust model, the wire shapes on both endpoints, the
token semantics, the rate limiter, and the front-end's i18n. If you are
adding capabilities here, the security boundary is the JWT verifier;
everything else is UX.

---

## 1. End-to-end flow

```
buyer creates RFQ in dashboard
     │
     ▼
POST /api/v1/costpulse/rfq            (auth: dashboard JWT + X-Org-ID)
     │
     ▼
arq job: services.rfq_dispatch.dispatch_rfq
     │     for each supplier on rfq.sent_to:
     │       mint token via services.rfq_tokens.mint_response_token
     │       build URL with services.rfq_tokens.build_response_url
     │       email link via services.mailer.send_mail
     │
     ▼
supplier clicks link → loads /rfq/respond?t=<jwt> in their browser
     │
     ▼
GET  /api/v1/public/rfq/context?t=…   (no auth header, no org header)
POST /api/v1/public/rfq/respond?t=…   (no auth header, no org header)
     │
     ▼
rfq.responses[i].quote populated, rfq.status → "responded"
buyer's dashboard re-renders (RfqResponsesPanel) on next refresh
```

---

## 2. Token shape

JWT signed with the same `supabase_jwt_secret` as the dashboard, but with a
distinct `aud` claim to prevent cross-replay:

```jsonc
{
  "iss": "aec-platform",
  "aud": "rfq_response",          // ← critical: distinguishes from dashboard JWT
  "iat": 1745678400,
  "exp": 1750862400,              // ← default 60 days from mint
  "rfq_id":      "<uuid>",
  "supplier_id": "<uuid>"
}
```

`mint_response_token` and `verify_response_token` live in
`apps/api/services/rfq_tokens.py`.

**Why a separate audience?** A leaked dashboard JWT (e.g. lifted from a
log line) must NOT unlock the public endpoints, and a leaked supplier
token must NOT unlock the dashboard. PyJWT's `decode(audience=…)` enforces
this — both routers verify with their own audience and reject the other.

**Why JWT over a DB-row token?** Stateless. Revocation = expiry. If a
supplier needs a re-issue, the dispatcher just mints a new token; the old
one keeps working until expiry but lands on the same RFQ. No revocation
list to maintain, no DB read on every request.

**TTL**: 60 days. Configurable via `rfq_token_ttl_seconds` setting. Covers
the typical deadline (7–30 days) plus grace for a late supplier; tight
enough that a stolen email screen-share isn't usable months later.

---

## 3. Endpoint contracts

### `GET /api/v1/public/rfq/context?t=<token>`

Returns what the supplier sees on the response page:

```jsonc
{
  "data": {
    "organization_name": "ACME Construction",
    "project_name":      "Tower X",   // null if RFQ not linked to a project
    "estimate_name":     "Schematic v1", // null if no linked estimate
    "deadline":          "2026-05-30",
    "message":           null,        // reserved; not currently set
    "boq_digest": [
      { "description": "Bê tông C30", "material_code": "CONC_C30",
        "quantity": 120, "unit": "m3" },
      …                               // capped at 20 lines
    ],
    "submission_status": "pending",   // or "submitted"
    "submitted_quote":   null         // populated when submission_status="submitted"
  }
}
```

### `POST /api/v1/public/rfq/respond?t=<token>`

Body shape (`schemas.public_rfq.PublicRfqQuote` with `extra="forbid"`):

```jsonc
{
  "total_vnd":      "12500000",       // optional (string Decimal)
  "lead_time_days": 14,                // optional, 0..365
  "valid_until":    "2026-06-15",      // optional ISO date
  "notes":          "FOB Hanoi · NET-30",  // optional, ≤2000 chars
  "line_items": [
    {
      "material_code":   "CONC_C30",
      "description":     "Concrete C30",
      "quantity":        120,
      "unit":            "m3",
      "unit_price_vnd":  "2050000"
    }
  ]
}
```

`extra="forbid"` rejects hand-crafted fields (`evil_admin: true`) with HTTP 422
— a probing attempt becomes visible rather than silently ignored.

### Status codes

| Code | Meaning |
|---|---|
| 200 | Happy path. |
| 401 | Token failed verification (signature / audience / expiry / malformed) **or** token's supplier isn't on `rfq.sent_to`. The body never distinguishes — a hand-edited token gets the same 401 as an expired one. |
| 404 | RFQ row gone (deleted / withdrawn) or supplier hard-deleted between dispatch and response. The UI distinguishes from 401 to render "RFQ withdrawn" copy. |
| 422 | Pydantic validation failure on the submitted body. |
| 429 | Per-token rate limit exceeded (see §5). |

---

## 4. Cross-tenancy

The public endpoints use `AdminSessionFactory` (BYPASSRLS as `aec` role)
because:

- The token IS the auth — there's no JWT subject to map to an org.
- The endpoints can only mutate ONE row (`rfqs` row keyed by token's
  `rfq_id`) and only ONE field (`responses[i].quote` for the matching
  `supplier_id`). Even with full DB access, the blast radius is tiny.
- The token's `(rfq_id, supplier_id)` pair gates every read/write — a
  token for `rfq_A.supplier_X` cannot affect `rfq_B` or any other
  supplier's slot in `rfq_A`.

---

## 5. Rate limiting

`services/rate_limit.py` — thread-safe in-memory token bucket, keyed on
`sha256(raw_key)[:16]` so the raw token never lives in the bucket map
(defence in depth against process-memory dumps).

| Endpoint | Capacity | Refill window | Notes |
|---|---|---|---|
| `GET /context`  | 10 | 60 s | Refresh-loop tolerant |
| `POST /respond` | 5  | 60 s | Most suppliers POST once |

Limit fires **before** token verification — a flood of garbage tokens
can't burn `verify_jwt` cycles. 429 includes `Retry-After: 60`.

The forward of `Retry-After` lives in `core/envelope.py::http_exception_handler`
— the original platform handler stripped `exc.headers`, which silently broke
machine clients that back off based on the header. That fix is critical;
don't regress it.

**Single-replica caveat**: this is in-process state. When the API scales
horizontally, swap `_BUCKETS` for a Redis-backed implementation behind
the same `check_and_consume` interface. Tests don't care which storage
backend you use.

---

## 6. UI

The public page lives outside the `(dashboard)` route group at
`apps/web/app/rfq/respond/page.tsx`. It:

- Reads `?t=` and `?lang=` directly from `window.location` (no
  `useSearchParams` so we don't need a suspense boundary).
- Defaults to Vietnamese; `?lang=en` flips to English; toggling the
  language selector in the header updates the URL via `replaceState`.
- Pre-fills the line-item form from the buyer's BOQ digest so the
  supplier edits prices in place rather than retyping descriptions.
- After submit, re-renders inline as the confirmation card (no extra
  fetch round-trip).

Strings live in `apps/web/app/rfq/respond/i18n.ts` rather than
going through `next-intl`. The dashboard's `next-intl/request.ts`
hard-codes `vi` and the supplier portal sits outside that flow
(no session, no cookie); a self-contained dictionary is simpler.
The keys mirror the `rfq_respond.*` namespace in
`apps/web/i18n/messages/{vi,en}.json` so a future migration to
next-intl-driven public locale is a copy-and-key swap.

---

## 7. Buyer-side surface

The dashboard exposes:

- **`<RfqResponsesPanel>`** in `packages/ui/costpulse/` — per-supplier
  table sorted (responded → dispatched → bounced/skipped → pending) with
  inline quote totals + lead time + email + status badges. Mounted on
  the RFQ Manager (`/costpulse/rfq`) as an expandable per-row section.
- The buyer sees `RfqResponseEntry` typed in `packages/types/costpulse.ts`
  — no more `Record<string, unknown>` casts.

---

## 8. Tests

- `apps/api/tests/test_rfq_tokens.py` — 8 tests: roundtrip, tampered
  signature, expiry, wrong-audience, wrong-secret, malformed UUID
  claims, URL composition, trailing-slash strip.
- `apps/api/tests/test_public_rfq_router.py` — 15 tests: every status
  code on both endpoints, idempotent re-submit, slot-creation when
  dispatcher hadn't run yet, `extra="forbid"`, 429 caps, per-token
  isolation.
- `apps/api/tests/test_rate_limit.py` — 7 tests: burst caps, refill,
  per-key isolation, idle clamp, capacity-change rebuild, hash key.
- `apps/api/tests/test_e2e_public_rfq.py` — integration: real DB,
  real FastAPI app via ASGI transport, real JWT mint+verify cycle,
  real `responses[]` JSONB write-back. Skipped unless
  `DATABASE_URL_ADMIN` is set. Catches secret/audience drift across
  process boundaries that unit tests can't.

Run the unit suite with:

```
python -m pytest apps/api/tests/test_rfq_tokens.py \
                 apps/api/tests/test_public_rfq_router.py \
                 apps/api/tests/test_rate_limit.py
```

Run the E2E with a live verify DB:

```
DATABASE_URL_ADMIN="postgresql+asyncpg://aec:aec@localhost:55432/aec" \
DATABASE_URL="postgresql+asyncpg://aec_app:aec_app@localhost:55432/aec" \
python -m pytest apps/api/tests/test_e2e_public_rfq.py --integration
```
