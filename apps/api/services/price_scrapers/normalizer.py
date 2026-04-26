"""Map raw Vietnamese material descriptions to our canonical `material_code`.

Vietnamese provincial price lists name the same materials inconsistently:
    "Bê tông thương phẩm M300" ≈ "Bê tông tươi C30 (30 MPa)" ≈ "BT C30"
We normalise to the same ~20 codes the cost pipelines use: CONC_C25,
CONC_C30, CONC_C40, REBAR_CB300, REBAR_CB500, BRICK_RED, TILE_CERAMIC,
PAINT_EMULSION, etc.

Approach: a list of (regex pattern, code, category, canonical_name, unit_hint)
rules, scanned in order. First match wins. The patterns are intentionally
permissive — we'd rather over-match than under-match, and the writer
de-duplicates on `(material_code, province, effective_date)`.

Rules that fail to match are surfaced via `unmatched` so ops can add new
patterns after each scrape run.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from .base import NormalisedPrice, ScrapedPrice

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    code: str
    category: str
    canonical: str
    preferred_units: tuple[str, ...] = ()


def _r(pat: str) -> re.Pattern[str]:
    return re.compile(pat, re.IGNORECASE)


# Rule order matters — put more-specific patterns first.
_RULES: list[_Rule] = [
    # Concrete by grade. Vietnamese practice uses both M-series (old, by
    # cube strength) and C-series (new, by cylinder — matches our codes).
    _Rule(_r(r"bê\s*tông.*(c[\s-]?40|m[\s-]?400|40\s*mpa)"), "CONC_C40", "concrete", "Concrete C40", ("m3",)),
    _Rule(_r(r"bê\s*tông.*(c[\s-]?30|m[\s-]?300|30\s*mpa)"), "CONC_C30", "concrete", "Concrete C30", ("m3",)),
    _Rule(_r(r"bê\s*tông.*(c[\s-]?25|m[\s-]?250|25\s*mpa)"), "CONC_C25", "concrete", "Concrete C25", ("m3",)),
    # Rebar.
    _Rule(
        _r(r"(thép|rebar).*(cb\s*500|sd\s*500|grade\s*500)"),
        "REBAR_CB500",
        "steel",
        "Rebar CB500",
        ("kg", "tấn", "ton"),
    ),
    _Rule(
        _r(r"(thép|rebar).*(cb\s*300|sd\s*295|grade\s*300)"),
        "REBAR_CB300",
        "steel",
        "Rebar CB300",
        ("kg", "tấn", "ton"),
    ),
    # Structural steel profiles.
    _Rule(
        _r(r"(thép\s*hình|thép\s*tấm|structural\s*steel|h[\s-]?beam|i[\s-]?beam)"),
        "STEEL_STRUCT",
        "steel",
        "Structural steel",
        ("kg", "tấn", "ton"),
    ),
    # Masonry — red clay brick vs AAC block.
    _Rule(
        _r(r"(gạch\s*AAC|aac|khí\s*chưng\s*áp|bê\s*tông\s*nhẹ)"), "BRICK_AAC", "masonry", "AAC block", ("m3", "viên")
    ),
    _Rule(
        _r(r"(gạch\s*đỏ|gạch\s*tuynel|clay\s*brick|red\s*brick|gạch\s*đất\s*nung)"),
        "BRICK_RED",
        "masonry",
        "Red clay brick",
        ("viên", "1000 viên"),
    ),
    # Cement.
    _Rule(
        _r(r"(xi\s*măng|cement).*(pcb[\s-]?40|pcb\s*40)"), "CEMENT_PCB40", "other", "Cement PCB40", ("kg", "bao", "tấn")
    ),
    # Aggregates.
    _Rule(_r(r"(cát\s*mịn|fine\s*sand|cát\s*vàng)"), "SAND_FINE", "other", "Fine sand", ("m3",)),
    _Rule(_r(r"(đá\s*1\s*x\s*2|gravel\s*1x2|đá\s*dăm)"), "GRAVEL_1x2", "other", "Gravel 1x2", ("m3",)),
    # Finishes.
    _Rule(
        _r(r"(gạch\s*(lát|ốp)|ceramic\s*tile|gạch\s*men|gạch\s*granite)"),
        "TILE_CERAMIC",
        "finishing",
        "Ceramic tile",
        ("m2",),
    ),
    _Rule(
        _r(r"(sơn\s*ngoại\s*thất|exterior\s*paint|sơn\s*chống\s*thấm)"),
        "PAINT_EXTERIOR",
        "finishing",
        "Exterior paint",
        ("kg", "lit", "lít"),
    ),
    _Rule(
        _r(r"(sơn\s*nội\s*thất|sơn\s*nhũ\s*tương|interior\s*paint|emulsion)"),
        "PAINT_EMULSION",
        "finishing",
        "Emulsion paint",
        ("kg", "lit", "lít"),
    ),
    _Rule(_r(r"(vữa\s*trát|plaster|vữa\s*xây)"), "PLASTER", "finishing", "Plaster mortar", ("m3",)),
    _Rule(
        _r(r"(chống\s*thấm|waterproof(ing)?|màng\s*bitum)"),
        "WATERPROOF_MEMBRANE",
        "finishing",
        "Waterproof membrane",
        ("m2", "kg"),
    ),
]


def _strip_accents(s: str) -> str:
    """Not used for matching (we want UTF-8-aware patterns) but handy for debug."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _match(raw_name: str) -> _Rule | None:
    s = raw_name.strip()
    for rule in _RULES:
        if rule.pattern.search(s):
            return rule
    return None


@dataclass(frozen=True)
class NormalisationResult:
    """Structured output of `normalise()` — used for drift telemetry.

    `rule_hits` maps `material_code` → number of rows that matched it
    in this single normalisation pass. Codes that didn't match anything
    are still listed at zero, so trend queries can spot a previously-
    active rule going dark (the strongest drift signal).

    For backward compatibility, this object unpacks as `(matched, unmatched)`
    via `__iter__` so callers that only want the original tuple shape keep
    working — but new code should reach for the named attributes.
    """

    matched: list[NormalisedPrice]
    unmatched: list[ScrapedPrice]
    rule_hits: dict[str, int]

    def __iter__(self):
        # 2-tuple unpacking — matches the historic return signature.
        # `for x in result` is meaningless here; this is solely for
        # `matched, unmatched = normalise(rows)` callers.
        yield self.matched
        yield self.unmatched


# All known material_codes — pre-populated to zero per call so a code
# that *should* fire but didn't this run is still in `rule_hits`.
# Computed once at import.
_ALL_CODES: tuple[str, ...] = tuple(rule.code for rule in _RULES)


def normalise(rows: list[ScrapedPrice]) -> NormalisationResult:
    """Map each ScrapedPrice to our catalogue.

    Returns a `NormalisationResult` with `matched`, `unmatched`, and
    `rule_hits`. Two-tuple unpacking still works:

        matched, unmatched = normalise(rows)

    Unmatched rows should be logged so ops can either update `_RULES` or
    mark them as intentionally-ignored (e.g. "Lao động phổ thông" —
    labour — doesn't belong in material_prices).
    """
    normalised: list[NormalisedPrice] = []
    unmatched: list[ScrapedPrice] = []
    hits: dict[str, int] = {code: 0 for code in _ALL_CODES}

    for row in rows:
        rule = _match(row.raw_name)
        if rule is None:
            unmatched.append(row)
            continue

        hits[rule.code] = hits.get(rule.code, 0) + 1

        # Sanity-check the unit vs what the rule expects. We don't reject
        # mismatches — some provinces publish rebar by the tonne, others
        # by the kilo; the cost pipeline already handles both by shopping
        # for the price_vnd that matches the caller's unit. We just log.
        if rule.preferred_units and row.raw_unit.lower() not in rule.preferred_units:
            logger.info(
                "scraper.normalise: unit mismatch for %s — got %r, expected one of %r",
                rule.code,
                row.raw_unit,
                rule.preferred_units,
            )

        normalised.append(
            NormalisedPrice(
                material_code=rule.code,
                name=rule.canonical,
                category=rule.category,
                unit=row.raw_unit,
                price_vnd=row.price_vnd,
                province=row.province,
                effective_date=row.effective_date,
                source_url=row.source_url,
            )
        )

    if unmatched:
        logger.warning(
            "scraper.normalise: %d of %d rows did not match any rule",
            len(unmatched),
            len(rows),
        )

    return NormalisationResult(matched=normalised, unmatched=unmatched, rule_hits=hits)
