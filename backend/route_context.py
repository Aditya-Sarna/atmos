"""Route-to-code context mapping for GitHub exploration runs.

Given a cloned repo and extracted routes, locate the source files that mention
those routes and infer likely user intent (send, receive, auth, settings, etc.).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git", "node_modules", ".next", "dist", "build", "out", "coverage",
    ".venv", "venv", "__pycache__", ".cache", ".turbo",
}

SOURCE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".mjs"}


def _infer_action(route: str, nearby_text: str) -> str:
    hay = f"{route} {nearby_text}".lower()
    if any(k in hay for k in ("send", "pay", "transfer", "checkout")):
        return "submit_payment"
    if any(k in hay for k in ("receive", "request", "redeem")):
        return "receive_flow"
    if any(k in hay for k in ("login", "signin", "auth", "onboarding", "lock")):
        return "auth_flow"
    if any(k in hay for k in ("profile", "setting", "security", "backup")):
        return "settings_flow"
    if any(k in hay for k in ("scan", "camera", "qr")):
        return "scan_flow"
    return "generic"


def _extract_field_hints(nearby_text: str) -> list[str]:
    hints = []
    for key in ("email", "password", "phone", "amount", "name", "address", "code", "otp"):
        if re.search(rf"\b{key}\b", nearby_text, re.I):
            hints.append(key)
    return hints


def _iter_source_files(repo_root: Path):
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            p = Path(root) / fname
            if p.suffix.lower() in SOURCE_EXTS:
                yield p


def build_route_contexts(repo_root: Path, routes: list[str]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {
        r: {"files": [], "action": "generic", "field_hints": []}
        for r in routes
    }

    # Precompile route regexes for fast scanning.
    route_patterns: dict[str, re.Pattern[str]] = {}
    for route in routes:
        lit = re.escape(route)
        route_patterns[route] = re.compile(rf"['\"]{lit}['\"]|\bto\s*=\s*['\"]{lit}['\"]|\bpath\s*=\s*['\"]{lit}['\"]")

    for fpath in _iter_source_files(repo_root):
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = str(fpath.relative_to(repo_root))
        lines = text.splitlines()

        for route, pat in route_patterns.items():
            m = pat.search(text)
            if not m:
                continue

            # Locate approximate line, then build a local context window.
            line_no = text[: m.start()].count("\n")
            start = max(0, line_no - 8)
            end = min(len(lines), line_no + 9)
            nearby = "\n".join(lines[start:end])

            entry = contexts[route]
            if rel not in entry["files"]:
                entry["files"].append(rel)
            action = _infer_action(route, nearby)
            if entry["action"] == "generic" and action != "generic":
                entry["action"] = action

            fh = _extract_field_hints(nearby)
            for h in fh:
                if h not in entry["field_hints"]:
                    entry["field_hints"].append(h)

    return contexts
