"""OpenAPI schema snapshot test.

FastAPI auto-derives `app.openapi()` from every route handler's
signature + every Pydantic schema referenced. Without a snapshot,
accidental breaking changes ship silently:

  * A field renamed in `schemas/*.py` (frontend types stop compiling
    if you're lucky; otherwise it's a runtime "missing field" 422).
  * A required parameter added to a `@router.get(...)` signature
    (every existing client breaks).
  * An endpoint deleted or path-prefix-renamed.
  * A response model swapped from `EnvelopeOut[Foo]` to `Foo` (the
    `data`/`meta`/`errors` shape disappears — the most-impactful
    silent regression because every TanStack hook unwraps via
    `res.data`).

This test serializes `app.openapi()` to a stable JSON shape and
diff-checks it against `tests/openapi.snapshot.json`. CI fails on
diff. Intentional changes regenerate the snapshot via:

    pytest tests/test_openapi_snapshot.py --snapshot-update

(See `_should_update()` below — we use a flag rather than the
pytest-snapshot dep so this stays at one file with no new install.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SNAPSHOT_PATH = Path(__file__).parent / "openapi.snapshot.json"


def _should_update() -> bool:
    """Read SNAPSHOT_UPDATE env var. Env-var rather than a CLI flag
    avoids adding a pytest plugin dep + the conftest registration
    that goes with it. Standard pattern: regenerate via
    `SNAPSHOT_UPDATE=1 pytest tests/test_openapi_snapshot.py`."""
    import os

    return os.environ.get("SNAPSHOT_UPDATE") == "1"


def _normalize(schema: dict) -> dict:
    """Strip fields that aren't part of the contract.

    `version` shifts on every release; we don't care about that for
    diffing — the contract is paths + schemas + parameter shapes.
    """
    schema = dict(schema)
    info = dict(schema.get("info", {}))
    info.pop("version", None)
    schema["info"] = info
    return schema


def test_openapi_schema_matches_snapshot():
    """Serialize the live OpenAPI schema and compare to the checked-in
    snapshot. Sort keys so the diff is line-by-line readable in code
    review when something does change."""
    from main import app

    current = _normalize(app.openapi())
    current_json = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False)

    if _should_update():
        SNAPSHOT_PATH.write_text(current_json + "\n", encoding="utf-8")
        pytest.skip(
            f"Snapshot updated: {SNAPSHOT_PATH.name} "
            f"({len(current.get('paths', {}))} paths, "
            f"{len(current.get('components', {}).get('schemas', {}))} schemas)"
        )

    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"No snapshot at {SNAPSHOT_PATH}. Run "
            "`SNAPSHOT_UPDATE=1 pytest tests/test_openapi_snapshot.py` "
            "to create it."
        )

    expected_json = SNAPSHOT_PATH.read_text(encoding="utf-8").rstrip()
    if current_json != expected_json:
        # Surface the first 3 path-level differences inline so the
        # CI log is informative without dumping the whole 194-path
        # schema.
        cur_paths = set(current.get("paths", {}).keys())
        with SNAPSHOT_PATH.open(encoding="utf-8") as f:
            expected = json.load(f)
        exp_paths = set(expected.get("paths", {}).keys())

        added = sorted(cur_paths - exp_paths)
        removed = sorted(exp_paths - cur_paths)

        msg = ["OpenAPI schema diverged from snapshot."]
        if added:
            msg.append(f"  ADDED paths ({len(added)}):")
            msg.extend(f"    + {p}" for p in added[:10])
            if len(added) > 10:
                msg.append(f"    ... and {len(added) - 10} more")
        if removed:
            msg.append(f"  REMOVED paths ({len(removed)}):")
            msg.extend(f"    - {p}" for p in removed[:10])
            if len(removed) > 10:
                msg.append(f"    ... and {len(removed) - 10} more")
        if not added and not removed:
            msg.append(
                "  Same path set — but parameter / response shapes changed. "
                "Run `SNAPSHOT_UPDATE=1 pytest tests/test_openapi_snapshot.py` "
                "to see the full diff in `git diff openapi.snapshot.json`."
            )
        msg.append("")
        msg.append("If the change is intentional, regenerate the snapshot with:")
        msg.append("  pytest tests/test_openapi_snapshot.py --snapshot-update")
        msg.append(
            "and commit the updated `tests/openapi.snapshot.json` in the "
            "same PR. Reviewers should scan the diff for breaking "
            "changes (renamed fields, removed endpoints, status-code "
            "shifts)."
        )

        pytest.fail("\n".join(msg))
