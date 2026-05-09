import Link from "next/link";
import { Activity, AlertTriangle, Gauge, ShieldCheck } from "lucide-react";


/**
 * Ops documentation — health probes + Prometheus scrape config.
 *
 * Static (server-rendered). The metric names + label shapes here are
 * the contract dashboards / alerts will be built on; the test
 * `test_metrics_emits_canonical_gauges` pins the same names on the
 * backend side, so a refactor that changes one and not the other
 * breaks CI.
 *
 * Source of truth: `apps/api/routers/ops.py`. If a new gauge lands
 * there, mirror the row + description here.
 */
export default function OpsDocsPage() {
  return (
    <div className="prose prose-slate max-w-none space-y-10 text-sm">
      <header className="not-prose space-y-2">
        <div className="flex items-center gap-2">
          <Activity size={20} className="text-blue-600" />
          <h1 className="text-2xl font-bold text-slate-900">Ops endpoints</h1>
        </div>
        <p className="text-sm text-slate-600">
          Probes ops dùng để wire vào k8s/ECS health checks +
          Prometheus scrape config. Mọi endpoint mounted ở root (không
          có <code>/api/v1</code> prefix) để khớp với cluster
          conventions.
        </p>
      </header>

      {/* ---------- Probes ---------- */}
      <section>
        <h2 id="probes" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          <ShieldCheck size={16} className="mr-1 inline align-text-top text-slate-500" />
          Health probes
        </h2>
        <div className="not-prose mt-3 overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-[11px] uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Endpoint</th>
                <th className="px-3 py-2">Hành vi</th>
                <th className="px-3 py-2">Khuyến nghị</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="px-3 py-2 font-mono">GET /healthz</td>
                <td className="px-3 py-2">
                  Pure liveness — process lên là return 200. Không touch
                  DB, không touch Redis.
                </td>
                <td className="px-3 py-2">
                  Wire vào liveness probe. Period 10s, failure threshold 3.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">GET /readyz</td>
                <td className="px-3 py-2">
                  Ping Postgres + Redis. 200 nếu cả hai reachable; 503
                  với <code>{`{ postgres: { ok, error }, redis: {...} }`}</code>{" "}
                  nếu một trong hai down.
                </td>
                <td className="px-3 py-2">
                  Wire vào readiness probe + ALB health check. LB sẽ
                  remove pod khỏi rotation ngay khi 503.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="not-prose mt-3 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">
          <pre className="font-mono">
            <code>{`# k8s example
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  periodSeconds: 10
  failureThreshold: 3
readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
  periodSeconds: 15
  failureThreshold: 2`}</code>
          </pre>
        </div>
      </section>

      {/* ---------- Metrics ---------- */}
      <section>
        <h2 id="metrics" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          <Activity size={16} className="mr-1 inline align-text-top text-slate-500" />
          Prometheus metrics
        </h2>
        <p className="text-sm text-slate-600">
          <code>GET /metrics?token=&lt;value&gt;</code> trả về text-format
          gauges Prometheus parse được. Token đến từ env{" "}
          <code>AEC_METRICS_TOKEN</code> — production deploys PHẢI set
          (nếu unset, endpoint open cho mọi caller — chỉ dùng cho local
          dev).
        </p>
        <div className="not-prose mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <p>
            Endpoint chạy 5 SELECT/scrape — Prometheus mặc định scrape
            mỗi 15-60s, an toàn. Đừng setup scrape ở 1s trừ khi index
            đã được verify dưới load.
          </p>
        </div>

        <h3 className="not-prose mt-4 text-sm font-semibold text-slate-700">Gauges</h3>
        <div className="not-prose mt-2 overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-[11px] uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Metric</th>
                <th className="px-3 py-2">Labels</th>
                <th className="px-3 py-2">Mô tả</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="px-3 py-2 font-mono">aec_webhook_deliveries_total</td>
                <td className="px-3 py-2 font-mono text-slate-500">{`status="{pending|delivered|failed}"`}</td>
                <td className="px-3 py-2">
                  Số webhook deliveries tạo trong 5 phút gần nhất, theo
                  status. Cả 3 status luôn xuất hiện (zero-padded) để
                  alert "no data" khác alert "0 failed".
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">aec_webhook_outbox_lag_seconds</td>
                <td className="px-3 py-2 text-slate-400">—</td>
                <td className="px-3 py-2">
                  Tuổi của pending delivery cũ nhất. Tăng = retry cron
                  đang fall behind. Alert tiêu chuẩn: &gt; 300s trong 5
                  phút.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">aec_webhook_outbox_pending</td>
                <td className="px-3 py-2 text-slate-400">—</td>
                <td className="px-3 py-2">
                  Số pending deliveries. Pair với lag để phân biệt
                  "1 stuck row" với "10k backlog".
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">aec_api_key_calls_total</td>
                <td className="px-3 py-2 font-mono text-slate-500">{`success="{true|false}"`}</td>
                <td className="px-3 py-2">
                  Tổng api-key calls trong 5 phút, split theo
                  success (2xx/3xx) vs failure (4xx/5xx + 429). Alert:
                  failure rate &gt; 5% trong 10 phút.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">aec_search_queries_total</td>
                <td className="px-3 py-2 text-slate-400">—</td>
                <td className="px-3 py-2">
                  Số search queries logged trong 5 phút. Spike đột
                  biến = bot hammering /search.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">aec_audit_events_total</td>
                <td className="px-3 py-2 text-slate-400">—</td>
                <td className="px-3 py-2">
                  Số audit events written trong 5 phút. Alert: drop về
                  0 trên platform busy = audit hook bị broken.
                </td>
              </tr>
              {/* ---------- Codeguard quota cap-check series ---------- */}
              {/* Different shape from the rollup gauges above: the
                  codeguard counters/histograms come from
                  `apps/api/core/metrics.py` (stdlib renderer, not the
                  rollup-table approach). They tick on every LLM-route
                  request — labels are bounded so cardinality stays
                  small. Names are pinned by the test
                  `test_metrics_endpoint_advertises_codeguard_quota_metrics`
                  on the backend side, so a dashboard query that
                  hardcodes them is safe. */}
              <tr>
                <td className="px-3 py-2 font-mono">codeguard_quota_429_total</td>
                <td className="px-3 py-2 font-mono text-slate-500">{`limit_kind="{input|output}"`}</td>
                <td className="px-3 py-2">
                  Counter — cap-check 429s by binding dimension. Ticks
                  on both the HTTP-429 path (pre-flight refused) AND
                  the in-stream re-check path (mid-SSE cap trip), so
                  one series covers all refusal types. See
                  alert <code>CodeguardQuotaRefusalSpike</code> below.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">codeguard_quota_check_duration_seconds</td>
                <td className="px-3 py-2 text-slate-400">—</td>
                <td className="px-3 py-2">
                  Histogram — pre-flight cap-check (SELECT) duration.
                  Fires on every LLM-route request, regardless of
                  allow/deny outcome. Use{" "}
                  <code>histogram_quantile(0.99, …)</code> to spot the
                  cap-check inflating p99 across the codeguard surface.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">codeguard_quota_check_cache_total</td>
                <td className="px-3 py-2 font-mono text-slate-500">{`outcome="{hit|miss|invalidate|error}"`}</td>
                <td className="px-3 py-2">
                  Counter — Redis cache effectiveness for the cap-check
                  layer. Healthy production runs ~50:1 hit:miss; closer
                  to 1:1 means the cache is doing nothing (TTL too
                  short? invalidation firing every request?).{" "}
                  <code>error</code> ticks when Redis is unreachable
                  and the helper failed open to a DB read — alert if
                  sustained.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">codeguard_quota_threshold_notifications_total</td>
                <td className="px-3 py-2 font-mono text-slate-500">{`channel="{email|slack}", outcome="{delivered|skipped|failed}"`}</td>
                <td className="px-3 py-2">
                  Counter — threshold-warning (80% / 95%) notification
                  outcomes by channel. Cardinality 6 (2 × 3).{" "}
                  <code>skipped</code> ticks when there are no opt-in
                  recipients (we still claim the dedupe row); the
                  dedupe table itself is the alternative source of
                  truth (<code>SELECT count(*) FROM
                  codeguard_quota_threshold_notifications</code>).
                  Suggested alerts in <code>docs/codeguard.md</code>{" "}
                  §15.3 (sustained <code>failed</code> rate, opt-in
                  coverage gap).
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 className="not-prose mt-6 text-sm font-semibold text-slate-700">Scrape config</h3>
        <div className="not-prose mt-2 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">
          <pre className="font-mono">
            <code>{`# prometheus.yml
scrape_configs:
  - job_name: aec-api
    metrics_path: /metrics
    params:
      token: ['<AEC_METRICS_TOKEN>']
    scrape_interval: 30s
    static_configs:
      - targets: ['api.aec-platform.vn:443']
    scheme: https`}</code>
          </pre>
        </div>

        <h3 className="not-prose mt-6 text-sm font-semibold text-slate-700">Sample alert rules</h3>
        <div className="not-prose mt-2 overflow-x-auto rounded-lg bg-slate-900 p-4 text-xs text-slate-100">
          <pre className="font-mono">
            <code>{`groups:
  - name: aec-platform
    rules:
      - alert: WebhookOutboxLagging
        expr: aec_webhook_outbox_lag_seconds > 300
        for: 5m
        annotations:
          summary: "Webhook outbox is more than 5 min behind"

      - alert: ApiKeyFailureRateHigh
        expr: |
          aec_api_key_calls_total{success="false"}
          / clamp_min(
            aec_api_key_calls_total{success="false"}
            + aec_api_key_calls_total{success="true"}, 1)
          > 0.05
        for: 10m
        annotations:
          summary: "API key failure rate exceeds 5% over 10m"

      - alert: AuditPipelineSilent
        expr: |
          aec_audit_events_total == 0
          and aec_api_key_calls_total{success="true"} > 50
        for: 15m
        annotations:
          summary: "Audit hook may be broken — 0 audit events while API traffic flows"

      # Codeguard quota rules — full file at infra/prometheus/codeguard.alerts.yml
      - alert: CodeguardQuotaCheckSlow
        expr: |
          histogram_quantile(0.99,
            sum by (le) (rate(codeguard_quota_check_duration_seconds_bucket[5m]))
          ) > 0.1
        for: 5m
        labels:
          severity: warn
        annotations:
          summary: "Codeguard cap-check p99 > 100ms — DB pressure on every LLM route"

      - alert: CodeguardQuotaRefusalSpike
        expr: sum(rate(codeguard_quota_429_total[5m])) > (5 / 60)
        for: 10m
        labels:
          severity: page
        annotations:
          summary: "Codeguard quota refusals > 5/min sustained — tenant hammering or cap regression"`}</code>
          </pre>
        </div>
      </section>

      {/* ---------- Codeguard quota operations ---------- */}
      <section>
        <h2 id="codeguard-quota" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          <Gauge size={16} className="mr-1 inline align-text-top text-slate-500" />
          Codeguard quota operations
        </h2>
        <p className="text-sm text-slate-600">
          Per-org token caps on the codeguard LLM surface. The full ops
          runbook lives in <code>docs/codeguard.md</code> §14 (CLI, threshold
          notifications, billing-dispute walkthrough); §15 covers the
          alert-rule rationale (why 100ms / 5-per-min, not 50ms / 1-per-min).
          The summary below is the load-bearing references — every operator
          needs these on hand at 2am.
        </p>

        <h3 className="not-prose mt-4 text-sm font-semibold text-slate-700">
          CLI (<code>scripts/codeguard_quotas.py</code>)
        </h3>
        <div className="not-prose mt-2 overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-[11px] uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Subcommand</th>
                <th className="px-3 py-2">Use when</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="px-3 py-2 font-mono">set &lt;org&gt; --input-limit N --output-limit M</td>
                <td className="px-3 py-2">
                  Raise/lower a tenant&apos;s monthly cap. Audited; fires
                  threshold notifications if the new cap puts the tenant
                  past 80%/95%. Add <code>--dry-run</code> to preview.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">get &lt;org&gt;</td>
                <td className="px-3 py-2">
                  Show one tenant&apos;s quota row + current-month usage with
                  %-of-cap. First step in &quot;why is this tenant 429ing?&quot;.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">list --over-pct 80</td>
                <td className="px-3 py-2">
                  At-risk tenant cohort. Run during a refusal-spike
                  alert to identify which org(s) are pinning.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">reset &lt;org&gt; --confirm</td>
                <td className="px-3 py-2">
                  Zero current-month usage. Billing dispute, contract
                  change, or load-test cleanup. <code>--dry-run</code>{" "}
                  bypasses <code>--confirm</code> for safe preview.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">audit &lt;org&gt; --since YYYY-MM-DD</td>
                <td className="px-3 py-2">
                  Read the audit log for one org. Compliance: &quot;who
                  raised this cap last week?&quot; without grepping shell
                  history.
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">reconcile --threshold-tokens 1000</td>
                <td className="px-3 py-2">
                  Compare org-level vs per-user usage totals. Runs
                  weekly as a cron; ad-hoc invocation when the
                  reconcile alert fires. Exits 1 on drift.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <h3 className="not-prose mt-6 text-sm font-semibold text-slate-700">Triage flowcharts</h3>
        <div className="not-prose mt-2 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-white p-4 text-xs">
            <div className="font-semibold text-slate-900">CodeguardQuotaRefusalSpike fires</div>
            <ol className="mt-2 list-decimal space-y-1 pl-4 text-slate-700">
              <li>
                <code>list --over-pct 100</code> → identify the offending
                org(s).
              </li>
              <li>
                <code>audit &lt;org&gt; --since &lt;today&gt;</code> →
                check for unexpected cap-lower events.
              </li>
              <li>
                Decide: deploy regression (roll back), tenant hammering
                (contact them), or intentional cap-lower (confirm
                tenant was notified).
              </li>
            </ol>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4 text-xs">
            <div className="font-semibold text-slate-900">Billing dispute</div>
            <ol className="mt-2 list-decimal space-y-1 pl-4 text-slate-700">
              <li>
                <code>audit &lt;org&gt; --since YYYY-MM-DD</code> → confirm
                what happened on the org.
              </li>
              <li>
                <code>reset &lt;org&gt; --confirm --actor
                ops-billing-${"{TICKET}"}</code> → zero counters.
              </li>
              <li>
                <code>audit &lt;org&gt; --action quota_reset --limit 5</code> →
                verify reset row landed with the right actor.
              </li>
            </ol>
          </div>
        </div>

        <p className="mt-4 text-xs text-slate-500">
          See also:{" "}
          <Link href="/codeguard/quota" className="font-medium text-blue-600 hover:underline">
            /codeguard/quota
          </Link>{" "}
          (tenant-facing planning page) ·{" "}
          <code>docs/codeguard.md</code> §14 (full ops runbook) ·{" "}
          <code>infra/prometheus/codeguard.alerts.yml</code> (rule file)
        </p>
      </section>

      <section>
        <h2 id="not-yet" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Không có (chưa)
        </h2>
        <ul className="space-y-1 text-sm text-slate-700">
          <li>
            <strong>Process metrics</strong> (open FDs, GC stats, RSS).
            Sẽ thêm qua sidecar hoặc{" "}
            <code>prometheus_fastapi_instrumentator</code>. Cho v1
            chúng ta focus vào application-level signals.
          </li>
          <li>
            <strong>Histograms</strong> (request latency p99, etc.).
            Cần cross-process state — đợi sidecar.
          </li>
          <li>
            <strong>Counters</strong> (cumulative since boot). Rollup
            tables (<code>api_key_calls</code>,{" "}
            <code>webhook_deliveries</code>) ARE counters by another
            name; gauges over windows give equivalent signal.
          </li>
        </ul>
      </section>
    </div>
  );
}
