# Runbook: audit-trail — querying `audit_events` during an investigation

The on-call procedure for using the `audit_events` table as an
investigation surface. Pairs with the audits:

  * `tests/test_audit_action_callsite_audit.py` — every
    `record(action=...)` call uses a string in the `AuditAction`
    Literal.
  * `tests/test_audit_completeness_audit.py` — every state-
    changing route emits an `audit_events` row.
  * `tests/test_audit_record_signature_pin.py` — the writer's
    signature is stable.

Both audits exist to keep the audit log USEFUL. A complete log
that's full of typo'd actions or missing rows is the worst
outcome — an investigation queries it and gets the wrong
answer, with no signal that the answer is wrong.

## What `audit_events` is

The append-only log of every governance-relevant action in the
platform: who did what to which resource and when. Schema (see
`models/audit.py` + migration `0022_audit_events`):

| Column | Purpose |
| --- | --- |
| `id` | UUID primary key |
| `created_at` | Event timestamp (UTC; server-side `now()`) |
| `organization_id` | Tenant scope. RLS filters on this |
| `actor_user_id` | User actor (NULL for API-key-driven events) |
| `actor_kind` | `user` / `api_key` / `system` / `cron` |
| `actor_api_key_id` | API-key actor (NULL for user actions) |
| `action` | Member of `AuditAction` Literal |
| `resource_type` | The resource family (`change_orders`, `webhooks`, …) |
| `resource_id` | The resource UUID (NULL for non-resource actions) |
| `before` | JSONB diff — the row state before the change |
| `after` | JSONB diff — the row state after the change |
| `request_id` | Correlation with HTTP request logs |
| `ip` | Source IP (when available) |
| `user_agent` | Source user-agent (when available) |

The `before` / `after` columns are diffs, NOT full row dumps —
the writer scrubs to fields that meaningfully changed. Secrets
are NEVER persisted to either column even in hashed form (see
`runbook-api-keys.md` for the secret-handling contract).

## Common investigation queries

### Who changed this resource recently?

```sql
SELECT created_at, actor_kind, actor_user_id, actor_api_key_id,
       action, before, after
FROM audit_events
WHERE resource_type = '<type>'
  AND resource_id = '<uuid>'
  AND organization_id = '<org_uuid>'  -- RLS will enforce; explicit for safety
ORDER BY created_at DESC
LIMIT 50;
```

### What did this user do today?

```sql
SELECT created_at, action, resource_type, resource_id
FROM audit_events
WHERE actor_user_id = '<user_uuid>'
  AND organization_id = '<org_uuid>'
  AND created_at >= NOW() - INTERVAL '1 day'
ORDER BY created_at DESC;
```

### How many `<action>` events fired in the last hour?

```sql
SELECT count(*), action
FROM audit_events
WHERE created_at >= NOW() - INTERVAL '1 hour'
GROUP BY action
ORDER BY count(*) DESC;
```

Useful baseline for "did the rate of X spike?" alerts.

### Reconstruct an entire org's mutation timeline

```sql
SELECT created_at, actor_kind, action, resource_type, resource_id
FROM audit_events
WHERE organization_id = '<org_uuid>'
  AND created_at BETWEEN '<start>' AND '<end>'
ORDER BY created_at;
```

The output is the org's "what happened" timeline. Useful for
incident reconstructions, customer support investigations, and
the GDPR right-of-access response.

### Who has an API key that's making this call?

```sql
SELECT created_at, action, resource_type, ip
FROM audit_events
WHERE actor_api_key_id = '<api_key_uuid>'
  AND created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
LIMIT 100;
```

Pairs with `services.api_keys` lookups for the key's metadata.

## When the audit log is silent on something

The ABSENCE of an audit row is itself a finding. Cases:

### Case 1: a state-changing endpoint without `record(...)`

The `test_audit_completeness_audit.py` audit catches this
pre-merge — every state-changing route calls `record(...)` OR
has an `# audit-trail: <reason>` marker. If the audit was
disabled on the affected branch, a route may have shipped
without auditing.

**Diagnosis:**

  1. Find the handler in `apps/api/routers/<file>.py`.
  2. Check for any of:
     * `audit_record(...)`
     * `audit.record(...)` / `_audit.record(...)`
     * `record_audit(...)`
     * `# audit-trail:` comment
  3. If NONE of those is present, the endpoint isn't auditing.
     Add `audit_record(...)` per the convention in any other
     `routers/<file>.py`.

### Case 2: a typo'd action string

The action passed to `record(...)` is wrong but lexically valid
(`"webhook.delivery.success"` instead of
`"webhooks.delivery.success"`). Queries that filter on the
canonical string silently miss the row.

**Diagnosis:**

```sql
-- Look for action strings that LOOK related but aren't in the
-- canonical Literal.
SELECT DISTINCT action
FROM audit_events
WHERE action ILIKE '%webhook%'
ORDER BY action;
```

If you see two near-identical strings, one of them is a typo.
The `test_audit_action_callsite_audit.py` audit catches this
pre-merge — if it was disabled, the typo is the bug.

### Case 3: `AdminSessionFactory` (BYPASSRLS) writes that look weird

Admin endpoints (cron, ops tooling) use `AdminSessionFactory`
which BYPASSRLS. Their audit rows are still written, but the
`organization_id` may be the operator's org rather than the
target org of the action. Look at `actor_kind = 'system'` rows
carefully.

## When you need to add a new audit action

1. **Add the string literal to `AuditAction`** in
   `apps/api/services/audit.py`. The Literal is the closed
   vocabulary; new strings MUST be members.

2. **Use the new action in the handler**:
   ```python
   await record(
       session,
       organization_id=auth.organization_id,
       auth=auth,
       action="my_module.entity.verb",
       resource_type="my_entities",
       resource_id=entity_id,
       before={"status": old_status},
       after={"status": new_status},
       request=request,
   )
   ```

3. **Run `pytest tests/test_audit_action_callsite_audit.py`** to
   confirm the new literal is recognised.

4. **Convention for the action string**: dot-separated,
   `<module>.<entity>.<verb>`. Examples:
   * `pulse.change_order.approve`
   * `webhooks.subscription.rotate_secret`
   * `admin.cron.run_now`

   The shape isn't enforced by the Literal (which only checks
   set-membership), but consistent shapes make GROUP BY queries
   meaningful.

## When the `before` / `after` diffs are missing

For state-machine transitions (status → status), the `before` /
`after` diff is the most useful column. If it's empty:

  * **Lookup endpoint**: by design — read paths don't have a
    diff to record. The audit row IS the read attestation.
  * **Idempotent UPSERT**: by design — if nothing changed, the
    diff is empty. The presence of the row is the attestation.
  * **Mutation endpoint**: bug. The handler should populate
    `before` (pre-mutation read of the row) and `after`
    (post-mutation values).

## GDPR / VN PDPL considerations

`audit_events` is a record of personal data — `actor_user_id`
is a user identifier; `ip` and `user_agent` are PII; `before` /
`after` may contain customer-supplied content. The retention
policy lives in `services/retention.py` (default: 365 days,
extensible per-tenant via `retention_overrides`).

**Right-of-access**: a user requesting their data per GDPR Art.
15 gets every `audit_events` row where they're the actor:

```sql
SELECT * FROM audit_events
WHERE actor_user_id = '<user_uuid>'
  AND organization_id = '<org_uuid>'
ORDER BY created_at;
```

**Right-of-erasure** (GDPR Art. 17): tricky — the audit log is
itself the legal record of the user's actions. The platform's
position is that erasure is honoured by anonymising
`actor_user_id` to NULL and redacting any PII in
`before` / `after`, NOT by deleting the row. The deletion would
break the audit trail for the org's other compliance
obligations.

The actual erasure procedure lives in the GDPR-DSR runbook
(separate doc — outside this runbook's scope).

## Common mistakes

### Querying without `organization_id` filter

RLS enforces tenant scope, but if you connect as the `aec`
superuser (BYPASSRLS) for a debugging query, RLS won't filter.
ALWAYS include `organization_id = '<uuid>'` explicitly when
running queries during an investigation, especially when
copying customer-supplied UUIDs.

### Trusting `actor_user_id` for events from API keys

API-key-driven actions write `actor_kind = 'api_key'` and
`actor_api_key_id = <uuid>`, with `actor_user_id` NULL. If you
filter on `actor_user_id` alone, you'll miss every API-key
event. Use `actor_kind` first; resolve to user identity per
case.

### Reading `before` / `after` as full row state

They're diffs of changed fields, not full dumps. A mutation
that changed only `status` will have `before = {"status":
"draft"}` and `after = {"status": "submitted"}` — the rest of
the row's columns aren't in the audit row.

### Modifying `audit_events` rows directly

Don't. The audit log is append-only by convention. The only
"mutation" is row insertion; updates / deletes break the trail.
If you need to redact (GDPR Art. 17), do it via the documented
procedure (anonymise + scrub PII fields) rather than DELETE.

## Related code + audits + runbooks

| Surface | Lives in |
| --- | --- |
| `record()` writer | `apps/api/services/audit.py::record` |
| `AuditAction` Literal | `apps/api/services/audit.py::AuditAction` |
| ORM model | `apps/api/models/audit.py::AuditEvent` |
| Audit-row router | `apps/api/routers/audit.py` |
| Action-callsite audit | `tests/test_audit_action_callsite_audit.py` |
| Completeness audit | `tests/test_audit_completeness_audit.py` |
| Writer signature pin | `tests/test_audit_record_signature_pin.py` |
| Cross-tenant incident | [`runbook-cross-tenant-incident.md`](runbook-cross-tenant-incident.md) |
| API-key surface | [`runbook-api-keys.md`](runbook-api-keys.md) |

## What this runbook is NOT for

  * **The webhook-delivery audit log** (different table —
    `webhook_deliveries`). See
    [`runbook-webhook-deliveries.md`](runbook-webhook-deliveries.md).
  * **Adding a new audit (test) to the suite.** That's
    [`runbook-audit-suite-on-call.md`](runbook-audit-suite-on-call.md).
  * **Configuring retention TTLs.** That's the retention
    surface in `services/retention.py` + `retention_overrides`.
