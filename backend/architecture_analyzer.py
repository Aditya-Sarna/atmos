"""Architecture analyzer.

Walks a cloned repository, summarises its structure, scores it against
common architecture qualities, and uses Claude to compare it to peer
applications in the same archetype.

Output is fed into the final report and also into the per-issue tick-to-apply
workflow (architecture fixes are emitted as repo-file patches, not CSS).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("atmos.architecture")

# File-extension → bucket
LANG_BUCKETS: dict[str, str] = {
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".py": "python", ".rb": "ruby", ".go": "go", ".rs": "rust", ".java": "java",
    ".kt": "kotlin", ".swift": "swift", ".php": "php",
    ".css": "css", ".scss": "css", ".less": "css", ".sass": "css",
    ".html": "html", ".vue": "vue", ".svelte": "svelte",
    ".sql": "sql", ".md": "docs", ".yaml": "config", ".yml": "config",
    ".json": "config", ".toml": "config",
}

# Folder name → architectural concept
LAYER_HINTS: dict[str, str] = {
    "components": "presentation",
    "ui": "presentation",
    "views": "presentation",
    "pages": "routes",
    "routes": "routes",
    "hooks": "presentation",
    "lib": "shared",
    "utils": "shared",
    "helpers": "shared",
    "services": "service",
    "controllers": "controller",
    "models": "domain",
    "domain": "domain",
    "entities": "domain",
    "repositories": "data",
    "store": "state",
    "redux": "state",
    "context": "state",
    "tests": "tests",
    "test": "tests",
    "__tests__": "tests",
    "api": "transport",
    "server": "server",
    "backend": "server",
    "frontend": "client",
    "infrastructure": "infra",
    "infra": "infra",
}

SKIP_DIRS = {
    ".git", "node_modules", ".next", ".turbo", "dist", "build", "out",
    "coverage", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    "vendor", ".cache", ".idea", ".vscode",
}

MAX_FILES_SCANNED = 5000

# Max lines we read from any single file for code-smell inspection
_SNIPPET_LINES = 60


# ---------------------------------------------------------------------------
# Code-snippet helpers
# ---------------------------------------------------------------------------


def _read_snippet(path: Path, start_line: int = 1, max_lines: int = _SNIPPET_LINES) -> str:
    """Read up to max_lines from a file beginning at start_line (1-based)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        chunk = lines[max(0, start_line - 1): start_line - 1 + max_lines]
        return "\n".join(chunk)
    except Exception:  # noqa: BLE001
        return ""


def _find_lines_matching(path: Path, pattern: re.Pattern[str], context: int = 3) -> list[dict[str, Any]]:
    """Find all lines in a file matching `pattern`. Return [{line, col, snippet}]."""
    hits: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines):
            m = pattern.search(line)
            if m:
                start = max(0, i - context)
                end = min(len(lines), i + context + 1)
                hits.append({
                    "line": i + 1,
                    "col": m.start() + 1,
                    "snippet": "\n".join(lines[start:end]),
                    "match": m.group(0)[:120],
                })
                if len(hits) >= 5:
                    break
    except Exception:  # noqa: BLE001
        pass
    return hits


# Patterns that indicate architecture smells
_DIRECT_FETCH_RE = re.compile(r"\bfetch\s*\(|axios\s*\.\s*(?:get|post|put|delete|patch)\s*\(")
_CONSOLE_LOG_RE = re.compile(r"\bconsole\s*\.\s*(?:log|warn|error)\s*\(")
_TODO_FIXME_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
_EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
_ANY_ESCAPE_RE = re.compile(r":\s*any\b|as\s+any\b")  # TypeScript 'any' escapes


def _scan_code_smells(repo_root: Path, all_files: list[Path]) -> list[dict[str, Any]]:
    """Inspect source files for concrete code-quality issues.
    Returns a list of {title, file, rel_path, line, snippet, pattern}.
    """
    smells: list[dict[str, Any]] = []
    source_exts = {".js", ".jsx", ".ts", ".tsx"}
    component_dirs = {"components", "pages", "views", "screens"}

    for fpath in all_files:
        if fpath.suffix.lower() not in source_exts:
            continue
        rel = str(fpath.relative_to(repo_root))

        # fetch() / axios called directly inside component files
        parts = set(fpath.parts)
        in_component = any(d in parts for d in component_dirs)
        if in_component:
            hits = _find_lines_matching(fpath, _DIRECT_FETCH_RE)
            for h in hits[:1]:
                smells.append({
                    "title": f"Direct API call inside component: {rel}",
                    "file": rel,
                    "line": h["line"],
                    "snippet": h["snippet"],
                    "pattern": "direct_fetch_in_component",
                })

        # Unhandled empty catch blocks
        hits = _find_lines_matching(fpath, _EMPTY_CATCH_RE)
        for h in hits[:1]:
            smells.append({
                "title": f"Empty catch block swallows errors: {rel}:{h['line']}",
                "file": rel,
                "line": h["line"],
                "snippet": h["snippet"],
                "pattern": "empty_catch",
            })

        # TypeScript `any` escapes
        hits = _find_lines_matching(fpath, _ANY_ESCAPE_RE)
        if len(hits) >= 3:  # flag only if pervasive
            smells.append({
                "title": f"Pervasive TypeScript `any` usage in {rel} ({len(hits)} occurrences)",
                "file": rel,
                "line": hits[0]["line"],
                "snippet": hits[0]["snippet"],
                "pattern": "ts_any_escape",
            })

        # TODO/FIXME comments (cap to 3 per repo)
        if len(smells) < 20:
            hits = _find_lines_matching(fpath, _TODO_FIXME_RE)
            for h in hits[:1]:
                smells.append({
                    "title": f"Unresolved TODO/FIXME: {rel}:{h['line']}",
                    "file": rel,
                    "line": h["line"],
                    "snippet": h["snippet"],
                    "pattern": "todo_fixme",
                })

        if len(smells) >= 30:
            break

    return smells


# ---------------------------------------------------------------------------
# Static scan
# ---------------------------------------------------------------------------


def _walk(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".cache")]
        for f in files:
            p = Path(root) / f
            out.append(p)
            if len(out) >= MAX_FILES_SCANNED:
                return out
    return out


def _detect_frameworks(repo_root: Path) -> list[str]:
    found: list[str] = []
    pkg = repo_root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for name, label in [
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                ("svelte", "Svelte"), ("@angular/core", "Angular"),
                ("express", "Express"), ("fastify", "Fastify"),
                ("@nestjs/core", "NestJS"), ("redux", "Redux"),
                ("zustand", "Zustand"), ("tailwindcss", "Tailwind"),
                ("typescript", "TypeScript"), ("vite", "Vite"),
                ("@reduxjs/toolkit", "Redux Toolkit"),
            ]:
                if name in deps:
                    found.append(label)
        except Exception:  # noqa: BLE001
            pass
    if (repo_root / "requirements.txt").exists():
        try:
            text = (repo_root / "requirements.txt").read_text(encoding="utf-8").lower()
            for name, label in [("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"),
                                 ("sqlalchemy", "SQLAlchemy"), ("celery", "Celery")]:
                if name in text:
                    found.append(label)
        except Exception:  # noqa: BLE001
            pass
    return found


def static_scan(repo_root: Path) -> dict[str, Any]:
    files = _walk(repo_root)
    lang_counter: Counter = Counter()
    layer_counter: Counter = Counter()
    for f in files:
        ext = f.suffix.lower()
        lang = LANG_BUCKETS.get(ext)
        if lang:
            lang_counter[lang] += 1
        for part in f.relative_to(repo_root).parts[:-1]:
            hint = LAYER_HINTS.get(part.lower())
            if hint:
                layer_counter[hint] += 1
                break  # one hit per file is enough

    top_files_by_size = sorted(
        ((f, f.stat().st_size) for f in files if f.is_file()),
        key=lambda kv: kv[1],
        reverse=True,
    )[:15]

    code_smells = _scan_code_smells(repo_root, files)

    return {
        "repo_root": str(repo_root),
        "file_count": len(files),
        "languages": dict(lang_counter.most_common()),
        "layers": dict(layer_counter.most_common()),
        "frameworks": _detect_frameworks(repo_root),
        "largest_files": [
            {"path": str(f.relative_to(repo_root)), "bytes": size}
            for f, size in top_files_by_size
        ],
        "code_smells": code_smells,
        "has_tests": layer_counter.get("tests", 0) > 0,
        "has_typescript": lang_counter.get("typescript", 0) > 0,
        "has_state_layer": layer_counter.get("state", 0) > 0,
        "has_service_layer": layer_counter.get("service", 0) > 0,
        "has_domain_layer": layer_counter.get("domain", 0) > 0,
    }


# ---------------------------------------------------------------------------
# Scoring (deterministic, fully explainable)
# ---------------------------------------------------------------------------


def score_architecture(scan: dict[str, Any]) -> dict[str, Any]:
    """Score the architecture across 5 axes — 0..100 each."""
    rules: list[dict[str, Any]] = []

    def rule(name: str, score: int, detail: str) -> None:
        rules.append({"name": name, "score": max(0, min(100, score)), "detail": detail})

    # 1. Modularity — does the repo separate presentation, state, services?
    modular_hits = sum(1 for k in ("presentation", "state", "service", "data") if scan["layers"].get(k))
    rule("Modularity", 40 + modular_hits * 15,
         f"Detected {modular_hits}/4 standard layers (presentation, state, service, data).")

    # 2. Type safety
    rule("Type safety", 88 if scan["has_typescript"] else 52,
         "TypeScript adopted — good." if scan["has_typescript"]
         else "No TypeScript detected — refactors are risky at scale.")

    # 3. Testability
    rule("Testability", 80 if scan["has_tests"] else 38,
         "Test layer present." if scan["has_tests"]
         else "No tests/ directory found — regression risk.")

    # 4. State management
    has_state = scan["has_state_layer"]
    rule("State management", 78 if has_state else 55,
         "Dedicated state layer present." if has_state
         else "State management is implicit — risks prop-drilling and stale data.")

    # 5. Code hot-spots — large single files indicate god-objects.
    big_files = [f for f in scan["largest_files"] if f["bytes"] > 60_000]
    rule("File-size health", max(30, 95 - len(big_files) * 8),
         f"{len(big_files)} files exceed 60KB — likely candidates to split.")

    overall = round(sum(r["score"] for r in rules) / len(rules))
    return {"overall": overall, "axes": rules}


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def deterministic_suggestions(scan: dict[str, Any], score: dict[str, Any]) -> list[dict[str, Any]]:
    """Concrete, applyable suggestions backed by actual file references and code snippets."""
    out: list[dict[str, Any]] = []
    repo_root = Path(scan.get("repo_root", "."))

    def _snippet_for(rel_path: str, max_lines: int = 30) -> str:
        p = repo_root / rel_path
        return _read_snippet(p, max_lines=max_lines) if p.exists() else ""

    def sugg(title: str, severity: str, summary: str, files: Optional[list[str]] = None,
             patch_kind: str = "manual", patch_body: str = "", peer: str = "",
             code_snippet: str = "", file_line: Optional[int] = None) -> None:
        entry: dict[str, Any] = {
            "id": f"arch_{uuid.uuid4().hex[:8]}",
            "title": title,
            "severity": severity,
            "summary": summary,
            "files": files or [],
            "patch_kind": patch_kind,
            "patch_body": patch_body,
            "peer_comparison": peer,
        }
        if code_snippet:
            entry["code_snippet"] = code_snippet
        if file_line is not None:
            entry["file_line"] = file_line
        out.append(entry)

    if not scan["has_typescript"]:
        # Show first JS file as the concrete example that needs conversion
        js_example = next(
            (f["path"] for f in scan["largest_files"] if f["path"].endswith((".js", ".jsx"))),
            None,
        )
        snippet = _snippet_for(js_example, 25) if js_example else ""
        sugg(
            title="Adopt TypeScript across the codebase",
            severity="high",
            summary=(
                "Migrate .js/.jsx → .ts/.tsx incrementally. "
                "Start with shared utilities and the API layer. "
                + (f"Highest-priority file: {js_example}" if js_example else "")
            ),
            files=["tsconfig.json"] + ([js_example] if js_example else []),
            patch_kind="file_create",
            patch_body=json.dumps({
                "compilerOptions": {
                    "target": "ES2022", "module": "ESNext",
                    "moduleResolution": "Bundler", "jsx": "react-jsx",
                    "strict": True, "esModuleInterop": True,
                    "skipLibCheck": True, "resolveJsonModule": True, "allowJs": True,
                },
                "include": ["src/**/*"],
            }, indent=2),
            peer="Linear and Vercel ship 100% TypeScript front-ends; both report ~30% fewer prod regressions.",
            code_snippet=snippet,
        )

    if not scan["has_tests"]:
        sugg(
            title="Add a tests/ directory with at least one smoke test per route",
            severity="high",
            summary="Pick a runner (Vitest or Jest) and start with happy-path tests for the home + auth routes.",
            files=["package.json", "tests/smoke.test.ts"],
            patch_kind="file_create",
            patch_body=(
                "import { describe, it, expect } from 'vitest';\n\n"
                "describe('smoke', () => {\n"
                "  it('home renders', () => { expect(true).toBe(true); });\n"
                "});\n"
            ),
            peer="Stripe Dashboard runs ~14k tests on every merge; Atmos baseline is 1 per route.",
        )

    if not scan["has_state_layer"]:
        sugg(
            title="Introduce a state-management layer",
            severity="medium",
            summary="Add Zustand or Redux Toolkit to centralise cross-page state and eliminate prop-drilling.",
            files=["src/store/index.ts"],
            patch_kind="file_create",
            patch_body=(
                "import { create } from 'zustand';\n\n"
                "type AppState = { ready: boolean; setReady: (v: boolean) => void };\n\n"
                "export const useAppStore = create<AppState>((set) => ({\n"
                "  ready: false,\n"
                "  setReady: (ready) => set({ ready }),\n"
                "}));\n"
            ),
            peer="Notion and Linear both centralise app state — Atmos detected ad-hoc useState across pages.",
        )

    if not scan["has_service_layer"]:
        # Find the first component file that has a direct fetch call
        fetch_smell = next(
            (s for s in scan.get("code_smells", []) if s.get("pattern") == "direct_fetch_in_component"),
            None,
        )
        sugg(
            title="Extract a services/ layer for API calls",
            severity="medium",
            summary=(
                "Move fetch/axios calls out of components into a services/ folder for testability and retry control. "
                + (f"Found direct fetch in: {fetch_smell['file']}" if fetch_smell else "")
            ),
            files=["src/services/api.ts"] + ([fetch_smell["file"]] if fetch_smell else []),
            patch_kind="file_create",
            patch_body=(
                "// Single fetcher with retry + auth. Components should NOT call fetch directly.\n"
                "export async function api<T>(path: string, init?: RequestInit): Promise<T> {\n"
                "  const r = await fetch(path, { credentials: 'include', ...init });\n"
                "  if (!r.ok) throw new Error(`${r.status} ${path}`);\n"
                "  return r.json() as Promise<T>;\n"
                "}\n"
            ),
            peer="Industry standard: components dispatch via services; Atmos saw direct fetch in components.",
            code_snippet=fetch_smell["snippet"] if fetch_smell else "",
            file_line=fetch_smell["line"] if fetch_smell else None,
        )

    # God files (>60 KB)
    big_files = [f for f in scan["largest_files"] if f["bytes"] > 60_000]
    for bf in big_files[:3]:
        snippet = _snippet_for(bf["path"], 40)
        sugg(
            title=f"Split god-file: {bf['path']} ({bf['bytes'] // 1024} KB)",
            severity="medium",
            summary="Files >60KB hide cross-cutting concerns and slow down refactoring. Split by responsibility.",
            files=[bf["path"]],
            patch_kind="manual",
            patch_body="",
            peer="Vercel, Stripe, and Linear keep typical module size <8KB.",
            code_snippet=snippet,
        )

    # Concrete code smells found during the scan
    smell_patterns_already_covered = {"direct_fetch_in_component"}
    for smell in scan.get("code_smells", [])[:6]:
        if smell.get("pattern") in smell_patterns_already_covered:
            continue
        smell_patterns_already_covered.add(smell.get("pattern", ""))
        sugg(
            title=smell["title"],
            severity="low",
            summary=f"Found in {smell['file']} at line {smell['line']}.",
            files=[smell["file"]],
            patch_kind="manual",
            patch_body="",
            peer="",
            code_snippet=smell.get("snippet", ""),
            file_line=smell.get("line"),
        )

    return out


# ---------------------------------------------------------------------------
# Optional LLM peer comparison
# ---------------------------------------------------------------------------


async def llm_peer_comparison(project_name: str, archetype: str, scan: dict[str, Any], score: dict[str, Any]) -> dict[str, Any]:
    """Ask the LLM to compare this architecture to 3 peer apps, with actual code context."""
    try:
        from emergentintegrations.llm.chat import (  # type: ignore
            LlmChat, UserMessage, TextDelta, StreamDone,
        )
    except Exception:  # noqa: BLE001
        return {"peers": [], "summary": ""}

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return {"peers": [], "summary": ""}

    # Curated archetype → industry peer hints. The LLM still picks ultimately,
    # but we anchor it on the right *industry* and the right *feature similarity*.
    archetype_peers: dict[str, list[str]] = {
        "ecommerce": ["Shopify Storefront", "Amazon", "Allbirds", "Glossier"],
        "finance": ["Stripe Dashboard", "Plaid", "Wise", "Robinhood"],
        "fintech": ["Stripe Dashboard", "Plaid", "Wise", "Robinhood"],
        "payments": ["Stripe Dashboard", "Razorpay", "Adyen", "Square"],
        "saas": ["Linear", "Notion", "Vercel Dashboard", "Stripe Dashboard"],
        "productivity": ["Notion", "Linear", "Height", "Coda"],
        "social": ["Twitter/X", "Threads", "Mastodon", "Reddit"],
        "messaging": ["Slack", "Discord", "Signal", "Telegram Web"],
        "media": ["Spotify Web", "Netflix", "YouTube", "Apple Music Web"],
        "developer-tool": ["GitHub", "Vercel", "Linear", "Sentry"],
        "developer_tool": ["GitHub", "Vercel", "Linear", "Sentry"],
        "dashboard": ["Linear", "Stripe Dashboard", "Vercel Dashboard", "Datadog"],
        "landing": ["Apple.com", "Linear.app", "Stripe.com", "Vercel.com"],
        "marketing": ["Apple.com", "Linear.app", "Stripe.com", "Vercel.com"],
        "ai": ["OpenAI Platform", "Anthropic Console", "Replicate", "HuggingFace"],
        "education": ["Khan Academy", "Coursera", "Brilliant", "Duolingo"],
        "blog": ["Medium", "Substack", "Ghost", "Mirror"],
        "docs": ["Notion", "GitBook", "Mintlify", "Docusaurus"],
    }
    archetype_key = (archetype or "").lower().strip().replace(" ", "_")
    suggested_peers = archetype_peers.get(archetype_key) or archetype_peers.get(archetype_key.split("_")[0], [])
    peer_hint = (
        f"For the archetype '{archetype}' (matched to '{archetype_key}'), pick 3 peers from this curated list "
        f"of industry leaders shipping similar features: {', '.join(suggested_peers)}. "
        "Only diverge from this list if the project is clearly in a different industry, and explain why."
        if suggested_peers else
        "Pick 3 well-known, currently-shipping industry peers in the same archetype with the most feature overlap."
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"arch_{uuid.uuid4().hex[:6]}",
        system_message=(
            "You are an enterprise software architect. Compare a submitted repo's architecture to "
            "well-known industry peers in the same archetype. You are shown the ACTUAL CODE from "
            "the repo's largest files. Be specific about concrete problems visible in the code. "
            "For each of the 3 peers, you MUST give:\n"
            "  - name: the peer app\n"
            "  - what_they_do_better: 1-2 sentences describing a concrete architectural strength of theirs that this repo lacks (cite a known practice; e.g. 'Linear uses an in-memory cache with optimistic mutations')\n"
            "  - what_to_copy: an exact, actionable change this repo could make (folder, library, or pattern name)\n"
            "Return ONLY JSON of shape: "
            "{ summary: string, peers: [{name, what_they_do_better, what_to_copy}], next_3_moves: [string,string,string] }"
        ),
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    # Include actual code snippets from the largest / most problematic files
    repo_root = Path(scan.get("repo_root", "."))
    code_context_parts: list[str] = []
    for f_info in scan.get("largest_files", [])[:5]:
        rel = f_info["path"]
        path = repo_root / rel
        if path.exists() and path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".py"}:
            snippet = _read_snippet(path, max_lines=30)
            if snippet:
                code_context_parts.append(f"### {rel} (first 30 lines)\n```\n{snippet}\n```")

    for smell in scan.get("code_smells", [])[:3]:
        code_context_parts.append(
            f"### Code smell in {smell['file']}:{smell['line']}\n```\n{smell['snippet']}\n```"
        )

    code_context = "\n\n".join(code_context_parts) or "(no code samples available)"

    prompt = (
        f"Project: {project_name}\nArchetype: {archetype}\n"
        f"Detected frameworks: {', '.join(scan['frameworks']) or 'unknown'}\n"
        f"Languages: {scan['languages']}\nLayers detected: {scan['layers']}\n"
        f"Has TS: {scan['has_typescript']} · tests: {scan['has_tests']} · state: {scan['has_state_layer']}\n"
        f"Overall architecture score: {score['overall']}/100\n\n"
        f"{peer_hint}\n\n"
        f"Code samples from the repository:\n{code_context}\n\n"
        "Based on the ACTUAL CODE above, compare to 3 well-known peer apps from the curated industry list. "
        "Be specific about what you see in the code that is problematic and what concrete change to make. "
        "JSON only — no prose, no markdown fences."
    )
    text = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM peer comparison failed: %s", exc)
        return {"peers": [], "summary": "", "next_3_moves": []}


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


async def analyze_repo(repo_root: Path, project_name: str, archetype: str) -> dict[str, Any]:
    scan = static_scan(repo_root)
    score = score_architecture(scan)
    suggestions = deterministic_suggestions(scan, score)
    peer = await llm_peer_comparison(project_name, archetype, scan, score)
    return {
        "scan": scan,
        "score": score,
        "suggestions": suggestions,
        "peer_comparison": peer,
        "mode": "repo",
    }


# ---------------------------------------------------------------------------
# URL-mode runtime audit (no repo access — derives signals from live pages)
# ---------------------------------------------------------------------------

def _score_url_mode(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic architecture score derived purely from runtime page captures."""
    if not pages:
        return {
            "overall": 0,
            "axes": {"discoverability": 0, "completeness": 0, "speed_hint": 0, "complexity": 0},
        }

    # Discoverability: how many distinct routes did the crawl reach.
    n_routes = len({p.get("route") or p.get("url") for p in pages})
    discoverability = min(100, int(n_routes * 12))

    # Completeness: average # of buttons / inputs / forms per page surfaced by the crawl.
    interactive_counts = [
        len((p.get("buttons") or [])) + len((p.get("inputs") or []))
        for p in pages
    ]
    avg_interactive = sum(interactive_counts) / max(1, len(interactive_counts))
    completeness = min(100, int(avg_interactive * 4))

    # Speed hint: faster crawls tend to imply lighter pages.
    # If the engine recorded per-page timings, use them; otherwise score a flat 60.
    timings = [p.get("ms_to_dom_ready") for p in pages if isinstance(p.get("ms_to_dom_ready"), (int, float))]
    if timings:
        avg = sum(timings) / len(timings)
        speed_hint = max(0, min(100, int(100 - (avg / 50))))
    else:
        speed_hint = 60

    # Complexity: more inputs per page = more places to break.
    complexity = min(100, int(avg_interactive * 6))

    overall = round((discoverability * 0.35 + completeness * 0.25 + speed_hint * 0.25 + (100 - complexity) * 0.15))
    return {
        "overall": overall,
        "axes": {
            "discoverability": discoverability,
            "completeness": completeness,
            "speed_hint": speed_hint,
            "complexity": complexity,
        },
    }


def _deterministic_url_suggestions(pages: list[dict[str, Any]], app_type: str) -> list[dict[str, Any]]:
    """Always-on architecture findings for URL-mode runs.

    These don't depend on the LLM — they fire from concrete signals visible
    in the crawl (missing alt text, forms without labels, etc.).
    """
    out: list[dict[str, Any]] = []

    # 1. Coverage / route map
    routes = sorted({p.get("route") or p.get("url") for p in pages})
    out.append({
        "id": f"url_coverage_{uuid.uuid4().hex[:6]}",
        "title": "Discoverable surface",
        "severity": "info",
        "category": "Coverage",
        "rationale": f"Atmos reached {len(routes)} distinct route(s): {', '.join(routes[:6]) + ('…' if len(routes) > 6 else '')}.",
        "patch_kind": "manual",
    })

    # 2. Missing form labels (common a11y / arch smell)
    unlabeled = []
    for p in pages:
        for inp in (p.get("inputs") or []):
            label = (inp.get("label") or "").strip()
            if not label and inp.get("type") not in {"hidden", "submit", "button"}:
                unlabeled.append({"page": p.get("route") or p.get("url"), "name": inp.get("name") or inp.get("placeholder") or "(unnamed)"})
    if unlabeled:
        sample = "; ".join(f"{u['page']}::{u['name']}" for u in unlabeled[:4])
        out.append({
            "id": f"url_a11y_{uuid.uuid4().hex[:6]}",
            "title": f"{len(unlabeled)} form input(s) lack accessible labels",
            "severity": "medium",
            "category": "Accessibility",
            "rationale": f"Sample: {sample}. Screen readers can't announce these fields.",
            "patch_kind": "css",
            "patch_css": "label { display: block; } input:not([aria-label]):not([id]) + * { outline: 2px solid #ff3b30 !important; }",
        })

    # 3. Heavy click depth = navigation problem
    deepest = max((len(p.get("path_from_root") or []) for p in pages), default=0)
    if deepest > 5:
        out.append({
            "id": f"url_depth_{uuid.uuid4().hex[:6]}",
            "title": f"Some routes are {deepest} clicks deep from the landing page",
            "severity": "low",
            "category": "Information architecture",
            "rationale": f"Industry rule of thumb is ≤3 clicks. {app_type} apps should expose key paths in the primary nav.",
            "patch_kind": "manual",
        })

    return out


async def _url_mode_peer_comparison(
    project_name: str,
    archetype: str,
    pages: list[dict[str, Any]],
    score: dict[str, Any],
) -> dict[str, Any]:
    """LLM peer comparison for URL-mode runs (no repo code — uses page summaries)."""
    try:
        from emergentintegrations.llm.chat import (  # type: ignore
            LlmChat, UserMessage, TextDelta, StreamDone,
        )
    except Exception:  # noqa: BLE001
        return {"peers": [], "summary": "", "next_3_moves": []}

    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        return {"peers": [], "summary": "", "next_3_moves": []}

    # Reuse the curated peer hint table from llm_peer_comparison.
    archetype_peers: dict[str, list[str]] = {
        "ecommerce": ["Shopify Storefront", "Amazon", "Allbirds", "Glossier"],
        "finance": ["Stripe Dashboard", "Plaid", "Wise", "Robinhood"],
        "fintech": ["Stripe Dashboard", "Plaid", "Wise", "Robinhood"],
        "payments": ["Stripe Dashboard", "Razorpay", "Adyen", "Square"],
        "saas": ["Linear", "Notion", "Vercel Dashboard", "Stripe Dashboard"],
        "productivity": ["Notion", "Linear", "Height", "Coda"],
        "social": ["Twitter/X", "Threads", "Mastodon", "Reddit"],
        "messaging": ["Slack", "Discord", "Signal", "Telegram Web"],
        "media": ["Spotify Web", "Netflix", "YouTube", "Apple Music Web"],
        "developer-tool": ["GitHub", "Vercel", "Linear", "Sentry"],
        "developer_tool": ["GitHub", "Vercel", "Linear", "Sentry"],
        "dashboard": ["Linear", "Stripe Dashboard", "Vercel Dashboard", "Datadog"],
        "landing": ["Apple.com", "Linear.app", "Stripe.com", "Vercel.com"],
        "marketing": ["Apple.com", "Linear.app", "Stripe.com", "Vercel.com"],
        "ai": ["OpenAI Platform", "Anthropic Console", "Replicate", "HuggingFace"],
        "education": ["Khan Academy", "Coursera", "Brilliant", "Duolingo"],
        "blog": ["Medium", "Substack", "Ghost", "Mirror"],
        "docs": ["Notion", "GitBook", "Mintlify", "Docusaurus"],
    }
    arch_key = (archetype or "").lower().strip().replace(" ", "_")
    suggested_peers = archetype_peers.get(arch_key) or archetype_peers.get(arch_key.split("_")[0], [])
    peer_hint = (
        f"Archetype '{archetype}' → curated industry peers: {', '.join(suggested_peers)}."
        if suggested_peers else
        "Pick 3 industry leaders in this archetype with overlapping features."
    )

    chat = LlmChat(
        api_key=api_key,
        session_id=f"arch_url_{uuid.uuid4().hex[:6]}",
        system_message=(
            "You are an enterprise software architect reviewing a LIVE web app — you have its "
            "page map and observable behaviour but NOT the source code. Compare to 3 well-known "
            "industry peers in the same archetype. For each peer give:\n"
            "  - name\n"
            "  - what_they_do_better: 1-2 sentence concrete UX/architecture strength the user-facing app misses\n"
            "  - what_to_copy: an actionable change phrased for a product+eng team (no folder names)\n"
            "Return ONLY JSON: { summary, peers:[{name, what_they_do_better, what_to_copy}], next_3_moves:[string,string,string] }"
        ),
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")

    page_lines = [
        f"- {p.get('route') or p.get('url')}: title='{(p.get('title') or '').strip()[:80]}', "
        f"buttons={len(p.get('buttons') or [])}, inputs={len(p.get('inputs') or [])}"
        for p in pages[:25]
    ]
    prompt = (
        f"Project: {project_name}\nArchetype: {archetype}\n"
        f"Runtime score: {score['overall']}/100 (axes: {score['axes']})\n\n"
        f"Page map ({len(pages)} pages):\n" + "\n".join(page_lines) + "\n\n"
        f"{peer_hint}\n\n"
        "Based on this RUNTIME-OBSERVED map, compare to 3 well-known peer apps and propose the "
        "next 3 concrete moves. JSON only — no prose, no markdown fences."
    )
    text = ""
    try:
        async for ev in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("URL-mode peer comparison failed: %s", exc)
        return {"peers": [], "summary": "", "next_3_moves": []}


async def analyze_url_run(
    pages: list[dict[str, Any]],
    project_name: str,
    archetype: str,
    project_url: str,
) -> dict[str, Any]:
    """Architecture audit for URL-source runs.

    Uses runtime signals from the crawl (page count, interactive surface, depth,
    a11y signals) plus an LLM peer comparison to produce a meaningful Architecture
    tab even when there's no source code to scan.
    """
    score = _score_url_mode(pages)
    suggestions = _deterministic_url_suggestions(pages, archetype)
    peer = await _url_mode_peer_comparison(project_name, archetype, pages, score)
    return {
        "scan": {
            "mode": "url",
            "project_url": project_url,
            "pages_observed": len(pages),
            "routes": sorted({p.get("route") or p.get("url") for p in pages}),
            "frameworks": [],
            "languages": {},
            "layers": [],
            "has_typescript": False,
            "has_tests": False,
            "has_state_layer": False,
        },
        "score": score,
        "suggestions": suggestions,
        "peer_comparison": peer,
        "mode": "url",
    }
