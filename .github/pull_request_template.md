## Summary
<!-- What changed and why. Link the ticket / spec section. -->

## Module
- [ ] WINWORK
- [ ] BIDRADAR
- [ ] CODEGUARD
- [ ] PULSE
- [ ] SITEEYE
- [ ] COSTPULSE
- [ ] Platform (infra / auth / shared)

## Changes
- <!-- bullet list -->

## Testing
- [ ] `pnpm -r typecheck` passes
- [ ] `pnpm -r lint` passes
- [ ] `pytest` passes in affected app(s)
- [ ] Manual check through the UI (describe below)

## Migration / rollout notes
<!-- Alembic migration? New env vars? Terraform changes? -->

## Audit baseline drift
<!--
A bot comment will appear below with the `BASELINE_*` constants
that moved on this branch vs `main`. If the table shows ratchets
LOOSENING (numbers going up), justify each one in the bullet list
above under Changes. If they're TIGHTENING (going down with 🎉),
no extra explanation needed.

To regenerate locally:
    make audit-drift
    # or with explicit refs:
    make audit-drift BASE=origin/main HEAD=feat/my-branch
-->
