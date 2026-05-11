"""Frontend bundle composition tracker.

Sister of `apps/web/scripts/check-bundle-size.mjs` — that script
pins TOTAL bundle BYTES. THIS audit pins WHICH PACKAGES are in
the bundle.

The bug class
-------------
Bundle bytes can stay flat while the *composition* drifts. The
canonical regression:

  * Someone refactors a util and accidentally pulls
    `aws-sdk` (server-only, 800kB) into a client component.
    Tree-shaking removes most of it, so the byte counter only
    moves 30kB — within the 10% noise floor of the byte audit.
    But now the SDK is reachable from a client route and the
    *next* import inside it pulls another 200kB, undetected.

  * Same shape for `bcrypt`, `pg`, `nodemailer`, `puppeteer` —
    server deps that should never appear in a client component.

The fix is to pin the *set* of packages reachable from the web
app's source. Adding a new package requires a baseline bump,
which forces a "yes, this is intentional" review.

What this audit checks
----------------------
Walks every `.ts` / `.tsx` / `.js` / `.jsx` / `.mjs` file under
`apps/web/{app,components,hooks,lib}`, excluding test files
(`__tests__/`, `*.test.*`, `*.spec.*`). Extracts every
third-party `import` / dynamic-import target, normalises to its
package name (`@scope/pkg/sub` → `@scope/pkg`), and compares
the resulting set against the pinned baseline.

Two ratchet directions:
  * New package not in baseline → fail (pulls in unreviewed dep).
  * Package in baseline no longer imported → fail (refresh the
    baseline so it reflects reality).

Server-side restrictions
------------------------
`SERVER_ONLY_PACKAGES` is a hardcoded denylist of packages that
should never appear in `apps/web/` source — Node-only modules
(`node:fs`, `node:crypto`), server SDKs, etc. If a package on
the denylist appears in a client-reachable import path, the
audit fails immediately (independent of the baseline ratchet).

What it doesn't check
---------------------
* Transitive deps. If `@aec/ui` (a workspace package) imports
  `clsx`, the audit doesn't flag `clsx` because `apps/web`
  source doesn't directly import it. The web app's *direct*
  surface is the lever the team controls.
* Dev-only packages used in build scripts (`apps/web/scripts/`).

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WEB_ROOT = _REPO_ROOT / "apps" / "web"
_SRC_DIRS = ["app", "components", "hooks", "lib"]


# Today's baseline. Set from a clean scan. Add a new package via
# `--update`-style refresh: re-run, copy the failure list into
# the set below, and submit the diff for review.
BASELINE_BUNDLE_PACKAGES: frozenset[str] = frozenset(
    {
        "@aec/sdk",  # Marketing-docs API surface page imports the typed SDK.
        "@aec/types",
        "@aec/ui",
        "@supabase/ssr",
        "@supabase/supabase-js",
        "@tanstack/react-query",
        "lucide-react",
        "next",
        "next-intl",
        "react",
    }
)


# Packages that must never appear in client-reachable code.
# Hard-fail independent of baseline ratchet — a new entry here
# is a security/perf bug, not just a "we grew a dep" event.
SERVER_ONLY_PACKAGES: frozenset[str] = frozenset(
    {
        # Node built-ins (the `node:` prefix is unambiguously server).
        "node:fs",
        "node:path",
        "node:crypto",
        "node:os",
        "node:child_process",
        "node:net",
        "node:dgram",
        "node:tls",
        "node:cluster",
        "node:worker_threads",
        "node:dns",
        "node:http",
        "node:https",
        # Common server-only npm packages that have shipped to
        # client bundles by mistake elsewhere. Keep the list short
        # — only entries with a clear "should never run in browser"
        # signal.
        "fs",
        "path",
        "crypto",
        "child_process",
        "pg",
        "bcrypt",
        "bcryptjs",
        "nodemailer",
        "aws-sdk",
        "@aws-sdk/client-s3",
        "puppeteer",
        "playwright",
        "@playwright/test",
        "vitest",
        "@testing-library/react",
        "@testing-library/jest-dom",
    }
)


# Per-(file_relpath, package) allowlist. Each entry needs a
# stated reason. Use sparingly — most server-only imports should
# be moved to a server-only file (route handler, server action)
# rather than allowlisted.
SERVER_ONLY_ALLOWLIST: dict[tuple[str, str], str] = {
    # No entries today.
}


# Regexes for `import` extraction. Three shapes covered:
#   import x from "pkg";
#   import "pkg";
#   } from "pkg";   (multi-line continuation)
#   await import("pkg")
#
# The IMPORT_LINE_RE intentionally matches `export … from` too so
# re-export indices count.
_IMPORT_LINE_RE = re.compile(r"""^\s*(?:import|export)\s.*\sfrom\s+['"]([^'"]+)['"]""")
_SIDE_EFFECT_IMPORT_RE = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""")
_CONTINUATION_FROM_RE = re.compile(r"""^\s*}\s*from\s+['"]([^'"]+)['"]""")
_DYNAMIC_IMPORT_RE = re.compile(r"""(?:^|[^a-zA-Z_$])import\s*\(\s*['"]([^'"]+)['"]""")


def _is_third_party(spec: str) -> bool:
    """Filter out relative imports and Next.js path aliases."""
    if spec.startswith(".") or spec.startswith("/"):
        return False
    if spec.startswith("@/"):  # next.js `@/` alias to `apps/web` root
        return False
    return True


def _package_name(spec: str) -> str:
    """`@scope/pkg/sub` → `@scope/pkg`. `pkg/sub` → `pkg`.
    `node:fs` → `node:fs` (preserve so denylist can match)."""
    if spec.startswith("node:"):
        return spec
    if spec.startswith("@"):
        parts = spec.split("/")
        return "/".join(parts[:2])
    return spec.split("/", 1)[0]


def _is_test_file(path: Path) -> bool:
    """Test files don't ship to client. Exclude them."""
    if "__tests__" in path.parts:
        return True
    name = path.name
    return name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))


def _scan_file(path: Path) -> set[tuple[str, str]]:
    """Return {(rel_path_str, package_name), ...} for every
    third-party import in the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    if not _WEB_ROOT.exists():
        return set()
    rel = str(path.relative_to(_WEB_ROOT))
    out: set[tuple[str, str]] = set()
    for line in text.splitlines():
        for r in (_IMPORT_LINE_RE, _SIDE_EFFECT_IMPORT_RE, _CONTINUATION_FROM_RE):
            m = r.search(line)
            if m and _is_third_party(m.group(1)):
                out.add((rel, _package_name(m.group(1))))
        for m in _DYNAMIC_IMPORT_RE.finditer(line):
            if _is_third_party(m.group(1)):
                out.add((rel, _package_name(m.group(1))))
    return out


def _walk_source_files() -> list[Path]:
    """All non-test source files under tracked dirs."""
    out: list[Path] = []
    if not _WEB_ROOT.exists():
        return out
    for d in _SRC_DIRS:
        root = _WEB_ROOT / d
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
                continue
            if _is_test_file(p):
                continue
            out.append(p)
    return sorted(out)


def _collect_imports() -> set[tuple[str, str]]:
    """Return {(file, package), ...} across the whole source tree."""
    out: set[tuple[str, str]] = set()
    for p in _walk_source_files():
        out.update(_scan_file(p))
    return out


def test_no_unreviewed_packages_enter_the_bundle():
    """Every third-party package imported from `apps/web/source`
    must be in `BASELINE_BUNDLE_PACKAGES`.

    The bug shape: someone refactors a util, accidentally pulls
    in a heavy library (`aws-sdk`, `moment`, …), tree-shaking
    masks most of the byte cost, and the regression slips past
    the byte-size guard.

    Same ratchet pattern. Failure surfaces both directions.
    """
    if not _WEB_ROOT.exists():
        pytest.skip("apps/web not present in this repo state")

    seen_pkgs = {pkg for _, pkg in _collect_imports()}

    # Direction 1: new packages not in baseline.
    new_pkgs = sorted(seen_pkgs - BASELINE_BUNDLE_PACKAGES)
    if new_pkgs:
        # For each new package, also report which file introduced it
        # so the operator doesn't have to grep.
        introductions: dict[str, list[str]] = {}
        for file_rel, pkg in _collect_imports():
            if pkg in new_pkgs:
                introductions.setdefault(pkg, []).append(file_rel)
        detail = "\n  ".join(
            f"{pkg}\n      first seen in: {sorted(introductions[pkg])[0]}"
            + (f" (+ {len(introductions[pkg]) - 1} more)" if len(introductions[pkg]) > 1 else "")
            for pkg in new_pkgs
        )
        pytest.fail(
            f"{len(new_pkgs)} new package(s) entered the web bundle:\n  "
            + detail
            + "\n\nIf this is intentional (a deliberate dependency add):\n"
            "  • Confirm it's needed on the client (not a server util\n"
            "    that should live in a route handler / server action).\n"
            "  • Confirm tree-shaking will trim unused exports — many\n"
            "    libs ship CommonJS that defeats Webpack's tree-shaker.\n"
            "  • Add the package name to BASELINE_BUNDLE_PACKAGES.\n\n"
            "If unintentional: remove the import or move the call site\n"
            "to a server-only file. Server work doesn't belong in the\n"
            "client bundle."
        )

    # Direction 2: baseline packages no longer imported. Refresh
    # so the audit reflects reality.
    stale_pkgs = sorted(BASELINE_BUNDLE_PACKAGES - seen_pkgs)
    if stale_pkgs:
        pytest.fail(
            f"{len(stale_pkgs)} package(s) in BASELINE_BUNDLE_PACKAGES "
            "are no longer imported anywhere:\n  "
            + "\n  ".join(stale_pkgs)
            + "\n\n🎉 Remove them from BASELINE_BUNDLE_PACKAGES so the "
            "set reflects what the bundle actually pulls in."
        )


def test_no_server_only_imports_in_client_source():
    """Server-only modules (`node:fs`, `pg`, `bcrypt`, …) must
    never appear in `apps/web/` client-reachable source. A
    client-reachable file accidentally importing one of these
    either:

      * Pulls a 200kB+ shim into the browser bundle (perf bug).
      * Crashes at runtime because the API isn't available
        (browser doesn't have `fs`).
      * Exposes a server SDK to a route an attacker can reach
        (security bug — credentials, internal endpoints).

    Hard-fail. Allowlist only with a stated reason — usually
    the right fix is to move the call to a server action /
    route handler instead.
    """
    if not _WEB_ROOT.exists():
        pytest.skip("apps/web not present in this repo state")

    findings: list[str] = []
    for file_rel, pkg in sorted(_collect_imports()):
        if pkg not in SERVER_ONLY_PACKAGES:
            continue
        if (file_rel, pkg) in SERVER_ONLY_ALLOWLIST:
            continue
        findings.append(f"{file_rel}: imports `{pkg}`")

    if findings:
        pytest.fail(
            f"{len(findings)} server-only import(s) reached client source:"
            "\n  " + "\n  ".join(findings) + "\n\nFixes (in order of preference):\n"
            "  1. Move the call site to a server-only file:\n"
            "     • `app/api/<route>/route.ts` (App-Router route handler)\n"
            "     • `'use server'` action\n"
            "     • `lib/server-only/<helper>.ts` imported only by\n"
            "       server components / route handlers.\n"
            "  2. If genuinely needed (e.g. a polyfill that's safe in\n"
            "     both runtimes), add the (file, pkg) tuple to\n"
            "     SERVER_ONLY_ALLOWLIST with a stated reason."
        )


def test_allowlist_entries_correspond_to_real_files():
    """Defensive: stale allowlist entries silently mask future
    regressions. Every (file, pkg) tuple must point at a real
    file, and every package on the allowlist must still be
    server-only-listed.
    """
    if not _WEB_ROOT.exists():
        pytest.skip("apps/web not present in this repo state")

    real_files = {str(p.relative_to(_WEB_ROOT)) for p in _walk_source_files()}
    stale_files = [k for k in SERVER_ONLY_ALLOWLIST if k[0] not in real_files]
    assert not stale_files, (
        f"Stale SERVER_ONLY_ALLOWLIST entries (file no longer exists): "
        f"{stale_files}. Remove them so the allowlist reflects only "
        "currently-live exemptions."
    )

    stale_pkgs = [k for k in SERVER_ONLY_ALLOWLIST if k[1] not in SERVER_ONLY_PACKAGES]
    assert not stale_pkgs, (
        f"Stale SERVER_ONLY_ALLOWLIST entries (pkg no longer denylisted): "
        f"{stale_pkgs}. Either re-add to SERVER_ONLY_PACKAGES or remove "
        "the allowlist entry — an entry whose package isn't denylisted "
        "is dead code."
    )


def test_audit_recognises_documented_import_shapes():
    """Defensive: positive + negative regex fixtures. A regression
    in `_IMPORT_LINE_RE` etc. would silently let new packages into
    the bundle.
    """
    # Standard import.
    assert _IMPORT_LINE_RE.search('import { foo } from "react"').group(1) == "react"
    # Default + named.
    assert _IMPORT_LINE_RE.search('import x, { y } from "next/link"').group(1) == "next/link"
    # Re-export.
    assert _IMPORT_LINE_RE.search('export { x } from "lodash"').group(1) == "lodash"
    # Side-effect.
    assert _SIDE_EFFECT_IMPORT_RE.search('import "polyfill"').group(1) == "polyfill"
    # Multi-line continuation.
    assert _CONTINUATION_FROM_RE.search('} from "@scope/pkg";').group(1) == "@scope/pkg"
    # Dynamic.
    assert _DYNAMIC_IMPORT_RE.search('await import("dyn-pkg")').group(1) == "dyn-pkg"

    # Package-name normalisation.
    assert _package_name("@scope/pkg/sub/path") == "@scope/pkg"
    assert _package_name("react/jsx-runtime") == "react"
    assert _package_name("node:fs") == "node:fs"

    # Third-party filtering.
    assert _is_third_party("react")
    assert _is_third_party("@scope/pkg")
    assert not _is_third_party("./local")
    assert not _is_third_party("../sibling")
    assert not _is_third_party("@/components/X")  # next.js alias

    # Negative: a comment or string that mentions `from` should not match.
    assert _IMPORT_LINE_RE.search("// imported from elsewhere") is None
    assert _IMPORT_LINE_RE.search('const s = "where from?";') is None
