"""provision the non-superuser `aec_app` runtime role

Why this matters: the dev `aec` role is a Postgres superuser, and
superusers implicitly BYPASSRLS. That means every RLS policy we've been
writing (0002_pulse, 0002_costpulse, 0004_bidradar, 0008_codeguard_rls)
is a no-op when the app connects as `aec` — tenant isolation is only
enforced in tests that `SET LOCAL ROLE` to a non-privileged role.

Fix: carve out a dedicated runtime role that cannot escape RLS:

  * `aec_app`    — NOBYPASSRLS, NOSUPERUSER, LOGIN. Used by the API +
                   arq workers in dev and prod. Has DML on the existing
                   tenant tables.
  * `aec`        — stays as the migration/admin role. DDL runs here so
                   Alembic keeps working without special permissions
                   dancing.

Migrations declare `ALTER DEFAULT PRIVILEGES FOR ROLE aec` so any table
or sequence created by *future* migrations automatically grants CRUD to
`aec_app` — we don't have to remember to add grants every time a new
table lands.

The default dev password is the role name; prod operators are expected
to `ALTER ROLE aec_app PASSWORD '<secret>'` out of band (or manage the
password via their secrets store / RDS IAM). `CREATE ROLE` runs only
when the role doesn't exist, so re-running this migration against a
prod DB with a rotated password is safe.

Revision ID: 0010_app_role
Revises: 0009_codeguard_hnsw
Create Date: 2026-04-23
"""

from __future__ import annotations

from alembic import op

revision = "0010_app_role"
down_revision = "0009_codeguard_hnsw"
branch_labels = None
depends_on = None


# Keep in sync with docker-compose's DATABASE_URL and the RLS test fixture.
_APP_ROLE = "aec_app"
_APP_PASSWORD_DEV_DEFAULT = "aec_app"


def upgrade() -> None:
    # Create the role if missing. DO block lets us stay idempotent without
    # requiring Postgres 9.6+ CREATE ROLE IF NOT EXISTS (which doesn't exist —
    # Postgres has no IF NOT EXISTS on CREATE ROLE even today).
    #
    # NOBYPASSRLS is the critical bit: without it, a role with membership in a
    # superuser group could still ignore policies. NOSUPERUSER is belt-and-
    # braces.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                CREATE ROLE {_APP_ROLE}
                    LOGIN
                    NOSUPERUSER
                    NOBYPASSRLS
                    NOCREATEDB
                    NOCREATEROLE
                    PASSWORD '{_APP_PASSWORD_DEV_DEFAULT}';
            END IF;
        END
        $$;
        """
    )

    # Schema + existing-object grants. `GRANT ... ON ALL TABLES` only affects
    # tables that exist *right now*, so we pair it with ALTER DEFAULT
    # PRIVILEGES below for future tables.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")

    # Future-proofing: any table/sequence subsequently created by `aec` (the
    # migration role) auto-grants the same DML to aec_app. Without this,
    # every new migration would need its own GRANT block — easy to forget,
    # and a forgotten grant manifests as a runtime "permission denied for
    # table X" after deploy.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE aec IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE aec IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {_APP_ROLE}"
    )


def downgrade() -> None:
    # Revoke future-table grants first, then existing-object grants, then
    # drop the role. Order matters: DROP ROLE fails if the role still owns
    # or has privileges on any object.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE aec IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE aec IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {_APP_ROLE}"
    )
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {_APP_ROLE}")
