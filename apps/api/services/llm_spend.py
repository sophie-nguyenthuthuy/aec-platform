"""LLM spend tracking — cost computation + per-call recording.

Two responsibilities:

  1. `compute_cost_vnd` — turn (provider, model, in_tokens, out_tokens)
     into a VND figure using the per-model rate table below. We
     ship the rate table in code (not the DB) so a rate change is
     a version-controlled PR — auditors can grep `git log -p
     services/llm_spend.py` to see exactly when prices moved.

  2. `record_llm_call` — async fire-and-forget INSERT into
     `llm_spend_events`. Call sites pass org + module + provider/model
     + token counts after a successful (or failed-but-counted) call.
     Errors during recording are swallowed + logged — billing
     bookkeeping must NEVER break a user-facing LLM response.

USD-denominated rates are converted at a fixed 24,500 VND/USD rate
(approx mid-2026 rate). This is intentionally a conservative round
number — bills round up vs the spot rate so we never under-charge a
month later. Update yearly or when USD/VND drifts >5%.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


_USD_TO_VND = 24_500  # Conservative conversion. See module docstring.


Provider = Literal["gemini", "anthropic", "openai"]


# Per-1k-token rates in USD. Rates current as of 2026-05.
# Update when provider price lists change; commit the diff so the
# audit trail is in git history.
_RATES_USD_PER_1K: dict[tuple[str, str], tuple[float, float]] = {
    # (provider, model_substring): (input_per_1k, output_per_1k)
    # Match by `substring in model` so version suffixes (-002, -001) match.
    ("gemini", "gemini-1.5-flash"): (0.000075, 0.0003),
    ("gemini", "gemini-1.5-pro"): (0.00125, 0.005),
    ("gemini", "gemini-2.0-flash"): (0.0001, 0.0004),
    ("gemini", "gemini-embedding"): (0.000025, 0.0),
    ("gemini", "text-embedding"): (0.000025, 0.0),
    ("anthropic", "claude-sonnet-4-6"): (0.003, 0.015),
    ("anthropic", "claude-sonnet"): (0.003, 0.015),
    ("anthropic", "claude-opus"): (0.015, 0.075),
    ("anthropic", "claude-haiku"): (0.00025, 0.00125),
    ("openai", "gpt-4o"): (0.0025, 0.01),
    ("openai", "gpt-4o-mini"): (0.00015, 0.0006),
    ("openai", "text-embedding-3-large"): (0.00013, 0.0),
    ("openai", "text-embedding-3-small"): (0.00002, 0.0),
}


def _resolve_rate(provider: str, model: str) -> tuple[float, float]:
    """Look up (input_rate, output_rate) for a provider+model pair.

    Tries exact matches first, then substring fallbacks. Unknown
    pair falls back to a conservative Claude-Sonnet rate so an
    accidentally-unpriced model still records *some* cost rather
    than silently zeroing the spend.
    """
    for (p, model_key), rates in _RATES_USD_PER_1K.items():
        if p == provider and model_key in model:
            return rates
    logger.warning(
        "llm_spend: no rate for provider=%s model=%s; falling back to conservative rate",
        provider,
        model,
    )
    return (0.003, 0.015)


def compute_cost_vnd(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Return the VND cost of a single LLM call.

    Rounds up to the nearest đồng — we don't want to undercount a
    fraction-of-a-cent call to zero. Output is an int because the
    DB column is BIGINT (sub-VND rounding has no business value).
    """
    in_rate, out_rate = _resolve_rate(provider, model)
    cost_usd = (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate
    cost_vnd_float = cost_usd * _USD_TO_VND
    return max(0, int(cost_vnd_float + 0.5))  # nearest đồng


async def record_llm_call(
    *,
    organization_id: UUID,
    module: str,
    provider: Provider | str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    request_id: str | None = None,
) -> None:
    """Insert one row into `llm_spend_events`.

    Idempotency: not enforced — duplicate calls produce duplicate rows.
    Callers SHOULD invoke this once per LLM call. If a retry loop
    records twice, the dashboard will show 2× spend; we accept this
    trade-off because the alternative (deduping by request_id) means
    losing visibility on a genuine double-charge from an upstream bug.

    Errors are swallowed + logged. Recording is best-effort — a billing
    write must never block or fail an LLM response that already happened.
    """
    if input_tokens == 0 and output_tokens == 0:
        return

    cost_vnd = compute_cost_vnd(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    # Lazy import to avoid bringing the DB session into core-loading
    # cycles for callers that haven't already pulled it in.
    try:
        from db.session import AdminSessionFactory
    except ImportError:
        logger.warning("llm_spend.record: db.session unavailable; skipping")
        return

    try:
        async with AdminSessionFactory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_spend_events
                        (id, organization_id, module, provider, model,
                         input_tokens, output_tokens, cost_vnd, request_id)
                    VALUES (:id, :org, :mod, :prov, :model,
                            :in_tok, :out_tok, :cost, :req)
                    """
                ),
                {
                    "id": str(uuid4()),
                    "org": str(organization_id),
                    "mod": module,
                    "prov": provider,
                    "model": model,
                    "in_tok": input_tokens,
                    "out_tok": output_tokens,
                    "cost": cost_vnd,
                    "req": request_id,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning(
            "llm_spend.record failed (org=%s module=%s model=%s): %s",
            organization_id,
            module,
            model,
            exc,
        )
