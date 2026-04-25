"""Unit tests for `pipelines.codeguard._ground_citations`.

This is the single choke point that guards the CODEGUARD query pipeline
against the #1 failure mode for RAG compliance tools: the LLM inventing
authoritative-looking section refs or quotes that don't exist in the
retrieved source. These tests feed it deliberately tampered inputs and
assert each class of tampering gets caught.

Why unit-test (not cover this in the integration test): the integration
test proves the happy path end-to-end. The tampered paths need deterministic
inputs — which we can only control cleanly at the function boundary.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# `pipelines.codeguard` imports `schemas.codeguard` from apps/api — add both
# to sys.path so pytest works from repo root without docker-compose env.
_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture
def candidates() -> list[dict]:
    """Two retrieved chunks — the set the LLM is allowed to cite from."""
    return [
        {
            "id": str(uuid4()),
            "regulation_id": "11111111-1111-1111-1111-111111111111",
            "section_ref": "3.2.1",
            "content": (
                "Chiều rộng thông thủy của hành lang thoát nạn trong nhà "
                "chung cư không được nhỏ hơn 1.4 m."
            ),
            "code_name": "QCVN 06:2022/BXD",
            "source_url": "https://example.gov.vn/qcvn06",
        },
        {
            "id": str(uuid4()),
            "regulation_id": "22222222-2222-2222-2222-222222222222",
            "section_ref": "4.1",
            "content": "Hệ thống báo cháy tự động phải được lắp đặt ở mọi tầng.",
            "code_name": "QCVN 06:2022/BXD",
            "source_url": None,
        },
    ]


def test_faithful_llm_excerpt_preserved(candidates):
    """LLM-provided excerpt that actually appears in the source is kept verbatim."""
    from pipelines.codeguard import _ground_citations

    raw = [
        {
            "chunk_index": 0,
            "regulation": "QCVN 06:2022/BXD",
            "section": "3.2.1",
            "excerpt": "không được nhỏ hơn 1.4 m",
        }
    ]
    out = _ground_citations(raw, candidates)

    assert len(out) == 1
    cit = out[0]
    assert cit.regulation_id == UUID("11111111-1111-1111-1111-111111111111")
    assert cit.section == "3.2.1"
    assert cit.excerpt == "không được nhỏ hơn 1.4 m"
    # Provenance (code_name, source_url) comes from the DB row, not the LLM.
    assert cit.regulation == "QCVN 06:2022/BXD"
    assert str(cit.source_url) == "https://example.gov.vn/qcvn06"


def test_hallucinated_excerpt_replaced_with_chunk_prefix(candidates, caplog):
    """LLM quote not present in the source chunk falls back to chunk[:300]."""
    from pipelines.codeguard import _ground_citations

    raw = [
        {
            "chunk_index": 0,
            "section": "3.2.1",
            # Plausible-sounding but not in the chunk content — the classic
            # compliance-tool failure mode.
            "excerpt": "must be at least 2.0 metres wide per Annex B",
        }
    ]
    with caplog.at_level(logging.WARNING, logger="pipelines.codeguard"):
        out = _ground_citations(raw, candidates)

    assert len(out) == 1
    # Guarded: excerpt replaced with the chunk content prefix.
    assert out[0].excerpt == candidates[0]["content"][:300]
    assert out[0].excerpt.startswith("Chiều rộng")
    # And it was logged, so production debugging is possible.
    assert any("ungrounded excerpt" in r.message for r in caplog.records)


def test_excerpt_match_is_case_and_whitespace_insensitive(candidates):
    """Collapsed whitespace + case-fold — common LLM paraphrasing."""
    from pipelines.codeguard import _ground_citations

    raw = [
        {
            "chunk_index": 0,
            # Original: "không được nhỏ hơn 1.4 m"
            # LLM variants we should accept as faithful:
            "excerpt": "KHÔNG   được\nnhỏ  hơn 1.4 m",
        }
    ]
    out = _ground_citations(raw, candidates)
    assert len(out) == 1
    # Preserved as-typed (display fidelity) — we only use the normalised
    # form for the substring check, not for storage.
    assert out[0].excerpt == "KHÔNG   được\nnhỏ  hơn 1.4 m"


def test_empty_excerpt_falls_back_to_chunk_prefix(candidates):
    """Missing/blank excerpt from the LLM → chunk content prefix, no warning needed."""
    from pipelines.codeguard import _ground_citations

    out = _ground_citations(
        [{"chunk_index": 1, "excerpt": ""}],
        candidates,
    )
    assert len(out) == 1
    assert out[0].excerpt == candidates[1]["content"][:300]


def test_missing_excerpt_key_falls_back_to_chunk_prefix(candidates):
    from pipelines.codeguard import _ground_citations

    out = _ground_citations([{"chunk_index": 1}], candidates)
    assert len(out) == 1
    assert out[0].excerpt.startswith("Hệ thống báo cháy")


def test_out_of_range_chunk_index_dropped(candidates, caplog):
    """LLM cites chunk 5 but only 2 were retrieved — drop it, log it."""
    from pipelines.codeguard import _ground_citations

    raw = [
        {"chunk_index": 0, "excerpt": "không được nhỏ hơn 1.4 m"},
        {"chunk_index": 5, "excerpt": "invented content"},  # out of range
    ]
    with caplog.at_level(logging.WARNING, logger="pipelines.codeguard"):
        out = _ground_citations(raw, candidates)

    assert len(out) == 1  # only the valid one survives
    assert out[0].regulation_id == UUID("11111111-1111-1111-1111-111111111111")
    assert any("out-of-range" in r.message for r in caplog.records)


def test_negative_chunk_index_dropped(candidates):
    """Python lets `list[-1]` return the last element, but that's not the
    intent — LLMs should cite by 0..N-1 index, negative is always noise."""
    from pipelines.codeguard import _ground_citations

    out = _ground_citations([{"chunk_index": -1, "excerpt": "x"}], candidates)
    assert out == []


def test_none_chunk_index_dropped(candidates):
    """LLM omitted chunk_index entirely — can't ground → drop."""
    from pipelines.codeguard import _ground_citations

    out = _ground_citations(
        [{"regulation": "Q", "section": "1.1", "excerpt": "y"}],
        candidates,
    )
    assert out == []


def test_string_chunk_index_dropped(candidates):
    """A string like '0' would TypeError on comparison — reject at type check."""
    from pipelines.codeguard import _ground_citations

    out = _ground_citations([{"chunk_index": "0", "excerpt": "z"}], candidates)
    assert out == []


def test_bool_chunk_index_dropped(candidates):
    """`isinstance(True, int)` is True in Python; treat bool as garbage."""
    from pipelines.codeguard import _ground_citations

    out = _ground_citations([{"chunk_index": True, "excerpt": "z"}], candidates)
    assert out == []


def test_empty_candidates_drops_everything(candidates):
    """Retrieval returned nothing → every citation is ungrounded → empty."""
    from pipelines.codeguard import _ground_citations

    raw = [{"chunk_index": 0, "excerpt": "anything"}]
    assert _ground_citations(raw, []) == []


def test_llm_cannot_override_regulation_or_section_fields(candidates):
    """Even if the LLM supplies 'regulation' and 'section' strings, the
    output comes from the DB row. This is the core grounding invariant:
    the LLM can only *choose* which chunk to cite, never *name* it."""
    from pipelines.codeguard import _ground_citations

    raw = [
        {
            "chunk_index": 0,
            "regulation": "FAKE CODE 99",
            "section": "§99.9",
            "excerpt": "không được nhỏ hơn 1.4 m",
        }
    ]
    out = _ground_citations(raw, candidates)
    assert out[0].regulation == "QCVN 06:2022/BXD"  # from DB
    assert out[0].section == "3.2.1"  # from DB


def test_malformed_regulation_id_in_source_drops_citation(candidates, caplog):
    """Defensive: if the retrieved row somehow has a non-UUID regulation_id
    (shouldn't happen with our schema but guards against DB corruption or
    future test-fixture mistakes), drop the citation instead of crashing."""
    from pipelines.codeguard import _ground_citations

    bad = dict(candidates[0])
    bad["regulation_id"] = "not-a-uuid"
    with caplog.at_level(logging.WARNING, logger="pipelines.codeguard"):
        out = _ground_citations([{"chunk_index": 0, "excerpt": "x"}], [bad])
    assert out == []
    assert any("regulation_id" in r.message for r in caplog.records)


def test_none_input_is_safe():
    """Pipeline passes `raw.get('citations', []) or []` — both None and []
    must be accepted without blowing up."""
    from pipelines.codeguard import _ground_citations

    assert _ground_citations([], []) == []
    # The pipeline's defensive `or []` converts None → [], but double-check
    # the function itself treats a falsy list-like as no citations.
    assert _ground_citations([], [{"regulation_id": str(uuid4()), "content": "x"}]) == []
