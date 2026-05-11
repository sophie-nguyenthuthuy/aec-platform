#!/usr/bin/env bash
#
# Bootstrap a fresh Supabase Postgres for the AEC platform:
#   1. Verify the connection works
#   2. Enable pgvector
#   3. Run alembic migrations (33 of them, last we counted)
#   4. Seed demo data — populates 1 org + 1 project + sample data
#      across every module so the UI renders something useful
#
# Idempotent — re-running upserts existing rows by stable natural keys,
# so it's safe to run multiple times.
#
# Usage:
#   export DATABASE_URL_SYNC="postgresql://postgres:[PWD]@db.[REF].supabase.co:5432/postgres"
#   export DATABASE_URL="postgresql+asyncpg://postgres:[PWD]@db.[REF].supabase.co:5432/postgres"
#   export OPENAI_API_KEY="sk-..."        # optional, for embedding seeds
#   export ANTHROPIC_API_KEY="sk-ant-..." # optional, for LLM seed previews
#   ./scripts/init-supabase.sh

set -euo pipefail

# --- locate repo root regardless of CWD ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$REPO_ROOT"

# --- preflight ---
if [ -z "${DATABASE_URL_SYNC:-}" ]; then
  echo "ERROR: DATABASE_URL_SYNC not set. See deploy/DEPLOY.md step 1." >&2
  exit 2
fi
if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL not set (async URL). See deploy/DEPLOY.md step 1." >&2
  exit 2
fi

# Need a virtualenv or a system python with apps/api/requirements.txt installed.
if [ ! -d "apps/api/.venv" ]; then
  echo "==> Creating virtualenv at apps/api/.venv"
  python3 -m venv apps/api/.venv
fi
# shellcheck disable=SC1091
source apps/api/.venv/bin/activate

echo "==> Installing apps/api/requirements.txt (this can take ~2 minutes)"
pip install --quiet --upgrade pip
pip install --quiet -r apps/api/requirements.txt
pip install --quiet -r apps/ml/requirements.txt

# --- step 1: verify connection ---
echo "==> Verifying connection to Postgres"
python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL_SYNC"]
eng = create_engine(url)
with eng.connect() as c:
    v = c.execute(text("select version()")).scalar()
    print(f"   {v}")
PY

# --- step 2: enable pgvector ---
echo "==> Enabling pgvector extension"
python - <<'PY'
import os
from sqlalchemy import create_engine, text
url = os.environ["DATABASE_URL_SYNC"]
eng = create_engine(url)
with eng.begin() as c:
    c.execute(text("create extension if not exists vector"))
PY

# --- step 3: alembic migrations ---
echo "==> Running alembic upgrade head"
( cd apps/api && alembic upgrade head )

# --- step 4: seed demo data ---
echo "==> Seeding demo data"
( cd apps/api && PYTHONPATH=".:../:../ml" python -m scripts.seed_demo )

echo ""
echo "✅ Supabase initialised. Capture the printed dev JWT + org/project IDs above."
echo "   Next: deploy to Vercel — see deploy/DEPLOY.md step 4."
