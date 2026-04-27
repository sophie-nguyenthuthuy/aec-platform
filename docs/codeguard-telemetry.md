# CODEGUARD telemetry — operating guide

The codeguard pipeline emits a structured log record for every LLM and
embedding call (see §11 "Cost telemetry" in `docs/codeguard.md`). This
guide bridges the gap between "records exist" and "ops can answer cost
questions" — without committing to a specific observability backend.

Three levels of capability, in increasing cost/effort:

1. **Tail + script** — `kubectl logs | spend_report.py`. Zero infra,
   useful in 30 seconds. Good for "what did the last hour look like."
2. **Loki / CloudWatch / Honeycomb queries** — push the JSON records
   into your log backend, run aggregation queries against them.
3. **OTEL traces** — wire the telemetry helper to OTLP for distributed
   tracing. Out of scope for now; the existing record shape is what
   you'd use as `span.attributes`.

This doc covers (1) and (2).

---

## 1. Make the records JSON-formatted

Python's standard logger emits text by default. The rollup script and
LogQL queries below assume JSON-per-line. Drop this in your FastAPI
startup (or wherever you configure logging):

```python
import logging
import sys

try:
    from pythonjsonlogger import jsonlogger
except ImportError:
    # python-json-logger isn't a runtime dep; install on prod images
    # that ship telemetry to a log backend.
    jsonlogger = None

if jsonlogger is not None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s "
                "%(call)s %(model)s %(latency_ms)s %(input_chars)s "
                "%(output_chars)s %(input_tokens)s %(output_tokens)s "
                "%(status)s %(error)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        ),
    )
    telemetry_logger = logging.getLogger("codeguard.telemetry")
    telemetry_logger.handlers = [handler]
    telemetry_logger.setLevel(logging.INFO)
    telemetry_logger.propagate = False  # don't double-emit on root
```

The `extra` fields the codeguard helper passes (`call`, `model`, ...)
are mapped to top-level keys in each JSON record by the format string.
Other handlers (request logs, exception tracebacks) keep their default
text format on the root logger — the `propagate=False` keeps the
streams clean.

A line in your logs will look like:

```json
{"timestamp": "2026-04-27T10:24:31.482Z", "name": "codeguard.telemetry",
 "level": "INFO", "message": "codeguard.llm_call",
 "call": "hyde_expand", "model": "claude-sonnet-4-6",
 "latency_ms": 480, "input_chars": 120, "output_chars": 280,
 "input_tokens": 30, "output_tokens": 70, "status": "ok", "error": null}
```

---

## 2. Tail-and-script: `scripts/codeguard_spend_report.py`

For a quick dashboard with no backend dependency, pipe logs into the
rollup script:

```bash
# Last hour of one pod
kubectl logs deploy/aec-api -c api --since=1h \
  | python scripts/codeguard_spend_report.py

# All replicas, last hour
kubectl logs -l app=aec-api --since=1h --prefix \
  | python scripts/codeguard_spend_report.py

# From a captured log file
python scripts/codeguard_spend_report.py < /var/log/aec-api.jsonl

# Machine-readable for scripting
python scripts/codeguard_spend_report.py --json < logs.jsonl \
  | jq '.totals'
```

Sample output:

```
CODEGUARD telemetry rollup — 1,247 call(s)
  ok:       1,242
  error:        5  (0.4%)

call                                  n   err   in_tok   out_tok  p50_ms  p95_ms  models
-----------------------------------------------------------------------------------------
qa_generate                         203     2  154,210    29,847    1924    3210  claude-sonnet-4-6
qa_generate_stream                   16     0   14,521     2,847    1820    2910  claude-sonnet-4-6
scan_generate.fire_safety            94     1   67,891    18,432    2140    3847  claude-sonnet-4-6
hyde_expand                          47     0   20,134     4,621     481     892  claude-sonnet-4-6
embed_query                         219     2        0         0      84     193  text-embedding-3-large

HyDE cache: 47 expand call(s) for 219 Q&A request(s) → estimated hit rate 78.5%
```

Lines that aren't JSON or that don't have a `call` field are skipped
silently — safe to point at a mixed log stream without pre-filtering.

---

## 3. Sample LogQL queries (Loki / Grafana)

If your logs ship to Loki, these queries answer the questions that
matter for cost ops.

### Anthropic spend last 24h (input + output tokens)

```logql
sum(
  sum_over_time(
    {service="aec-api"}
      | json
      | name="codeguard.telemetry"
      | model =~ "claude.*"
      | unwrap input_tokens
      [24h]
  )
  +
  sum_over_time(
    {service="aec-api"}
      | json
      | name="codeguard.telemetry"
      | model =~ "claude.*"
      | unwrap output_tokens
      [24h]
  )
)
```

### Spend by call name (table view)

```logql
sum by (call) (
  sum_over_time(
    {service="aec-api"}
      | json
      | name="codeguard.telemetry"
      | unwrap input_tokens
      [1h]
  )
)
```

### P95 latency per call

```logql
quantile_over_time(0.95,
  {service="aec-api"}
    | json
    | name="codeguard.telemetry"
    | unwrap latency_ms
    [5m]
) by (call)
```

### Error rate per call (5-minute window)

```logql
sum by (call) (
  count_over_time(
    {service="aec-api"} | json | name="codeguard.telemetry"
      | status="error" [5m]
  )
)
/
sum by (call) (
  count_over_time(
    {service="aec-api"} | json | name="codeguard.telemetry" [5m]
  )
)
```

### HyDE cache hit rate

Cache hits emit no record, so the hit rate is derived: `1 -
(hyde_expand calls / Q&A calls)`.

```logql
1 -
(
  count_over_time(
    {service="aec-api"} | json | name="codeguard.telemetry"
      | call="hyde_expand" [1h]
  )
  /
  count_over_time(
    {service="aec-api"} | json | name="codeguard.telemetry"
      | call =~ "qa_generate.*" [1h]
  )
)
```

A working cache should sit between 0.5 and 0.95 once an active session
has built up its keyspace. Lower values mean the TTL is too short or
the question diversity is too high; higher values are usually fine but
worth checking that you're not serving stale HyDE for changed
regulations.

---

## 4. What's deliberately not here

- **Per-org spend.** The current telemetry record doesn't carry
  `org_id` — adding it requires plumbing the auth context through to
  the pipeline, which is a separate round of work. When that lands,
  every query above gets a `by (org_id)` breakdown for free.
- **OTEL trace export.** The record shape (`call`, `model`,
  `latency_ms`, `input_tokens`, `output_tokens`) is exactly the set of
  attributes a span would carry. A future round can swap the `info()`
  call for `tracer.start_span(...)` without changing the field
  vocabulary.
- **Live cost-in-dollars.** Token-to-dollar conversion depends on
  current Anthropic/OpenAI pricing, which drifts. Keep the dashboards
  in token units; convert at presentation time using whatever
  pricing-config sheet your finance team maintains.

---

## 5. Reference

- Helper: `_record_llm_call` in `apps/ml/pipelines/codeguard.py`.
- Token capture: `_UsageCaptureHandler` in the same file (LangChain
  callback hook on `on_llm_end`).
- Rollup script: `scripts/codeguard_spend_report.py`.
- Tests: `apps/ml/tests/test_codeguard_telemetry.py`,
  `apps/ml/tests/test_codeguard_spend_report.py`.
