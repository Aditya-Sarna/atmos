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

    def _probe() -> dict:
        try:
            from github import Github, GithubException  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "stage": "import", "detail": f"PyGithub missing: {exc}"}

        try:
            gh = Github(token, per_page=1, timeout=15)
            viewer = gh.get_user()
            login = viewer.login  # forces a request
        except GithubException as exc:
            status = getattr(exc, "status", 0)
            if status == 401:
                return {"ok": False, "stage": "auth", "detail": "GitHub returned 401 — the token is invalid, revoked or expired."}
            return {"ok": False, "stage": "auth", "detail": f"GitHub returned {status}: {exc.data}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "stage": "auth", "detail": f"Could not reach GitHub: {exc}"}

        # Probe repo access.
        try:
            repo = gh.get_repo(repo_full)
            default_branch = repo.default_branch
            try:
                permissions = getattr(repo, "permissions", None)
                can_push = bool(permissions and getattr(permissions, "push", False))
            except Exception:  # noqa: BLE001
                can_push = False
        except GithubException as exc:
            status = getattr(exc, "status", 0)
            if status == 404:
                return {"ok": False, "stage": "repo", "detail": f"This token cannot see {repo_full}. Make sure the PAT has `repo` scope and access to that repository (for org repos, the org must have approved the token)."}
            return {"ok": False, "stage": "repo", "detail": f"GitHub returned {status}: {exc.data}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "stage": "repo", "detail": str(exc)}

        # Scopes (classic PATs only — fine-grained tokens won't expose this header).
        scopes: list[str] = []
        try:
            # Direct REST hit so we can read the X-OAuth-Scopes header.
            import httpx
            with httpx.Client(timeout=10) as h:
                r = h.get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 200:
                    raw = r.headers.get("x-oauth-scopes") or ""
                    scopes = [s.strip() for s in raw.split(",") if s.strip()]
        except Exception:  # noqa: BLE001
            scopes = []

        return {
            "ok": True,
            "stage": "ready",
            "login": login,
            "repo": repo_full,
            "default_branch": default_branch,
            "can_push": can_push,
            "scopes": scopes,
            "detail": "Token is valid and can open PRs against this repo.",
        }

    return await asyncio.to_thread(_probe)



@api.get("/projects")
async def list_projects(user: User = Depends(current_user)):
    await ensure_org_for_user(db, user.user_id, user.email, user.name)
    q = await project_query_for_user(db, user.user_id)
    cur = db.projects.find(q, {"_id": 0}).sort("created_at", -1)
    projects = await cur.to_list(200)
    out = []
    for p in projects:
        last = await db.test_runs.find_one(
            {"project_id": p["project_id"]},
            {"_id": 0},
            sort=[("started_at", -1)],
        )
        out.append({"project": p, "last_run": last})
    return out


@api.get("/projects/{project_id}")
async def get_project(project_id: str, user: User = Depends(current_user)):
    q = await project_query_for_user(db, user.user_id)
    q["project_id"] = project_id
    proj = await db.projects.find_one(q, {"_id": 0})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    runs = await db.test_runs.find({"project_id": project_id}, {"_id": 0}).sort("started_at", -1).to_list(50)
    custom_cases = await db.custom_test_cases.find({"project_id": project_id}, {"_id": 0}).to_list(100)
    return {"project": proj, "runs": runs, "custom_test_cases": custom_cases}


class RunCreate(BaseModel):
    command: str = "/atmos test"
    plan_id: Optional[str] = None
    enable_dopamine_max: bool = False
    design_theme_override: Optional[str] = None


VALID_COMMANDS = {
    "/atmos analyze", "/atmos explore", "/atmos test", "/atmos regress", "/atmos mobile",
    "/atmos benchmark", "/atmos accessibility", "/atmos personas", "/atmos record", "/atmos report",
}


@api.post("/projects/{project_id}/runs")
async def start_run(project_id: str, body: RunCreate, user: User = Depends(current_user)):
    await ensure_org_for_user(db, user.user_id, user.email, user.name)
    await require_permission(db, user.user_id, "runs:start")
    q = await project_query_for_user(db, user.user_id)
    q["project_id"] = project_id
    proj = await db.projects.find_one(q, {"_id": 0})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    command = body.command.strip()
    if command not in VALID_COMMANDS:
        raise HTTPException(status_code=400, detail="Unknown command")

    run_id = f"run_{uuid.uuid4().hex[:10]}"
    plan_doc = None
    if body.plan_id:
        plan_doc = await db.test_plans.find_one(
            {"plan_id": body.plan_id, "project_id": project_id, "user_id": user.user_id},
            {"_id": 0},
        )
    run = TestRun(
        run_id=run_id,
        project_id=project_id,
        user_id=user.user_id,
        command=command,
        status="running",
    )
    doc = run.model_dump()
    doc["started_at"] = doc["started_at"].isoformat()
    doc["plan_id"] = body.plan_id
    doc["enable_dopamine_max"] = body.enable_dopamine_max
    doc["design_theme_override"] = body.design_theme_override
    await db.test_runs.insert_one(doc)

    asyncio.create_task(_execute_run(
        run_id, proj, command,
        test_plan=plan_doc,
        enable_dopamine_max=body.enable_dopamine_max,
        design_theme_override=body.design_theme_override,
    ))
    return {"run_id": run_id}


@api.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(current_user)):
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    proj = await db.projects.find_one({"project_id": run["project_id"]}, {"_id": 0})
    events = await db.run_events.find({"run_id": run_id}, {"_id": 0}).sort("seq", 1).to_list(2000)
    return {"run": run, "project": proj, "events": events}


@api.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    # EventSource cannot set custom headers, so auth via cookie (or local bypass).
    if _auth_bypass_enabled(request):
        user_id = "user_local_dev"
    else:
        token = request.cookies.get("session_token")
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        if not session:
            raise HTTPException(status_code=401, detail="Invalid session")
        user_id = session["user_id"]
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_gen() -> AsyncIterator[bytes]:
        q = _subscribe(run_id)
        try:
            past = await db.run_events.find({"run_id": run_id}, {"_id": 0}).sort("seq", 1).to_list(2000)
            for ev in past:
                yield f"data: {json.dumps(ev)}\n\n".encode()

            if run["status"] in ("completed", "failed"):
                fresh = await db.test_runs.find_one({"run_id": run_id}, {"_id": 0})
                yield f"event: done\ndata: {json.dumps({'status': fresh['status']})}\n\n".encode()
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if ev.get("__type") == "done":
                    yield f"event: done\ndata: {json.dumps({'status': ev.get('status', 'completed')})}\n\n".encode()
                    break
                yield f"data: {json.dumps(ev)}\n\n".encode()
        finally:
            _unsubscribe(run_id, q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ----------------------------------------------------------------------------
# Test-run simulation engine
# ----------------------------------------------------------------------------

VIEWPORTS = [
    {"label": "iPhone 15", "w": 393, "h": 852},
    {"label": "iPhone SE", "w": 375, "h": 667},
    {"label": "Pixel 8 Pro", "w": 412, "h": 915},
    {"label": "Galaxy Fold", "w": 344, "h": 882},
    {"label": "iPad Air", "w": 820, "h": 1180},
    {"label": "iPad Pro", "w": 1024, "h": 1366},
    {"label": "Desktop 1440", "w": 1440, "h": 900},
    {"label": "Ultrawide", "w": 2560, "h": 1080},
]

PERSONAS = [
    {"id": "elderly", "label": "Elderly User (65+)", "focus": "Vision, dexterity, slow reading"},
    {"id": "blind", "label": "Blind User", "focus": "Screen reader, keyboard-only"},
    {"id": "low_vision", "label": "Low-Vision User", "focus": "200–400% zoom"},
    {"id": "color_blind", "label": "Color-Blind User", "focus": "Protanopia / Deuteranopia / Tritanopia"},
    {"id": "first_time", "label": "First-Time User", "focus": "Discoverability"},
    {"id": "power_user", "label": "Power User", "focus": "Shortcuts, efficiency"},
    {"id": "child", "label": "Child User", "focus": "Readability, misclicks"},
]

BENCHMARKS = {
    "finance": ["Stripe", "PayPal", "Wise"],
    "e-commerce": ["Amazon", "Shopify", "Apple Store"],
    "calendar": ["Google Calendar", "Fantastical", "Cron"],
    "dashboard": ["Linear", "Notion", "Vercel"],
    "generic": ["Apple", "Stripe", "Linear"],
}


async def _llm_plan(project: dict[str, Any], command: str) -> dict[str, Any]:
    try:
        from user_llm_proxy import user_llm_json
        data = await user_llm_json(
            db,
            project.get("user_id") or "user_local_dev",
            (
                f"Target: {project['name']} at {project['url']}\n"
                f"Detected app type: {project['app_type']}\n"
                f"Command: {command}\n"
                "Return JSON only with keys: narrative (1-sentence intro), "
                "focus_areas (5-8 short strings naming concrete UX surfaces or risks to probe)."
            ),
            system=(
                "You are Atmos, an autonomous UX testing agent. Respond with ONLY JSON, no prose."
            ),
            purpose="run_plan",
        )
        if isinstance(data, dict) and data.get("focus_areas"):
            return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM plan failed: %s", exc)
    return {
        "narrative": f"Probe core journeys on {project.get('name')}.",
        "focus_areas": ["onboarding", "primary CTA", "forms", "navigation", "errors"],
    }



async def _llm_report(project: dict[str, Any], command: str, focus_areas: list[str], issues: list[dict]) -> dict[str, Any]:
    try:
        from user_llm_proxy import user_llm_json
        prompt = (
            f"Target: {project['name']} ({project['url']})\n"
            f"App type: {project['app_type']}\n"
            f"Command: {command}\n"
            f"Focus areas probed: {focus_areas}\n"
            f"Issues found: {json.dumps(issues[:20])}\n"
            "Return JSON only with keys: critical_findings (array of 3-5 short sentences), "
            "recommendations (array of 5 imperative sentences, each <=15 words), "
            "competitive_insight (1-2 sentences benchmarking vs industry leaders)."
        )
        data = await user_llm_json(
            db,
            project.get("user_id") or "user_local_dev",
            prompt,
            system="You are Atmos, producing an executive testing report. Return JSON ONLY.",
            purpose="executive_report",
        )
        if isinstance(data, dict) and ("critical_findings" in data or "recommendations" in data):
            return data
        raise RuntimeError("unexpected report shape")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM report failed: %s", exc)
        return {
            "critical_findings": [
                "Automated report generation unavailable — review live issues in the monitor.",
            ],
            "recommendations": [
                "Triage critical and high severity issues first.",
                "Keep the Atmos IDE extension open to fund LLM analysis on your quota.",
                "Validate critical paths manually.",
            ],
            "competitive_insight": "Connect Cursor/VS Code Atmos extension so reports use your IDE model entitlement.",
        }



# Theatrical seed helpers (_seed_issues / _test_cases / _persona_scores) removed.
# Live runs use Playwright engines + command profiles only.

def _github_test_cases(pages: list[dict[str, Any]], button_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate test cases from the actual pages and button interactions discovered
    in a GitHub repo run — every case references a real screenshot and real route."""
    cases: list[dict[str, Any]] = []

    # Case 1: one per discovered route (navigation test)
    for p in pages[:8]:
        route = p.get("route", "/")
        mobile_cap = p["captures"].get("iPhone SE", {})
        desktop_cap = p["captures"].get("Desktop 1440", {})
        caps_ok = mobile_cap.get("ok") and desktop_cap.get("ok")
        cases.append({
            "name": f"Route '{route}' renders on both mobile and desktop",
            "category": "Visual",
            "steps": [
                f"Navigate to {p['url']}",
                "Capture iPhone SE viewport",
                "Capture Desktop 1440 viewport",
                "Assert no blank/error screen",
            ],
            "expected_result": "pass" if caps_ok else "warn",
            "explanation": (
                f"'{route}' captured successfully on mobile and desktop." if caps_ok
                else f"One or more viewports failed to capture for '{route}'."
            ),
            "frames": [f for f in [
                desktop_cap.get("url_path"),
                mobile_cap.get("url_path"),
            ] if f],
        })

    # Case 2: icon & button interaction tests (one per discovered button action)
    icon_actions = [a for a in button_actions if a.get("isIcon")]
    text_actions = [a for a in button_actions if not a.get("isIcon")]
    for actions, kind in [(icon_actions, "icon"), (text_actions, "button")]:
        for act in actions[:3]:
            navigated = act.get("navigated", False)
            cases.append({
                "name": f"Click {kind} '{act['label']}' on {act.get('route', act.get('from', ''))}",
                "category": "UX",
                "steps": [
                    f"Navigate to {act.get('from', '')}",
                    f"Click {kind}: {act['label']}",
                    "Assert destination rendered" if navigated else "Assert panel / modal visible",
                ],
                "expected_result": "pass" if navigated or kind == "button" else "warn",
                "explanation": (
                    f"Clicking '{act['label']}' navigated to {act.get('to', '—')}." if navigated
                    else f"Clicking '{act['label']}' triggered a UI state change (no navigation)."
                ),
                "frames": [],
            })

    # Case 3: responsive sweep summary
    all_ok = all(
        p["captures"].get("iPhone SE", {}).get("ok") and p["captures"].get("Desktop 1440", {}).get("ok")
        for p in pages
    )
    cases.append({
        "name": f"Responsive sweep — {len(pages)} routes on mobile and desktop",
        "category": "Visual",
        "steps": [f"Capture {p['url']} on iPhone SE" for p in pages[:6]] + ["Capture all on Desktop 1440"],
        "expected_result": "pass" if all_ok else "warn",
        "explanation": (
            f"All {len(pages)} routes rendered successfully on both viewports." if all_ok
            else f"Some routes failed to render on one or more viewports."
        ),
        "frames": [
            p["captures"].get("Desktop 1440", {}).get("url_path")
            for p in pages[:4] if p["captures"].get("Desktop 1440", {}).get("ok")
        ],
    })

    # Strip None frames
    for c in cases:
        c["frames"] = [f for f in (c.get("frames") or []) if f]

    return cases


async def _execute_run(
    run_id: str,
    project: dict[str, Any],
    command: str,
    *,
    test_plan: Optional[dict[str, Any]] = None,
    enable_dopamine_max: bool = False,
    design_theme_override: Optional[str] = None,
) -> None:
    """Real engine: optionally boot a GitHub repo → crawl + click buttons →
    per-page LLM vision → patch & re-capture → fuzz form fields → architecture
    analysis → executive report. Emits live JPEG frames the UI consumes as a stream."""
    seq = {"n": 0}
    app_type = project.get("app_type") or "generic"
    source = project.get("source") or "url"
    profile = get_command_profile(command)
    a11y_result: dict[str, Any] = {"score": 0, "findings": [], "pages": []}
    try:
        await _emit(run_id, seq, "log", {"level": "info",
            "message": f"Atmos {command} → {project['name']} ({app_type}) via {source} · profile: {profile.get('label')}"})

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            booted_url: Optional[str] = None
            repo_root: Optional[Path] = None
            repo_ctx = None

            try:
                # ── Phase 0: If GitHub source, clone + boot locally ──────
                if source == "github" and project.get("github_url"):
                    await _emit(run_id, seq, "phase", {"phase": "github_boot", "label": "Cloning & Booting Repo"})

                    async def gh_log(level: str, message: str) -> None:
                        await _emit(run_id, seq, "log", {"level": level, "message": message})

                    secret = await db.project_secrets.find_one({"project_id": project["project_id"]}, {"_id": 0})
                    pat = (secret or {}).get("github_token")
                    repo_ctx = boot_repo(project["github_url"], on_log=gh_log, github_token=pat)
                    booted_url, _stack, repo_root = await repo_ctx.__aenter__()
                    target_url = booted_url
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Cloned repo → booted locally at {booted_url}"})
                else:
                    target_url = project["url"]

                # ── Phase 1: Crawl + Capture every reachable page ───────
                await _emit(run_id, seq, "phase", {"phase": "analyze", "label": "Project Understanding"})
                await _emit(run_id, seq, "log", {"level": "info",
                    "message": f"Launching headless Chromium against {target_url}…"})

                async def on_progress(ev: dict[str, Any]):
                    et = ev.get("type")
                    if et == "page_capture":
                        await _emit(run_id, seq, "page_capture", {
                            "url": ev["url"],
                            "viewport": ev["viewport"],
                            "ok": ev["ok"],
                            "url_path": ev["url_path"],
                            "title": ev["title"],
                            "page_index": ev["page_index"],
                        })
                        if ev["ok"]:
                            await _emit(run_id, seq, "screenshot", {
                                "action": "navigate", "target": ev["url"],
                                "viewport": ev["viewport"],
                                "caption": f"{ev['viewport']} · {ev['title'] or ev['url']}",
                                "url_path": ev["url_path"],
                            })
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"{'✓' if ev['ok'] else '✗'} {ev['viewport']} · {ev['url']}"})
                    elif et == "live_frame":
                        await _emit(run_id, seq, "live_frame", {
                            "kind": ev.get("kind", "live"),
                            "label": ev.get("label", ""),
                            "image_b64": ev["image_b64"],
                        })
                    elif et == "route_context":
                        await _emit(run_id, seq, "log", {
                            "level": "info",
                            "message": (
                                f"Route {ev.get('route')} -> action={ev.get('action')} "
                                f"filled={ev.get('filled_fields')} "
                                f"cta={ev.get('clicked_cta') or 'none'} "
                                f"sources={', '.join((ev.get('source_files') or [])[:2]) or 'n/a'}"
                            ),
                        })
                    elif et == "route_video":
                        await _emit(run_id, seq, "route_video", ev)
                    elif et == "screen":
                        await _emit(run_id, seq, "screen_discovered", ev)
                        await _emit(run_id, seq, "log", {
                            "level": "info",
                            "message": (
                                f"Screen '{ev.get('name')}' ({ev.get('route')}) — "
                                f"{ev.get('field_count', 0)} input(s): "
                                f"{', '.join((ev.get('fields') or [])[:4]) or 'none'}"
                            ),
                        })
                    elif et == "screen_context":
                        await _emit(run_id, seq, "log", {
                            "level": "info",
                            "message": (
                                f"Testing '{ev.get('screen_name')}' — {ev.get('purpose') or 'screen'} "
                                f"· {ev.get('planned_cases', 0)} test case(s)"
                            ),
                        })
                    elif et == "screen_test":
                        await _emit(run_id, seq, "screen_test", ev)
                    elif et == "test_case":
                        await _emit(run_id, seq, "test_case", ev)
                    elif et == "test_case_step":
                        await _emit(run_id, seq, "test_case_step", ev)
                    elif et == "duplicate_capture":
                        await _emit(run_id, seq, "log", {
                            "level": "warning",
                            "message": (
                                f"Possible duplicate visual state for route {ev.get('route')} "
                                f"(same as {ev.get('duplicate_of')})."
                            ),
                        })
                    elif et == "fuzz_case":
                        await _emit(run_id, seq, "fuzz_case", ev)

                await _emit(run_id, seq, "phase", {"phase": "explore", "label": "Crawling & Clicking Buttons"})
                flow_screens: list[dict[str, Any]] = []
                # Always try agentic flow exploration first (for both live URLs and
                # booted GitHub apps). Falling back to route/direct crawling only
                # when too few distinct screens are discovered avoids "same first
                # screen" captures on auth-gated SPAs.
                explore_secs = int(profile.get("explore_max_secs") or max(30, EXPLORE_TIMEOUT_SECS - 10))
                explore_secs = max(30, min(explore_secs, EXPLORE_TIMEOUT_SECS))
                try:
                    flow = await explore_app_flow(
                        browser,
                        target_url,
                        run_id,
                        on_progress=on_progress,
                        max_duration_secs=explore_secs,
                        db=db,
                        user_id=project.get("user_id"),
                    )
                    flow_screens = flow.get("screens", [])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("flow explorer failed: %s", exc)
                    flow = {"screens": [], "pages": [], "button_actions": []}

                if len(flow_screens) >= 2:
                    crawl = {"pages": flow["pages"], "button_actions": flow.get("button_actions", [])}
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Flow explorer drove the app to {len(flow_screens)} distinct screen(s)."})
                elif source == "github" and repo_root is not None:
                    routes = extract_routes_from_source(repo_root)
                    route_contexts = build_route_contexts(repo_root, routes)
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Flow explorer found {len(flow_screens)} screen(s). Falling back to {len(routes)} source routes."})
                    crawl = await capture_routes_direct(
                        browser,
                        target_url,
                        routes,
                        run_id,
                        route_contexts=route_contexts,
                        on_progress=on_progress,
                    )
                else:
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": "Flow explorer found few screens; falling back to shallow crawl."})
                    crawl = await crawl_and_capture(browser, target_url, run_id, on_progress=on_progress)
                pages = crawl["pages"]
                button_actions = crawl.get("button_actions", [])
                if not pages or not any(any(c.get("ok") for c in p["captures"].values()) for p in pages):
                    raise RuntimeError("No page captures succeeded — site may be blocking automated traffic.")

                await _emit(run_id, seq, "app_graph", {
                    "pages": [{"url": p["url"], "title": p["title"], "slug": p["slug"]} for p in pages],
                    "button_actions": button_actions,
                })
                await _emit(run_id, seq, "log", {"level": "info",
                    "message": f"Crawled {len(pages)} page(s) · {len(button_actions)} button clicks. Per-page vision analysis next."})

                if test_plan:
                    await _emit(run_id, seq, "test_plan", {
                        "plan_id": test_plan.get("plan_id"),
                        "narrative": test_plan.get("narrative"),
                        "focus_areas": test_plan.get("focus_areas"),
                        "test_cases": test_plan.get("test_cases"),
                        "status": "executing",
                    })
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Executing approved test plan — {len(enabled_cases_from_plan(test_plan))} enabled case(s)."})

                # ── Design theory fundamentals ─────────────────────────
                design_result: dict[str, Any] = {}
                if profile["includes"]("design_theory"):
                    await _emit(run_id, seq, "phase", {"phase": "design_theory", "label": "Design Fundamentals Audit"})

                    async def design_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "design_theory":
                            await _emit(run_id, seq, "design_theory", ev)
                        elif ev.get("type") == "design_theory_issue":
                            await _emit(run_id, seq, "design_issue", ev)

                    design_result = await analyze_design_theory(
                        browser, target_url, run_id, app_type,
                        theme_override=design_theme_override or project.get("design_theme"),
                        on_progress=design_progress,
                    )
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Design theory ({design_result.get('theme_label')}): {design_result.get('issue_count', 0)} issue(s), score {design_result.get('score')}/100"})

                # ── Competitive side-by-side diff ──────────────────────
                competitive_results: list[dict[str, Any]] = []
                if profile["includes"]("competitive"):
                    await _emit(run_id, seq, "phase", {"phase": "competitive", "label": "Competitive UX Diff"})
                    first_cap = None
                    if pages:
                        for cap in pages[0].get("captures", {}).values():
                            if cap.get("url_path"):
                                first_cap = cap["url_path"]
                                break

                    async def comp_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "competitive_diff":
                            await _emit(run_id, seq, "competitive_diff", ev)

                    competitive_results = await run_competitive_diffs(
                        browser, target_url, run_id, app_type,
                        your_screenshot_url=first_cap,
                        on_progress=comp_progress,
                        db=db,
                        user_id=project.get("user_id"),
                    )
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Competitive diff: {len(competitive_results)} side-by-side comparison(s) vs industry leaders."})

                # ── Phase 2: Per-page LLM vision analysis (parallel batched) ──
                aggregated_issues: list[dict[str, Any]] = []
                page_summaries: list[dict[str, Any]] = []
                vp_labels = [v["label"] for v in REAL_VIEWPORTS]
                if profile["includes"]("per_page"):
                    await _emit(run_id, seq, "phase", {"phase": "per_page", "label": "Per-Page Vision Analysis"})
                    pages = pages[: int(profile.get("max_pages_analyze") or 12)]

                # Bound concurrency so we don't blast the LLM provider.
                ANALYSIS_CONCURRENCY = int(os.environ.get("ATMOS_PAGE_ANALYSIS_CONCURRENCY", "4"))
                PER_PAGE_TIMEOUT = int(os.environ.get("ATMOS_PER_PAGE_TIMEOUT_SECS", "75"))
                pages_for_analysis = pages if profile["includes"]("per_page") else []
                focus_areas: list[str] = []
                narrative = f"Atmos {profile.get('label', command)} on {project['name']}."
                sem = asyncio.Semaphore(ANALYSIS_CONCURRENCY)

                async def _analyze_one(p: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                    async with sem:
                        try:
                            res = await asyncio.wait_for(llm_analyze_page(project, p, db=db), timeout=PER_PAGE_TIMEOUT)
                            return p, res
                        except asyncio.TimeoutError:
                            logger.warning("per-page analysis TIMED OUT for %s after %ds", p["url"], PER_PAGE_TIMEOUT)
                            return p, {"page_summary": "", "issues": []}
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("per-page analysis failed for %s: %s", p["url"], exc)
                            return p, {"page_summary": "", "issues": []}

                analyses = await asyncio.gather(*[_analyze_one(pg) for pg in pages_for_analysis]) if pages_for_analysis else []

                for p, page_analysis in analyses:
                    summary_line = page_analysis.get("page_summary") or ""
                    page_summaries.append({"url": p["url"], "title": p["title"], "summary": summary_line})
                    if summary_line:
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"· {p['url']} — {summary_line}"})
                    for raw in (page_analysis.get("issues") or [])[:5]:
                        raw["page_url"] = p["url"]
                        raw["viewport_label"] = raw.get("viewport_label") if raw.get("viewport_label") in vp_labels else "Desktop 1440"
                        aggregated_issues.append(raw)

                if not aggregated_issues:
                    # Fallback to the holistic analyzer (or deterministic) if per-page found nothing.
                    try:
                        holistic = await llm_analyze_app(project, command, pages, db=db)
                        aggregated_issues = list(holistic.get("issues") or [])
                        focus_areas = holistic.get("focus_areas", []) or []
                        narrative = holistic.get("narrative", "")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("holistic fallback failed: %s", exc)
                        fb = deterministic_fallback(project, pages)
                        aggregated_issues = list(fb.get("issues") or [])
                        focus_areas = fb.get("focus_areas", []) or []
                        narrative = fb.get("narrative", "")
                else:
                    focus_areas = [s["summary"].split(".")[0] for s in page_summaries if s["summary"]][:8]
                    narrative = f"Atmos analyzed {len(pages)} pages and observed {len(aggregated_issues)} issues across them."

                await _emit(run_id, seq, "log", {"level": "info", "message": narrative})
                await _emit(run_id, seq, "plan", {"focus_areas": focus_areas})

                # ── Phase 3: Real accessibility audit + Personas ───────
                if profile["includes"]("accessibility"):
                    await _emit(run_id, seq, "phase", {"phase": "accessibility", "label": "Accessibility Audit"})

                    async def a11y_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "a11y_log":
                            await _emit(run_id, seq, "log", {"level": "info", "message": ev.get("message", "")})
                        elif ev.get("type") == "a11y_page":
                            await _emit(run_id, seq, "log", {"level": "info",
                                "message": f"A11y {ev.get('url')}: score {ev.get('score')}/100 · {ev.get('findings')} finding(s)"})
                        elif ev.get("type") == "a11y_report":
                            await _emit(run_id, seq, "a11y_report", ev)

                    try:
                        a11y_result = await run_accessibility_audit(
                            browser, target_url, pages,
                            deep=bool(profile.get("a11y_deep")),
                            mobile_preferred=bool(profile.get("mobile_viewports_only")),
                            on_progress=a11y_progress,
                        )
                        # Promote a11y findings into issue stream for report/monitor
                        for f in (a11y_result.get("findings") or [])[:8]:
                            aggregated_issues.append({
                                "category": "Accessibility",
                                "severity": f.get("severity", "medium"),
                                "title": f.get("title", "A11y finding"),
                                "cause": f.get("cause", ""),
                                "page_url": f.get("page_url") or target_url,
                                "patch_css": "",
                                "patch_explanation": "Fix accessible name, contrast, or keyboard path.",
                                "alternatives": [],
                            })
                        await _emit(run_id, seq, "log", {"level": "info", "message": a11y_result.get("summary", "A11y audit complete")})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("a11y audit failed: %s", exc)

                if profile["includes"]("personas"):
                    await _emit(run_id, seq, "phase", {"phase": "personas", "label": "Human Persona Simulation"})
                persona_ids = None
                if profile.get("persona_ids") == "all" or command == "/atmos personas":
                    persona_ids = [p["id"] for p in PERSONA_DEFINITIONS]
                elif isinstance(profile.get("persona_ids"), list):
                    persona_ids = profile["persona_ids"]

                async def persona_progress(ev: dict[str, Any]) -> None:
                    if ev.get("type") == "persona_complete":
                        await _emit(run_id, seq, "persona", ev)
                    elif ev.get("type") == "persona_annotation":
                        await _emit(run_id, seq, "persona_annotation", ev)

                personas = []
                if profile["includes"]("personas"):
                    personas = await run_persona_simulations(
                        browser, target_url, run_id,
                        on_progress=persona_progress,
                        persona_ids=persona_ids,
                    )
                    for p in personas:
                        await _emit(run_id, seq, "log", {
                            "level": "info",
                            "message": f"Persona {p['label']}: {p['score']}/100 — {p.get('rules_passed', 0)}/{p.get('rules_total', 0)} rules passed",
                        })

                # ── Phase 4: Issues — patch & re-capture full pages ─────
                emitted_issues: list[dict[str, Any]] = []
                if profile["includes"]("issues"):
                    await _emit(run_id, seq, "phase", {"phase": "issues", "label": "Executed Fixes"})
                pages_by_url = {p["url"]: p for p in pages}

                for raw in (aggregated_issues[:12] if profile["includes"]("issues") else []):
                    page_url = raw.get("page_url") or pages[0]["url"]
                    target_page = pages_by_url.get(page_url) or pages[0]
                    vp_label = raw.get("viewport_label") if raw.get("viewport_label") in vp_labels else "Desktop 1440"

                    # baseline already captured during crawl
                    before_cap = target_page["captures"].get(vp_label) or next(
                        (c for c in target_page["captures"].values() if c.get("ok")), {}
                    )
                    before_url = before_cap.get("url_path")

                    iss_id = f"iss_{uuid.uuid4().hex[:8]}"
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Applying patch for ‘{raw.get('title', 'issue')}’ on {target_page['url']} ({vp_label})…"})

                    after_result = await apply_patch_full_page(
                        browser, target_page["url"], vp_label,
                        raw.get("patch_css", ""), run_id, f"{iss_id}_after", target_page["slug"],
                        baseline_url_path=before_url,
                    )

                    alts_out = []
                    for ai, alt in enumerate((raw.get("alternatives") or [])[:2]):
                        alt_result = await apply_patch_full_page(
                            browser, target_page["url"], vp_label,
                            alt.get("patch_css", ""), run_id, f"{iss_id}_alt{ai}", target_page["slug"],
                            baseline_url_path=before_url,
                        )
                        alts_out.append({
                            "label": alt.get("label", f"Alternative {ai+1}"),
                            "summary": alt.get("summary", ""),
                            "tradeoff": alt.get("tradeoff", ""),
                            "patch_css": alt.get("patch_css", ""),
                            "screenshot_url": alt_result.get("after_url"),
                            "diff_url": alt_result.get("diff_url"),
                            "changed_pct": alt_result.get("changed_pct"),
                            "applied": alt_result.get("applied"),
                            "no_op_reason": alt_result.get("no_op_reason"),
                        })

                    issue_full = {
                        "id": iss_id,
                        "category": raw.get("category", "UX"),
                        "severity": raw.get("severity", "medium"),
                        "title": raw.get("title", "Untitled issue"),
                        "cause": raw.get("cause", ""),
                        "page_url": target_page["url"],
                        "page_title": target_page.get("title", ""),
                        "viewport": vp_label,
                        "before": {
                            "headline": raw.get("title", ""),
                            "detail": raw.get("cause", ""),
                            "screenshot_url": before_url,
                        },
                        "after": {
                            "headline": "Atmos applied this fix",
                            "detail": raw.get("patch_explanation", ""),
                            "code": raw.get("patch_css", ""),
                            "screenshot_url": after_result.get("after_url"),
                        },
                        "diff_url": after_result.get("diff_url"),
                        "changed_pct": after_result.get("changed_pct"),
                        "applied": after_result.get("applied"),
                        "no_op_reason": after_result.get("no_op_reason"),
                        "alternatives": alts_out,
                        "patch_kind": "css_patch",
                    }
                    emitted_issues.append(issue_full)
                    await _emit(run_id, seq, "issue", issue_full)

                # Enrich issues with Mobbin/Pinterest UI references
                emitted_issues = await enrich_issues_with_references(db, emitted_issues, app_type)
                for iss in emitted_issues:
                    if iss.get("ui_references"):
                        await _emit(run_id, seq, "ui_reference", {
                            "issue_id": iss["id"],
                            "references": iss["ui_references"],
                        })

                # ── Phase 5: Fuzz / boundary input test cases ───────────
                fuzz_cases: list[dict[str, Any]] = []
                if profile["includes"]("fuzz"):
                    await _emit(run_id, seq, "phase", {"phase": "fuzz", "label": "Boundary Input Fuzzing"})
                    for url in [p["url"] for p in pages[:4]]:
                        try:
                            new_cases = await asyncio.wait_for(
                                run_fuzz_suite(
                                    browser,
                                    url,
                                    run_id,
                                    on_progress=on_progress,
                                    max_fields=4,
                                    max_cases_per_field=8,
                                ),
                                timeout=FUZZ_URL_TIMEOUT_SECS,
                            )
                            fuzz_cases.extend(new_cases)
                        except asyncio.TimeoutError:
                            await _emit(run_id, seq, "log", {
                                "level": "warning",
                                "message": f"Fuzz timeout after {FUZZ_URL_TIMEOUT_SECS}s on {url}; continuing run.",
                            })
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("fuzz failed on %s: %s", url, exc)

                    if not fuzz_cases and flow_screens:
                        await _emit(run_id, seq, "log", {
                            "level": "info",
                            "message": f"URL fuzz found no stable inputs; running live fuzz against {len(flow_screens)} discovered screen(s).",
                        })
                        try:
                            live_fuzz = await fuzz_flow_screens(
                                browser, flow_screens, run_id, on_progress=on_progress,
                            )
                            fuzz_cases.extend(live_fuzz)
                            await _emit(run_id, seq, "log", {"level": "info",
                                "message": f"Live screen fuzz: ran {len(live_fuzz)} case(s) with video."})
                        except Exception as exc:
                            logger.warning("fuzz_flow_screens failed: %s", exc)

                # ── Phase 5b: Per-screen, context-aware test cases (with video) ─
                screen_test_results: list[dict[str, Any]] = []
                if flow_screens and profile["includes"]("screen_tests"):
                    await _emit(run_id, seq, "phase", {"phase": "screen_tests", "label": "Per-Screen Test Cases"})
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Generating elaborate test cases for {len(flow_screens)} screen(s); recording a video per case."})
                    try:
                        screen_test_results = await generate_and_run_screen_tests(
                            browser, flow_screens, run_id, project, on_progress=on_progress, db=db,
                        )
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Ran {len(screen_test_results)} per-screen test case(s) with video."})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("screen tests failed: %s", exc)

                # ── Phase 6: Architecture analysis (GitHub repo OR URL runtime) ─
                arch_payload: Optional[dict[str, Any]] = None
                if profile["includes"]("architecture") and source == "github" and repo_root is not None:
                    await _emit(run_id, seq, "phase", {"phase": "architecture", "label": "Architecture Analysis"})
                    try:
                        arch_payload = await analyze_repo(repo_root, project["name"], app_type, db=db, user_id=project.get("user_id"))
                        await _emit(run_id, seq, "architecture", arch_payload)
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Architecture score: {arch_payload['score']['overall']}/100 · {len(arch_payload['suggestions'])} suggestions"})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("arch analysis failed: %s", exc)
                elif profile["includes"]("architecture") and pages:
                    # URL-mode runtime audit — no source code, but we can still
                    # observe the live surface and benchmark against industry peers.
                    await _emit(run_id, seq, "phase", {"phase": "architecture", "label": "Architecture Analysis (URL mode)"})
                    try:
                        arch_payload = await analyze_url_run(pages, project["name"], app_type, project["url"], db=db, user_id=project.get("user_id"))
                        await _emit(run_id, seq, "architecture", arch_payload)
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Architecture score (URL mode): {arch_payload['score']['overall']}/100 · {len(arch_payload['suggestions'])} suggestions"})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("URL-mode arch analysis failed: %s", exc)

                # ── Phase 7: Real Playwright playback of plan/seed cases ─
                emitted_cases = []
                if profile["includes"]("test_cases"):
                    await _emit(run_id, seq, "phase", {"phase": "test_cases", "label": "Live Test Case Playback"})
                    if test_plan and enabled_cases_from_plan(test_plan):
                        cases = [
                            {
                                "name": c["name"],
                                "category": c.get("category", "UX"),
                                "steps": c.get("steps", []),
                                "expected_result": "pass",
                                "explanation": c.get("rationale", "From approved test plan"),
                                "frames": [],
                            }
                            for c in enabled_cases_from_plan(test_plan)
                        ]
                    elif source == "github" and pages:
                        cases = _github_test_cases(pages, button_actions)
                    else:
                        cases = seed_test_cases(app_type, pages)

                    async def plan_progress(ev: dict[str, Any]) -> None:
                        et = ev.get("type")
                        if et == "custom_test_start":
                            await _emit(run_id, seq, "test_case", {
                                "id": ev["case_id"], "name": ev["name"], "phase": "start",
                                "steps": ev.get("steps", []), "status": "running", "source": "plan",
                            })
                        elif et == "custom_test_step":
                            await _emit(run_id, seq, "test_case_step", {
                                "case_id": ev["case_id"], "step_index": ev["step_index"],
                                "step": ev["step"], "status": ev.get("status", "running"),
                                "screenshot_url": ev.get("screenshot_url"), "source": "plan",
                            })
                        elif et == "custom_test_complete":
                            emitted_cases.append({
                                "id": ev["case_id"], "name": ev["name"],
                                "status": ev.get("status", "fail"), "video_url": ev.get("video_url"),
                                "steps": ev.get("step_results") or [], "source": "plan",
                            })
                            await _emit(run_id, seq, "test_case", {
                                "id": ev["case_id"], "name": ev["name"], "phase": "end",
                                "status": ev.get("status", "fail"), "video_url": ev.get("video_url"),
                                "source": "plan",
                            })

                    try:
                        await run_plan_cases_playwright(
                            browser, target_url, cases, run_id, on_progress=plan_progress,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("plan case playback failed: %s", exc)

                # ── Phase 7b: User-written custom test cases (Playwright video) ─
                custom_case_results: list[dict[str, Any]] = []
                custom_cases = await db.custom_test_cases.find(
                    {"project_id": project["project_id"], "enabled": {"$ne": False}},
                    {"_id": 0},
                ).to_list(50)
                if custom_cases and profile["includes"]("custom_tests"):
                    await _emit(run_id, seq, "phase", {"phase": "custom_tests", "label": "Custom Test Cases"})
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Running {len(custom_cases)} user-written test case(s) with video recording…"})

                    async def custom_progress(ev: dict[str, Any]) -> None:
                        et = ev.get("type")
                        if et == "custom_test_start":
                            await _emit(run_id, seq, "test_case", {
                                "id": ev["case_id"], "name": ev["name"], "phase": "start",
                                "steps": ev.get("steps", []), "status": "running", "source": "custom",
                            })
                        elif et == "custom_test_step":
                            await _emit(run_id, seq, "test_case_step", {
                                "case_id": ev["case_id"], "step_index": ev["step_index"],
                                "step": ev["step"], "status": ev.get("status", "running"),
                                "screenshot_url": ev.get("screenshot_url"), "source": "custom",
                            })
                        elif et == "custom_test_complete":
                            await _emit(run_id, seq, "custom_test", ev)
                            await _emit(run_id, seq, "test_case", {
                                "id": ev["case_id"], "name": ev["name"], "phase": "end",
                                "status": ev.get("status", "fail"), "video_url": ev.get("video_url"),
                                "source": "custom",
                            })

                    custom_case_results = await run_custom_test_cases(
                        browser, target_url, custom_cases, run_id, on_progress=custom_progress,
                    )

                # ── Phase 8: Real conversion funnel + benchmark ─────────
                funnel_result: dict[str, Any] = {"benchmarks": [], "your_clicks": None, "industry_avg": None}
                bench_rows: list[dict[str, Any]] = []
                if profile["includes"]("benchmark"):
                    await _emit(run_id, seq, "phase", {"phase": "benchmark", "label": "Conversion Funnel & Benchmark"})

                    async def funnel_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "benchmark":
                            await _emit(run_id, seq, "benchmark", ev)
                        elif ev.get("type") == "funnel_analysis":
                            await _emit(run_id, seq, "funnel_analysis", ev)

                    funnel_result = await analyze_conversion_funnel(
                        browser, target_url, pages, button_actions, app_type, run_id,
                        on_progress=funnel_progress,
                    )
                    bench_rows = funnel_result.get("benchmarks", [])
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": funnel_result.get("comparison", f"{funnel_result.get('your_clicks')} clicks to goal")})

                # ── Dopamine + dark patterns ───────────────────────────
                dopamine_result: Optional[dict[str, Any]] = None
                if profile["includes"]("dopamine"):
                    await _emit(run_id, seq, "phase", {"phase": "dopamine", "label": "Engagement & Dark Patterns"})
                    engagement_max = bool(enable_dopamine_max or project.get("enable_dopamine_max"))

                    async def dopamine_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "dopamine_analysis":
                            await _emit(run_id, seq, "dopamine_analysis", ev)

                    dopamine_result = await analyze_dopamine_engagement(
                        browser, target_url, app_type,
                        enabled=True,
                        engagement_max=engagement_max,
                        on_progress=dopamine_progress,
                    )
                    dp_n = len(dopamine_result.get("dark_patterns") or [])
                    sug_n = len(dopamine_result.get("suggestions") or [])
                    miss_n = len(dopamine_result.get("dark_pattern_suggestions") or [])
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": (
                            f"Engagement/dark-patterns: score {dopamine_result.get('dark_pattern_score')}/100 · "
                            f"{dp_n} present · {miss_n} missing suggestions (disclaimer) · {sug_n} ethical tip(s)"
                            + (" · max mode on" if engagement_max else "")
                        )})
                    for di in (dopamine_result.get("dark_pattern_issues") or [])[:8]:
                        issue = {
                            "id": di.get("id") or f"dp_{uuid.uuid4().hex[:8]}",
                            "category": "Dark pattern",
                            "severity": di.get("severity", "medium"),
                            "title": di.get("title") or "Dark pattern",
                            "cause": di.get("cause") or "",
                            "page_url": target_url,
                            "file": urlparse(target_url).path or "/",
                            "patch_css": "",
                            "patch_explanation": di.get("recommendation") or "Remove deceptive design.",
                            "alternatives": [],
                            "summary": di.get("recommendation") or "",
                        }
                        aggregated_issues.append(issue)
                        await _emit(run_id, seq, "issue", issue)

                # ── Marketing copywriting alternatives ─────────────────
                copywriting_result: dict[str, Any] = {}
                if profile["includes"]("copywriting"):
                    await _emit(run_id, seq, "phase", {"phase": "copywriting", "label": "Marketing Copy Alternatives"})

                    async def copy_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "copy_suggestion":
                            await _emit(run_id, seq, "copy_suggestion", ev)
                        elif ev.get("type") == "copywriting_report":
                            await _emit(run_id, seq, "copywriting_report", ev)

                    copywriting_result = await analyze_copywriting(
                        browser, target_url, project, run_id,
                        db=db,
                        user_id=project.get("user_id"),
                        on_progress=copy_progress,
                    )
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": copywriting_result.get("summary", f"Copy: {copywriting_result.get('blocks_analyzed', 0)} blocks")})

                # ── Demand intelligence (Reddit / GitHub / Google reviews) ─
                demand_result: dict[str, Any] = {}
                if profile["includes"]("demand"):
                    await _emit(run_id, seq, "phase", {"phase": "demand", "label": "Feature Demand Intelligence"})

                    async def demand_progress(ev: dict[str, Any]) -> None:
                        if ev.get("type") == "demand_log":
                            await _emit(run_id, seq, "log", {"level": "info", "message": ev.get("message", "")})
                        elif ev.get("type") == "demand_plan":
                            await _emit(run_id, seq, "log", {"level": "info", "message": ev.get("message", "Research plan ready")})
                            await _emit(run_id, seq, "demand_plan", {
                                "plan": ev.get("plan"),
                                "message": ev.get("message"),
                            })
                        elif ev.get("type") == "demand_report":
                            await _emit(run_id, seq, "demand_report", ev)

                    demand_result = await build_demand_report(
                        project,
                        pages=pages,
                        button_actions=button_actions,
                        page_summaries=page_summaries,
                        on_progress=demand_progress,
                        db=db,
                        user_id=project.get("user_id"),
                        run_id=run_id,
                    )
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": demand_result.get("executive_summary", "Demand report ready")})

                await _emit(run_id, seq, "phase", {"phase": "report", "label": "Executive Report"})
                report = await _llm_report(project, command, focus_areas, emitted_issues)

                ax_count = sum(1 for i in emitted_issues if i["category"] == "Accessibility")
                ux_count = sum(1 for i in emitted_issues if i["category"] == "UX")
                rel_count = sum(1 for i in emitted_issues if i["category"] == "Functional")
                a11y_score = int(a11y_result.get("score") or 0)
                summary = {
                    "scores": {
                        "accessibility": a11y_score if a11y_score else max(40, 96 - ax_count * 6),
                        "ux": max(40, 94 - ux_count * 7),
                        "reliability": max(40, 95 - rel_count * 8),
                    },
                    "counts": {
                        "functional": sum(1 for i in emitted_issues if i["category"] == "Functional"),
                        "visual": sum(1 for i in emitted_issues if i["category"] == "Visual"),
                        "accessibility": ax_count,
                        "performance": sum(1 for i in emitted_issues if i["category"] == "Performance"),
                        "ux": ux_count,
                    },
                    "personas": personas,
                    "issues": emitted_issues,
                    "test_cases": emitted_cases,
                    "custom_test_results": custom_case_results,
                    "fuzz_cases": fuzz_cases,
                    "benchmarks": bench_rows,
                    "funnel": {
                        "your_clicks": funnel_result.get("your_clicks"),
                        "industry_avg": funnel_result.get("industry_avg"),
                        "video_url": funnel_result.get("video_url"),
                        "verdict": funnel_result.get("verdict"),
                        "comparison": funnel_result.get("comparison"),
                        "path": funnel_result.get("path"),
                        "funnel_steps": funnel_result.get("funnel_steps"),
                    },
                    "design_theory": design_result,
                    "competitive_diffs": competitive_results,
                    "dopamine": dopamine_result,
                    "copywriting": copywriting_result,
                    "demand_intelligence": demand_result,
                    "accessibility_audit": a11y_result,
                    "command_profile": {"command": command, "label": profile.get("label"), "phases": sorted(profile["phases"])},
                    "test_plan_id": test_plan.get("plan_id") if test_plan else None,
                    "focus_areas": focus_areas,
                    "narrative": narrative,
                    "source": source,
                    "button_actions": button_actions,
                    "page_summaries": page_summaries,
                    "architecture": arch_payload,
                    "app_graph": [
                        {"url": p["url"], "title": p["title"], "slug": p["slug"],
                         "captures": {k: {"ok": v.get("ok"), "url_path": v.get("url_path")} for k, v in p["captures"].items()}}
                        for p in pages
                    ],
                    **report,
                }
                # Craft Score — category system of record + baseline + gate
                baseline_doc = await db.test_runs.find_one(
                    {
                        "project_id": project["project_id"],
                        "status": "completed",
                        "run_id": {"$ne": run_id},
                        "summary.craft_score.overall": {"$exists": True},
                    },
                    {"_id": 0, "run_id": 1, "summary.craft_score": 1},
                    sort=[("completed_at", -1)],
                )
                baseline_craft = None
                if baseline_doc and baseline_doc.get("summary", {}).get("craft_score"):
                    baseline_craft = {
                        **baseline_doc["summary"]["craft_score"],
                        "run_id": baseline_doc["run_id"],
                    }
                gate_threshold = int(
                    project.get("craft_gate_threshold")
                    if project.get("craft_gate_threshold") is not None
                    else DEFAULT_GATE_THRESHOLD
                )
                attach_craft_to_summary(
                    summary,
                    baseline_craft=baseline_craft,
                    gate_threshold=gate_threshold,
                    run_id=run_id,
                )
                await db.projects.update_one(
                    {"project_id": project["project_id"]},
                    {"$set": {
                        "latest_craft_score": summary["craft_score"],
                        "latest_craft_gate": summary["craft_gate"],
                        "latest_craft_run_id": run_id,
                        "latest_craft_at": summary["craft_score"].get("computed_at"),
                    }},
                )
                await db.test_runs.update_one(
                    {"run_id": run_id},
                    {"$set": {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "summary": summary,
                    }},
                )
                await _emit(run_id, seq, "summary", summary)
                await _emit(run_id, seq, "craft_score", {
                    **summary["craft_score"],
                    "gate": summary["craft_gate"],
                    "baseline": summary["craft_baseline"],
                })
                await _publish(run_id, {"__type": "done", "status": "completed"})
            finally:
                if repo_ctx is not None:
                    try:
                        await repo_ctx.__aexit__(None, None, None)
                    except Exception:  # noqa: BLE001
                        pass
                await browser.close()

    except Exception as exc:  # noqa: BLE001
        logger.exception("Run failed: %s", exc)
        await _emit(run_id, seq, "log", {"level": "error", "message": f"Run aborted: {exc}"})
        await db.test_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed", "completed_at": datetime.now(timezone.utc).isoformat()}},
        )
        await _publish(run_id, {"__type": "done", "status": "failed"})


# ----------------------------------------------------------------------------
# Apply patches as PRs against the user's GitHub repo
# ----------------------------------------------------------------------------


class ApplyPatchBody(BaseModel):
    kind: str                       # "issue" | "alt" | "architecture"
    issue_id: Optional[str] = None  # for kind in ("issue", "alt")
    alt_index: Optional[int] = None # for kind == "alt"
    suggestion_id: Optional[str] = None  # for kind == "architecture"
    base_branch: Optional[str] = None


def _find_issue(summary: dict[str, Any], issue_id: str) -> Optional[dict[str, Any]]:
    for i in summary.get("issues") or []:
        if i.get("id") == issue_id:
            return i
    return None


def _find_arch_suggestion(summary: dict[str, Any], suggestion_id: str) -> Optional[dict[str, Any]]:
    arch = summary.get("architecture") or {}
    for s in arch.get("suggestions") or []:
        if s.get("id") == suggestion_id:
            return s
    return None


# ────────────────────────────────────────────────────────────────────────
# Chaos Lab — architecture live stress + crash test (+ payment probes)
# ────────────────────────────────────────────────────────────────────────

from swarm_api import SwarmConfigBody, SwarmResultsResponse, ShipReportResponse


class ChaosStartBody(BaseModel):
    scope: str = "app"                 # app | pages
    pages: Optional[list[str]] = None  # paths or absolute URLs
    mode: str = "fixed"                # fixed | crash
    users: int = 50                    # fixed concurrency OR crash start
    max_users: int = 400               # crash ceiling
    step_factor: float = 2.0
    hold_secs: float = 10.0
    include_payments: bool = False
    payment_provider: str = "stripe"
    break_success_rate: float = 0.85
    break_p95_ms: float = 5000.0


class ChaosTargetsBody(BaseModel):
    scope: str = "pages"  # app | pages
    pages: list[str] = Field(default_factory=list)
    include_payments: bool = False
    source: str = "ide"  # ide | ui


class SwarmStartBody(BaseModel):
    """Legacy — maps into Chaos Lab fixed mode."""
    target_users: int = 50
    profile: str = "burst"
    journey: str = "generic"
    duration_secs: int = 30


async def _resolve_chaos_pages(project: dict[str, Any], body_pages: Optional[list[str]], scope: str, user_id: str) -> list[str]:
    if scope == "pages" and body_pages:
        return body_pages
    # Prefer IDE-saved targets
    saved = await db.chaos_targets.find_one({"project_id": project["project_id"]}, {"_id": 0})
    if scope == "pages" and saved and saved.get("pages"):
        return list(saved["pages"])
    if saved and saved.get("scope") == "pages" and saved.get("pages") and not body_pages:
        return list(saved["pages"])
    # Fall back to last run app_graph
    last = await db.test_runs.find_one(
        {"project_id": project["project_id"], "status": "completed"},
        {"_id": 0, "summary.app_graph": 1},
        sort=[("completed_at", -1)],
    )
    graph_pages = []
    if last:
        for p in (last.get("summary") or {}).get("app_graph") or []:
            if p.get("url"):
                graph_pages.append(p["url"])
    if scope == "app":
        return graph_pages[:12] or [project.get("url") or "/"]
    return body_pages or graph_pages[:8] or [project.get("url") or "/"]


@api.put("/projects/{project_id}/chaos/targets")
async def set_chaos_targets(project_id: str, body: ChaosTargetsBody, user: User = Depends(current_user)):
    """IDE / UI: select entire app or specific pages for Chaos Lab."""
    await require_project_for_user(db, project_id, user.user_id, permission="runs:start")
    doc = {
        "project_id": project_id,
        "user_id": user.user_id,
        "scope": body.scope if body.scope in {"app", "pages"} else "pages",
        "pages": body.pages or [],
        "include_payments": body.include_payments,
        "source": body.source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chaos_targets.update_one({"project_id": project_id}, {"$set": doc}, upsert=True)
    return doc


@api.get("/projects/{project_id}/chaos/targets")
async def get_chaos_targets(project_id: str, user: User = Depends(current_user)):
    await require_project_for_user(db, project_id, user.user_id, permission="runs:read")
    doc = await db.chaos_targets.find_one({"project_id": project_id}, {"_id": 0})
    return doc or {"project_id": project_id, "scope": "app", "pages": [], "include_payments": False}


@api.post("/runs/{run_id}/chaos/start")
async def start_chaos(run_id: str, body: ChaosStartBody, user: User = Depends(current_user)):
    """Start architecture-aware Chaos Lab (fixed load or crash-test ramp)."""
    from chaos_lab import run_chaos_lab

    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:start")
    project = await db.projects.find_one({"project_id": run["project_id"]}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = body.mode if body.mode in {"fixed", "crash"} else "fixed"
    scope = body.scope if body.scope in {"app", "pages"} else "app"
    pages = await _resolve_chaos_pages(project, body.pages, scope, user.user_id)
    users = max(1, min(int(body.users), 500))
    max_users = max(users, min(int(body.max_users), 2000))
    hold = max(3.0, min(float(body.hold_secs), 60.0))

    seed = {
        "status": "running",
        "mode": mode,
        "scope": scope,
        "pages": pages,
        "users": users,
        "max_users": max_users,
        "include_payments": body.include_payments,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.test_runs.update_one(
        {"run_id": run_id},
        {"$set": {"chaos_summary": seed, "swarm_summary": {**seed, "legacy_alias": True}}},
    )

    async def _go():
        ide = await get_ide_context(db, user.user_id) or {}

        async def on_progress(ev: dict[str, Any]) -> None:
            kind = ev.get("type") or "chaos"
            payload = {k: v for k, v in ev.items() if k != "type"}
            payload.update({
                "run_id": run_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": "chaos_event",
                "event": kind,
            })
            await db.run_events.insert_one(dict(payload))
            await _publish(run_id, {k: v for k, v in payload.items() if k != "_id"})
            # Mirror key milestones onto swarm_summary for older UI
            if kind in {"chaos_metrics", "chaos_stage", "chaos_completed"}:
                patch = {"chaos_summary.live": payload}
                if kind == "chaos_completed":
                    patch = {}
                if patch:
                    try:
                        await db.test_runs.update_one({"run_id": run_id}, {"$set": patch})
                    except Exception:  # noqa: BLE001
                        pass

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
                )
                try:
                    summary = await run_chaos_lab(
                        browser,
                        base_url=project.get("url") or pages[0],
                        pages=pages,
                        scope=scope,
                        mode=mode,
                        users=users,
                        max_users=max_users,
                        step_factor=float(body.step_factor),
                        hold_secs=hold,
                        include_payments=bool(body.include_payments),
                        payment_provider=body.payment_provider,
                        break_success_rate=float(body.break_success_rate),
                        break_p95_ms=float(body.break_p95_ms),
                        ide_files=ide.get("files") or [],
                        on_progress=on_progress,
                    )
                    await db.test_runs.update_one(
                        {"run_id": run_id},
                        {"$set": {
                            "chaos_summary": summary,
                            "swarm_summary": {
                                **summary,
                                "target_users": users,
                                "success_rate": summary.get("success_rate"),
                                "latency_p95_ms": summary.get("latency_p95_ms"),
                                "breaking_point_users": summary.get("breaking_point_users"),
                                "status": "completed",
                            },
                            "payment_summary": summary.get("payment_summary"),
                        }},
                    )
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chaos lab failed: %s", exc)
            fail = {"status": "failed", "error": str(exc)[:400]}
            await db.test_runs.update_one(
                {"run_id": run_id},
                {"$set": {"chaos_summary": fail, "swarm_summary": fail}},
            )
            await on_progress({"type": "chaos_failed", **fail})

    asyncio.create_task(_go())
    return {"ok": True, "run_id": run_id, "mode": mode, "scope": scope, "pages": pages}


@api.get("/runs/{run_id}/chaos/live")
async def get_chaos_live(run_id: str, user: User = Depends(current_user)):
    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:read")
    events = await db.run_events.find(
        {"run_id": run_id, "kind": "chaos_event"},
        {"_id": 0},
    ).sort("ts", -1).to_list(80)
    return {
        "summary": run.get("chaos_summary") or {},
        "events": list(reversed(events)),
    }


@api.post("/runs/{run_id}/swarm/start")
async def start_swarm(run_id: str, body: SwarmStartBody, user: User = Depends(current_user)):
    """Legacy alias → Chaos Lab fixed mode."""
    chaos = ChaosStartBody(
        scope="app",
        mode="crash" if body.profile == "ramp" else "fixed",
        users=body.target_users,
        max_users=max(body.target_users * 4, 200) if body.profile == "ramp" else body.target_users,
        hold_secs=float(body.duration_secs),
        include_payments=body.journey == "finance",
    )
    return await start_chaos(run_id, chaos, user)


# ============================================================================
# Payment sandbox — finance app testing (now routes into Chaos Lab)
# ============================================================================


class PaymentSimulateBody(BaseModel):
    provider: str = "stripe"           # stripe | razorpay | paypal
    concurrent: int = 25               # how many parallel payment attempts
    outcomes: list[str] = ["success", "decline_insufficient_funds", "fraud", "3ds_required"]
    amount_cents: int = 4999
    pages: Optional[list[str]] = None  # optional payment/checkout pages


# Aliases mapping the UI's outcome strings → PaymentOutcome enum members.
# This lets the API accept user-friendly outcome names without forcing the UI
# to learn the lower-level enum vocabulary.
_PAYMENT_OUTCOME_ALIASES: dict[str, str] = {
    "success": "success",
    "decline": "decline",
    "decline_insufficient_funds": "insufficient_funds",
    "insufficient_funds": "insufficient_funds",
    "decline_lost_card": "decline",
    "decline_expired_card": "expired_card",
    "expired_card": "expired_card",
    "incorrect_cvc": "incorrect_cvc",
    "processing_error": "processing_error",
    "timeout": "timeout",
    "network_timeout": "timeout",
    "network_failure": "network_failure",
    "rate_limited": "rate_limited",
    "duplicate": "duplicate_charge",
    "duplicate_charge": "duplicate_charge",
    # Outcomes the underlying enum doesn't model — synthesize them from
    # 'decline' so we still produce a sensible non-success result.
    "fraud": "decline",
    "3ds_required": "decline",
    "threeds_required": "decline",
}


@api.post("/runs/{run_id}/payment/simulate")
async def simulate_payments(run_id: str, body: PaymentSimulateBody, user: User = Depends(current_user)):
    """Payment stress → Chaos Lab with live payment field probes (no sleep theater)."""
    pages = body.pages
    if not pages:
        # Prefer checkout-looking pages from last graph
        run = await require_run_for_user(db, run_id, user.user_id, permission="runs:start")
        graph = (run.get("summary") or {}).get("app_graph") or []
        pages = [
            p["url"] for p in graph
            if p.get("url") and any(k in p["url"].lower() for k in ("pay", "checkout", "billing", "cart"))
        ] or None
    chaos = ChaosStartBody(
        scope="pages" if pages else "app",
        pages=pages,
        mode="crash" if body.concurrent >= 100 else "fixed",
        users=max(10, min(body.concurrent, 200)),
        max_users=max(body.concurrent * 2, 200),
        hold_secs=12,
        include_payments=True,
        payment_provider=body.provider,
    )
    result = await start_chaos(run_id, chaos, user)
    return {**result, "routed_to": "chaos_lab", "include_payments": True}


@api.get("/runs/{run_id}/payment/results")
async def get_payment_results(run_id: str, user: User = Depends(current_user)):
    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:read")
    chaos = run.get("chaos_summary") or {}
    return {
        "summary": run.get("payment_summary") or chaos.get("payment_summary") or {},
        "results": run.get("payment_results") or [],
        "chaos": chaos,
    }


@api.get("/runs/{run_id}/swarm/live")
async def get_swarm_live(run_id: str, user: User = Depends(current_user)):
    """Poll live swarm progress for the UI."""
    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:read")
    events = await db.run_events.find(
        {"run_id": run_id, "kind": "swarm_event"},
        {"_id": 0},
    ).sort("ts", -1).to_list(200)
    return {
        "summary": run.get("swarm_summary") or {},
        "events": list(reversed(events)),
    }


@api.post("/runs/{run_id}/swarm/config")
async def configure_swarm_test(run_id: str, config: SwarmConfigBody, user: User = Depends(current_user)):
    """Configure swarm load testing parameters."""
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Store swarm configuration
    await db.test_runs.update_one(
        {"run_id": run_id},
        {"$set": {"swarm_config": config.dict()}},
    )
    
    return {"status": "configured", "config": config.dict()}


@api.get("/runs/{run_id}/swarm/results")
async def get_swarm_results(run_id: str, user: User = Depends(current_user)):
    """Get swarm test results and metrics."""
    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:read")

    # Collect swarm test events from database
    events = await db.run_events.find(
        {"run_id": run_id, "kind": {"$in": ["load_test_event", "swarm_metric"]}},
        {"_id": 0}
    ).to_list(None)

    summary = run.get("swarm_summary", {})

    return {
        "test_id": run_id,
        "status": summary.get("status", "pending"),
        "events": events,
        "summary": summary,
    }


@api.post("/runs/{run_id}/swarm/ship-report")
async def generate_ship_report(run_id: str, user: User = Depends(current_user)):
    """Generate business-focused Ship Report from swarm + audit results."""
    from ship_report import ShipReportGenerator

    run = await require_run_for_user(db, run_id, user.user_id, permission="runs:read")
    
    summary = run.get("summary", {})
    swarm_summary = run.get("swarm_summary", {})
    
    # Extract relevant metrics
    load_metrics = {
        "success_rate": swarm_summary.get("success_rate", 0.0),
        "error_rate": swarm_summary.get("error_rate", 0.0),
        "latency_p95": swarm_summary.get("latency_p95_ms", 0.0),
        "target_users": swarm_summary.get("target_users", 0),
        "breaking_point_users": swarm_summary.get("breaking_point_users"),
        "revenue_impact_dollars": swarm_summary.get("revenue_risk_per_hour", 0.0),
    }
    
    accessibility_issues = [
        i for i in summary.get("issues", [])
        if i.get("category") == "Accessibility"
    ]
    
    payment_test_results = swarm_summary.get("payment_results", {})
    
    # Generate report
    generator = ShipReportGenerator(app_name=run.get("project_id", "Unknown"))
    report = generator.generate_from_load_test(
        load_metrics=load_metrics,
        accessibility_issues=accessibility_issues,
        payment_test_results=payment_test_results,
    )
    
    return {
        "readiness": report.readiness.value,
        "confidence_score": report.confidence_score,
        "executive_summary": report.executive_summary,
        "can_users_use_it": report.can_users_use_it,
        "can_disabled_users_use_it": report.can_disabled_users_use_it,
        "can_handle_peak_users": report.can_handle_peak_users,
        "are_payments_working": report.are_payments_working,
        "checkout_abandonment_risk": report.checkout_abandonment_risk,
        "top_3_issues": report.top_3_issues,
        "launch_blockers": report.launch_blockers,
        "recommendations": report.recommendations,
        "metrics": {
            "success_rate": report.success_rate,
            "error_rate": report.error_rate,
            "latency_p95_ms": report.latency_p95_ms,
            "breaking_point_users": report.breaking_point_users,
        },
    }


@api.post("/runs/{run_id}/apply")
async def apply_patch_to_repo(run_id: str, body: ApplyPatchBody, user: User = Depends(current_user)):
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    summary = run.get("summary") or {}

    proj = await db.projects.find_one({"project_id": run["project_id"]}, {"_id": 0})
    if not proj or proj.get("source") != "github" or not proj.get("github_owner") or not proj.get("github_repo"):
        raise HTTPException(status_code=400, detail="This run isn't connected to a GitHub repository. Add the repo when creating the project to enable Apply.")

    secret = await db.project_secrets.find_one({"project_id": proj["project_id"]}, {"_id": 0})
    token = (secret or {}).get("github_token")
    if not token:
        raise HTTPException(status_code=400, detail="No GitHub token on file for this project — cannot open a PR.")

    repo_full = f"{proj['github_owner']}/{proj['github_repo']}"
    base_branch = body.base_branch or "main"

    if body.kind == "issue":
        if not body.issue_id:
            raise HTTPException(status_code=400, detail="issue_id required")
        issue = _find_issue(summary, body.issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found in this run")
        patch = PatchSpec(
            kind="css_patch",
            title=issue.get("title", "fix"),
            body=issue.get("after", {}).get("detail", "") or issue.get("cause", ""),
            css=issue.get("after", {}).get("code", ""),
        )
    elif body.kind == "alt":
        if not body.issue_id or body.alt_index is None:
            raise HTTPException(status_code=400, detail="issue_id and alt_index required")
        issue = _find_issue(summary, body.issue_id)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        alts = issue.get("alternatives") or []
        if body.alt_index < 0 or body.alt_index >= len(alts):
            raise HTTPException(status_code=400, detail="alt_index out of range")
        alt = alts[body.alt_index]
        patch = PatchSpec(
            kind="css_patch",
            title=f"{issue.get('title', 'fix')} ({alt.get('label', 'alternative')})",
            body=alt.get("summary", "") + (f" — Trade-off: {alt['tradeoff']}" if alt.get("tradeoff") else ""),
            css=alt.get("patch_css", ""),
        )
    elif body.kind == "architecture":
        if not body.suggestion_id:
            raise HTTPException(status_code=400, detail="suggestion_id required")
        sugg = _find_arch_suggestion(summary, body.suggestion_id)
        if not sugg:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if sugg.get("patch_kind") == "manual":
            raise HTTPException(status_code=400, detail="This suggestion requires manual implementation; no auto-PR available.")
        files = sugg.get("files") or []
        if not files:
            raise HTTPException(status_code=400, detail="Suggestion has no target file path.")
        patch = PatchSpec(
            kind=sugg.get("patch_kind", "file_create"),
            title=sugg.get("title", "architecture change"),
            body=sugg.get("patch_body") or "",
            file_path=files[0],
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown kind: {body.kind}")

    try:
        result = await asyncio.to_thread(
            open_pull_request,
            repo_full,
            token=token,
            patch=patch,
            base_branch=base_branch,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("PR creation failed: %s", exc)
        # Surface a more useful diagnostic to the UI.
        err_text = str(exc)
        hint = ""
        low = err_text.lower()
        if "401" in low or "bad credentials" in low:
            hint = " Tip: the stored GitHub token is invalid or expired. Use the Test connection button to re-validate it."
        elif "403" in low and "rate" in low:
            hint = " Tip: GitHub rate-limited the token; try again in a minute."
        elif "403" in low:
            hint = " Tip: the token lacks `repo` write access on this repository, or your org hasn't approved the PAT."
        elif "404" in low:
            hint = " Tip: the token cannot see this repo. For org-owned repos, the org must approve the PAT."
        elif "422" in low and "branch" in low:
            hint = " Tip: a branch with that name already exists — Atmos retries with a numeric suffix; try again."
        raise HTTPException(status_code=502, detail=f"Could not open PR: {err_text}.{hint}")

    await db.applied_patches.insert_one({
        "run_id": run_id,
        "user_id": user.user_id,
        "kind": body.kind,
        "issue_id": body.issue_id,
        "alt_index": body.alt_index,
        "suggestion_id": body.suggestion_id,
        "pr_url": result["url"],
        "pr_number": result["number"],
        "branch": result["branch"],
        "applied_at": datetime.now(timezone.utc).isoformat(),
    })
    return result


# ----------------------------------------------------------------------------
# RBAC — Team roles & permissions
# ----------------------------------------------------------------------------


class RolePermissionsUpdate(BaseModel):
    permissions: list[str]


class MemberInvite(BaseModel):
    email: str
    role: str = "viewer"


class MemberRoleUpdate(BaseModel):
    role: str


@api.get("/team")
async def get_team(user: User = Depends(current_user)):
    await ensure_org_for_user(db, user.user_id, user.email, user.name)
    member = await get_member(db, user.user_id)
    if not member:
        raise HTTPException(status_code=404, detail="No team")
    org = await db.organizations.find_one({"org_id": member["org_id"]}, {"_id": 0})
    members = await db.org_members.find({"org_id": member["org_id"]}, {"_id": 0}).to_list(100)
    roles = await db.role_permissions.find({"org_id": member["org_id"]}, {"_id": 0}).to_list(20)
    _, perms = await get_user_permissions(db, user.user_id)
    return {
        "org": org,
        "members": members,
        "roles": roles,
        "permissions_catalog": ALL_PERMISSIONS,
        "builtin_roles": BUILTIN_ROLES,
        "your_role": member.get("role"),
        "your_permissions": sorted(perms),
    }


@api.put("/team/roles/{role_id}")
async def update_role_permissions(role_id: str, body: RolePermissionsUpdate, user: User = Depends(current_user)):
    await require_permission(db, user.user_id, "roles:manage")
    member = await get_member(db, user.user_id)
    if role_id not in BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    perms = [p for p in body.permissions if p in {x["id"] for x in ALL_PERMISSIONS}]
    if role_id == "admin" and "roles:manage" not in perms:
        perms.append("roles:manage")
    await db.role_permissions.update_one(
        {"org_id": member["org_id"], "role_id": role_id},
        {"$set": {
            "permissions": sorted(set(perms)),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": user.user_id,
        }},
        upsert=True,
    )
    return {"ok": True, "role_id": role_id, "permissions": sorted(set(perms))}


@api.post("/team/members")
async def invite_member(body: MemberInvite, user: User = Depends(current_user)):
    await require_permission(db, user.user_id, "members:write")
    member = await get_member(db, user.user_id)
    if body.role not in BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    existing_user = await db.users.find_one({"email": body.email.strip().lower()}, {"_id": 0})
    invitee_id = existing_user["user_id"] if existing_user else f"pending_{uuid.uuid4().hex[:10]}"
    await db.org_members.update_one(
        {"org_id": member["org_id"], "email": body.email.strip().lower()},
        {"$set": {
            "org_id": member["org_id"],
            "user_id": invitee_id,
            "email": body.email.strip().lower(),
            "role": body.role,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "invited_by": user.user_id,
        }},
        upsert=True,
    )
    return {"ok": True, "email": body.email, "role": body.role}


@api.patch("/team/members/{target_user_id}")
async def update_member_role(target_user_id: str, body: MemberRoleUpdate, user: User = Depends(current_user)):
    await require_permission(db, user.user_id, "members:write")
    member = await get_member(db, user.user_id)
    if body.role not in BUILTIN_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    org = await db.organizations.find_one({"org_id": member["org_id"]}, {"_id": 0})
    if target_user_id == org.get("owner_user_id") and body.role != "admin":
