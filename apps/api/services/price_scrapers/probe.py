"""URL-discovery probe for PENDING_URL provinces.

Most of the 63 provincial DOC sites follow one of a handful of URL
templates: subdomain ∈ {`sxd.`, `soxaydung.`} × path ∈ {`/thong-bao-gia*`,
`/cong-bo-gia*`}. This module generates candidate URLs from those
templates and probes each one looking for an actual bulletin link.

CLI usage (from a network that can reach `.gov.vn`):

    python -m services.price_scrapers.probe                # all PENDING
    python -m services.price_scrapers.probe ha-giang       # one slug
    python -m services.price_scrapers.probe --json out.json

Output (text mode) is one row per slug with its first responsive
candidate. If no candidate matches, the slug is reported with `MISS`
and the operator does the manual lookup. Either way the operator
edits `provinces.py` and replaces `PENDING_URL` with the verified URL.

The probe is intentionally *not* wired into the cron — it's a discovery
tool, not a recurring monitor. Repeated probing across 53 gov sites
would be rude (and give us nothing new once a URL is known).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


# ---------- Candidate URL generation ----------


# Subdomain prefixes commonly used by provincial Departments of Construction.
# Order matters: the first responsive candidate wins, so put the most
# common pattern first to minimise probe traffic.
_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "sxd",
    "soxaydung",
)

# Path suffixes — bulletins live under one of these on most provincial
# sites. Listed roughly by frequency observed in the 8 already-verified
# provinces.
_PATH_SUFFIXES: tuple[str, ...] = (
    "/thong-bao-gia-vat-lieu",
    "/thong-bao-gia",
    "/cong-bo-gia-vlxd",
    "/cong-bo-gia",
    "/bao-gia-vat-lieu",
)


def _slug_to_subdomain(slug: str) -> str:
    """`ba-ria-vung-tau` → `bariavungtau`. Hyphens are slugger-only."""
    return slug.replace("-", "")


def candidate_urls(slug: str) -> list[str]:
    """Return all candidate listing URLs to probe for `slug`, in priority order.

    With 2 prefixes × 5 paths = 10 candidates per slug. Even at 53
    pending provinces that's ≤ 530 HEADs total — well under "rude" — and
    most slugs will short-circuit on the first or second hit.
    """
    domain = _slug_to_subdomain(slug)
    return [f"https://{prefix}.{domain}.gov.vn{path}" for prefix in _SUBDOMAIN_PREFIXES for path in _PATH_SUFFIXES]


# ---------- Probe one candidate ----------


# A page that *contains* a bulletin link contains at least one href whose
# value matches this regex. Same regex used by `GenericProvinceScraper`'s
# default `bulletin_link_re` — keeping them in sync means a successful
# probe → URL → scraper hit chain is one-jump.
_BULLETIN_HREF_RE = re.compile(
    r'href="[^"]*(?:thong-bao-gia|bao-gia|cong-bo-gia)[^"]*"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProbeResult:
    slug: str
    url: str
    status: int | None
    """HTTP status code, or None for a transport-level failure (DNS, TLS, timeout)."""

    has_bulletin_link: bool
    """True iff the response body contains at least one bulletin-shaped href."""

    error: str | None
    """Stringified exception for transport failures, else None."""

    elapsed_ms: int
    """Wall-clock time spent on this probe."""

    @property
    def is_match(self) -> bool:
        """A 'match' = HTTP 200 *and* the body contains a bulletin link.

        A 200 with no bulletin link is a wrong-page hit (we landed on the
        DOC home page or a generic news index). A 404 or transport
        failure is a no-server-here hit.
        """
        return self.status == 200 and self.has_bulletin_link


async def probe_url(slug: str, url: str, *, http_client) -> ProbeResult:
    """Probe one candidate URL. Never raises; transport failures → status=None."""
    start = time.monotonic()
    try:
        resp = await http_client.get(url, timeout=10.0)
        body = resp.text or ""
        return ProbeResult(
            slug=slug,
            url=url,
            status=resp.status_code,
            has_bulletin_link=bool(_BULLETIN_HREF_RE.search(body)),
            error=None,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        return ProbeResult(
            slug=slug,
            url=url,
            status=None,
            has_bulletin_link=False,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )


async def probe_slug(slug: str, *, http_client) -> ProbeResult | None:
    """Try every candidate URL for `slug` until one matches.

    Returns the first matching ProbeResult, or `None` if every
    candidate failed. The caller decides what to do with `None` —
    typically log the slug for manual lookup.
    """
    for url in candidate_urls(slug):
        result = await probe_url(slug, url, http_client=http_client)
        if result.is_match:
            return result
    return None


# ---------- CLI ----------


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m services.price_scrapers.probe",
        description=("Probe PENDING_URL provincial Departments of Construction for their bulletin-listing URLs."),
    )
    parser.add_argument(
        "slugs",
        nargs="*",
        help="Specific slug(s) to probe (default: every PENDING_URL province).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Also write a JSON report to this path (one object per slug).",
    )
    args = parser.parse_args(argv)

    # Lazy imports — keeps `python -c "from .probe import candidate_urls"` cheap.
    import httpx

    from .generic_province import PENDING_URL
    from .provinces import ALL

    targets: list[str] = args.slugs if args.slugs else [c.slug for c in ALL if c.listing_url == PENDING_URL]
    print(f"# Probing {len(targets)} province(s)…", file=sys.stderr)

    results: list[dict] = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for slug in targets:
            match = await probe_slug(slug, http_client=client)
            if match is None:
                results.append({"slug": slug, "match": None})
                print(f"{slug:<22} MISS")
            else:
                results.append({"slug": slug, "match": asdict(match)})
                print(f"{slug:<22} HIT  {match.url}  ({match.elapsed_ms} ms)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"# wrote {args.json}", file=sys.stderr)

    misses = sum(1 for r in results if r["match"] is None)
    return 1 if misses == len(results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
