"""Atmos — Autonomous Product Testing & UX Intelligence Agent
FastAPI backend.

- Emergent Auth (Google) — session cookies, /api/auth/*
- LLM via user's IDE model quota (vscode.lm bridge) — no Atmos API key required
- Projects + Test Runs with simulated, observable real-time execution streamed
  via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).parent

import httpx
from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")

from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.cors import CORSMiddleware

def _ensure_playwright_browsers() -> None:
    """Auto-install chromium if the EXACT binary version expected by the current
    Playwright build is missing.

    Why we can't just check 'does any chromium_headless_shell-* dir exist':
    when the Playwright pip package is upgraded, it bumps its required browser
    revision (e.g. 1208 → 1223). The old dir lingers on disk, so a naive check
    passes — but BrowserType.launch then fails with 'Executable doesn't exist'.

    The reliable signal is the registry shipped with the installed Playwright
    package: it tells us the EXACT versioned folder name the runtime will look
    for. We probe for that, and only that.
    """
    import logging as _logging
    import subprocess
    _log = _logging.getLogger("atmos.playwright_bootstrap")

    browsers_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers"))

    expected_dirs: list[Path] = []
    try:
        from playwright._impl._driver import compute_driver_executable  # type: ignore  # noqa: F401
        # Newer playwright versions expose a registry that knows the exact dir names.
        from playwright._impl._browser_paths import compute_browsers_path  # type: ignore  # noqa: F401
    except Exception:
        pass
    try:
        # The simplest, version-proof check: launch playwright in --dry-run via the CLI.
        # It exits 0 if browsers are installed, non-zero otherwise.
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}
        # Use the venv playwright binary directly to avoid PATH ambiguity
        # between the supervisor child process and the user shell.
        import sys as _sys
        playwright_bin = str(Path(_sys.executable).parent / "playwright")
        if not Path(playwright_bin).exists():
            playwright_bin = "playwright"
        rc = subprocess.run(
            [playwright_bin, "install", "--dry-run", "chromium"],
            env=env, capture_output=True, text=True, timeout=20,
        )
        # The CLI prints "browser: chromium ... install location: …" lines.
        # If any listed chromium install location does NOT contain the expected
        # browser executable, we must run a real install. Skip FFmpeg lines —
        # they list an ffmpeg-* dir that never contains a chromium binary.
        needs_install = False
        found_any_binary = False
        for line in rc.stdout.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("install location:"):
                continue
            loc = Path(stripped.split(":", 1)[1].strip())
            if "ffmpeg" in loc.name.lower():
                continue
            expected_dirs.append(loc)
            # Linux: chrome-linux/headless_shell | macOS: chrome-headless-shell-mac-*/chrome-headless-shell
            # Windows: chrome-win/chrome.exe
            has_bin = (
                (loc / "chrome-linux" / "headless_shell").exists()
                or (loc / "chrome-linux" / "chrome").exists()
                or any(loc.glob("chrome-headless-shell-*/chrome-headless-shell"))
                or any(loc.glob("chrome-mac*/Chromium.app"))
                or any(loc.glob("chrome-win*/chrome.exe"))
            )
            if has_bin:
                found_any_binary = True
        if expected_dirs:
            needs_install = not found_any_binary
        else:
            # Old playwright versions — fall back to the simple glob check.
            candidate = list(browsers_dir.glob("chromium_headless_shell-*")) + list(browsers_dir.glob("chromium-*"))
            needs_install = not any(
                (d / "chrome-linux" / "headless_shell").exists()
                or any(d.glob("chrome-headless-shell-*/chrome-headless-shell"))
                for d in candidate
            )
        if not needs_install:
            return
    except Exception as exc:  # noqa: BLE001
        _log.warning("playwright dry-run check failed (%s); assuming install needed.", exc)

    _log.warning(
        "Playwright chromium binary missing under %s (expected %s); running `playwright install chromium`…",
        browsers_dir, expected_dirs or "(unknown version)",
    )
    try:
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}
        subprocess.run([playwright_bin, "install", "chromium"], check=True, env=env, timeout=600)
        _log.info("Playwright chromium installed.")
    except Exception as exc:  # noqa: BLE001
        _log.error("Could not auto-install Playwright chromium: %s", exc)


_ensure_playwright_browsers()


from atmos_engine import (
    SCREENSHOTS_DIR,
    VIDEOS_DIR,
    VIEWPORTS as REAL_VIEWPORTS,
    configure_playwright_browsers,
    crawl_and_capture,
    capture_routes_direct,
    apply_patch_full_page,
    llm_analyze_app,
    llm_analyze_page,
    deterministic_fallback,
    seed_test_cases,
)
from architecture_analyzer import analyze_repo, analyze_url_run
from fuzz_generator import run_fuzz_suite, _classify_field, fuzz_flow_screens
from github_runner import boot_repo, parse_github_url
from github_pr import PatchSpec, open_pull_request
from route_extractor import extract_routes_from_source
from route_context import build_route_contexts
from flow_explorer import explore_app_flow
from screen_testcases import generate_and_run_screen_tests
from load_simulator import LoadSimulator, LoadProfile, UserMode
from payment_sandbox import PaymentSandbox, TestPaymentGenerator, PaymentProvider
from ship_report import ShipReportGenerator
from persona_engine import run_persona_simulations, PERSONA_DEFINITIONS
from rbac import (
    ALL_PERMISSIONS,
    BUILTIN_ROLES,
    DEFAULT_ROLE_PERMISSIONS,
    ensure_org_for_user,
    get_member,
    get_role_permissions,
    get_user_permissions,
    project_query_for_user,
    require_permission,
)
from custom_test_runner import run_custom_test_cases, run_plan_cases_playwright, VALID_ACTIONS
from a11y_engine import run_accessibility_audit
from command_profiles import get_command_profile
from reference_engine import enrich_issues_with_references, ensure_reference_cache, get_references_for_query
from funnel_analyzer import analyze_conversion_funnel
from competitive_diff import run_competitive_diffs
from design_theory_engine import analyze_design_theory, CONTEXT_THEMES
from dopamine_engine import analyze_dopamine_engagement
from test_plan_editor import generate_test_plan, update_test_plan, enabled_cases_from_plan
from user_llm_proxy import get_user_llm_config
from codebase_context import store_ide_context, get_ide_context, build_context_summary
from copywriting_engine import analyze_copywriting, MARKETING_PROFILES
from demand_scraper import build_demand_report, REPORTS_DIR
from ops import validate_startup_env, SimpleRateLimitMiddleware, RequestIdMiddleware
from craft_score import (
    DEFAULT_GATE_THRESHOLD,
    attach_craft_to_summary,
    evaluate_gate,
    render_craft_markdown,
)
from tenant_guard import require_run_for_user, require_project_for_user

configure_playwright_browsers()

# ----------------------------------------------------------------------------
# Mongo
# ----------------------------------------------------------------------------

_startup_warnings = validate_startup_env()
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ----------------------------------------------------------------------------
# Logging / FastAPI
# ----------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("atmos")

# Hard stop for each fuzz sweep so one bad page cannot stall the whole run.
FUZZ_URL_TIMEOUT_SECS = int(os.environ.get("ATMOS_FUZZ_URL_TIMEOUT_SECS", "45"))
# Hard stop for flow exploration so auth-gated apps cannot stall the run.
EXPLORE_TIMEOUT_SECS = int(os.environ.get("ATMOS_EXPLORE_TIMEOUT_SECS", "420"))

app = FastAPI(title="Atmos")
api = APIRouter(prefix="/api")
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    SimpleRateLimitMiddleware,
    limit=int(os.environ.get("ATMOS_RATE_LIMIT", "180")),
    window=60.0,
)

# ----------------------------------------------------------------------------
# Real-time pub/sub for SSE (per-run)
# ----------------------------------------------------------------------------

run_channels: dict[str, list[asyncio.Queue]] = {}


def _subscribe(run_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    run_channels.setdefault(run_id, []).append(q)
    return q


def _unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    subs = run_channels.get(run_id, [])
    if q in subs:
        subs.remove(q)
    if not subs:
        run_channels.pop(run_id, None)


async def _publish(run_id: str, event: dict[str, Any]) -> None:
    for q in list(run_channels.get(run_id, [])):
        try:
            q.put_nowait(event)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------


class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Project(BaseModel):
    project_id: str
    user_id: str
    name: str
    url: str
    app_type: Optional[str] = None
    source: str = "url"             # "url" | "github"
    github_url: Optional[str] = None
    github_owner: Optional[str] = None
    github_repo: Optional[str] = None
    has_github_token: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TestRun(BaseModel):
    run_id: str
    project_id: str
    user_id: str
    command: str
    status: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    summary: Optional[dict[str, Any]] = None
