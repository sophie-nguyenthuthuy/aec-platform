"""Billing plans, limits, and plan-gate helpers.

Plan catalogue lives here (not in the DB) so adding a new tier or
changing pricing is a code change with a clear PR diff. Customer-
visible plan choice is reflected on `subscriptions.plan`; the
hard limits + AI quotas + module gates are looked up from this dict.

Two billing rails:

  * **Stripe** — international cards. Used by foreign-owned EPCs +
    private-sector customers. Webhook-driven subscription lifecycle.
  * **VietQR** — domestic bank transfer with a memorable reference
    string in the memo. Standard Vietnamese B2B payment flow; SOE
    customers reject card billing for procurement-compliance reasons.

The VietQR path is operator-confirmed (an ops admin marks the
invoice paid when the bank statement matches the reference). No
automatic reconciliation — Vietnamese banks don't expose a clean
webhook API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal


PlanSlug = Literal["starter", "pro", "enterprise"]


@dataclass(frozen=True)
class PlanDefinition:
    slug: PlanSlug
    name_vi: str
    # Pricing — monthly billing cycle. None for `enterprise` (custom).
    price_vnd_monthly: int | None
    price_usd_monthly: int | None
    # Hard caps. None = unlimited.
    max_users: int | None
    max_projects: int | None
    max_drawings_gb: int | None
    # AI quotas — multiplier against the org's monthly codeguard quota.
    ai_quota_multiplier: float
    # Display blurb on the pricing page.
    tagline_vi: str
    features_vi: tuple[str, ...]


PLANS: dict[PlanSlug, PlanDefinition] = {
    "starter": PlanDefinition(
        slug="starter",
        name_vi="Khởi đầu",
        price_vnd_monthly=0,
        price_usd_monthly=0,
        max_users=3,
        max_projects=1,
        max_drawings_gb=2,
        ai_quota_multiplier=0.2,
        tagline_vi="Miễn phí cho nhóm 1-3 người đang đánh giá nền tảng.",
        features_vi=(
            "1 dự án",
            "3 thành viên",
            "2 GB lưu trữ bản vẽ",
            "200 lượt CodeGuard/tháng",
            "Tất cả 14 module — không khoá tính năng",
        ),
    ),
    "pro": PlanDefinition(
        slug="pro",
        name_vi="Chuyên nghiệp",
        price_vnd_monthly=4_900_000,
        price_usd_monthly=199,
        max_users=25,
        max_projects=10,
        max_drawings_gb=50,
        ai_quota_multiplier=1.0,
        tagline_vi="Cho nhà thầu tầm trung quản lý vài dự án song song.",
        features_vi=(
            "10 dự án",
            "25 thành viên",
            "50 GB lưu trữ bản vẽ",
            "1.000 lượt CodeGuard/tháng",
            "PDF báo cáo dự án + biên bản bàn giao",
            "Xuất KTNN audit log",
            "Email hỗ trợ trong ngày làm việc",
        ),
    ),
    "enterprise": PlanDefinition(
        slug="enterprise",
        name_vi="Doanh nghiệp",
        price_vnd_monthly=None,
        price_usd_monthly=None,
        max_users=None,
        max_projects=None,
        max_drawings_gb=None,
        ai_quota_multiplier=5.0,
        tagline_vi="Cho SOE, tổng thầu lớn, hoặc nhà thầu yêu cầu deploy on-prem.",
        features_vi=(
            "Không giới hạn dự án + người dùng",
            "Lưu trữ bản vẽ tuỳ chọn (MinIO on-prem hoặc cloud)",
            "SSO Microsoft Entra + Google Workspace",
            "SLA 99.9% — cam kết uptime trong hợp đồng",
            "Hỗ trợ qua hotline + Slack dùng chung",
            "Custom QCVN ingest (regulation riêng của khách hàng)",
        ),
    ),
}


def plan_definition(plan: str) -> PlanDefinition:
    """Look up a plan by slug. Falls back to `starter` for unknown
    values so a bad data row doesn't 500 the gate check — instead
    the user gets the minimum tier until ops fixes the row."""
    if plan in PLANS:
        return PLANS[plan]  # type: ignore[index]
    return PLANS["starter"]


# ---------- VietQR reference helpers ----------


def make_vietqr_reference(*, organization_id: str, plan: PlanSlug) -> str:
    """Build a memorable transfer-memo reference.

    Format: `AEC-<PLAN>-<YYYYMM>-<ORG8>` where ORG8 is the first 8
    chars of the org UUID. The pattern is recognisable in the bank
    statement export so an ops admin can grep for `AEC-PRO-` and
    match against pending subscriptions in bulk.
    """
    yyyymm = datetime.now(UTC).strftime("%Y%m")
    org_prefix = organization_id.replace("-", "")[:8].upper()
    return f"AEC-{plan.upper()}-{yyyymm}-{org_prefix}"


# ---------- Period helpers ----------


def next_period_end(plan: PlanSlug, *, from_dt: datetime | None = None) -> datetime:
    """Return the period end for a one-month billing cycle.

    Vietnamese B2B convention: monthly bank transfers are the norm;
    annual prepay gets a discount but isn't the default. We standardise
    on +30 days so a transfer that lands on the 31st of one month
    doesn't expire on the 28th of February.
    """
    start = from_dt or datetime.now(UTC)
    return start + timedelta(days=30)


# ---------- Module gate helper ----------


def can_use_feature(plan: str, feature: str) -> bool:
    """Boolean: is this feature available on the given plan?

    Module gating is intentionally lightweight — the platform's pitch
    is "all 14 modules included on every plan". The only gates are:

      * `pdf_reports` — Pro + Enterprise
      * `audit_export` — Pro + Enterprise (KTNN customers buy Pro at minimum)
      * `sso` — Enterprise only
      * `priority_support` — Pro + Enterprise

    Add new feature gates here as we ship Pro/Enterprise-only
    features. Returning True for unknown features means "default
    available to everyone" — safer than accidentally locking a
    new feature behind a gate that hasn't been priced yet.
    """
    if plan == "enterprise":
        return True
    if plan == "pro":
        return feature in {
            "pdf_reports",
            "audit_export",
            "priority_support",
            "import_wizard",
        }
    # starter
    return feature not in {
        "pdf_reports",
        "audit_export",
        "sso",
        "priority_support",
    }
