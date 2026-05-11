"""HTTP status code → severity tone mapper (cycle EE3, Python half).

Pinned seams (mirror of `apps/web/lib/__tests__/http-status-tone.test.ts`):
  1. SEVERITIES = (success, redirect, client_error, server_error, unknown).
  2. TONES     = (emerald, sky, amber, rose, zinc) parallel order.
  3. 2xx → success/emerald.
  4. 3xx → redirect/sky.
  5. 4xx → client_error/amber (408, 429 included).
  6. 5xx → server_error/rose.
  7. 1xx, 6xx+, None → unknown/zinc.
"""

from __future__ import annotations

from services.http_status_tone import (
    SEVERITIES,
    TONES,
    StatusTone,
    classify_status,
)

# ---------- Constants ----------


def test_severities_canonical_order():
    assert SEVERITIES == (
        "success",
        "redirect",
        "client_error",
        "server_error",
        "unknown",
    )


def test_tones_canonical_order():
    """Tailwind-compatible color names. Pin so a refactor to
    "danger" / "warn" doesn't break component class generation."""
    assert TONES == ("emerald", "sky", "amber", "rose", "zinc")


def test_severities_and_tones_parallel_length():
    assert len(SEVERITIES) == len(TONES)


# ---------- 2xx success ----------


def test_classify_200_success_emerald():
    assert classify_status(200) == StatusTone(severity="success", tone="emerald")


def test_classify_2xx_range_is_success():
    for code in [201, 204, 299]:
        assert classify_status(code).severity == "success"


# ---------- 3xx redirect ----------


def test_classify_301_redirect_sky():
    assert classify_status(301) == StatusTone(severity="redirect", tone="sky")


def test_classify_3xx_range_is_redirect():
    for code in [302, 307, 308]:
        assert classify_status(code).severity == "redirect"


# ---------- 4xx client_error ----------


def test_classify_400_client_error_amber():
    assert classify_status(400) == StatusTone(severity="client_error", tone="amber")


def test_classify_404_is_client_error():
    assert classify_status(404).severity == "client_error"


def test_classify_408_request_timeout_is_client_error_not_server():
    """Pin: 408 is HTTP-spec client_error — the client is at
    fault for taking too long. A "treat 408 as server_error
    because the network died" shortcut would mis-classify the
    failure card in the Slack digest."""
    assert classify_status(408) == StatusTone(severity="client_error", tone="amber")


def test_classify_429_too_many_requests_is_client_error():
    """Pin: 429 is client_error. NOT server_error."""
    assert classify_status(429) == StatusTone(severity="client_error", tone="amber")


def test_classify_4xx_range_boundary():
    assert classify_status(422).severity == "client_error"
    assert classify_status(499).severity == "client_error"


# ---------- 5xx server_error ----------


def test_classify_500_server_error_rose():
    assert classify_status(500) == StatusTone(severity="server_error", tone="rose")


def test_classify_5xx_range_is_server_error():
    for code in [502, 503, 504]:
        assert classify_status(code).severity == "server_error"


def test_classify_599_is_server_error():
    """Range boundary."""
    assert classify_status(599).severity == "server_error"


# ---------- Unknown ----------


def test_classify_1xx_is_unknown():
    """1xx is rare in webhook delivery context — treat as unknown
    rather than carve out an "info" bucket."""
    assert classify_status(100) == StatusTone(severity="unknown", tone="zinc")
    assert classify_status(199) == StatusTone(severity="unknown", tone="zinc")


def test_classify_6xx_plus_is_unknown():
    assert classify_status(600) == StatusTone(severity="unknown", tone="zinc")
    assert classify_status(999) == StatusTone(severity="unknown", tone="zinc")


def test_classify_zero_and_negative_is_unknown():
    assert classify_status(0).severity == "unknown"
    assert classify_status(-1).severity == "unknown"


def test_classify_none_is_unknown():
    """A row with NULL response_status (e.g. delivery failed
    before getting a response) classifies as unknown — pin so
    the row renders rather than crashes."""
    assert classify_status(None) == StatusTone(severity="unknown", tone="zinc")


# ---------- Boundary values ----------


def test_boundary_199_unknown_200_success():
    assert classify_status(199).severity == "unknown"
    assert classify_status(200).severity == "success"


def test_boundary_299_success_300_redirect():
    assert classify_status(299).severity == "success"
    assert classify_status(300).severity == "redirect"


def test_boundary_399_redirect_400_client_error():
    assert classify_status(399).severity == "redirect"
    assert classify_status(400).severity == "client_error"


def test_boundary_499_client_error_500_server_error():
    assert classify_status(499).severity == "client_error"
    assert classify_status(500).severity == "server_error"


# ---------- StatusTone shape ----------


def test_status_tone_is_frozen():
    s = StatusTone(severity="success", tone="emerald")
    try:
        s.severity = "unknown"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("StatusTone should be frozen")


# ---------- Cross-language consistency ----------


def test_matches_ts_half_byte_for_byte():
    """Cross-language pin: TS and Python halves classify every
    representative code identically. A divergence (e.g. one
    half treating 408 as server_error) would surface here."""
    cases = [
        (200, "success", "emerald"),
        (201, "success", "emerald"),
        (301, "redirect", "sky"),
        (308, "redirect", "sky"),
        (400, "client_error", "amber"),
        (404, "client_error", "amber"),
        (408, "client_error", "amber"),
        (429, "client_error", "amber"),
        (500, "server_error", "rose"),
        (502, "server_error", "rose"),
        (100, "unknown", "zinc"),
        (600, "unknown", "zinc"),
        (None, "unknown", "zinc"),
    ]
    for code, expected_severity, expected_tone in cases:
        result = classify_status(code)
        assert result.severity == expected_severity, (
            f"classify_status({code}).severity = {result.severity!r}, expected {expected_severity!r}"
        )
        assert result.tone == expected_tone, (
            f"classify_status({code}).tone = {result.tone!r}, expected {expected_tone!r}"
        )
