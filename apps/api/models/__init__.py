"""Central model registry. Import everything here so Alembic sees all tables."""
from __future__ import annotations


def register_all() -> None:
    # Import inside function to avoid circulars during tooling
    from . import core  # noqa: F401
    from . import winwork  # noqa: F401
    from . import costpulse  # noqa: F401
    from . import pulse  # noqa: F401
    from . import codeguard  # noqa: F401
    from . import handover  # noqa: F401
    from . import drawbridge  # noqa: F401
    from . import siteeye  # noqa: F401
    from . import bidradar  # noqa: F401
