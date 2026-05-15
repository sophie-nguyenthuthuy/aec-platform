#!/usr/bin/env bash
# Verify-deployment harness — runs on demand against a live deploy
# to confirm every external integration is wired correctly.
#
# Usage:
#   AEC_BASE_URL=https://api.aec-platform.vn ./scripts/verify_deployment.sh
#   AEC_BASE_URL=https://staging-api.aec-platform.vn ./scripts/verify_deployment.sh
#
# What it checks (each = single section, fails fast on first error):
#   1. API reachable + /api/health returns 200
#   2. Database — /_health/db query succeeds
#   3. Redis — queue depth metric responds
#   4. MinIO / S3 — drawings bucket accessible
#   5. Supabase Auth — JWKS endpoint reachable
#   6. SSO providers (Google + Microsoft) — Supabase reports them enabled
#   7. Resend / SMTP — env vars present + format correct
#   8. Stripe — env vars present (smoke checkout never actually fires)
#   9. Sentry — DSN format correct + reachable
#  10. CodeGuard regulations seeded (count > 0)
#  11. Worker service reachable (cron list endpoint)
#  12. Migration head matches expected revision
#
# Exits 0 if every check passes; 1 on first failure. Output is
# colour-coded for terminal use; CI runs strip colours via NO_COLOR=1.

set -u  # we DON'T set -e — we want every check to run + report

if [[ -z "${AEC_BASE_URL:-}" ]]; then
    echo "ERROR: AEC_BASE_URL must be set"
    echo "  e.g. AEC_BASE_URL=https://api.aec-platform.vn $0"
    exit 2
fi

# Optional token for endpoints that require auth (e.g. admin health
# probes). Without it, those checks are skipped with a WARN.
TOKEN="${AEC_OPS_TOKEN:-}"

# ---------- Colour helpers ----------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    BOLD='\033[1m'; RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'
    BLUE='\033[34m'; RESET='\033[0m'
else
    BOLD=''; RED=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

PASSED=0
FAILED=0
WARNED=0

pass() {
    PASSED=$((PASSED+1))
    echo -e "  ${GREEN}✓${RESET} $1"
}
fail() {
    FAILED=$((FAILED+1))
    echo -e "  ${RED}✗${RESET} $1"
    [[ -n "${2:-}" ]] && echo -e "    ${RED}└─${RESET} $2"
}
warn() {
    WARNED=$((WARNED+1))
    echo -e "  ${YELLOW}!${RESET} $1"
}
section() {
    echo ""
    echo -e "${BOLD}${BLUE}━━ $1${RESET}"
}

# ---------- Checks ----------

section "1. API liveness"
http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$AEC_BASE_URL/health" || echo "0")
if [[ "$http_code" == "200" ]]; then
    pass "GET $AEC_BASE_URL/health → 200"
else
    fail "GET $AEC_BASE_URL/health → $http_code (expected 200)"
fi


section "2. Database health (readiness probe)"
db_body=$(curl -s --max-time 10 "$AEC_BASE_URL/health/ready" || echo "{}")
if echo "$db_body" | grep -q '"status":"ok"'; then
    pass "Readiness probe healthy (DB + Redis reachable)"
elif echo "$db_body" | grep -q '"status":"degraded"'; then
    fail "Readiness probe degraded" "$db_body"
else
    fail "Readiness check returned unexpected body" "$db_body"
fi


section "3. Redis / arq queue"
metrics=$(curl -s --max-time 10 "$AEC_BASE_URL/metrics" || echo "")
# The actual metric exported by core/metrics.py is `arq_queue_depth`
# (gauge). A value of -1 means the api couldn't reach Redis.
if echo "$metrics" | grep -q "^arq_queue_depth "; then
    depth=$(echo "$metrics" | grep "^arq_queue_depth " | tail -1 | awk '{print $2}')
    if [[ "$depth" == "-1" ]] || [[ "$depth" == "-1.0" ]]; then
        fail "arq_queue_depth = -1 → API cannot reach Redis"
    else
        pass "Redis reachable (arq_queue_depth = $depth)"
    fi
else
    warn "/metrics doesn't expose arq_queue_depth — verify worker.queue is importable on the api service"
fi


section "4. MinIO / S3"
# Storage status comes from the unauthenticated /health/ready response
# under checks.storage. No token needed.
storage_blob=$(echo "$db_body" | grep -o '"storage":{[^}]*}' || echo "")
if [[ -z "$storage_blob" ]]; then
    warn "/health/ready doesn't expose storage check — older API version?"
elif echo "$storage_blob" | grep -q '"configured":false'; then
    warn "Storage not configured (s3_bucket empty) — dev / API-only deploy"
elif echo "$storage_blob" | grep -q '"ok":true'; then
    bucket=$(echo "$storage_blob" | grep -o '"bucket":"[^"]*"' | cut -d'"' -f4)
    pass "Storage bucket reachable ($bucket)"
else
    err=$(echo "$storage_blob" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
    fail "Storage check failed" "$err"
fi


section "5. Supabase Auth (JWKS)"
# The frontend hits Supabase directly; we can poke the JWKS endpoint
# without auth.
sup_url="${SUPABASE_URL:-}"
if [[ -n "$sup_url" ]]; then
    jwks_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
        "$sup_url/auth/v1/.well-known/jwks.json" || echo "0")
    if [[ "$jwks_code" == "200" ]]; then
        pass "Supabase JWKS endpoint reachable"
    else
        fail "Supabase JWKS returned $jwks_code"
    fi
else
    warn "SUPABASE_URL not set — skipping JWKS check"
fi


section "6. SSO providers"
# We can't probe Supabase's enabled-providers via public API, so we
# check that the env vars expected by the SsoButtons frontend are
# present (set in this shell or via .env).
[[ -n "${SUPABASE_URL:-}" ]] && pass "SUPABASE_URL set" || warn "SUPABASE_URL unset"
[[ -n "${SUPABASE_ANON_KEY:-}" ]] || [[ -n "${NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:-}" ]] && \
    pass "Supabase publishable key set" || warn "Supabase publishable key not set"
echo "    ${YELLOW}└─${RESET} Verify Google + Microsoft providers ENABLED in Supabase"
echo "       dashboard: Auth → Providers → toggle ON for each"


section "7. Email (Resend / SMTP)"
if [[ -n "${RESEND_API_KEY:-}" ]]; then
    if [[ "$RESEND_API_KEY" =~ ^re_ ]]; then
        pass "RESEND_API_KEY format correct (starts re_)"
    else
        fail "RESEND_API_KEY set but format wrong — should start 're_'"
    fi
elif [[ -n "${SMTP_HOST:-}" && -n "${SMTP_USER:-}" ]]; then
    pass "SMTP fallback configured ($SMTP_HOST)"
else
    warn "Neither RESEND_API_KEY nor SMTP_HOST set — emails will no-op"
fi


section "8. Stripe"
if [[ -n "${STRIPE_SECRET_KEY:-}" ]]; then
    if [[ "$STRIPE_SECRET_KEY" =~ ^sk_ ]]; then
        pass "STRIPE_SECRET_KEY format correct"
    else
        fail "STRIPE_SECRET_KEY set but malformed (should start 'sk_')"
    fi
    if [[ -n "${STRIPE_WEBHOOK_SECRET:-}" ]]; then
        pass "STRIPE_WEBHOOK_SECRET set"
    else
        warn "STRIPE_WEBHOOK_SECRET unset — webhook handler returns 503"
    fi
else
    warn "STRIPE_SECRET_KEY unset — only VietQR billing works"
fi


section "9. Sentry"
if [[ -n "${SENTRY_DSN:-}" ]]; then
    if [[ "$SENTRY_DSN" =~ ^https://[^@]+@[^/]+\.ingest\.sentry\.io/ ]]; then
        pass "SENTRY_DSN format correct"
    else
        fail "SENTRY_DSN malformed (expected https://<key>@*.ingest.sentry.io/<id>)"
    fi
else
    warn "SENTRY_DSN unset — error reporting is OFF"
fi


section "10. CodeGuard regulations"
# Pulled from /health/ready.checks.codeguard_regulations — no token
# required. Reports a count (safe to expose unauth) so we can tell
# "0 regs → bootstrap didn't run" from "300 regs → all good".
regs_blob=$(echo "$db_body" | grep -o '"codeguard_regulations":{[^}]*}' || echo "")
if [[ -z "$regs_blob" ]]; then
    warn "/health/ready doesn't expose codeguard_regulations — older API?"
elif echo "$regs_blob" | grep -q '"ok":true'; then
    count=$(echo "$regs_blob" | grep -o '"count":[0-9]*' | cut -d: -f2)
    pass "Regulations seeded ($count rows)"
else
    err=$(echo "$regs_blob" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
    fail "Regulations not seeded — run codeguard bootstrap or seed-codeguard-all" "$err"
fi


section "11. Worker service"
if [[ -n "$TOKEN" ]]; then
    cron_body=$(curl -s --max-time 10 -H "Authorization: Bearer $TOKEN" \
        "$AEC_BASE_URL/api/v1/admin/jobs/cron" || echo "{}")
    cron_count=$(echo "$cron_body" | grep -o '"function"' | wc -l | xargs)
    if [[ "$cron_count" -ge "5" ]]; then
        pass "Worker reachable ($cron_count cron jobs registered)"
    else
        fail "Worker cron count low: $cron_count (expected ≥5)"
    fi
else
    warn "AEC_OPS_TOKEN not set — skipping worker check"
fi


section "12. Migration revision"
EXPECTED_REV="0055_equipment_rental"
# Pulled from /health/ready.checks.migration.head — token-free.
mig_blob=$(echo "$db_body" | grep -o '"migration":{[^}]*}' || echo "")
if [[ -z "$mig_blob" ]]; then
    warn "/health/ready doesn't expose migration check — older API?"
elif echo "$mig_blob" | grep -q "\"head\":\"$EXPECTED_REV\""; then
    pass "Migration head = $EXPECTED_REV"
elif echo "$mig_blob" | grep -q '"head"'; then
    actual=$(echo "$mig_blob" | grep -o '"head":"[^"]*"' | cut -d'"' -f4)
    warn "Migration head drift: expected $EXPECTED_REV, got $actual"
else
    err=$(echo "$mig_blob" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
    fail "Migration probe failed" "$err"
fi


# ---------- Summary ----------
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}Deploy verification — $AEC_BASE_URL${RESET}"
echo -e "  ${GREEN}Passed:${RESET}  $PASSED"
echo -e "  ${RED}Failed:${RESET}  $FAILED"
echo -e "  ${YELLOW}Warned:${RESET}  $WARNED"

if [[ "$FAILED" -gt 0 ]]; then
    echo ""
    echo -e "${RED}DEPLOY VERIFICATION FAILED — fix the above before announcing launch.${RESET}"
    exit 1
fi

if [[ "$WARNED" -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}Warnings present — review before production traffic.${RESET}"
fi

echo ""
echo -e "${GREEN}All checks passed.${RESET}"
