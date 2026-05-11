"""cron_runs — last-run telemetry for the arq cron registry

The `/admin/crons` dashboard (J-cycle) launched showing the registry
only — schedules + next-run, no last-run. The amber callout on the
page flagged the gap: arq stores `JobResult` in Redis with a short
TTL (default 1h via `keep_result_s`), so persisted "when did this
last fire and did it succeed" needed its own table.

Schema rationale:

  * **One row per cron invocation.** Indexed on (cron_name,
    started_at DESC) so "last run for cron X" is a single
    `LIMIT 1` index lookup, and "recent runs across every cron"
    (the dashboard's sparkline) is a small index scan.

  * **Status enum-like text.** `running | succeeded | failed`. Text
    column rather than a real PG enum because we'd otherwise need
    a follow-up migration on every status addition; the values are
    pinned in `services/cron_telemetry.py` and validated there.

  * **error_message TEXT (nullable).** Captures the exception
    message when status='failed'. Truncated to 2000 chars at write
    time so a runaway traceback doesn't bloat the table.

  * **No organization_id.** Crons are platform-wide — one row per
    invocation regardless of how many tenants the cron touched.
    The audit_events table carries per-tenant attribution where it
    matters.

  * **Pruned by the existing retention cron.** Added to
    `RETENTION_POLICIES` with a 30-day default — long enough to see
    the trend on a weekly cron, short enough that the table stays
    tens-of-MB rather than gigabytes.

What this migration does NOT do:

  * Doesn't backfill historical runs. The dashboard shows
    "(no runs yet)" for crons that haven't fired since this ships.
  * Doesn't rename / reshape audit events. Some crons already write
    audit rows (e.g. retention_prune writes `admin.retention.run`);
    those keep doing that. cron_runs is the structured-telemetry
    side-channel that complements audit, not replaces it.

Revision ID: 0042_cron_runs
Revises: 0041_merge_api_keys_cg_route
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042_cron_runs"
down_revision = "0041_merge_api_keys_cg_route"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cron_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # `cron_name` matches arq's CronJob.name (e.g.
        # "cron:weekly_report_cron"). Indexed below for the per-cron
        # "last run" query the dashboard fires.
        sa.Column("cron_name", sa.Text, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # `finished_at` is null while the cron is still running; the
        # decorator sets it on completion (success or failure).
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        # 'running' rows let the dashboard show "currently executing"
        # for long-running crons. Transitions to 'succeeded' / 'failed'
        # once the body returns / raises.
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'running'"),
        ),
        # Truncated traceback on failure. Capped at 2000 chars by the
        # writer to bound row size.
        sa.Column("error_message", sa.Text),
        # Convenience: filled by the writer at finish time so the
        # dashboard doesn't have to subtract timestamps. Postgres
        # returns NULL for unfinished rows.
        sa.Column("duration_ms", sa.Integer),
    )

    # Per-cron "last run" lookup + recent-runs scroll. The DESC
    # ordering is the natural shape of the dashboard query
    # (`ORDER BY started_at DESC LIMIT N`). PG can use the index
    # for both the per-cron filter and the global "every cron's
    # latest" via DISTINCT ON.
    op.create_index(
        "ix_cron_runs_cron_name_started_at",
        "cron_runs",
        ["cron_name", sa.text("started_at DESC")],
    )

    # Status-only filter for "show me running / failed crons across
    # the platform" triage queries. Partial index on the in-flight +
    # failed states only — succeeded rows are by far the majority and
    # don't benefit from the index.
    op.create_index(
        "ix_cron_runs_status_active",
        "cron_runs",
        ["status", sa.text("started_at DESC")],
        postgresql_where=sa.text("status IN ('running', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index("ix_cron_runs_status_active", table_name="cron_runs")
    op.drop_index("ix_cron_runs_cron_name_started_at", table_name="cron_runs")
    op.drop_table("cron_runs")
