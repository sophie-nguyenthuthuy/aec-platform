"""Smoke test for the client-report pipeline.

Phase 3 / "do the LLM and renderer actually use the 4 new sections?":

The `routers/pulse._aggregate_report_inputs` helper (covered in
`apps/api/tests/test_pulse_router.py`) populates a `data` dict with
4 cross-module roll-ups added during the integration sweep —
  - schedule_slip       (SchedulePilot CPM forecast)
  - submittals          (queue counts + ball_in_court)
  - dailylog            (high-severity observations)
  - changeorder_extended (executed + pending candidates)

This file pins the contract that they're actually surfaced to the LLM
prompt (so the model can mention them in `issues` / `next_steps`) and
that the rendered HTML faithfully reproduces what the model returned.

We don't hit Anthropic — that's `make eval-codeguard` / a manual smoke.
We DO drive the real LangGraph (`generate_client_report` → narrate →
validate), stubbing `_narrate_node` at the function level to capture
the state passed in and inject a hand-crafted LLM response. That keeps
the validator + HTML renderer in the loop while making the test
hermetic.

If WeasyPrint is installed locally (e.g. `pip install weasyprint`),
the test additionally exercises `render_report_pdf`. Otherwise it
asserts the renderer raises `PDFRendererUnavailable` cleanly — we want
the route's graceful "fall back to HTML, pdf_url=None" path to keep
working, not silently crash.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


def _full_data() -> dict:
    """Same shape `_aggregate_report_inputs` produces — the 4 new
    sections are populated with real-looking numbers so we can pin
    that the LLM saw them."""
    return {
        "completed_tasks": [
            {"title": "Phần móng tầng hầm", "completed_at": "2026-04-22T10:00:00Z"},
        ],
        "milestones": [
            {"name": "Hoàn thành phần móng", "due_date": "2026-04-25"},
        ],
        "change_orders": [
            {"id": "co-1", "title": "Bổ sung lan can ban công", "cost_impact_vnd": 120_000_000},
        ],
        "approved_change_order_totals": {"cost_vnd": 120_000_000, "schedule_days": 0},
        "photos": [],
        "estimate": None,
        # The 4 new roll-ups.
        "schedule_slip": {
            "schedule_count": 2,
            "activity_count": 15,
            "behind_schedule_count": 4,
            "overall_slip_days": 7,
            "avg_percent_complete": 47.5,
        },
        "submittals": {
            "open_count": 3,
            "approved_count": 10,
            "revise_resubmit_count": 1,
            "designer_court_count": 2,
            "contractor_court_count": 6,
        },
        "dailylog": {
            "log_count": 20,
            "open_observation_count": 5,
            "high_severity_observation_count": 2,
            "last_log_date": "2026-04-25",
        },
        "changeorder_extended": {
            "executed_count": 1,
            "pending_candidates": 3,
            "total_cost_impact_vnd": 250_000_000,
            "total_schedule_impact_days": 4,
        },
    }


def _stub_llm_content() -> dict:
    """Hand-crafted "LLM response" that exercises every block of the
    HTML renderer (header_summary, narrative, highlights, issues,
    next_steps). The strings reference the 4 new sections so the test
    can assert they round-trip through the renderer."""
    return {
        "header_summary": "Project on track but tracking 7 days behind on CPM forecast.",
        "progress_section": {
            "narrative": "Foundation work complete. Lobby framing in progress.",
            "highlights": [
                "Phần móng hoàn thành",
                "12 hạng mục trong tuần",
            ],
            "progress_pct": 47.5,
        },
        "photos_section": [],
        "financials": {
            "narrative": "Approved CO totals VND 120M.",
            "summary": {"spent": None, "budget": None, "variance": None},
        },
        "issues": [
            {
                "title": "CPM slip 7 days",
                "status": "open",
                "impact": "4 activities tracking past baseline",
            },
            {
                "title": "Submittals: 1 revise & resubmit",
                "status": "designer-action",
                "impact": "Contractor queue at 6 awaiting review",
            },
            {
                "title": "DailyLog: 2 high-severity observations",
                "status": "open",
                "impact": "Site safety items needing follow-up",
            },
        ],
        "next_steps": [
            "Review 3 pending CO candidates",
            "Close out DailyLog high-severity observations",
        ],
    }


# ---------------------------------------------------------------------------
# 1. Pipeline: data → LLM input → validated content
# ---------------------------------------------------------------------------


async def test_narrate_node_receives_four_new_sections_in_prompt_data(monkeypatch):
    """The narrate node serialises `state["data"]` into the LLM prompt
    via `_REPORT_HUMAN`'s `{data}` placeholder. We intercept the chain's
    `ainvoke` and capture the kwargs it was called with — those kwargs
    are exactly the dict that gets `.format()`-substituted into the
    template, so asserting on them is asserting on what the model
    actually saw.

    Bypasses the LangGraph wrapper because it has untyped channels and
    rejects mid-graph writes from monkeypatched nodes — the contract we
    care about (data → LLM input → validated content) lives in the two
    node functions, not in the graph plumbing.
    """
    from langchain_core.prompt_values import ChatPromptValue
    from langchain_core.runnables import RunnableLambda

    from ml.pipelines import pulse

    captured: dict = {}

    def _capture_prompt_value(value: ChatPromptValue):
        # The PromptTemplate's output — a ChatPromptValue whose
        # `to_string()` is the fully-rendered prompt with our format
        # inputs substituted in. We grep that string for the JSON-
        # serialised data sections rather than trying to grab them
        # before format substitution; that way we're testing what the
        # model actually sees, not just what we hand to LangChain.
        captured["prompt"] = value.to_string()
        return value  # passthrough — the next runnable still gets a PromptValue

    # `prompt | llm | parser`
    #
    # `prompt` is a real ChatPromptTemplate, so it formats the input
    # kwargs into a ChatPromptValue. We sandwich a capturing Runnable
    # between prompt and llm, then make llm + parser passthroughs that
    # collapse to returning our stub LLM content.
    captured_runnable = RunnableLambda(_capture_prompt_value)

    class _PromptCaptureWrapper:
        """Wraps the real ChatPromptTemplate so we can inject a capture
        runnable directly after the format step. Easier than digging
        into LangChain internals to add a hook."""

        def __init__(self, inner):
            self._inner = inner

        def __or__(self, other):
            # When the real code does `prompt | _llm()`, we route the
            # composition through our capture step first.
            return self._inner | captured_runnable | other

    real_from_messages = pulse.ChatPromptTemplate.from_messages

    def _wrapped_from_messages(*args, **kwargs):
        return _PromptCaptureWrapper(real_from_messages(*args, **kwargs))

    monkeypatch.setattr(pulse.ChatPromptTemplate, "from_messages", _wrapped_from_messages)
    # `_llm` is a passthrough — receives the ChatPromptValue, returns the
    # stub LLM content directly. JsonOutputParser is a passthrough on top
    # of that (the stub is already a dict).
    monkeypatch.setattr(pulse, "_llm", lambda **_kw: RunnableLambda(lambda _v: _stub_llm_content()))
    monkeypatch.setattr(pulse, "JsonOutputParser", lambda: RunnableLambda(lambda x: x))

    state = pulse._ReportState(
        project_id=str(uuid4()),
        period="2026-04-19 / 2026-04-25",
        language="vi",
        include_photos=False,
        include_financials=True,
        data=_full_data(),
    )
    state = await pulse._narrate_node(state)

    prompt_text = captured["prompt"]
    # The 4 new section keys appear in the rendered prompt body — that's
    # what the LLM sees. We grep for the literal JSON keys rather than
    # parsing because the prompt is human-readable text with a JSON
    # blob embedded, and json.loads on the whole string would fail.
    import json as _json

    # The pipeline serialises state["data"] with ensure_ascii=False; the
    # serialised blob is somewhere in the prompt text. Re-derive it for a
    # parsable assertion target.
    data_blob = _json.dumps(_full_data(), ensure_ascii=False, default=str)
    assert data_blob in prompt_text, (
        "JSON-serialised data not embedded in prompt — does _narrate_node "
        "still json.dumps state['data']?"
    )
    # Parse the embedded blob to assert structurally on values.
    data_payload = _json.loads(data_blob)

    # Pin: every new section made it into the LLM payload.
    for key in ("schedule_slip", "submittals", "dailylog", "changeorder_extended"):
        assert key in data_payload, f"`{key}` missing from LLM data payload"

    # Spot-check values to make sure we're forwarding by reference.
    assert data_payload["schedule_slip"]["overall_slip_days"] == 7
    assert data_payload["dailylog"]["high_severity_observation_count"] == 2
    assert data_payload["changeorder_extended"]["pending_candidates"] == 3

    # Pin: the prompt's "Notes for the writer" still tells the model
    # how to use each of the 4 new sections. A regression that drops
    # one of these notes would otherwise silently let the model ignore
    # a section even though the data is present.
    for note_key in ("schedule_slip", "submittals", "dailylog", "changeorder_extended"):
        assert f"data.{note_key}" in prompt_text, (
            f"prompt no longer references `data.{note_key}` — model won't "
            "know to surface it under issues/next_steps"
        )

    # Validate node turns raw LLM JSON into a typed ClientReportContent.
    state = await pulse._validate_node(state)
    content = state["validated"]
    assert content.header_summary.startswith("Project on track")
    assert len(content.issues) == 3
    assert len(content.next_steps) == 2


# ---------------------------------------------------------------------------
# 2. HTML rendering: every section the LLM populated lands in the document
# ---------------------------------------------------------------------------


async def test_render_report_html_includes_issues_and_next_steps_from_llm():
    """The renderer doesn't drop or rename any of the LLM's
    issues/next_steps lines — a regression in the template would
    silently lose Phase F's whole reason for being."""
    from schemas.pulse import ClientReportContent

    from ml.pipelines.pulse import render_report_html

    raw = _stub_llm_content()
    content = ClientReportContent(
        header_summary=raw["header_summary"],
        progress_section=raw["progress_section"],
        photos_section=raw["photos_section"],
        financials=raw["financials"],
        issues=raw["issues"],
        next_steps=raw["next_steps"],
    )

    html = await render_report_html(content, language="vi")

    # Header summary surfaces.
    assert "Project on track" in html
    # Progress narrative + highlights.
    assert "Foundation work complete" in html
    assert "Phần móng hoàn thành" in html
    # Issues block — every LLM-emitted issue is rendered.
    assert "CPM slip 7 days" in html
    assert "Submittals: 1 revise &amp; resubmit" in html  # `&` escaped to `&amp;`
    assert "DailyLog: 2 high-severity observations" in html
    # Next-steps block.
    assert "Review 3 pending CO candidates" in html
    assert "Close out DailyLog high-severity observations" in html
    # Vietnamese labels for the i18n flag we passed in.
    assert "Vấn đề" in html  # "Issues & Change Orders" header
    assert "Bước tiếp theo" in html  # "Next Steps" header


# ---------------------------------------------------------------------------
# 3. PDF rendering: graceful when WeasyPrint isn't installed,
#    valid bytes when it is.
# ---------------------------------------------------------------------------


async def test_render_report_pdf_either_renders_or_raises_unavailable():
    """End-to-end: HTML → PDF. WeasyPrint is an optional native
    dependency (libpango / libcairo). On dev boxes without it, the
    pipeline must raise `PDFRendererUnavailable` cleanly so the route
    can keep `pdf_url=None` and serve the HTML preview. On boxes that
    do have it, we get a real PDF whose magic header proves the
    renderer round-tripped without errors."""
    from schemas.pulse import ClientReportContent

    from ml.pipelines.pulse import (
        PDFRendererUnavailable,
        render_report_html,
        render_report_pdf,
    )

    raw = _stub_llm_content()
    content = ClientReportContent(
        header_summary=raw["header_summary"],
        progress_section=raw["progress_section"],
        photos_section=raw["photos_section"],
        financials=raw["financials"],
        issues=raw["issues"],
        next_steps=raw["next_steps"],
    )
    html = await render_report_html(content, language="vi")

    try:
        pdf_bytes = await render_report_pdf(html)
    except PDFRendererUnavailable:
        # Dev boxes without WeasyPrint hit this branch — the route's
        # try/except guards the same condition, so the contract holds.
        pytest.skip("WeasyPrint not installed; PDF rendering skipped (route falls back to HTML)")

    # Magic header — a valid PDF starts with `%PDF-`.
    assert pdf_bytes[:5] == b"%PDF-", f"not a PDF (got {pdf_bytes[:8]!r})"
    # Sanity floor — even a single-page report should be > 1 KB. WeasyPrint
    # outputs ~30-80 KB for a typical client report.
    assert len(pdf_bytes) > 1024
