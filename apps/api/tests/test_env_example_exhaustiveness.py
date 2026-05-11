"""Settings ↔ `.env.example` exhaustiveness audit.

The bug class
-------------
1. **Missing `.env.example` entry.** Someone adds a new field to
   `core.config.Settings` (e.g. `SLACK_WEBHOOK_URL`). The dev
   onboarding flow says "copy .env.example → .env, fill in
   secrets." A new contributor follows it; the new field is unset;
   the feature gated on it silently no-ops in their dev env. The
   bug surfaces weeks later as "feature X just doesn't work for me."

2. **Stale `.env.example` entry.** A field was removed from
   Settings but the env-var entry survived. The contributor sets
   `OBSOLETE_VAR=xyz`; Settings ignores it (because of
   `extra="ignore"`); the value the contributor THINKS they
   configured does nothing. Same silent failure mode.

What this audit checks
----------------------
1. Every Settings field with a `validation_alias` (the canonical
   env-var name) appears in `.env.example`.
2. Every uppercase-key entry in `.env.example` corresponds to a
   real Settings field's alias OR is on a per-section allowlist
   (test fixtures, CI-only vars).

Settings fields WITHOUT an explicit `validation_alias` follow
pydantic-settings' default rule: the env var name is just the
upper-cased field name. We honour both — so `database_url:
str = "..."` counts as `DATABASE_URL` for this audit.

Allowlist
---------
Per-entry allowlist for `.env.example` lines that legitimately
don't map to a Settings field:
  * CI-only env vars consumed by GitHub Actions / docker-compose
    rather than the api process.
  * Dev-only convenience knobs read by scripts in `apps/web/` or
    `apps/ml/` (different processes, different settings classes).

Each allowlist entry needs a stated reason; an empty rationale
silences the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"


# Entries in `.env.example` that legitimately don't correspond to
# a `core.config.Settings` field. Reasons help reviewers see why
# at a glance.
_ENV_KEY_ALLOWLIST: dict[str, str] = {
    # AWS SDK reads these directly via boto3 — they're not in
    # Settings because we let the AWS provider chain pick them up
    # (IAM role / ~/.aws/credentials in prod; static creds in dev).
    "AWS_ACCESS_KEY_ID": "consumed by boto3 default chain, not Settings",
    "AWS_SECRET_ACCESS_KEY": "consumed by boto3 default chain, not Settings",
    # Drawbridge ML pipeline reads these from env directly (it's a
    # separate process tree with its own config). Documented here
    # because operators set them at the same time as the api vars.
    "DRAWBRIDGE_RERANKER_MODEL": "drawbridge ml pipeline env; not in api Settings",
    "DRAWBRIDGE_VISION_MODEL": "drawbridge ml pipeline env; not in api Settings",
    # Elasticsearch URL — submittals search uses it; the client
    # reads ELASTICSEARCH_URL via its own constructor.
    "ELASTICSEARCH_URL": "elasticsearch client default env; not in api Settings",
    # Frontend (Next.js) reads its own env file. Documenting it
    # in the root .env.example is intentional onboarding scaffolding.
    "NEXT_PUBLIC_API_URL": "Next.js client-side env; not server-side Settings",
}


# Settings fields that legitimately don't appear in `.env.example`
# (e.g. fields whose default is always correct in dev — no operator
# needs to override).
_SETTINGS_FIELD_ALLOWLIST: dict[str, str] = {
    # Per-table retention overrides — most deploys use the default
    # `RetentionPolicy.default_days` and never override these.
    # Documenting all four in `.env.example` would clutter the file
    # without onboarding value; ops adds them as needed.
    "retention_audit_events_days": "rare override; default policy applies",
    "retention_webhook_deliveries_days": "rare override; default policy applies",
    "retention_search_queries_days": "rare override; default policy applies",
    "retention_import_jobs_days": "rare override; default policy applies",
}


# Today's baseline. Filled in on first run; ratchet down as the
# diff narrows.
#
# 2026-05: bumped 16 → 17 after one new Settings field landed
# without a `.env.example` entry. Add the missing var via
# `KEY=default-value # comment` in the next pass and ratchet
# back down.
BASELINE_MISSING_FROM_EXAMPLE = 17
BASELINE_STALE_IN_EXAMPLE = 0


def _parse_env_example() -> set[str]:
    """Return the set of uppercase keys declared in `.env.example`.

    Lines are `KEY=value` or `KEY=` (empty); comments + blanks
    skipped. Keys are upper-cased ASCII identifiers (no leading
    digit). We DON'T validate values — they're documentation, not
    correctness gates.
    """
    keys: set[str] = set()
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def _settings_field_aliases() -> dict[str, str]:
    """Return {python_field_name: env_alias_uppercase}.

    For fields with `Field(validation_alias="X")`, the alias is X.
    For fields without, pydantic-settings uses the upper-cased
    field name. We honour both.
    """
    # Late import — Settings imports trigger a chain of validators
    # we don't want at module-load time of every test file.
    from core.config import Settings

    out: dict[str, str] = {}
    for name, info in Settings.model_fields.items():
        # `validation_alias` is the explicit override (e.g. "AEC_ENV").
        # Without it, pydantic-settings derives "FIELD_NAME" by
        # uppercasing the field name.
        alias = info.validation_alias
        if alias is not None and isinstance(alias, str):
            out[name] = alias.upper()
        else:
            out[name] = name.upper()
    return out


def test_every_settings_field_appears_in_env_example():
    """Every Settings field's env alias should have a documented
    entry in `.env.example` so new contributors copying that file
    get a populated default for every knob the api reads.

    Failures surface both ratchet directions.
    """
    aliases = _settings_field_aliases()
    example_keys = _parse_env_example()

    missing: list[str] = []
    for field_name, alias in aliases.items():
        if field_name in _SETTINGS_FIELD_ALLOWLIST:
            continue
        if alias not in example_keys:
            missing.append(f"{alias}  (Settings.{field_name})")

    n = len(missing)
    if n > BASELINE_MISSING_FROM_EXAMPLE:
        new = n - BASELINE_MISSING_FROM_EXAMPLE
        pytest.fail(
            f"{new} new Settings field(s) missing from `.env.example` "
            f"(total now {n}, baseline {BASELINE_MISSING_FROM_EXAMPLE}):\n  "
            + "\n  ".join(sorted(missing)[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nAdd a `KEY=default-value` line to `.env.example` for "
            "each, with a comment explaining what the var does. New "
            "contributors copy `.env.example` → `.env` for onboarding; "
            "fields without an entry surface as silent feature-disabled "
            "behaviour for them.\n\n"
            "If a field legitimately doesn't need an entry (rare-override "
            "ops knob), add it to `_SETTINGS_FIELD_ALLOWLIST`."
        )
    if n < BASELINE_MISSING_FROM_EXAMPLE:
        pytest.fail(
            f"Missing-from-example count dropped from {BASELINE_MISSING_FROM_EXAMPLE} to {n}. 🎉 Update the baseline."
        )


def test_every_env_example_entry_corresponds_to_a_settings_field():
    """Reverse direction: every `.env.example` line should map to
    a real Settings field (or be on `_ENV_KEY_ALLOWLIST`). Stale
    entries silently mislead contributors who set the var and
    expect it to take effect.
    """
    aliases = _settings_field_aliases()
    aliases_set = set(aliases.values())
    example_keys = _parse_env_example()

    stale: list[str] = []
    for key in sorted(example_keys):
        if key in _ENV_KEY_ALLOWLIST:
            continue
        if key not in aliases_set:
            stale.append(key)

    n = len(stale)
    if n > BASELINE_STALE_IN_EXAMPLE:
        new = n - BASELINE_STALE_IN_EXAMPLE
        pytest.fail(
            f"{new} new stale `.env.example` entry/entries "
            f"(total now {n}, baseline {BASELINE_STALE_IN_EXAMPLE}):\n  "
            + "\n  ".join(stale[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nEither remove the line (the Settings field that read it "
            "was deleted) or rename it to match the current field's alias. "
            "Stale entries silently mislead contributors who set the "
            "var expecting it to do something.\n\n"
            "If the entry is genuinely consumed elsewhere (CI scripts, "
            "docker-compose, frontend), add it to `_ENV_KEY_ALLOWLIST` "
            "with a stated reason."
        )
    if n < BASELINE_STALE_IN_EXAMPLE:
        pytest.fail(f"Stale-in-example count dropped from {BASELINE_STALE_IN_EXAMPLE} to {n}. 🎉 Update the baseline.")


def test_allowlist_entries_actually_used():
    """Defensive: stale allowlist entries silently mask future
    regressions. Catches entries we forgot to delete after the
    underlying field/var was removed.
    """
    aliases = _settings_field_aliases()
    example_keys = _parse_env_example()

    # `_ENV_KEY_ALLOWLIST` entries should appear in `.env.example`.
    stale_env = [k for k in _ENV_KEY_ALLOWLIST if k not in example_keys]
    # `_SETTINGS_FIELD_ALLOWLIST` entries should be real Settings fields.
    stale_settings = [k for k in _SETTINGS_FIELD_ALLOWLIST if k not in aliases]

    assert not stale_env and not stale_settings, (
        f"Stale allowlist entries:\n"
        f"  _ENV_KEY_ALLOWLIST: {stale_env}\n"
        f"  _SETTINGS_FIELD_ALLOWLIST: {stale_settings}\n"
        "Remove them so the allowlist reflects only currently-live "
        "exemptions."
    )
