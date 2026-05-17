#!/usr/bin/env bash
# Print an actionable env-var checklist for a given Railway service.
#
# Usage:
#   ./scripts/setup_env_checklist.sh api      # required env for the api service
#   ./scripts/setup_env_checklist.sh worker   # required env for the worker service
#   ./scripts/setup_env_checklist.sh all
#
# Output is grouped by priority:
#   - CRITICAL: deploy won't function without these
#   - IMPORTANT: features degrade silently without these
#   - OPTIONAL: nice-to-have
#
# Each var has:
#   - Name + brief description
#   - Format example (no real secrets)
#   - Where to get the value
#
# Designed for paste-into-ticket workflows when handing off to ops.

set -u

target="${1:-all}"

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    BOLD='\033[1m'; RED='\033[31m'; YELLOW='\033[33m'; GREEN='\033[32m'
    BLUE='\033[34m'; DIM='\033[2m'; RESET='\033[0m'
else
    BOLD=''; RED=''; YELLOW=''; GREEN=''; BLUE=''; DIM=''; RESET=''
fi

print_var() {
    local pri="$1" name="$2" example="$3" source="$4"
    case "$pri" in
        critical) color="$RED" ;;
        important) color="$YELLOW" ;;
        optional)  color="$DIM" ;;
        *)         color="$RESET" ;;
    esac
    printf "  ${color}%-32s${RESET} ${DIM}# %s${RESET}\n" "$name" "$source"
    printf "    ${DIM}Example: %s${RESET}\n" "$example"
}

print_header() {
    local title="$1"
    echo ""
    echo -e "${BOLD}${BLUE}━━ $title ━━${RESET}"
}


api_env() {
    print_header "API service ($BOLD${target}${RESET}${BOLD}${BLUE}) — Railway → aec-platform-api → Variables"
    echo ""
    echo -e "${BOLD}CRITICAL (deploy will not work without these):${RESET}"
    print_var critical "DATABASE_URL" "postgresql+asyncpg://postgres.<ref>:<pwd>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres" "Supabase Settings → Database → Connection pooling (Transaction)"
    print_var critical "DATABASE_URL_ADMIN" "postgresql+asyncpg://postgres.<ref>:<pwd>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres" "Supabase Connection pooling (Session) — superuser for cron"
    print_var critical "DATABASE_URL_SYNC" "postgresql://postgres:<pwd>@db.<ref>.supabase.co:5432/postgres" "Supabase Direct connection (NOT pooler) — for alembic"
    print_var critical "REDIS_URL" "rediss://default:<pwd>@<region>-redis.upstash.io:6379" "Upstash → DB → Details → Connect → TLS"
    print_var critical "SUPABASE_URL" "https://YOUR-PROJECT-REF.supabase.co" "Supabase → Settings → API"
    print_var critical "SUPABASE_JWT_SECRET" "<copy from Supabase>" "Supabase → Settings → API → JWT secret"
    print_var critical "SUPABASE_SECRET_KEY" "sb_secret_..." "Supabase → Settings → API → service_role key"
    print_var critical "AEC_ENV" "production" "Use 'production' for prod deploys"

    echo ""
    echo -e "${BOLD}IMPORTANT (features silently broken without):${RESET}"
    print_var important "GOOGLE_API_KEY" "AIza..." "Google AI Studio → Get API key"
    print_var important "SENTRY_DSN" "https://<key>@o123.ingest.sentry.io/<project>" "Sentry → Project → Client Keys (DSN)"
    print_var important "S3_BUCKET" "aec-platform-files" "Bucket name in MinIO/AWS S3"
    print_var important "S3_ENDPOINT_URL" "(leave EMPTY for AWS S3, or http://minio.x.vn:9000 for MinIO)" "Only set for MinIO"
    print_var important "S3_ACCESS_KEY_ID" "<MinIO access key OR AWS access key>" "Required for MinIO; optional for AWS if using IAM role"
    print_var important "S3_SECRET_ACCESS_KEY" "<MinIO secret OR AWS secret>" "Required for MinIO; optional for AWS if using IAM role"
    print_var important "AWS_REGION" "ap-southeast-1" "AWS region for S3, or MinIO region label"
    print_var important "RESEND_API_KEY" "re_..." "Resend → Settings → API keys"
    print_var important "RESEND_FROM" "AEC Platform <no-reply@aec-platform.vn>" "Must use verified Resend domain"

    echo ""
    echo -e "${BOLD}OPTIONAL (nice-to-have):${RESET}"
    print_var optional "STRIPE_SECRET_KEY" "sk_live_..." "Stripe Dashboard → Developers → API keys"
    print_var optional "STRIPE_WEBHOOK_SECRET" "whsec_..." "Stripe → Webhooks → Add endpoint → /api/v1/billing/webhooks/stripe"
    print_var optional "STRIPE_PRICE_PRO_USD" "price_..." "Stripe → Products → Chuyên nghiệp Monthly"
    print_var optional "BILLING_BANK_NAME" "Vietcombank — CN Hà Nội" "VietQR receiving bank info"
    print_var optional "BILLING_BANK_ACCOUNT" "0011004212345" "Bank account number"
    print_var optional "BILLING_BANK_HOLDER" "CONG TY CO PHAN AEC PLATFORM" "Account holder name (no diacritics)"
    print_var optional "SENTRY_TRACES_SAMPLE_RATE" "0.1" "Default 0.1 = 10% requests traced"
    print_var optional "WEB_BASE_URL" "https://aec-platform-web.vercel.app" "Used for absolute URLs in emails"
    print_var optional "CORS_ORIGINS" '["https://aec-platform-web.vercel.app"]' "JSON array of allowed origins"
}


worker_env() {
    print_header "Worker service — Railway → aec-platform-worker → Variables"
    echo ""
    echo -e "${BOLD}Worker needs SAME critical + important env as api${RESET}"
    echo -e "${DIM}(database, redis, supabase, google_api_key, s3, resend)${RESET}"
    echo ""
    echo -e "${BOLD}Worker-specific:${RESET}"
    print_var optional "SITEEYE_RAY_SERVE_URL" "http://siteeye-safety:8000" "Ray Serve YOLO inference URL (default: local docker network)"
    print_var optional "SITEEYE_YOLO_WEIGHTS" "s3://aec-platform-models/siteeye/yolov8m-safety-vi.pt" "Path to YOLO weights"
    print_var optional "CODEGUARD_BOOTSTRAP_DISABLED" "" "Set to '1' to skip first-boot codeguard ingest (default: enabled)"
}


supabase_config() {
    print_header "Supabase dashboard config (NOT env vars — toggle in UI)"
    echo ""
    echo -e "${BOLD}Authentication → Providers:${RESET}"
    echo "  ☐ Google — toggle ON, paste Client ID + Secret from Google Cloud"
    echo "  ☐ Azure (Microsoft) — toggle ON, paste Application ID + Secret + Tenant URL"
    echo "  ☐ Email — toggle ON (already default)"
    echo ""
    echo -e "${BOLD}Authentication → URL Configuration → Redirect URLs:${RESET}"
    echo "  Add (without trailing slash):"
    echo "    https://aec-platform-web.vercel.app/auth/callback"
    echo "    https://aec-platform-web.vercel.app/auth/callback?next=/**"
    echo "    http://localhost:3000/auth/callback"
    echo ""
    echo -e "${BOLD}Database → Database Settings → Connection pooling:${RESET}"
    echo "  ☐ Confirm pooler enabled in 'Transaction' mode"
    echo "  ☐ Note both pooler URL (port 5432) + direct URL (port 5432) — both needed"
}


vercel_env() {
    print_header "Vercel web service — Project → Settings → Environment Variables"
    echo ""
    echo -e "${BOLD}Required (Production + Preview scope):${RESET}"
    print_var critical "NEXT_PUBLIC_SUPABASE_URL" "https://YOUR-PROJECT-REF.supabase.co" "Same as SUPABASE_URL on Railway"
    print_var critical "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY" "eyJ..." "Supabase → Settings → API → anon/publishable key"
    print_var critical "NEXT_PUBLIC_API_URL" "https://aec-platform-production.up.railway.app" "Railway api service public URL"

    echo ""
    echo -e "${BOLD}Optional but recommended:${RESET}"
    print_var optional "NEXT_PUBLIC_AEC_REALTIME" "on" "Set 'off' to disable presence indicators"
    print_var optional "NEXT_PUBLIC_SENTRY_DSN" "(same DSN as backend)" "Browser-side error reporting"
    print_var optional "NEXT_PUBLIC_AEC_ENV" "production" "Tags Sentry events"
}


verify_steps() {
    print_header "Verify after setting all of the above"
    echo ""
    echo "1. Wait ~5 minutes for Railway / Vercel to redeploy."
    echo "2. Run:"
    echo -e "   ${GREEN}AEC_BASE_URL=https://aec-platform-production.up.railway.app \\${RESET}"
    echo -e "   ${GREEN}    ./scripts/verify_deployment.sh${RESET}"
    echo ""
    echo "3. Expected output: 12 ✓ / 0 ✗ / 0 ⚠"
    echo ""
    echo "4. Sign up a test account, walk through onboarding wizard,"
    echo "   verify Google/Microsoft SSO works."
    echo ""
    echo "5. Check ${BLUE}/admin/setup-status${RESET} in the app — should show 'Sẵn sàng launch' verdict."
}


case "$target" in
    api)
        api_env
        verify_steps
        ;;
    worker)
        worker_env
        verify_steps
        ;;
    supabase)
        supabase_config
        ;;
    vercel)
        vercel_env
        ;;
    all)
        api_env
        worker_env
        supabase_config
        vercel_env
        verify_steps
        ;;
    *)
        echo "Usage: $0 {api|worker|supabase|vercel|all}"
        exit 2
        ;;
esac

echo ""
echo -e "${DIM}Full runbook: deploy/LAUNCH-CHECKLIST.md${RESET}"
echo -e "${DIM}Latest gap report: deploy/PROD-GAPS-2026-05-15.md${RESET}"
