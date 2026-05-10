"""Vietnamese name formatter (cycle QQ2, Python half).

Server-side mirror of `apps/web/lib/format-name-vn.ts`. Used by:

  * The audit row actor display (`actor_name` column).
  * The Slack alert digest's "approved by" attribution.
  * The invoice template's signer line.
  * The CSV pinned-export columns where actor names appear.

  format_name_vn(name, fmt)   — formatted string
  VietnameseName              — frozen dataclass
  NameFormat                  — Literal type

Pure stdlib.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

NameFormat = Literal["full", "given", "western", "initials"]


@dataclass(frozen=True)
class VietnameseName:
    """A Vietnamese name in three parts.

    family: Họ (surname) — required.
    middle: Tên đệm — optional, may be multi-word.
    given:  Tên — optional.
    """

    family: str
    middle: str
    given: str


_WHITESPACE_SPLIT_RE = re.compile(r"\s+")


def _initials(parts: list[str]) -> str:
    """First-letter initial for each space-separated word."""
    result: list[str] = []
    for part in parts:
        for word in _WHITESPACE_SPLIT_RE.split(part):
            if word:
                result.append(word[0].upper())
    return "".join(result)


def format_name_vn(
    name: VietnameseName,
    fmt: NameFormat = "full",
) -> str:
    """Format a VN name.

    Empty family → "" (family is required — defends against
    accidental "given-only" output that looks like a Western
    first name in an audit attribution).
    """
    family = name.family.strip()
    if not family:
        return ""

    middle = name.middle.strip()
    given = name.given.strip()

    if fmt == "given":
        return given

    if fmt == "western":
        return f"{given} {family}" if given else family

    if fmt == "initials":
        parts = [family]
        if middle:
            parts.append(middle)
        if given:
            parts.append(given)
        return _initials(parts)

    # Default: "full" — VN convention family → middle → given.
    parts = [family]
    if middle:
        parts.append(middle)
    if given:
        parts.append(given)
    return " ".join(parts)
