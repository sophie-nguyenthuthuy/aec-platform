# Runbook: alembic migration rollback

The on-call procedure when a deploy lands a bad migration and
ops needs to roll back. Pairs with the audits:

- `tests/test_alembic_chain_integrity_audit.py` — chain-level
  health (orphan revisions, multi-head, etc.)
- `tests/test_migration_upgrade_downgrade_symmetry_audit.py` —
  every `upgrade()` has a non-empty `downgrade()`

Both audits should be green before any deploy lands. If they're
red on `main`, fix THAT first — rolling back over a corrupt
chain is its own incident.

## When to roll back vs forward-fix

| Symptom | Right action |
| --- | --- |
| Migration applied; subsequent SELECTs / INSERTs erroring | **Roll back.** The migration's schema is the cause. |
| Migration applied; data integrity issue (a row got mis-attributed) | **Forward-fix.** A downgrade can't restore the bad data; fix in code + cleanup migration. |
| Migration partially applied (worker died mid-DDL) | **Manual recovery** (see below). Don't blindly downgrade. |
| Migration applied; performance regression | **Forward-fix** (add the missing index). Rollback often makes performance worse during the rollback window. |

The default for "the deploy broke things and I'm not sure why"
is roll back, but check the table above first.

## Standard rollback (the happy path)

If the most recent migration `<latest>` is healthy in shape (the
audits are green) and you just want to undo it:

```bash
# 1. Verify what alembic thinks is the current head.
pnpm --filter @aec/api exec alembic current

# 2. See which migration is one step back.
pnpm --filter @aec/api exec alembic history -i | head -10

# 3. Roll back ONE step.
pnpm --filter @aec/api exec alembic downgrade -1

# 4. Verify.
pnpm --filter @aec/api exec alembic current
```

After step 4, `alembic current` should show the migration BEFORE
the one you just rolled back. If it shows the same as before
step 3, the downgrade silently no-op'd — go to "When downgrade
silently fails" below.

## Pre-rollback checklist (≤2 minutes)

Before running `alembic downgrade`, verify:

1. **No customer-facing writes are mid-transaction** that the
   downgrade would orphan. The 5-minute lull after a deploy is
   the safest window.
2. **You have the deploy's actual migration file open** so you
   can read its `downgrade()` and predict what'll change.
3. **You're connected to the right DB.** Running `alembic
   downgrade` against staging when you meant prod is a
   recoverable embarrassment; the reverse is a real incident.
4. **The replicas are caught up** — `pg_replication_lag()` near
   zero. Rolling back schema while a replica is behind makes
   replica-promotion harder if the rollback itself fails.

## When downgrade silently fails

`alembic downgrade -1` returns 0 but `alembic current` shows the
same revision. Causes:

### Case 1: empty `downgrade()` body

The migration's `def downgrade(): pass` (or has a comment-only
body). Alembic dutifully runs the no-op, marks the migration
un-applied in `alembic_version`, and the schema is unchanged.

**Fix:**
1. Reapply the migration (`alembic stamp <revision>`) so
   alembic_version matches reality.
2. Manually run the SQL that the downgrade SHOULD have run.
3. Re-run `alembic stamp <previous_revision>` to mark the
   downgrade complete.
4. File a follow-up to add the missing downgrade body in code.
5. The `test_migration_upgrade_downgrade_symmetry_audit.py`
   audit catches this class of bug pre-merge — confirm the audit
   was passing on the deploy that introduced the migration.

### Case 2: downgrade ran but partially failed

The downgrade ran multiple statements; one succeeded, the next
raised, the rest didn't run. Symptoms: schema is in a weird
intermediate state, alembic_version may or may not have been
updated.

**Fix:**
1. Read the downgrade SQL line-by-line.
2. Verify each statement's effect via `\d <table>` and
   `pg_indexes` lookups.
3. Run the missing statements by hand.
4. Use `alembic stamp <correct_revision>` to reconcile.

This is exactly the scenario the symmetry audit's "1-hour
recovery" warning predicts. The audit prevents the asymmetric
case; this section handles the partially-applied case.

## Manual recovery (when alembic itself is corrupt)

Symptoms:
- `alembic current` errors.
- `alembic_version` table contains a revision that doesn't exist
  in `alembic/versions/`.
- The chain has multiple heads or an orphan reference (the
  chain integrity audit catches these pre-merge but they can
  still slip through if the audit was disabled).

The 7 known chain bugs that already exist (per
`test_alembic_chain_integrity_audit.py`'s allowlist):

| Bug | Migration | Fix |
| --- | --- | --- |
| Orphan `down_revision='ceff072b3343'` | `0026_codeguard_quota_audit_log.py` | Repoint to the correct ancestor (`0025_webhooks` is the most likely intent) |
| Multi-head: `0025_notification_prefs` | (no descendant) | Add a merge migration listing both 0025_* heads |
| Multi-head: `0025_webhooks` | (no descendant) | Same — same merge migration |
| Filename↔rev mismatch | `0030_codeguard_quota_threshold_notifications.py` says revision `0030_codeguard_quota_thresholds` | Rename the revision to match the file (DB table is `_notifications`) |
| Filename↔rev mismatch | `0040_codeguard_user_usage_by_route.py` says revision `0040_codeguard_user_usage_route` | Pick one and align |
| Orphan `down_revision='0044_audit_exports'` | `0045_cron_alert_dedup.py` | The 0044 migration was never landed. Confirm the intended ancestor (likely `0043_webhook_secret_rotation`) and update 0045's `down_revision` line |
| Multi-head: `0043_webhook_secret_rotation` | (no descendant — chain branched at the 0044 dangling reference above) | Pair with the 0044 fix above. Once 0045 is repointed at 0043, this resolves automatically |

If a fresh-DB deploy (new replica, contributor onboarding) hits
one of these, do NOT try to roll back through it — fix the chain
metadata first:

```bash
# 1. Identify which revision alembic THINKS is current.
psql -c "SELECT * FROM alembic_version;"

# 2. Compare to the chain integrity audit's _KNOWN_* allowlists
# to confirm the bug matches a known case.
pytest apps/api/tests/test_alembic_chain_integrity_audit.py -v

# 3. Apply the correct fix from the table above.
# 4. Re-verify the audit passes BEFORE running any further migrations.
```

The rule: never downgrade through a corrupt chain link. Fix the
link first.

## After the rollback

1. **Confirm the schema matches expectations.** Run
   `pg_dump --schema-only` and diff against the previous
   working dump if you have one.
2. **Confirm row counts.** `SELECT count(*) FROM <affected_table>`
   should match the pre-deploy count (data wasn't lost).
3. **Verify the audits are still green.**
   ```bash
   pnpm --filter @aec/api exec pytest apps/api/tests/test_alembic_chain_integrity_audit.py
   pnpm --filter @aec/api exec pytest apps/api/tests/test_migration_upgrade_downgrade_symmetry_audit.py
   ```
   If either fires red, the rollback created a chain bug or
   left a half-applied migration — fix before deploying again.
4. **Re-deploy a known-good build.** Don't leave the rollback
   state on prod for hours; partner integrations don't expect
   the schema to flap.

## Communication during a rollback

The rollback procedure is fast (typically <1 minute for the
DDL itself), but the BEFORE/AFTER checks add 15+ minutes.
Communicate:

- **Before**: "Rolling back migration `<revision>` due to
  `<symptom>`. ETA: 20 min including verification."
- **After downgrade succeeds**: "Migration rolled back. Running
  schema verification."
- **After verification**: "Rollback complete. Schema matches
  `<previous_revision>`. Re-deploy is queued / planned."

If the rollback runs longer than 30 minutes, escalate. The
"15-minute incident becomes 1-hour incident" failure mode
documented in the symmetry audit usually means alembic itself
is in a corrupt state and needs the manual-recovery procedure
above.

## Forward-fix-instead patterns

Sometimes "roll back" is the wrong instinct. Cases where forward-fix
is faster:

### Missing index causing slow queries

Don't roll back the migration that created the schema; ADD the
missing index in a follow-up migration. Faster to write + safer
than reverting.

### NOT NULL constraint with bad backfill

The migration added a column with a default backfill, the
backfill was wrong, every row has the wrong value. Forward-fix:

```sql
-- The wrong default has already populated. Fix the data.
UPDATE <table> SET <column> = <correct_value> WHERE <condition>;
```

A downgrade would drop the column entirely, losing whatever
correct values DID make it through.

### Audit log gap

The migration created a new audit-action and the action string
has a typo. Don't roll back; the audit rows already written are
historical record. Add a forward-fix migration that updates the
typo'd rows AND fix the AuditAction Literal in the same PR.

(The `test_audit_action_callsite_audit.py` audit catches this
pre-merge; if it didn't, that audit's allowlist needs a TODO entry.)

## Related runbooks + audits

| Surface | Lives in |
| --- | --- |
| Migration symmetry audit | `tests/test_migration_upgrade_downgrade_symmetry_audit.py` |
| Chain integrity audit | `tests/test_alembic_chain_integrity_audit.py` |
| RLS policy conventions | [`runbook-rls-policies.md`](runbook-rls-policies.md) |
| Migration safety audit | `tests/test_migration_safety_audit.py` (the existing audit suite's broader migration check) |
| `alembic` config | `alembic.ini` + `alembic/env.py` |
