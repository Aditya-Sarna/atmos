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


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------

EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
AUTH_BYPASS_MODE = os.environ.get("ATMOS_DISABLE_AUTH", "auto").strip().lower()


def _auth_bypass_enabled(request: Request) -> bool:
    if AUTH_BYPASS_MODE in {"1", "true", "yes"}:
        return True
    if AUTH_BYPASS_MODE in {"0", "false", "no"}:
        return False
    host = (request.url.hostname or "").lower()
    # Default "auto": allow bypass only for local development hosts.
    return host in {"localhost", "127.0.0.1"}


async def _exchange_session_id(session_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(EMERGENT_SESSION_DATA_URL, headers={"X-Session-ID": session_id})
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session_id")
        return r.json()


async def current_user(request: Request) -> User:
    if _auth_bypass_enabled(request):
        user = User(
            user_id="user_local_dev",
            email="local-dev@atmos.local",
            name="Local Dev",
            picture=None,
        )
        await db.users.update_one(
            {"user_id": user.user_id},
            {"$set": {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "picture": user.picture,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return user

    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user_doc)


class SessionExchangeBody(BaseModel):
    session_id: str


class LocalAuthBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = None


def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def _set_session_cookie(request: Request, response: Response, session_token: str) -> None:
    cookie_secure_env = os.environ.get("ATMOS_COOKIE_SECURE", "auto").strip().lower()
    host = (request.url.hostname or "").lower()
    if cookie_secure_env in {"1", "true", "yes"}:
        cookie_secure = True
    elif cookie_secure_env in {"0", "false", "no"}:
        cookie_secure = False
    else:
        cookie_secure = host not in {"localhost", "127.0.0.1"}
    cookie_samesite = "none" if cookie_secure else "lax"
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/",
    )


async def _create_session_for_user(
    request: Request,
    response: Response,
    *,
    user_id: str,
    email: str,
    name: str,
    picture: Optional[str] = None,
    session_token: Optional[str] = None,
) -> dict[str, Any]:
    token = session_token or f"sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one(
        {
            "user_id": user_id,
            "session_token": token,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _set_session_cookie(request, response, token)
    return {"user_id": user_id, "email": email, "name": name, "picture": picture}


@api.post("/auth/register")
async def auth_register(body: LocalAuthBody, request: Request, response: Response):
    email = str(body.email).strip().lower()
    if await db.users.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    name = (body.name or email.split("@")[0]).strip() or "Atmos user"
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    await db.users.insert_one(
        {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": None,
            "password_hash": _hash_password(body.password),
            "auth_provider": "local",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    await ensure_org_for_user(db, user_id, email, name)
    return await _create_session_for_user(
        request, response, user_id=user_id, email=email, name=name,
    )


@api.post("/auth/login")
async def auth_login(body: LocalAuthBody, request: Request, response: Response):
    email = str(body.email).strip().lower()
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    if not user_doc or not user_doc.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not _verify_password(body.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return await _create_session_for_user(
        request,
        response,
        user_id=user_doc["user_id"],
        email=user_doc["email"],
        name=user_doc.get("name") or email.split("@")[0],
        picture=user_doc.get("picture"),
    )


@api.post("/auth/session")
async def auth_session(body: SessionExchangeBody, request: Request, response: Response):
    data = await _exchange_session_id(body.session_id)
    email = data["email"]
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture")
    session_token = data["session_token"]

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one(
            {
                "user_id": user_id,
                "email": email,
                "name": name,
                "picture": picture,
                "auth_provider": "emergent",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return await _create_session_for_user(
        request,
        response,
        user_id=user_id,
        email=email,
        name=name,
        picture=picture,
        session_token=session_token,
    )


@api.get("/auth/me")
async def auth_me(user: User = Depends(current_user)):
    org = await ensure_org_for_user(db, user.user_id, user.email, user.name)
    member = await get_member(db, user.user_id)
    org_id, perms = await get_user_permissions(db, user.user_id)
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "org_id": org_id,
        "org_name": org.get("name") if org else None,
        "role": member.get("role") if member else None,
        "permissions": sorted(perms),
    }


@api.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ----------------------------------------------------------------------------
# Project + Run endpoints
# ----------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    name: str
    url: Optional[str] = None
    github_url: Optional[str] = None
    github_token: Optional[str] = None  # PAT, only used to (a) clone private repos and (b) open PRs


class ProjectGithubTokenUpdate(BaseModel):
    github_token: str


def _classify_app_type(url: str, name: str) -> str:
    text = f"{url} {name}".lower()
    if any(k in text for k in ["stripe", "pay", "bank", "wallet", "finance", "invoice", "transaction"]):
        return "finance"
    if any(k in text for k in ["shop", "store", "checkout", "cart", "commerce", "amazon", "etsy"]):
        return "e-commerce"
    if any(k in text for k in ["calendar", "schedule", "event", "meeting", "booking"]):
        return "calendar"
    if any(k in text for k in ["dashboard", "analytics", "metric", "admin", "report"]):
        return "dashboard"
    return "generic"


@api.post("/projects")
async def create_project(body: ProjectCreate, user: User = Depends(current_user)):
    gh_meta = parse_github_url(body.github_url) if body.github_url else None
    if not body.url and not gh_meta:
        raise HTTPException(status_code=400, detail="Provide a URL or a GitHub repository URL.")

    if gh_meta:
        clean_url = f"https://github.com/{gh_meta['owner']}/{gh_meta['repo']}"
        source = "github"
        display_url = clean_url
    else:
        parsed = urlparse(body.url if "://" in body.url else f"https://{body.url}")
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid URL")
        display_url = clean_url
        source = "url"

    await ensure_org_for_user(db, user.user_id, user.email, user.name)
    await require_permission(db, user.user_id, "projects:write")
    member = await get_member(db, user.user_id)
    org_id = member["org_id"] if member else None

    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    proj = Project(
        project_id=project_id,
        user_id=user.user_id,
        name=(body.name or "").strip() or (gh_meta["repo"] if gh_meta else urlparse(display_url).netloc),
        url=display_url,
        app_type=_classify_app_type(display_url, body.name),
        source=source,
        github_url=clean_url if source == "github" else None,
        github_owner=gh_meta["owner"] if gh_meta else None,
        github_repo=gh_meta["repo"] if gh_meta else None,
        has_github_token=bool(body.github_token),
    )
    doc = proj.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    doc["org_id"] = org_id
    # Persist the PAT separately so it never leaks via /api/projects.
    if body.github_token:
        await db.project_secrets.update_one(
            {"project_id": project_id},
            {"$set": {"project_id": project_id, "github_token": body.github_token}},
            upsert=True,
        )
    await db.projects.insert_one(doc)
    return proj.model_dump()


@api.post("/projects/{project_id}/github-token")
async def update_project_github_token(project_id: str, body: ProjectGithubTokenUpdate, user: User = Depends(current_user)):
    project = await db.projects.find_one({"project_id": project_id, "user_id": user.user_id}, {"_id": 0, "source": 1})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("source") != "github":
        raise HTTPException(status_code=400, detail="Only GitHub projects can store a GitHub token.")

    token = (body.github_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is required.")

    await db.project_secrets.update_one(
        {"project_id": project_id},
        {"$set": {"project_id": project_id, "github_token": token}},
        upsert=True,
    )
    await db.projects.update_one(
        {"project_id": project_id},
        {"$set": {"has_github_token": True}},
    )
    return {"ok": True, "has_github_token": True}


@api.post("/projects/{project_id}/github-token/test")
async def test_project_github_token(project_id: str, user: User = Depends(current_user)):
    """Validate that the stored GitHub PAT can actually open a PR.

    Checks:
      1. Token exists.
      2. Token authenticates to api.github.com (returns viewer login).
      3. Token has access to the linked repo.
      4. Token has the scopes required to create branches and PRs (repo or public_repo).
    """
    project = await db.projects.find_one({"project_id": project_id, "user_id": user.user_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("source") != "github":
        raise HTTPException(status_code=400, detail="Only GitHub projects can be tested.")

    secret = await db.project_secrets.find_one({"project_id": project_id}, {"_id": 0})
    token = (secret or {}).get("github_token")
    if not token:
        return {"ok": False, "stage": "missing", "detail": "No GitHub token stored for this project. Paste a Personal Access Token (with `repo` scope) on the New Run page."}

    repo_full = f"{project['github_owner']}/{project['github_repo']}"

