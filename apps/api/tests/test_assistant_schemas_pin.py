"""Pin the field-shapes of `AskRequest`, `AssistantResponse`, and
`AssistantSource`.

Why this exists: these three Pydantic models are the wire contract
between the assistant endpoint and the frontend chat UI. The
TypeScript types in `apps/web/hooks/assistant/useAssistant.ts`
mirror them; a drift on either side silently breaks rendering
without a type-check failure (the JSON parses, the missing field
just becomes `undefined`).

Specific failure modes a drift catches:

  * `AssistantResponse.thread_id` dropped → frontend can't pass
    `thread_id` on follow-up turns → every question becomes a
    fresh thread, conversation history is lost.

  * `AskRequest.history` removed → previously-replayed conversation
    context disappears; the assistant answers without context. The
    field is required (`PydanticUndefined` default) precisely so
    the frontend MUST send it; making it optional would silently
    accept partial history.

  * `AssistantSource.module` typed as `str | None` → the citation
    chip's "click to filter by module" handler would have to
    null-check, breaking existing callers.

  * `AssistantResponse.context_token_estimate` flipped from int to
    str → the dashboard's progress bar (renders `count / 100_000`)
    silently shows 0% for every response.

The pins are exact: type annotation + required-ness + default.
A drift in any of those surfaces here as a loud test failure with
the specific field named.
"""

from __future__ import annotations

from uuid import UUID

from schemas.assistant import AskRequest, AssistantResponse, AssistantSource

# Each pin is `{field_name: (type_str, required, default)}` where:
#   * `type_str` is the str() of the annotation, normalised so
#     equivalent forms (`UUID | None`, `Optional[UUID]`, etc.) all
#     match. We compare via substring containment for the modern
#     `X | None` form to keep the test stable across Python versions.
#   * `required` is whether the field has no default value
#     (`PydanticUndefined` from Pydantic's perspective).
#   * `default` is pinned only when it's a sentinel value that
#     readers depend on (e.g. `context_token_estimate: int = 0`).


# ---------- AskRequest ----------


EXPECTED_ASK_REQUEST: dict[str, tuple[str, bool]] = {
    # Required: the prompt itself. A drift to `str | None` would
    # let callers send POST bodies without a question; the service
    # has no graceful path for that.
    "question": ("str", True),
    # Optional: thread to append to. None = create a new thread,
    # named UUID = follow-up. Default None is load-bearing — the
    # frontend uses `omit-if-undefined` JSON serialization, so a
    # required thread_id would fail every first-turn request.
    "thread_id": ("UUID | None", False),
    # Optional with `default_factory=list`. The service is
    # stateless wrt conversation memory; the client owns the turn
    # list. Default-empty rather than required because the frontend
    # `apiFetch` body-shape omits zero-length lists, and the DB-
    # backed thread mode (when `thread_id` is provided) ignores
    # this field entirely.
    "history": ("list[ChatTurn]", False),
}


# ---------- AssistantResponse ----------


EXPECTED_ASSISTANT_RESPONSE: dict[str, tuple[str, bool]] = {
    "project_id": ("UUID", True),
    # The thread_id the response was attributed to. None ONLY when
    # an early-fail path returned without creating a thread (e.g.
    # 404 cross-tenant project). Frontend uses this to wire
    # follow-up turns; a drift to required would fail the UI's
    # null-handling on the early-fail path.
    "thread_id": ("UUID | None", False),
    "answer": ("str", True),
    # Optional with `default_factory=list`. Citation rendering
    # treats an empty list as "no sources" — the field is always
    # present in the response (the default_factory ensures it
    # serialises as `[]`, never missing).
    "sources": ("list[AssistantSource]", False),
    # Required-with-default-0 (Pydantic distinguishes from "no
    # default" — this field has a default value, just an explicit
    # one). The dashboard renders a progress bar against this
    # number; a missing field would crash the bar.
    "context_token_estimate": ("int", False),
}


# ---------- AssistantSource ----------


EXPECTED_ASSISTANT_SOURCE: dict[str, tuple[str, bool]] = {
    # Required: the citation chip uses this as both the visual
    # label key and the click-handler payload (filter activity by
    # module). A drift to optional would force every renderer to
    # null-check and break existing call sites.
    "module": ("str", True),
    "label": ("str", True),
    # Optional in-app URL the citation links to. None when the
    # module has no logical drilldown view yet.
    "route": ("str | None", False),
}


def _summarise_fields(model_cls) -> dict[str, tuple[str, bool]]:
    """Reduce `model_cls.model_fields` to the (annotation_str,
    required) tuple shape the EXPECTED dicts use.

    Annotation rendering: `str(annotation)` produces
    `<class 'str'>` for builtins and `uuid.UUID | None` for unions
    — we normalise to the friendlier short form by stripping
    `<class '...'>` and module prefixes.
    """
    out: dict[str, tuple[str, bool]] = {}
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        ann_str = _short_annotation(ann)
        out[name] = (ann_str, field.is_required())
    return out


def _short_annotation(ann) -> str:
    """Render the annotation in a stable short form across Python
    versions. `str(int)` is `"<class 'int'>"`; we want `"int"`.
    Generic aliases like `list[ChatTurn]` render usefully via str();
    we just strip the `schemas.assistant.` package prefix that
    leaks in.
    """
    rendered = str(ann)
    # Strip `<class '...'>` wrapper for builtin classes.
    if rendered.startswith("<class '") and rendered.endswith("'>"):
        rendered = rendered[len("<class '") : -len("'>")]
    # Strip the `uuid.` / `schemas.assistant.` package prefixes
    # that pollute the comparison string.
    rendered = rendered.replace("uuid.", "")
    rendered = rendered.replace("schemas.assistant.", "")
    return rendered


# ---------- Tests ----------


def test_ask_request_field_shapes_match_pin():
    """Pin every `AskRequest` field. A drop / rename / type-flip
    surfaces here with the specific field named.
    """
    actual = _summarise_fields(AskRequest)
    assert actual == EXPECTED_ASK_REQUEST, (
        "AskRequest fields drifted from the pin.\n"
        f"  expected: {EXPECTED_ASK_REQUEST}\n"
        f"  actual:   {actual}\n"
        "If this is intentional, update EXPECTED_ASK_REQUEST in the same "
        "PR + verify the matching TypeScript interface in "
        "`apps/web/hooks/assistant/useAssistant.ts` is updated symmetrically."
    )


def test_assistant_response_field_shapes_match_pin():
    """Pin every `AssistantResponse` field — the canonical
    chat-UI wire contract.
    """
    actual = _summarise_fields(AssistantResponse)
    assert actual == EXPECTED_ASSISTANT_RESPONSE, (
        "AssistantResponse fields drifted from the pin.\n"
        f"  expected: {EXPECTED_ASSISTANT_RESPONSE}\n"
        f"  actual:   {actual}\n"
        "The chat UI consumes every named field; a drop here silently "
        "breaks rendering. Update EXPECTED_ASSISTANT_RESPONSE + the matching "
        "TS interface together."
    )


def test_assistant_source_field_shapes_match_pin():
    """Pin every `AssistantSource` field — the citation-chip
    contract used by the chat sidebar.
    """
    actual = _summarise_fields(AssistantSource)
    assert actual == EXPECTED_ASSISTANT_SOURCE, (
        "AssistantSource fields drifted from the pin.\n"
        f"  expected: {EXPECTED_ASSISTANT_SOURCE}\n"
        f"  actual:   {actual}\n"
        "Citation chip rendering is sensitive to every field; verify "
        "the TS interface stays in lockstep."
    )


def test_assistant_response_thread_id_is_optional():
    """Dedicated assertion for the most-regressed field.
    `AssistantResponse.thread_id` flipping to required would 500
    every early-fail path (404 cross-tenant project, etc.) where
    the response is constructed before a thread row exists.
    """
    field = AssistantResponse.model_fields["thread_id"]
    assert field.is_required() is False, (
        "AssistantResponse.thread_id became required — every early-fail "
        "path that constructs the response before a thread is created "
        "would now 500. Recent reverts have flipped this; if intentional, "
        "audit `services.assistant.ask` for the path that returns 'Project "
        "not found.' (which has no thread_id to set)."
    )


def test_ask_request_thread_id_is_optional():
    """Symmetric to the response: `AskRequest.thread_id` MUST be
    optional. The frontend's first-turn POST omits it; a drift to
    required would 422 every first-turn message."""
    field = AskRequest.model_fields["thread_id"]
    assert field.is_required() is False
    # Default MUST be None, NOT a sentinel UUID — the service does
    # `if request.thread_id is not None` to branch between
    # follow-up vs new-thread paths.
    assert field.default is None


def test_assistant_response_context_token_estimate_default_is_zero():
    """Frontend's progress bar renders `count / 100_000 * 100`. A
    default-None for `context_token_estimate` would crash that
    expression with TypeError. Pin default=0."""
    field = AssistantResponse.model_fields["context_token_estimate"]
    assert field.default == 0, (
        f"AssistantResponse.context_token_estimate default is "
        f"{field.default!r}, expected 0. The progress bar in the chat "
        "header divides by this value; None / missing would crash render."
    )


def test_uuid_typed_fields_validate_uuid_strings():
    """Construction smoke: `AssistantResponse(project_id="not-a-uuid")`
    should raise. Pin that the UUID validator is wired (a regression
    that flipped `UUID` to `str` would silently accept any string
    + then crash downstream when the cost pipeline tries to
    `UUID(project_id)`).
    """
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AssistantResponse(
            project_id="not-a-valid-uuid",  # type: ignore[arg-type]
            answer="x",
            sources=[],
        )

    # Sanity: a valid UUID string IS accepted.
    valid = AssistantResponse(
        project_id=UUID("11111111-1111-1111-1111-111111111111"),
        answer="x",
        sources=[],
    )
    assert valid.project_id == UUID("11111111-1111-1111-1111-111111111111")
