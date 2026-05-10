"""Audit search highlighter (cycle WW1, Python half).

Server-side mirror of `apps/web/lib/highlight-matches.ts`. Used
by the Slack alert digest excerpt builder, the email digest's
search-result preview, and the audit row plaintext export's
highlight markers.

  find_matches(text, terms)  — tuple[Match, ...]
  Match                      — frozen dataclass: (start, end)

Composes with II1's `parse_search_query.free_text`.

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    """A non-overlapping match span in the original text.

    `start` is inclusive, `end` is exclusive. Indexes refer to
    the ORIGINAL `text` (NOT the lowercased version) — caller
    can slice directly.
    """

    start: int
    end: int


def find_matches(
    text: str | None,
    terms: list[str],
) -> tuple[Match, ...]:
    """Find non-overlapping match spans for any of `terms` in `text`.

    Algorithm:
      1. Lowercase `text` and each `term` for case-insensitive
         matching.
      2. Collect ALL candidate matches (overlapping allowed).
      3. Sort by (start ASC, length DESC) so earlier wins; on
         tie, longer term wins.
      4. Greedy left-to-right select non-overlapping spans.

    Returns matches in document order.
    """
    if not text or not terms:
        return ()

    text_lower = text.lower()
    candidates: list[tuple[int, int]] = []

    for term in terms:
        if not term:
            continue
        t = term.strip().lower()
        if not t:
            continue
        idx = 0
        while idx < len(text_lower):
            found = text_lower.find(t, idx)
            if found < 0:
                break
            candidates.append((found, found + len(t)))
            idx = found + 1

    if not candidates:
        return ()

    # Sort: start ASC, length DESC (longer wins on same start).
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))

    result: list[Match] = []
    last_end = 0
    for start, end in candidates:
        if start >= last_end:
            result.append(Match(start=start, end=end))
            last_end = end

    return tuple(result)
