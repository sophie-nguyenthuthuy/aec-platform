# Runbook: API key lifecycle

The complete operator-facing playbook for the partner API-key
surface — mint, list, rotate, revoke, plus the unused-key
detection that has its own
[runbook-api-keys-unused.md](runbook-api-keys-unused.md).

## Surface overview

The API-keys settings page (`/settings/api-keys`) is the
admin-only surface where org admins create and manage the keys
their integration partners use to call our API. Three orthogonal
concerns:

| Concern        | Where in the UI                | Endpoint                                     |
| -------------- | ------------------------------ | -------------------------------------------- |
| Mint a new key | "Create key" button + form     | `POST /api/v1/api-keys`                       |
| List existing  | The table on the settings page | `GET  /api/v1/api-keys`                       |
| Revoke one     | Per-row "Revoke" action        | `POST /api/v1/api-keys/{id}/revoke`           |
| Bulk-revoke    | "Show unused" view             | (delegated; see runbook-api-keys-unused.md)   |

All endpoints are gated by `Role.ADMIN` server-side. A non-admin
member who navigates to the settings page sees the page render
empty (the API call returns 403); the in-page copy explains.

## Mint a new key

### What happens on the wire

1. Admin fills the form: `name` (any string, max 120 chars),
   `scopes` (closed-set checkboxes), `rate_limit_per_minute`
   (optional override; default 60), `expires_at` (optional;
   None = never expires), `mode` (`live` or `test`),
   `project_ids` (optional per-project allowlist; empty =
   all projects).
2. Frontend POSTs to `/api/v1/api-keys`.
3. Backend mints `aec_<32-hex-chars>`, hashes it, persists the
   row, returns the **plaintext** in the response body.
4. Frontend shows a one-shot "save this now" dialog with a
   copy-to-clipboard button.

### What ops should know

- **The plaintext is shown ONCE.** The DB stores only the SHA-256
  hash. There is no "reveal secret" endpoint and there will not
  be one.
- The key prefix (first 8 chars after `aec_`) is what the listing
  page shows so admins can identify which key is which.
- The mode is the live-vs-test discriminator. Test-mode keys can
  hit the `/api/v1/sandbox/*` routes against synthetic fixtures;
  live keys hit prod data.
- The `*` scope is the superuser scope. Today it's gated only by
  the route-level admin check (any org admin can mint a `*` key);
  treat it accordingly.

### Common mistakes

- **Pasting the secret into Slack / a ticket**: the `aec_` prefix
  is what log-scrubbers look for. Even if you redact, assume any
  pasted secret is compromised; revoke + re-mint.
- **Setting an `expires_at` in the past**: the auth lookup checks
  `expires_at > NOW()`, so the key 401s on the first request.
  The form should validate but ops can also catch this by
  checking the listing page's "expires" column.
- **Forgetting to save the secret**: there's no recovery. Revoke
  + mint a fresh key.

## List existing keys

The settings page renders one row per key in the org. Columns:

| Column          | What it tells you                                       |
| --------------- | ------------------------------------------------------- |
| `name`          | The human label given at mint time                      |
| `prefix`        | First 8 chars after `aec_` (the UI identifier)          |
| `scopes`        | Scope set carried by the key                            |
| `rate_limit`    | Per-minute cap (default 60 if `rate_limit_per_minute` is null) |
| `last_used_at`  | Last auth-middleware bump (or `—` if never used)        |
| `last_used_ip`  | The X-Forwarded-For first hop or peer IP                |
| `created_at`    | Mint time                                               |
| `revoked_at`    | Revocation time, or `—` if active                       |

The list is sorted newest-first. Revoked keys stay visible (with
their `revoked_at` populated) for forensic continuity — partners
asking "when was that key cut off?" need a durable record.

The list endpoint **does not** expose the plaintext or the hash.
Ever. (Pinned by `test_api_keys_router_surface_pin.py`.)

## Rotate a key

We don't currently expose a "rotate" endpoint — the documented
flow is **revoke + mint**:

1. Mint a fresh key with the same scopes / rate-limit / mode.
2. Send the new secret to the partner via a secure channel.
3. Once the partner confirms they've cut over, **revoke the old
   key** so any leaked copy is invalid.
4. The audit log carries both events (`api_keys.create` for the
   mint, `api_keys.revoke` for the revoke) so compliance can
   reconstruct the rotation later.

A future enhancement may add an in-place rotate-secret endpoint
(matching the webhook subscription's rotation pattern with a
grace window) but that's not on the roadmap today.

## Revoke a key

### Per-key revoke

The settings page has a "Revoke" button per row. Confirmation
dialog → backend issues `POST /api/v1/api-keys/{id}/revoke`.

The endpoint:
- Filters by `auth.organization_id` so a typo'd id from another
  tenant 404s rather than revoking someone else's key.
- Sets `revoked_at = COALESCE(revoked_at, NOW())` — so revoking
  an already-revoked key keeps the original timestamp (forensic
  audit trail preservation, pinned in the surface pin).
- Returns 404 with `api_key_not_found` if the id doesn't exist.

The partial index `ix_api_keys_hash_active` is `WHERE
revoked_at IS NULL`, so the auth lookup drops the key from its
hot path immediately. No cache invalidation; the next partner
request from the revoked key 401s.

### Bulk revoke (unused keys)

See [runbook-api-keys-unused.md](runbook-api-keys-unused.md).

### When NOT to revoke

- **Mid-incident**: revoke is a destructive change; if an
  integration is already breaking, adding revokes complicates
  the triage.
- **Without warning the partner**: legitimate revokes still break
  partner integrations until they re-mint. Coordinate.
- **Right after a deploy that may have changed auth semantics**:
  if partners are 401'ing en masse, check whether it's the
  middleware first.

## Recover from a leaked secret

The "secret got pasted into Slack" / "secret committed to a
public repo" scenario:

1. **Revoke the leaked key immediately.** No grace period.
2. **Check `last_used_at` and `last_used_ip`** for the key. If
   the IP changed unexpectedly OR `last_used_at` jumped after
   the leak window, treat as confirmed compromise. Even if not,
   the audit log entries from the revocation cycle are useful
   for the post-mortem.
3. **Mint a replacement** with the same scopes; deliver the new
   secret out-of-band to the partner.
4. **Audit-log review**: pull every `api_keys.create` /
   `api_keys.revoke` event from the org's audit log for the
   incident window, plus any anomalous `last_used_*` data.

## Audit trail

Every mint and revoke writes one `audit_events` row:

| Action                | When                              |
| --------------------- | --------------------------------- |
| `api_keys.create`     | Per `POST /api/v1/api-keys`       |
| `api_keys.revoke`     | Per `POST /api/v1/api-keys/{id}/revoke` |
| `admin.api_key.bulk_revoke` | Per row in the bulk-revoke flow (see runbook-api-keys-unused.md) |

To see every key-management event for your org over the last
90 days:

```sql
SELECT actor_user_id, action, resource_id, created_at
FROM audit_events
WHERE organization_id = '<your-org-id>'
  AND action LIKE 'api_keys.%' OR action LIKE 'admin.api_key.%'
  AND created_at >= NOW() - INTERVAL '90 days'
ORDER BY created_at DESC;
```

## Related code

| Component                      | Lives in                                              |
| ------------------------------ | ----------------------------------------------------- |
| Mint / list / revoke endpoints | `routers/api_keys.py`                                 |
| Verify + scope-check helpers   | `services/api_keys.py`                                |
| Auth middleware                | `middleware/api_key_auth.py`                          |
| Frontend page                  | `apps/web/app/(dashboard)/settings/api-keys/page.tsx` |
| Frontend hook                  | `apps/web/hooks/apiKeys/useApiKeys.ts`                |

## Pin tests (tripwires)

These tests guard the API-keys surface from silent regressions:

- `apps/api/tests/test_api_keys_router_surface_pin.py` — endpoint
  paths, admin gate, secret-on-create-only, list-without-secret,
  COALESCE on revoke, 404 on missing key.
- `apps/api/tests/test_api_keys_service_pin.py` — `KEY_PREFIX`,
  hash algorithm, scope/project access semantics, rate-limit
  no-redis short-circuit.
- `apps/api/tests/test_api_key_auth_contract_pin.py` —
  middleware role synthesis, scope/project gates, dispatch on
  `aec_` prefix.

If any go red on CI, the API-keys surface's contract has
drifted — investigate before merging.
