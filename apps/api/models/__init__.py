"""Central model registry. Import everything here so Alembic sees all tables."""

from __future__ import annotations


def register_all() -> None:
    # Import inside function to avoid circulars during tooling
    from . import (
        assistant,  # noqa: F401
        bidradar,  # noqa: F401
        changeorder,  # noqa: F401
        codeguard,  # noqa: F401
        core,  # noqa: F401
        costpulse,  # noqa: F401
        dailylog,  # noqa: F401
        drawbridge,  # noqa: F401
        handover,  # noqa: F401
        pulse,  # noqa: F401
        punchlist,  # noqa: F401
        schedulepilot,  # noqa: F401
        search,  # noqa: F401
        siteeye,  # noqa: F401
        submittals,  # noqa: F401
        webhooks,  # noqa: F401
        winwork,  # noqa: F401
    )
