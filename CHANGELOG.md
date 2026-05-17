# Changelog

All notable changes to AEC Platform.

Format inspired by [Keep a Changelog](https://keepachangelog.com/).
Versioning follows [Semantic Versioning](https://semver.org/) —
**MAJOR.MINOR.PATCH**:
* **MAJOR** — breaking API change, schema migration that requires
  downtime, or a deliberate cross-tenant data shift.
* **MINOR** — new module, new endpoint, additive schema migration.
* **PATCH** — bug fix, performance improvement, doc update, internal
  refactor.

The `VERSION` file at the repo root is the single source of truth.
`scripts/release.sh` reads it; the api + web both read it at
build/import time. CI tags `v{VERSION}` on every commit where the
file changes.

---

## [Unreleased]

Tracks work-in-progress on `main` ahead of the next tag. Lines move
into a versioned section when a release ships.

---

## [1.0.0] — 2026-05-15

First production-ready release. 20 modules, end-to-end onboarding,
billing, AI eval harness, multi-region failover scaffolding,
public marketing site + status page, sales playbook + 24 demo
video scripts, 1080+ tests green.

### Added — Modules (20 total)

* **WinWork** — proposal authoring with AI scope generation.
* **BidRadar** — gov tender scraping + AI scoring.
* **CostPulse** — BOQ + supplier RFQ flow.
* **CodeGuard** — QCVN/TCVN compliance scan, regulation Q&A,
  checklist export.
* **Drawbridge** — drawing PDF ingest + Q&A with citations,
  conflict scan.
* **Pulse** — kanban, milestones, change orders, meetings, weekly
  client reports.
* **SchedulePilot** — CPM Gantt, baseline tracking, AI risk forecast.
* **SiteEye** — mobile photo upload + YOLO PPE detection + weekly
  safety report.
* **PermitFlow** — building permit application tracking.
* **PCCC** — fire safety certification.
* **Handover** — closeout checklist, as-built drawings, O&M manuals,
  handover certificate PDF.
* **Punchlist** — close-out item tracker.
* **Daily log** — site daily report.
* **Change orders** — full lifecycle with cost + schedule impact.
* **CashFlow** — project inflow/outflow forecast + actuals.
* **SafetyToolboxTalks** — daily safety briefings (Nghị định
  06/2021 compliance).
* **SubcontractorPortal** — token-auth public portal for nhà thầu phụ.
* **EquipmentRental** — máy thi công thuê tracking + idle alerts.
* **MaterialPriceIndex** — Sở Xây dựng province bulletin data
  surface (compare / time series / latest).
* **WarrantyTracker** — claims workflow + auto-reminders 60/30/7d
  before expiry.

### Added — Platform

* Onboarding wizard (4-step new-user flow with seed-demo).
* Billing: Stripe + VietQR with subscription tracking.
* LLM cost tracking per-org per-module.
* Real-time presence indicators (Supabase Realtime).
* Public landing + pricing page + status page.
* Background job dashboard (/admin/jobs).
* Background admin setup-status page surfacing integration
  configuration state without leaking secrets.
* PWA + Capacitor mobile shell scaffolding.
* SSO Google + Microsoft Entra.
* Resend transactional email backend (Resend → SMTP fallback).
* Sentry observability wiring.
* KTNN audit log export (CSV + XLSX with SHA-256 provenance).
* PDF reports: project summary + handover certificate.
* MinIO S3-compatible storage layer.
* Vietnamese user guide docs (docs/huong-dan-su-dung/).
* 24-video walkthrough scripts (demo/VIDEO-SCRIPTS/).
* Sales playbook (outbound emails, discovery, prospect profiles).

### Added — Engineering

* AI quality eval harness (CodeGuard + Drawbridge curated Q&A
  with HTML reports).
* Redis read cache for hot dashboard paths.
* Multi-region failover runbook (Singapore → Tokyo).
* Deploy-verification script (`make verify-deploy`) +
  integration-status admin API.
* Environment checklist generator (`make env-checklist`).
* Cross-platform docs/performance.md operating manual.

### Changed

* All sidebar labels Vietnamese-first.
* Default landing for unauthed users: marketing page (was: redirect
  to /winwork).
* Post-login redirect goes to `/inbox` (was `/`).
* `/health/ready` adds storage + migration + codeguard-regs sub-probes
  (token-free).

### Migration history

0001 → 0055. Every migration applied via Alembic. Major DDL
events:

* 0005 — CodeGuard regulations + pgvector(3072 → 768 via 0041)
* 0022 — Audit events (org-scoped, append-only)
* 0029 — Import jobs (CSV/XLSX bulk import staging)
* 0050 — Billing subscriptions + invoices
* 0051 — LLM spend events
* 0052 — Cashflow entries + actuals
* 0053 — Safety toolbox talks + attendance
* 0054 — Subcontractor portal grants + assignments + progress events
* 0055 — Warranty claims + reminders sent

### Operational notes

* Production deploy: Railway api + worker, Vercel web, Supabase
  Singapore PostgreSQL, Upstash Redis, MinIO or AWS S3.
* Plans: Khởi đầu (free) / Chuyên nghiệp (4.9M VNĐ/tháng) /
  Doanh nghiệp (custom).
* All 20 modules available on every plan; only limits + advanced
  features (SSO, on-prem MinIO, KTNN export, SLA) differ by tier.

---

## Versioning conventions going forward

* **Patch (1.0.x)** — bug fixes, doc updates, perf, internal
  refactors. Released as needed, often multiple per week.
* **Minor (1.x.0)** — new module, new endpoint, additive schema.
  Released ~monthly.
* **Major (x.0.0)** — breaking API change OR schema requiring
  downtime. Released ~yearly with a clear migration guide.
