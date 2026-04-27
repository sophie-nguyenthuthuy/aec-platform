"""Unit tests for `pipelines.codeguard.generate_permit_checklist_stream`.

The streaming checklist's contract differs from the streaming Q&A's
because the LLM produces an array of items, not a single text answer.
The look-ahead-by-one heuristic in the generator means each item is
emitted only once, fully populated, even though `JsonOutputParser`
yields successive partial parses.

Coverage:
  * Items arrive in input order, exactly once each.
  * The trailing item gets emitted at end-of-stream (no item N+1
    triggers it via look-ahead).
  * Empty `items` array → no `item_done` events, single terminal
    `done` with empty list.
  * Items with missing fields get sane defaults via `_shape_checklist_item`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

_ML_ROOT = Path(__file__).resolve().parent.parent
_API_ROOT = _ML_ROOT.parent / "api"
for _p in (_ML_ROOT, _API_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _clear_hyde_cache():
    """Sibling tests share the cache across files; keep state clean."""
    import pipelines.codeguard as cg

    cg._hyde_clear_cache()
    yield
    cg._hyde_clear_cache()


def _canned_response(items: list[dict]) -> str:
    """Build a JSON string the FakeListChatModel will replay verbatim."""
    return json.dumps({"items": items}, ensure_ascii=False)


async def test_each_item_emits_once_in_input_order(monkeypatch):
    """Three items in the LLM response → three `item_done` events, in
    order, each shaped as a `ChecklistItem`. Then exactly one terminal
    `done` event with the full list.
    """
    import pipelines.codeguard as cg
    from schemas.codeguard import ChecklistItem

    canned = _canned_response(
        [
            {
                "id": "site-survey",
                "title": "Khảo sát hiện trạng",
                "description": "Bản vẽ khảo sát.",
                "regulation_ref": "QCVN 06:2022 §1.1",
                "required": True,
            },
            {
                "id": "fire-approval",
                "title": "Phê duyệt PCCC",
                "description": None,
                "regulation_ref": None,
                "required": True,
            },
            {
                "id": "env-impact",
                "title": "Đánh giá môi trường",
                "description": None,
                "regulation_ref": None,
                "required": False,
            },
        ]
    )
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.2: FakeListChatModel(responses=[canned]))

    events: list[tuple[str, object]] = []
    async for ev in cg.generate_permit_checklist_stream(
        db=None,
        jurisdiction="Hồ Chí Minh",
        project_type="residential",
        parameters=None,
    ):
        events.append(ev)

    item_events = [e for e in events if e[0] == "item_done"]
    assert len(item_events) == 3
    assert [e[1].id for e in item_events] == ["site-survey", "fire-approval", "env-impact"]
    # Items are real ChecklistItem instances, not raw dicts.
    assert all(isinstance(e[1], ChecklistItem) for e in item_events)

    # Single `done` at the very end, carrying the full list.
    assert events[-1][0] == "done"
    final_items = events[-1][1]
    assert len(final_items) == 3
    assert final_items[0].title == "Khảo sát hiện trạng"


async def test_single_item_still_gets_emitted_at_end_of_stream(monkeypatch):
    """The trailing item never gets the look-ahead trigger (no item
    N+1 ever appears) so it must be flushed at end-of-stream. Test
    with a single-item response to isolate this exit path."""
    import pipelines.codeguard as cg

    canned = _canned_response([{"id": "only", "title": "Lone item", "required": True}])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.2: FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.generate_permit_checklist_stream(
            db=None,
            jurisdiction="HCM",
            project_type="residential",
            parameters=None,
        )
    ]

    item_events = [e for e in events if e[0] == "item_done"]
    assert len(item_events) == 1
    assert item_events[0][1].id == "only"
    assert events[-1][0] == "done"
    assert len(events[-1][1]) == 1


async def test_empty_items_yields_only_terminal_done(monkeypatch):
    """LLM returned `{"items": []}` — emit no `item_done` events,
    single `done` with empty list. The frontend's empty-checklist
    advisory triggers off this shape."""
    import pipelines.codeguard as cg

    canned = _canned_response([])
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.2: FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.generate_permit_checklist_stream(
            db=None,
            jurisdiction="HCM",
            project_type="residential",
            parameters=None,
        )
    ]

    assert all(e[0] != "item_done" for e in events), (
        f"empty checklist emitted item events: {events}"
    )
    assert events[-1][0] == "done"
    assert events[-1][1] == []


async def test_missing_fields_get_sane_defaults(monkeypatch):
    """LLM omits fields → `_shape_checklist_item` fills defaults
    (synthetic `id`, empty `title`, required=True, status="pending").
    Pin so a careless prompt change doesn't crash the pipeline on
    incomplete items."""
    import pipelines.codeguard as cg

    canned = _canned_response(
        [
            {},  # totally bare
            {"title": "With title only"},
        ]
    )
    monkeypatch.setattr(cg, "_llm", lambda temperature=0.2: FakeListChatModel(responses=[canned]))

    events = [
        ev
        async for ev in cg.generate_permit_checklist_stream(
            db=None,
            jurisdiction="HCM",
            project_type="residential",
            parameters=None,
        )
    ]
    items = events[-1][1]
    assert items[0].id == "item-0"
    assert items[0].title == ""
    assert items[0].required is True
    assert items[0].status.value == "pending"
    assert items[1].title == "With title only"
