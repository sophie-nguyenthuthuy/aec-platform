# Runbook: unused API key detection + bulk revoke

## What this is

Long-lived API keys are a security debt. A partner integration
mints a key for a specific use, the use is retired, but the key
stays valid forever — visible to every admin in the org, available
to anyone who happened to copy the secret somewhere. The unused-key
detector surfaces these so an admin can revoke them.

The detection runs against `api_keys.last_used_at` — the column
the auth middleware bumps on every authenticated request. A key
with:

- `revoked_at IS NULL` (still active), AND
- `last_used_at IS NULL` (never used since mint) OR
  `last_used_at < (NOW() - <window>)` (stale)

is "unused" by the documented threshold. Default window: **90
days**.

## Why 90 days

- **Shorter (30/60d)** would flag legitimate quarterly-cron keys
  (e.g. weekly scrape, monthly invoice export) that legitimately
  go quiet between runs.
- **Longer (180d/1y)** lets keys accumulate that are realistically
  abandoned — defeats the cleanup point.
- 90 days is a quarterly review boundary that aligns with most
  enterprise-security audit cycles.

The window is configurable per call (the unused-keys endpoint
accepts a `days` query param), but the **default** is what the
admin UI's "Show unused keys" button uses.

## How to read the unused-keys list

The dashboard surfaces one row per flagged key with:

| Column          | What it tells you                                      |
| --------------- | ------------------------------------------------------ |
| `name`          | The human label the admin gave at mint time            |
| `prefix`        | First 8 chars after `aec_` (the UI identifier)         |
| `last_used_at`  | Last time the auth middleware saw this key (or `—` if never) |
| `created_at`    | When the key was minted                                |
| `created_by`    | The admin who minted it                                |
| `scopes`        | Scope set the key carries (e.g. `projects:read`)       |

**Read order**: scan `last_used_at` first. Keys with `—` (never
used) are the highest-confidence revoke candidates — they were
minted but no integration ever consumed them. Next: keys whose
last use is many months old (long since past the 90d cutoff).

## When ops sees a key flagged

### Triage tree

1. **Look at the `name` + `created_by`.** A name like
   `weekly-prosperia-export` minted by a developer who left the
   company is a clear revoke candidate. A name like
   `terraform-bootstrap` might be tied to infra automation that
   only runs on rare events — pause before revoking.

2. **Cross-reference recent ops history.** If the key was last
   used 91 days ago, you might be one cron-run away from
   re-activation. Check the cron schedule (some are quarterly).

3. **Reach out before revoking** for keys with a clear owner.
   The admin UI shows `created_by` (the minting user); a quick
   message ("are you still using key `aec_abcd1234`?") prevents
   the unhappy "you broke our integration" support ticket.

4. **Default action: revoke.** A key that's been unused for 90+
   days is a security debt; the burden of proof is on "we still
   need this," not "we can revoke it." Revoke is reversible
   (the partner mints a fresh key + updates the integration).

### Bulk revoke

The dashboard offers a "revoke all selected" action. The flow:

1. Select the rows to revoke (or "select all flagged").
2. Confirm in the dialog (which restates the count + names).
3. The backend issues `services.api_keys.revoke_unused_keys`
   against the listed key ids. The endpoint:
    - Filters by `auth.organization_id` (cross-tenant safety —
      a request body with key ids from another tenant is a
      no-op).
    - Sets `revoked_at = NOW()` per key (uses `COALESCE` so
      already-revoked keys keep their original timestamp).
    - Writes an `admin.api_key.bulk_revoke` audit row per
      revocation.
4. Affected partners see HTTP 401 on their next request from
   the revoked key.

## Audit trail

Each revocation emits an `admin.api_key.bulk_revoke` audit row
into `audit_events`. The row carries:

- `actor_user_id` — the admin who fired the bulk revoke
- `resource_id` — the api_key.id revoked
- `before` = `{revoked_at: null}`, `after` = `{revoked_at: <ts>}`
- `request.user_agent` + `request.ip` — for forensics

To list every bulk revoke in the last 90 days:

```sql
SELECT actor_user_id, resource_id, created_at
FROM audit_events
WHERE action = 'admin.api_key.bulk_revoke'
  AND organization_id = '<your-org-id>'
  AND created_at >= NOW() - INTERVAL '90 days'
ORDER BY created_at DESC;
```

## When ops should NOT bulk-revoke

- **Right after a major outage** — keys quiet during the outage
  but actively used. The 90-day window naturally excludes them
  (NOW() - 90d should still be pre-outage), but check the cutoff.

- **Mid-incident** — bulk revoke is a destructive operation; if
  ops is already debugging an integration break, adding revokes
  to the mix complicates the incident.

- **For partner-managed keys without warning the partner** — even
  legitimate revokes break partner integrations until they re-mint
  + re-deploy. Coordinate.

## Restoring a revoked key

A revoked key cannot be un-revoked. The partial index
`ix_api_keys_hash_active` is `WHERE revoked_at IS NULL`, so the
auth lookup will never find the row again. To restore access,
the partner must mint a fresh key and update their integration.

## Related code

| Component                              | Lives in                                           |
| -------------------------------------- | -------------------------------------------------- |
| Detection helper                       | `services.api_keys.find_unused_keys`               |
| Bulk-revoke helper                     | `services.api_keys.revoke_unused_keys`             |
| Admin endpoints (list + bulk revoke)   | `routers/api_keys.py`                              |
| Frontend page                          | `apps/web/app/(dashboard)/settings/api-keys/page.tsx` |
| Frontend hook                          | `apps/web/hooks/apiKeys/useApiKeys.ts`             |
| Audit-row writer                       | `services.audit.record(action="admin.api_key.bulk_revoke")` |

## Pin tests (tripwires)

These tests guard the unused-key surface from silent regressions:

- `apps/api/tests/test_api_keys_unused.py` — pins the WHERE clause
  shape (NULL branch + cutoff branch), the org-id filter, and the
  90-day default window.
- `apps/api/tests/test_api_keys_router_surface_pin.py` — pins the
  parent api-keys router's admin gate + `IdempotentRoute` posture.
- `apps/api/tests/test_audit_action_callsite_audit.py` — catches
  if the bulk-revoke action string drifts from the canonical
  `AuditAction` Literal.

If any of these go red on CI, the unused-key feature's contract
has drifted — investigate before merging.
