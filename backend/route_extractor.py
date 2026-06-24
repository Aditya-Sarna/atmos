"""Route extractor for GitHub repos.

Reads the cloned source tree and derives the full set of navigable URL paths
without running the dev server.  Handles:
  - React Router v5/v6  (<Route path>, path:, createBrowserRouter)
  - Next.js pages/ directory
  - Next.js app/ directory (App Router)
  - NavLink / Link to=
  - useNavigate("...") / navigate("...")
  - Bottom-nav / sidebar data-arrays with `to:` or `href:` keys

Returns a sorted list of path strings like ["/", "/home", "/send", ...] that
Playwright can navigate to directly on the booted dev server.
"""
from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("atmos.routes")

SKIP_DIRS = {
    ".git", "node_modules", ".next", "dist", "build", "out", "coverage",
    ".venv", "venv", "__pycache__", ".cache", ".turbo",
}

# Regex patterns that may contain route paths
_PATTERNS: list[re.Pattern[str]] = [
    # React Router v6: <Route path="/foo">
    re.compile(r"""<Route[^>]+path\s*=\s*['"]([^'"]+)['"]"""),
    # React Router createBrowserRouter / createHashRouter entries: { path: "/foo"
    re.compile(r"""[{\[,]\s*path\s*:\s*['"]([^'"]+)['"]"""),
    # NavLink / Link to="/foo"
    re.compile(r"""(?:NavLink|Link)\b[^>]*\bto\s*=\s*['"]([^'"]+)['"]"""),
    # to="/foo" anywhere in JSX (also catches nav arrays)
    re.compile(r"""\bto\s*=\s*['"](/[^'"]*?)['"]"""),
    # useNavigate / navigate("/foo")
    re.compile(r"""navigate\s*\(\s*['"]([^'"]+)['"]"""),
    # nav(-1) / nav("/home")  (named navigate alias is often `nav`)
    re.compile(r"""\bnav\s*\(\s*['"]([^'"]+)['"]"""),
    # href="/foo"
    re.compile(r"""\bhref\s*=\s*['"](/[^'"#?]*?)['"]"""),
    # to: "/foo" in plain JS object (nav arrays, sidebar configs)
    re.compile(r"""\bto\s*:\s*['"](/[^'"]+?)['"]"""),
    # path: "/foo" in plain JS object
    re.compile(r"""\bpath\s*:\s*['"](/[^'"]+?)['"]"""),
    # Switch to "/foo"  (older navigation patterns)
    re.compile(r"""['"](/[a-z][a-z0-9/_-]{1,60})['"]"""),
]

_SKIP_ROUTE_RE = re.compile(
    r"""^(https?://|//|mailto:|tel:|#|javascript:|data:)"""
    r"""|[:*\[\]]"""          # dynamic segments
    r"""|\.(css|js|ts|json|png|svg|ico|woff|ttf|map)$""",
    re.I,
)

def _candidate(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    if _SKIP_ROUTE_RE.search(raw):
        return None
    if len(raw) > 120:
        return None
    raw = raw.split("?")[0].split("#")[0]
    if not raw.startswith("/"):
        return None
    return raw or None


def _routes_from_source_files(repo_root: Path) -> set[str]:
    routes: set[str] = set()
    source_exts = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".mjs"}

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if Path(fname).suffix.lower() not in source_exts:
                continue
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pat in _PATTERNS:
                for m in pat.finditer(text):
                    r = _candidate(m.group(1))
                    if r:
                        routes.add(r)
    return routes


def _routes_from_pages_dir(repo_root: Path) -> set[str]:
    """Next.js pages/ and app/ directory conventions."""
    routes: set[str] = set()
    page_suffix_re = re.compile(r"\.(js|jsx|ts|tsx)$", re.I)
    dynamic_re = re.compile(r"\[")

    for pages_dir_name in ("pages", "src/pages", "app", "src/app"):
        pages_dir = repo_root / pages_dir_name
        if not pages_dir.is_dir():
            continue
        for fpath in pages_dir.rglob("*"):
            if not fpath.is_file():
                continue
            if not page_suffix_re.search(fpath.name):
                continue
            rel = fpath.relative_to(pages_dir)
            parts = list(rel.parts)
            if not parts:
                continue
            # Skip _app, _document, _error, [...slug], etc.
            if any(p.startswith("_") or dynamic_re.search(p) for p in parts):
                continue
            # Strip extension from last part
            stem = page_suffix_re.sub("", parts[-1])
            parts[-1] = stem
            route = "/" + "/".join(parts)
            if route.endswith("/index"):
                route = route[: -len("/index")] or "/"
            if r := _candidate(route):
                routes.add(r)
    return routes


def extract_routes_from_source(repo_root: Path) -> list[str]:
    """Return a sorted, deduplicated list of navigable paths for this repo."""
    routes: set[str] = {"/"}
    routes |= _routes_from_source_files(repo_root)
    routes |= _routes_from_pages_dir(repo_root)

    # De-duplicate paths that differ only in trailing slash
    normalised: set[str] = set()
    for r in routes:
        normalised.add(r.rstrip("/") or "/")

    filtered = sorted(
        r for r in normalised
        if _candidate(r) or r == "/"
    )

    logger.info("Route extractor: found %d unique routes in %s", len(filtered), repo_root.name)
    for r in filtered[:50]:
        logger.debug("  route: %s", r)

    return filtered
