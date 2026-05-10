# Runbook: cross-tenant data exposure incident

The on-call procedure when a customer reports — or telemetry
suggests — that one tenant's data became visible or mutable to
another. This is the single highest-stakes incident type on the
platform. Every minute matters; this runbook is optimised for
"containment first, investigation second."

Pairs with the cross-tenant security perimeter audits, all of
which exist to PREVENT the incident from happening:

| Audit | What it prevents |
| --- | --- |
| `tests/test_admin_session_factory_usage_audit.py` | BYPASSRLS-via-session leaking into a user-facing handler |
| `tests/test_input_schemas_no_organization_id_audit.py` | Client overriding tenant via request body |
| `tests/test_output_schemas_no_secret_fields_audit.py` | Server leaking secret material via response |
| `tests/test_admin_routes_role_gate_audit.py` | New admin endpoint shipped without role gate |
| `tests/test_orm_tables_organization_id_audit.py` | New tenant-bearing table without `organization_id` |
| `tests/test_rls_policy_coverage_audit.py` | Tenant-bearing table without an RLS policy |

If the incident happened, the audit either fired and was
ignored OR a regression slipped through a path the audits
don't cover. The post-incident review SHOULD widen the audit
suite to catch the new path.

## What "cross-tenant data exposure" means here

Three distinct shapes:

1. **Read exposure** — a user from org A saw rows belonging to
   org B. Examples: a list endpoint returned cross-tenant rows;
   a search result included rows the user shouldn't have seen.

2. **Write exposure** — a user from org A successfully mutated
   rows belonging to org B. Strictly worse than read exposure
   because the data is now corrupted, not just leaked.

3. **Secret exposure** — verification material (API key
   plaintext, webhook signing secret, password hash) was
   returned in a response where it shouldn't have been. Doesn't
   require cross-tenant scoping to be catastrophic; even an
   admin reading their own data shouldn't see another admin's
   key plaintext.

The triage flow is similar across all three; severity ordering
is "write > read > secret-without-cross-tenant" but treat any
of them as P0.

## First 15 minutes — containment

The goal: stop ANY further exposure while you investigate.
Investigation can wait; containment cannot.

### 1. Identify the affected endpoint

The customer report or alert names a symptom. Translate to a
specific endpoint URL:

- Customer says "I saw another company's project list" →
  affected endpoint is `GET /api/v1/projects` (or whatever
  list endpoint produced the screenshot).
- Customer says "I logged in and got data from a different org" →
  affected endpoint may be the `/me/orgs` endpoint or the
  org-switching path.

If you can't identify the endpoint in 5 minutes, MOVE ON to
step 2 with the understanding that you'll be containing
broadly rather than narrowly.

### 2. Stop the bleed

Two options, in order of preference:

**Option A — feature-flag the endpoint off.** If the endpoint
has a feature flag, disable it. The page renders an empty state;
no further exposure.

**Option B — return 503 from the LB or middleware.** Add a
match-rule to the LB that returns 503 for the affected URL.
Customer integrations break; cross-tenant exposure stops.

**Option C (last resort) — disable the affected router.** Comment
out `app.include_router(<affected>.router)` in
`apps/api/main.py`, hot-deploy. The whole vertical goes dark
but the exposure stops.

What NOT to do:
- **Don't drop tables** to "make the data go away." The
  exposure has already happened; deleting evidence of it makes
  the post-incident review impossible.
- **Don't disable RLS** — it's the safety net. The leak path is
  almost certainly upstream of RLS (a handler that uses
  `AdminSessionFactory`, an admin endpoint without a role gate,
  etc.).
- **Don't roll back the latest migration** until you've verified
  the migration is the cause. Most cross-tenant exposures are
  application-layer bugs, not schema bugs.

### 3. Snapshot the audit log

The next 15 minutes WILL include writes that overwrite
forensically valuable rows. Snapshot the audit log NOW so
the investigation has data to read:

```sql
\copy (
  SELECT *
  FROM audit_events
  WHERE created_at >= NOW() - INTERVAL '24 hours'
  ORDER BY created_at DESC
) TO '/tmp/audit_snapshot_<timestamp>.csv' WITH CSV HEADER;
```

Save the file somewhere the post-incident review can access.

### 4. Page the appropriate humans

- Engineering on-call (you).
- Security lead — even at 3 AM. Cross-tenant exposure has
  notification obligations under GDPR (within 72 hours of
  becoming aware) and VN PDPL.
- Customer Success — they'll handle the customer-facing
  communication.
- Legal — for any incident involving PII.

## Investigation (after containment)

### Identify the leak path

The 4 cross-tenant security audits cover 4 known leak paths.
Run each against the deployed code:

```bash
# 1. Did a handler accidentally use AdminSessionFactory?
pnpm --filter @aec/api exec pytest \
  apps/api/tests/test_admin_session_factory_usage_audit.py -v

# 2. Did an input schema accept organization_id from the body?
pnpm --filter @aec/api exec pytest \
  apps/api/tests/test_input_schemas_no_organization_id_audit.py -v

# 3. Did an admin route ship without a role gate?
pnpm --filter @aec/api exec pytest \
  apps/api/tests/test_admin_routes_role_gate_audit.py -v

# 4. Did an output schema leak a secret-shaped field?
pnpm --filter @aec/api exec pytest \
  apps/api/tests/test_output_schemas_no_secret_fields_audit.py -v
```

If ANY fires red, that audit's failure message names the
specific file + symbol that caused the exposure.

If ALL pass, the leak path is something the audits don't cover.
Common cases:

- **A handler that scopes via `auth.organization_id` but does so
  on the wrong column.** E.g. a query that filters
  `WHERE assignee_id = auth.organization_id` (bug: should be
  `organization_id`). Code review of the affected handler
  finds this.
- **An RLS policy that filters on the wrong column or wrong
  GUC.** Run the smoke tests in
  [`runbook-rls-policies.md`](runbook-rls-policies.md) to
  verify policies are actually filtering.
- **A frontend bug** — the API correctly returned tenant-A data,
  but the frontend rendered it under the org-B label. Less
  catastrophic (the data didn't actually leak; only the UI was
  confusing), but still requires investigation.

### Quantify the exposure

Once you've identified the leak path, query the audit log to
estimate scope:

```sql
-- How many requests hit the leaking endpoint in the window?
SELECT count(*) FROM audit_events
WHERE action = '<inferred-action>'
  AND created_at >= '<incident-start>';

-- Which orgs were the actors? Which orgs are in the resource_id?
-- Cross-reference: an actor in org A reading a resource_id that
-- belongs to org B is the bad case.
SELECT
  actor_user_id, organization_id, resource_id, created_at
FROM audit_events
WHERE created_at >= '<incident-start>'
  AND action = '<inferred-action>';
```

If the leaking endpoint isn't audit-logged, you may need to
reconstruct from request logs (`request_id` correlation) or
from `audit_events` rows that the affected handlers DO write
(if any).

### Identify affected orgs

Build the list of orgs whose data was exposed AND the list of
orgs whose users saw exposed data. These overlap but aren't the
same:

- **Data-source orgs**: orgs whose rows appeared in cross-tenant
  responses. These need the "your data was exposed" notification.
- **Data-recipient orgs**: orgs whose users SAW the exposed data.
  These need the "you saw data you shouldn't have, please delete
  any local copies" notification.

The Customer Success team handles the actual outreach. Your job
is to give them the lists.

## Notification

Required within 72 hours under GDPR for any incident involving
EU-resident PII; under VN PDPL the timeline is similar. Customer
Success drives the actual communication; engineering's job is
the data + a 1-paragraph technical summary.

### Technical summary template

```
On <date> from <start time> to <end time> UTC, a regression in
<endpoint or component> caused users in some organisations to
see data belonging to other organisations. The cause was
<one-sentence root-cause from the investigation>. The exposure
was contained at <containment time> by <containment action>.

Scope:
  - <N> requests in the affected window.
  - <N1> distinct organisations whose data appeared in
    cross-tenant responses (data-source orgs).
  - <N2> distinct organisations whose users saw exposed data
    (data-recipient orgs).

Data exposed: <e.g. "project metadata: name, owner, description.
No financial data, no credentials, no documents.">

The fix: <how the leak was closed; e.g. "replaced
AdminSessionFactory with TenantAwareSession in
routers/<file>.py and added a regression test pin.">

Long-term: the audit at
`tests/test_admin_session_factory_usage_audit.py` would have
caught this had it been run on the affected branch. CI was
configured to skip audits for that branch; we're updating the
config to enforce the audit suite on every branch.
```

The "long-term" paragraph is critical. Every incident report
should name how the audit suite would prevent it from happening
again — either an existing audit that was bypassed, or a new
audit being added.

## Post-incident review checklist

Within 72 hours of containment:

1. **Run all 4 cross-tenant security audits + the orm-tables
   audit + the RLS coverage audit on `main`** as it stood
   during the incident. Record results.
2. **Identify which audit (if any) would have caught the bug.**
   If one would have but didn't run on the bad PR, fix the CI
   gate.
3. **If no audit covers the leak path**, write a new one in the
   same shape as the existing 6. Pin the property; add a
   regression-prevention test that exercises the bug shape.
4. **Update this runbook.** If the investigation flow surfaced a
   gap (a step that wasn't documented), add it.
5. **File a follow-up to the migration / handler / schema** that
   caused the leak, even if the immediate fix was already
   deployed. Document the long-term remediation in the issue.
6. **Tabletop exercise within 30 days** — walk through this
   runbook with another engineer using the actual incident's
   data. Surfaces gaps in the runbook that pure post-incident
   review misses.

## Related code + tests

| Component | Lives in |
| --- | --- |
| AdminSessionFactory (BYPASSRLS) | `db/session.py` |
| TenantAwareSession (RLS-scoped) | `db/session.py` |
| Audit-record writer | `services/audit.py::record` |
| RLS policy reference | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| Migration rollback | [`runbook-migration-rollback.md`](runbook-migration-rollback.md) |

## What this runbook is NOT for

- **A customer asking a clarifying question about their own
  data.** Not an incident; route to support.
- **A bug that exposes tenant-A's data to tenant-A members
  who shouldn't see it within their own org.** That's a per-user
  RBAC bug, not cross-tenant. Different (lower-stakes) triage
  path; doesn't trigger the GDPR notification timer.
- **A test failure on the cross-tenant audits.** That's
  pre-deploy detection — celebrate, fix the bug, ship the
  green build. The audit doing its job is the OPPOSITE of an
  incident.
