import Link from "next/link";
import { ArrowRight, CheckCircle2, Clock, ShieldCheck, Webhook } from "lucide-react";


/**
 * Developer docs for the webhook subsystem.
 *
 * Static (server-rendered) — no client state, no API calls. The
 * authoritative source for the constants here is
 * `apps/api/services/webhooks.py`:
 *   * `_KNOWN_EVENT_TYPES` — the event catalog table
 *   * `_BACKOFF_MINUTES`   — the retry schedule
 *   * The HMAC scheme + `X-AEC-*` headers
 *
 * If those change, the docs need a hand-edit. The `_KNOWN_EVENT_TYPES`
 * registry is unlikely to drift because every audit-mirrored entry has
 * a comment in services/webhooks.py reminding the next editor to
 * update both lists. The retry schedule is even more stable; we don't
 * touch it without coordinating with at least one customer.
 */
export default function WebhookDocsPage() {
  return (
    <div className="prose prose-slate max-w-none space-y-10 text-sm">
      {/* ---------- Header ---------- */}
      <header className="space-y-2 not-prose">
        <div className="flex items-center gap-2">
          <Webhook size={20} className="text-blue-600" />
          <h1 className="text-2xl font-bold text-slate-900">Webhook documentation</h1>
        </div>
        <p className="text-sm text-slate-600">
          Subscribe to platform events via signed HTTP callbacks. Each event
          is delivered at-least-once with HMAC-SHA256 signing, exponential
          backoff on failure, and an idempotency key on every retry.
        </p>
        <p className="text-xs text-slate-500">
          Manage subscriptions:{" "}
          <Link
            href="/settings/webhooks"
            className="font-medium text-blue-600 hover:underline"
          >
            /settings/webhooks
          </Link>
        </p>
      </header>

      {/* ---------- TL;DR ---------- */}
      <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 not-prose">
        <h2 className="text-sm font-semibold text-blue-900">Tóm tắt</h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-blue-900">
          <li>Tạo subscription tại <code>/settings/webhooks</code> — copy secret xuất hiện đúng một lần.</li>
          <li>Khi event nổ ra, server POST JSON tới URL bạn cung cấp với header <code>X-AEC-Signature: sha256=…</code>.</li>
          <li>Verify chữ ký bằng <code>hmac.compare_digest</code> (xem snippet bên dưới) trước khi tin payload.</li>
          <li>Trả về <code>2xx</code> trong vòng 10 giây. Khác → backoff retry (1m → 5m → 30m → 2h → 12h, 6 lần).</li>
          <li>Idempotency: dùng <code>X-AEC-Delivery-ID</code> làm khóa — retry dùng lại cùng UUID.</li>
        </ol>
      </section>

      {/* ---------- Headers ---------- */}
      <section>
        <h2 id="headers" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Request headers
        </h2>
        <p className="text-sm text-slate-600">
          Every webhook POST carries these four headers in addition to{" "}
          <code>Content-Type: application/json</code>:
        </p>
        <div className="not-prose overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-[11px] uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Header</th>
                <th className="px-3 py-2">Example</th>
                <th className="px-3 py-2">Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="px-3 py-2 font-mono">X-AEC-Signature</td>
                <td className="px-3 py-2 font-mono text-slate-500">sha256=4f9b…ec</td>
                <td className="px-3 py-2">HMAC-SHA256(secret, raw_body), hex-encoded.</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">X-AEC-Event-Type</td>
                <td className="px-3 py-2 font-mono text-slate-500">project.created</td>
                <td className="px-3 py-2">Event type slug. See catalog below.</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">X-AEC-Delivery-ID</td>
                <td className="px-3 py-2 font-mono text-slate-500">b0e1…f2</td>
                <td className="px-3 py-2">UUID stable across retries. Use as idempotency key.</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono">X-AEC-Timestamp</td>
                <td className="px-3 py-2 font-mono text-slate-500">1746201234</td>
                <td className="px-3 py-2">Unix seconds. Reject deliveries older than ~5 min as replays.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* ---------- Signature verification ---------- */}
      <section>
        <h2 id="verify" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Verifying the signature
        </h2>
        <p className="text-sm text-slate-600">
          The signature is over the <strong>raw bytes</strong> of the POST body
          — verify <em>before</em> JSON-decoding. If your framework decodes
          for you, hold onto the original buffer (most have a "raw body"
          escape hatch). Use <code>hmac.compare_digest</code> /{" "}
          <code>crypto.timingSafeEqual</code> to avoid timing attacks.
        </p>

        <CodeBlock language="TypeScript / Node.js" code={TS_VERIFY_SNIPPET} />
        <CodeBlock language="Python" code={PY_VERIFY_SNIPPET} />
        <CodeBlock language="Go" code={GO_VERIFY_SNIPPET} />
      </section>

      {/* ---------- Retry semantics ---------- */}
      <section>
        <h2 id="retries" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Retry semantics
        </h2>
        <div className="not-prose grid gap-3 sm:grid-cols-3">
          <Tile
            icon={<Clock size={16} />}
            title="Backoff schedule"
            body="0, 1, 5, 30, 120, 720 minutes — six attempts before a delivery is marked failed."
          />
          <Tile
            icon={<CheckCircle2 size={16} />}
            title="Success criterion"
            body="Any 2xx (200 / 204). Anything else (incl. 5xx, network, timeout > 10s) is retryable."
          />
          <Tile
            icon={<ShieldCheck size={16} />}
            title="Auto-disable"
            body="20 consecutive failures across deliveries auto-disables the subscription. Counter resets on success."
          />
        </div>
        <p className="mt-4 text-sm text-slate-600">
          The cron drains pending deliveries every 60 seconds, so a fresh
          event lands within ~1 minute. Retries fire at the scheduled
          backoff interval +/- the cron tick.
        </p>
      </section>

      {/* ---------- Idempotency ---------- */}
      <section>
        <h2 id="idempotency" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Idempotency
        </h2>
        <p className="text-sm text-slate-600">
          Deliveries are <strong>at-least-once</strong>. A receiver returning
          200 to attempt #2 of the same delivery (because attempt #1's TCP
          ACK got lost) will see two POSTs with the same{" "}
          <code>X-AEC-Delivery-ID</code> UUID. Persist that UUID and skip
          the second:
        </p>
        <CodeBlock language="Python (sketch)" code={IDEMPOTENCY_SNIPPET} />
        <p className="text-xs text-slate-500">
          A Redis SETNX with a 7-day TTL is plenty — backoff caps out at
          ~12 hours, so a delivery older than a day is permanently failed.
        </p>
      </section>

      {/* ---------- Event catalog ---------- */}
      <section>
        <h2 id="events" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Event catalog
        </h2>
        <p className="text-sm text-slate-600">
          A subscription can target a specific list of event types, or omit
          the list to match every event in the org. Mirror of{" "}
          <code>_KNOWN_EVENT_TYPES</code> in{" "}
          <code>services/webhooks.py</code>:
        </p>
        <EventTable />
      </section>

      {/* ---------- Local dev ---------- */}
      <section>
        <h2 id="dev" className="not-prose mt-0 text-lg font-semibold text-slate-900">
          Testing locally
        </h2>
        <ol className="ml-6 list-decimal space-y-2 text-sm text-slate-600">
          <li>
            Expose your local server with{" "}
            <code className="rounded bg-slate-100 px-1 text-xs">ngrok http 4000</code>{" "}
            (or Cloudflare Tunnel / localhost.run).
          </li>
          <li>
            Paste the public URL into{" "}
            <Link href="/settings/webhooks" className="text-blue-600 hover:underline">
              /settings/webhooks
            </Link>{" "}
            as the subscription URL. Copy the secret on creation — it's
            shown exactly once.
          </li>
          <li>
            Click <strong>Send test event</strong> on the subscription row.
            That fires a <code>webhook.test</code> event with a deterministic
            payload so you can pin assertions in your handler tests.
          </li>
          <li>
            Trigger a real event to validate end-to-end (e.g. approve a
            change order in <Link href="/changeorder" className="text-blue-600 hover:underline">/changeorder</Link>{" "}
            for <code>pulse.change_order.approve</code>).
          </li>
        </ol>
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900">
          <strong>Production gotcha:</strong> ngrok URLs change on free
          accounts every restart. For staging, use a static domain or
          paid ngrok plan — the auto-disable counter doesn't care that
          you're "just developing".
        </div>
      </section>

      {/* ---------- Footer ---------- */}
      <footer className="not-prose flex items-center gap-2 border-t border-slate-200 pt-6 text-xs text-slate-500">
        <span>Cần thêm event type? Mở issue trên repo.</span>
        <Link
          href="/settings/webhooks"
          className="ml-auto inline-flex items-center gap-1 text-blue-600 hover:underline"
        >
          Quản lý subscriptions <ArrowRight size={12} />
        </Link>
      </footer>
    </div>
  );
}


// ---------- Sub-components ----------


function Tile({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-slate-700">
        <span className="text-slate-400">{icon}</span>
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <p className="mt-2 text-xs text-slate-600">{body}</p>
    </div>
  );
}


function CodeBlock({ language, code }: { language: string; code: string }) {
  return (
    <div className="not-prose mt-3 overflow-hidden rounded-lg border border-slate-200">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-1.5 text-[11px] font-medium text-slate-600">
        <span>{language}</span>
      </div>
      <pre className="overflow-x-auto bg-slate-950 p-4 text-xs leading-relaxed text-slate-100">
        <code>{code}</code>
      </pre>
    </div>
  );
}


// ---------- Event catalog table ----------


// Mirrors `_KNOWN_EVENT_TYPES` in services/webhooks.py. Grouped by
// module so users can scan for "the bidding events" without grepping.
const EVENT_GROUPS: Array<{
  module: string;
  events: Array<{ type: string; description: string }>;
}> = [
  {
    module: "CostPulse",
    events: [
      { type: "costpulse.estimate.approve", description: "Dự toán được duyệt." },
      { type: "costpulse.boq.import", description: "BoQ được import vào estimate." },
      { type: "costpulse.suppliers.import", description: "Bulk import suppliers (legacy CSV path)." },
      { type: "costpulse.rfq.slots_expired", description: "Slot RFQ hết hạn không có offer." },
    ],
  },
  {
    module: "Pulse",
    events: [
      { type: "pulse.change_order.approve", description: "Change order được duyệt — gắn với audit." },
      { type: "pulse.change_order.reject", description: "Change order bị từ chối." },
    ],
  },
  {
    module: "Org / IAM",
    events: [
      { type: "org.member.role_change", description: "Vai trò thành viên thay đổi." },
      { type: "org.member.remove", description: "Thành viên bị xoá khỏi org." },
      { type: "org.invitation.create", description: "Lời mời mới được tạo." },
      { type: "org.invitation.revoke", description: "Lời mời bị thu hồi." },
      { type: "org.invitation.accept", description: "Lời mời được chấp nhận." },
    ],
  },
  {
    module: "Notifications",
    events: [
      { type: "notifications.preference.update", description: "User toggle email/Slack opt-in." },
    ],
  },
  {
    module: "Handover",
    events: [
      { type: "handover.package.deliver", description: "Bàn giao gói tài liệu cho khách." },
      { type: "handover.defect.reported", description: "Lỗi mới được báo cáo (snag list)." },
    ],
  },
  {
    module: "Punchlist",
    events: [
      { type: "punchlist.list.sign_off", description: "Sign-off một punch list." },
    ],
  },
  {
    module: "Submittals",
    events: [
      { type: "submittals.review.approve", description: "Approve submittal." },
      { type: "submittals.review.approve_as_noted", description: "Approve as noted (with comments)." },
      { type: "submittals.review.revise_resubmit", description: "Revise & resubmit." },
      { type: "submittals.review.reject", description: "Reject submittal." },
    ],
  },
  {
    module: "Project / SiteEye",
    events: [
      { type: "project.created", description: "New project (manual / from WinWork)." },
      { type: "siteeye.safety_incident.detected", description: "PPE/safety incident detected from photo." },
    ],
  },
  {
    module: "Test",
    events: [
      {
        type: "webhook.test",
        description:
          "Fired by 'Send test event' on /settings/webhooks. Same payload shape as a real event — receivers can't distinguish.",
      },
    ],
  },
];


function EventTable() {
  return (
    <div className="not-prose space-y-4">
      {EVENT_GROUPS.map((group) => (
        <div key={group.module} className="overflow-hidden rounded-lg border border-slate-200">
          <div className="bg-slate-50 px-3 py-1.5 text-[11px] font-semibold uppercase text-slate-600">
            {group.module}
          </div>
          <table className="w-full text-xs">
            <tbody className="divide-y divide-slate-100">
              {group.events.map((e) => (
                <tr key={e.type}>
                  <td className="w-1/3 px-3 py-2 font-mono text-slate-800">{e.type}</td>
                  <td className="px-3 py-2 text-slate-600">{e.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}


// ---------- Code snippets ----------


const TS_VERIFY_SNIPPET = `import { createHmac, timingSafeEqual } from "node:crypto";

// Express handler. Use express.raw() (NOT json()) so req.body is a Buffer.
app.post("/webhooks/aec", express.raw({ type: "application/json" }), (req, res) => {
  const sig = req.header("X-AEC-Signature") ?? "";
  const expected = createHmac("sha256", process.env.AEC_WEBHOOK_SECRET!)
    .update(req.body)
    .digest("hex");
  // Accept "sha256=…" or bare hex for ergonomics.
  const got = sig.startsWith("sha256=") ? sig.slice(7) : sig;
  const a = Buffer.from(expected, "hex");
  const b = Buffer.from(got, "hex");
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return res.status(401).end();
  }

  const event = JSON.parse(req.body.toString("utf-8"));
  // ... handle event ...
  res.status(200).end();
});`;


const PY_VERIFY_SNIPPET = `import hmac, hashlib, os
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()

@app.post("/webhooks/aec")
async def aec_webhook(
    request: Request,
    x_aec_signature: str = Header(...),
    x_aec_delivery_id: str = Header(...),
):
    body = await request.body()  # raw bytes — verify before parsing
    secret = os.environ["AEC_WEBHOOK_SECRET"].encode()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    got = x_aec_signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, got):
        raise HTTPException(401, "bad signature")

    # Idempotency: skip if we've seen this delivery before.
    if await already_processed(x_aec_delivery_id):
        return {"status": "duplicate"}

    event = json.loads(body)
    # ... handle event ...
    await mark_processed(x_aec_delivery_id)
    return {"status": "ok"}`;


const GO_VERIFY_SNIPPET = `package main

import (
    "crypto/hmac"
    "crypto/sha256"
    "encoding/hex"
    "io"
    "net/http"
    "os"
    "strings"
)

func handler(w http.ResponseWriter, r *http.Request) {
    body, err := io.ReadAll(r.Body)
    if err != nil {
        http.Error(w, "bad body", http.StatusBadRequest)
        return
    }
    secret := []byte(os.Getenv("AEC_WEBHOOK_SECRET"))
    mac := hmac.New(sha256.New, secret)
    mac.Write(body)
    expected := mac.Sum(nil)

    got := strings.TrimPrefix(r.Header.Get("X-AEC-Signature"), "sha256=")
    gotBytes, err := hex.DecodeString(got)
    if err != nil || !hmac.Equal(expected, gotBytes) {
        http.Error(w, "bad signature", http.StatusUnauthorized)
        return
    }

    // ... handle event with body + r.Header.Get("X-AEC-Delivery-ID") ...
    w.WriteHeader(http.StatusOK)
}`;


const IDEMPOTENCY_SNIPPET = `# At the top of your handler, before doing any side-effects:
key = f"aec:webhook:{x_aec_delivery_id}"
if not await redis.set(key, "1", nx=True, ex=7 * 86400):
    return {"status": "duplicate"}  # already processed; ack with 200`;
