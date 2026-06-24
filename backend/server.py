"""Atmos — Autonomous Product Testing & UX Intelligence Agent
FastAPI backend.

- Emergent Auth (Google) — session cookies, /api/auth/*
- Claude Sonnet 4.5 via emergentintegrations.LlmChat — context-aware test plans
- Projects + Test Runs with simulated, observable real-time execution streamed
  via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
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
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

def _ensure_playwright_browsers() -> None:
    """Auto-install chromium if the binary expected by the current Playwright is missing."""
    import logging as _logging
    import subprocess
    _log = _logging.getLogger("atmos.playwright_bootstrap")

    browsers_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers"))
    candidate_dirs = list(browsers_dir.glob("chromium_headless_shell-*")) + list(browsers_dir.glob("chromium-*"))
    has_binary = any((d / "chrome-linux" / "headless_shell").exists() for d in candidate_dirs)
    if has_binary:
        return
    _log.warning("Playwright chromium binary missing under %s; running `playwright install chromium`…", browsers_dir)
    try:
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers_dir)}
        subprocess.run(["playwright", "install", "chromium"], check=True, env=env, timeout=300)
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

configure_playwright_browsers()

# ----------------------------------------------------------------------------
# Mongo
# ----------------------------------------------------------------------------

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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one(
        {
            "user_id": user_id,
            "session_token": session_token,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    cookie_secure_env = os.environ.get("ATMOS_COOKIE_SECURE", "auto").strip().lower()
    host = (request.url.hostname or "").lower()
    if cookie_secure_env in {"1", "true", "yes"}:
        cookie_secure = True
    elif cookie_secure_env in {"0", "false", "no"}:
        cookie_secure = False
    else:
        # Local HTTP dev cannot persist Secure cookies.
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
    return {"user_id": user_id, "email": email, "name": name, "picture": picture}


@api.get("/auth/me")
async def auth_me(user: User = Depends(current_user)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
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
    cur = db.projects.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1)
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
    proj = await db.projects.find_one({"project_id": project_id, "user_id": user.user_id}, {"_id": 0})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    runs = await db.test_runs.find({"project_id": project_id}, {"_id": 0}).sort("started_at", -1).to_list(50)
    return {"project": proj, "runs": runs}


class RunCreate(BaseModel):
    command: str = "/atmos test"


VALID_COMMANDS = {
    "/atmos analyze", "/atmos explore", "/atmos test", "/atmos regress", "/atmos mobile",
    "/atmos benchmark", "/atmos accessibility", "/atmos personas", "/atmos record", "/atmos report",
}


@api.post("/projects/{project_id}/runs")
async def start_run(project_id: str, body: RunCreate, user: User = Depends(current_user)):
    proj = await db.projects.find_one({"project_id": project_id, "user_id": user.user_id}, {"_id": 0})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    command = body.command.strip()
    if command not in VALID_COMMANDS:
        raise HTTPException(status_code=400, detail="Unknown command")

    run_id = f"run_{uuid.uuid4().hex[:10]}"
    run = TestRun(
        run_id=run_id,
        project_id=project_id,
        user_id=user.user_id,
        command=command,
        status="running",
    )
    doc = run.model_dump()
    doc["started_at"] = doc["started_at"].isoformat()
    await db.test_runs.insert_one(doc)

    asyncio.create_task(_execute_run(run_id, proj, command))
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
    # EventSource cannot set custom headers, so auth via cookie only here.
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": session["user_id"]}, {"_id": 0})
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
        from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # type: ignore

        chat = LlmChat(
            api_key=os.environ["EMERGENT_LLM_KEY"],
            session_id=f"plan_{project['project_id']}_{uuid.uuid4().hex[:6]}",
            system_message=(
                "You are Atmos, an autonomous UX testing agent. Given a target application, "
                "produce a tight JSON plan with keys: narrative (1-sentence intro), "
                "focus_areas (5-8 short strings naming concrete UX surfaces or risks to probe). "
                "Be specific to the product context. Respond with ONLY JSON, no prose."
            ),
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        msg = UserMessage(
            text=(
                f"Target: {project['name']} at {project['url']}\n"
                f"Detected app type: {project['app_type']}\n"
                f"Command: {command}\n"
                "Return JSON only."
            )
        )
        text = ""
        async for ev in chat.stream_message(msg):
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
        logger.warning("LLM plan failed: %s", exc)
        return {
            "narrative": f"Probing {project['name']} for {project['app_type']} risks.",
            "focus_areas": [
                "Primary navigation discoverability",
                "Form input validation",
                "Touch target sizing",
                "Color contrast and focus states",
                "Empty / error states",
                "Mobile viewport behavior",
            ],
        }


async def _llm_report(project: dict[str, Any], command: str, focus_areas: list[str], issues: list[dict]) -> dict[str, Any]:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # type: ignore

        chat = LlmChat(
            api_key=os.environ["EMERGENT_LLM_KEY"],
            session_id=f"report_{project['project_id']}_{uuid.uuid4().hex[:6]}",
            system_message=(
                "You are Atmos, producing an executive testing report. Return JSON ONLY with keys: "
                "critical_findings (array of 3-5 short sentences), recommendations (array of 5 imperative sentences, each <=15 words), "
                "competitive_insight (1-2 sentences benchmarking vs industry leaders)."
            ),
        ).with_model("anthropic", "claude-sonnet-4-5-20250929")
        prompt = (
            f"Target: {project['name']} ({project['url']})\n"
            f"App type: {project['app_type']}\n"
            f"Command: {command}\n"
            f"Focus areas probed: {focus_areas}\n"
            f"Issues found: {json.dumps(issues[:20])}\n"
            "Return JSON only."
        )
        text = ""
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
        logger.warning("LLM report failed: %s", exc)
        return {
            "critical_findings": [
                "Senior users struggle with onboarding.",
                "Checkout abandonment risk is high.",
                "Screen reader support is incomplete.",
            ],
            "recommendations": [
                "Increase touch target size.",
                "Simplify navigation hierarchy.",
                "Improve accessibility labels.",
                "Reduce checkout friction.",
                "Improve error messaging.",
            ],
            "competitive_insight": "Lagging Stripe and Apple on conversion-clarity by roughly 30%.",
        }


def _seed_issues(app_type: str) -> list[dict[str, Any]]:
    """Each issue carries a render-spec the frontend uses to visualize the problem,
    Atmos's executed fix, and two alternative fixes.

    Schema:
        category, severity, title, file, cause,
        scene: identifier the frontend renders ("cta-overlap", "aria-form", "deep-nav",
                "focus-ring", "empty-crash", "image-lcp", "currency-precision",
                "deep-checkout", "calendar-clip", "dst-doublebook", "grid-freeze",
                "card-overload", "error-jargon", "coupon-negative"),
        before: { headline, detail },
        after:  { headline, detail, code? },
        alternatives: [ { label, summary, tradeoff, scene_variant }, ... ]
    """
    def alts(*items):
        return list(items)

    common = [
        {
            "category": "Visual", "severity": "high",
            "title": "Primary CTA overlaps footer on iPhone SE",
            "file": "components/Footer.tsx",
            "cause": "Flex container overflow at <380px viewport.",
            "scene": "cta-overlap",
            "before": {"headline": "Tap target collides with footer",
                       "detail": "Pay button overlaps copyright text at 375×667. Users tap the wrong target ~14% of attempts."},
            "after": {"headline": "Stacked column at <420px",
                      "detail": "Footer drops below the CTA via flex-wrap and a sticky safe-area inset.",
                      "code": "footer{flex-wrap:wrap; padding-bottom:env(safe-area-inset-bottom);}"},
            "alternatives": alts(
                {"label": "Sticky bottom-sheet CTA", "scene_variant": "sticky",
                 "summary": "Pin the primary CTA to the bottom in a translucent bar; footer scrolls under it.",
                 "tradeoff": "Loses 56px of content height. Best for high-conversion checkout pages."},
                {"label": "Move footer to settings drawer", "scene_variant": "drawer",
                 "summary": "Demote legal/links into a profile drawer; footer disappears below the fold.",
                 "tradeoff": "Reduces footer discoverability — only suitable when legal links are duplicated elsewhere."},
            ),
        },
        {
            "category": "Accessibility", "severity": "critical",
            "title": "Sign-in form inputs missing aria-label",
            "file": "pages/auth/SignIn.tsx",
            "cause": "Inputs identified only by placeholder text — invisible to screen readers.",
            "scene": "aria-form",
            "before": {"headline": "Screen reader announces \"edit, edit\"",
                       "detail": "Email & password fields rely on placeholder; NVDA / VoiceOver have no accessible name."},
            "after": {"headline": "Persistent labels above each field",
                      "detail": "Visible <label> elements bound by htmlFor + aria-describedby for error messages.",
                      "code": "<label htmlFor=\"email\">Email</label><input id=\"email\" aria-describedby=\"email-err\"/>"},
            "alternatives": alts(
                {"label": "Floating labels", "scene_variant": "float",
                 "summary": "Material-style floating labels animate up when the field is focused.",
                 "tradeoff": "Trickier to localize and clipped at 200% zoom — but feels more compact."},
                {"label": "Inline icon + aria-label", "scene_variant": "icon",
                 "summary": "Keep the icon-only look; add aria-label=\"Email address\" to each input.",
                 "tradeoff": "Visible UI unchanged but visual users lose the help that labels provide."},
            ),
        },
        {
            "category": "UX", "severity": "medium",
            "title": "8 clicks to reach primary action",
            "file": "router.tsx",
            "cause": "Deep nav hierarchy; the primary action is hidden under a hamburger.",
            "scene": "deep-nav",
            "before": {"headline": "8 hops to start the main task",
                       "detail": "Hamburger → menu → submenu → tab → list → row → modal → CTA."},
            "after": {"headline": "Global primary action in the header",
                      "detail": "Expose the primary verb as a persistent button next to the search bar.",
                      "code": "<Header><PrimaryAction/></Header>  // visible on every page"},
            "alternatives": alts(
                {"label": "Command palette (⌘K)", "scene_variant": "palette",
                 "summary": "Add a ⌘K palette so power users can fire any action with one keystroke.",
                 "tradeoff": "Adds shortcut discoverability load — pair with an onboarding tooltip."},
                {"label": "Persistent left-rail with 5 actions", "scene_variant": "rail",
                 "summary": "Surface the 5 most-used verbs as a left rail visible on every page.",
                 "tradeoff": "Steals ~64px of horizontal real estate; great for dashboards."},
            ),
        },
        {
            "category": "Visual", "severity": "low",
            "title": "Focus ring invisible on dark surfaces",
            "file": "styles/focus.css",
            "cause": "outline color near-matches background; <2:1 contrast on dark elements.",
            "scene": "focus-ring",
            "before": {"headline": "Keyboard users get lost",
                       "detail": "outline: 1px solid rgba(255,255,255,0.05) on dark surfaces — invisible."},
            "after": {"headline": "WCAG-compliant focus ring",
                      "detail": "2px solid Brand Blue + 2px white offset — visible on any surface.",
                      "code": ":focus-visible{outline:2px solid #0071E3; outline-offset:2px;}"},
            "alternatives": alts(
                {"label": "Inset focus glow", "scene_variant": "glow",
                 "summary": "box-shadow inset glow rather than outline — works inside overflow:hidden parents.",
                 "tradeoff": "Slightly heavier visually; great for cards with rounded corners."},
                {"label": "Background tint on focus", "scene_variant": "tint",
                 "summary": "Tint the element background 10% on focus instead of an outline.",
                 "tradeoff": "Calmer but less explicit — pair with outline for AAA."},
            ),
        },
        {
            "category": "Functional", "severity": "high",
            "title": "Empty state crashes on stale cache",
            "file": "hooks/useProjects.ts",
            "cause": "Null projects array dereferenced before first paint.",
            "scene": "empty-crash",
            "before": {"headline": "White screen of death",
                       "detail": "TypeError: Cannot read properties of null (reading 'length')."},
            "after": {"headline": "Graceful empty state",
                      "detail": "Optional chaining + skeleton on undefined, illustrated empty state on [].",
                      "code": "const list = data?.projects ?? [];\nif (!list.length) return <EmptyState/>;"},
            "alternatives": alts(
                {"label": "Optimistic seed state", "scene_variant": "seed",
                 "summary": "Render an example project card so the UI never feels empty on first load.",
                 "tradeoff": "Adds tutorial-style content; can confuse repeat users."},
                {"label": "Error boundary + retry", "scene_variant": "retry",
                 "summary": "Wrap the route in an error boundary with a Retry button.",
                 "tradeoff": "Less elegant but catches every runtime error in the subtree."},
            ),
        },
        {
            "category": "Performance", "severity": "medium",
            "title": "Hero image at 2.4 MB blocks LCP",
            "file": "public/hero.png",
            "cause": "Unoptimized asset, no responsive srcSet, no AVIF/WebP.",
            "scene": "image-lcp",
            "before": {"headline": "LCP 4.8s on 4G",
                       "detail": "Single 2.4 MB PNG served to every device. No width hints."},
            "after": {"headline": "LCP 1.1s",
                      "detail": "AVIF + WebP fallback, srcSet at 480/960/1440, fetchpriority=high.",
                      "code": "<img srcSet=\"hero-480.avif 480w, hero-960.avif 960w\" fetchpriority=\"high\"/>"},
            "alternatives": alts(
                {"label": "CSS gradient hero", "scene_variant": "gradient",
                 "summary": "Replace image with a tuned CSS gradient — 0 KB hero.",
                 "tradeoff": "Loses product photography; suits brand/marketing pages."},
                {"label": "Lazy hero with LQIP", "scene_variant": "lqip",
                 "summary": "Inline a 12-byte LQIP placeholder, lazy-load the full hero below the fold.",
                 "tradeoff": "Quick flash from blur → sharp; pair with prefers-reduced-motion."},
            ),
        },
    ]
    specific = {
        "finance": [
            {
                "category": "Functional", "severity": "critical",
                "title": "Currency precision loss at >$9,999.99",
                "file": "lib/money.ts",
                "cause": "Number.parseFloat drops trailing precision past 4 integer digits.",
                "scene": "currency-precision",
                "before": {"headline": "$9,999.99 → $10,000",
                           "detail": "Float math silently rounds. A $9,999.99 invoice is paid as $10,000."},
                "after": {"headline": "Exact decimal arithmetic",
                          "detail": "Use bigint cents or dinero.js. Never store money as Number.",
                          "code": "import Dinero from 'dinero.js'; Dinero({amount: 999999, currency:'USD'})"},
                "alternatives": alts(
                    {"label": "Server-side authoritative totals", "scene_variant": "server",
                     "summary": "Move the math to the server; client just renders. No JS Number math anywhere.",
                     "tradeoff": "Roundtrip on every line-item edit; needs optimistic UI."},
                    {"label": "Decimal.js across the stack", "scene_variant": "decimal",
                     "summary": "Use Decimal.js end-to-end; richer API than Dinero, slightly larger bundle.",
                     "tradeoff": "+12 KB bundle but cleaner ergonomics for tax & fee math."},
                ),
            },
            {
                "category": "UX", "severity": "high",
                "title": "Transaction error #405 shown verbatim",
                "file": "components/PaymentError.tsx",
                "cause": "Raw backend code rendered to the user without translation.",
                "scene": "error-jargon",
                "before": {"headline": "\"Error #405\"",
                           "detail": "User has no idea if money moved. Support tickets spike at checkout."},
                "after": {"headline": "Plain-English assurance",
                          "detail": "\"Your payment couldn't be processed. No funds were deducted. Please try again.\"",
                          "code": "<Alert>Your payment couldn't be processed.<br/>No funds were deducted.</Alert>"},
                "alternatives": alts(
                    {"label": "Show next-best action", "scene_variant": "action",
                     "summary": "After the apology, offer \"Try a different card\" and \"Pay later\" buttons.",
                     "tradeoff": "Adds 2 buttons — needs UX writing review."},
                    {"label": "Live-chat hand-off", "scene_variant": "chat",
                     "summary": "Embed support chat opening with the error context pre-filled.",
                     "tradeoff": "Requires staffed support; great for high-AOV flows."},
                ),
            },
        ],
        "e-commerce": [
            {
                "category": "UX", "severity": "high",
                "title": "Checkout requires 7 clicks (industry: 4)",
                "file": "pages/Checkout.tsx",
                "cause": "Address & shipping forced into separate steps.",
                "scene": "deep-checkout",
                "before": {"headline": "7-step checkout funnel",
                           "detail": "Cart → Address → Shipping → Billing → Review → Confirm → Pay."},
                "after": {"headline": "Single-page checkout",
                          "detail": "One scrollable page with progressive disclosure of payment.",
                          "code": "<CheckoutOnePage sections={[Address,Shipping,Payment]} />"},
                "alternatives": alts(
                    {"label": "Express checkout (Apple/Google Pay)", "scene_variant": "express",
                     "summary": "Offer Apple Pay / Google Pay above the form — 0-click checkout for returning users.",
                     "tradeoff": "Requires merchant approval; massive conversion lift on mobile."},
                    {"label": "Two-step (auth + pay)", "scene_variant": "two",
                     "summary": "Email first → auto-resume cart on the next page with everything pre-filled.",
                     "tradeoff": "Adds 1 click vs single-page but lets you email cart-abandoners."},
                ),
            },
            {
                "category": "Functional", "severity": "medium",
                "title": "Coupon stacking allows negative totals",
                "file": "lib/coupons.ts",
                "cause": "Missing floor at zero in discount reducer.",
                "scene": "empty-crash",
                "before": {"headline": "Total: -$3.20",
                           "detail": "Two 50% codes stack; order completes at a negative total."},
                "after": {"headline": "Total clamped at $0.00",
                          "detail": "discount reducer wrapped in Math.max(0, …) and limited to one promo code per cart.",
                          "code": "const total = Math.max(0, subtotal - discount);"},
                "alternatives": alts(
                    {"label": "Cap discount at 90%", "scene_variant": "cap",
                     "summary": "Hard-cap any cart-level discount at 90% so merchants still capture revenue.",
                     "tradeoff": "Some marketing campaigns rely on >90% — flag those explicitly."},
                    {"label": "Single-coupon policy", "scene_variant": "single",
                     "summary": "Only one promo code may apply at a time; offer the bigger one automatically.",
                     "tradeoff": "Simpler math, less hacking — annoys couponers."},
                ),
            },
        ],
        "calendar": [
            {
                "category": "Functional", "severity": "high",
                "title": "DST transition double-books recurring event",
                "file": "lib/recurrence.ts",
                "cause": "Naive datetime arithmetic across DST.",
                "scene": "dst-doublebook",
                "before": {"headline": "Two events at 9 AM on Mar 12",
                           "detail": "Recurring weekly event materializes twice on DST day."},
                "after": {"headline": "TZ-anchored RRULE expansion",
                          "detail": "Use ical.js with the user's IANA tz; UTC arithmetic only.",
                          "code": "RRULE:FREQ=WEEKLY;BYDAY=MO  // expand in user's IANA tz"},
                "alternatives": alts(
                    {"label": "Store float-time + tz separately", "scene_variant": "floattz",
                     "summary": "Persist (wall_clock_time, tz) pairs; render from there.",
                     "tradeoff": "More columns but trivially correct around DST."},
                    {"label": "Switch to Temporal API polyfill", "scene_variant": "temporal",
                     "summary": "Adopt the TC39 Temporal proposal via polyfill — eliminates the class of bug.",
                     "tradeoff": "+18 KB polyfill; future-proof once Temporal ships natively."},
                ),
            },
            {
                "category": "Visual", "severity": "medium",
                "title": "Long event titles clip without ellipsis",
                "file": "components/EventCard.tsx",
                "cause": "overflow:visible on grid cell.",
                "scene": "calendar-clip",
                "before": {"headline": "Title spills across columns",
                           "detail": "\"Quarterly business review with…\" bleeds into next event."},
                "after": {"headline": "Truncate with tooltip",
                          "detail": "white-space:nowrap; overflow:hidden; text-overflow:ellipsis; <Tooltip/>",
                          "code": ".event-title{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"},
                "alternatives": alts(
                    {"label": "Two-line clamp", "scene_variant": "clamp",
                     "summary": "Allow up to 2 lines with -webkit-line-clamp before truncating.",
                     "tradeoff": "Better readability on tall events, useless on 30-min slots."},
                    {"label": "Hover-to-expand pop-out", "scene_variant": "popout",
                     "summary": "Expand the card on hover with full content + actions.",
                     "tradeoff": "Adds motion; conflicts with drag-to-resize."},
                ),
            },
        ],
        "dashboard": [
            {
                "category": "Performance", "severity": "high",
                "title": "Large datasets freeze main thread at 10k rows",
                "file": "components/DataGrid.tsx",
                "cause": "No virtualization; full re-render on filter.",
                "scene": "grid-freeze",
                "before": {"headline": "UI freezes for 6s",
                           "detail": "Filtering 10k rows blocks the main thread; the page is non-interactive."},
                "after": {"headline": "Virtualized + debounced filter",
                          "detail": "Render only visible window with TanStack Virtual; debounce filter input.",
                          "code": "useVirtualizer({count: rows.length, estimateSize:()=>40})"},
                "alternatives": alts(
                    {"label": "Server-side pagination", "scene_variant": "server",
                     "summary": "Fetch 50 rows at a time; filter is a backend query.",
                     "tradeoff": "Removes the freeze entirely but loses instant sort/search."},
                    {"label": "Web Worker for filter", "scene_variant": "worker",
                     "summary": "Move filtering into a Web Worker; main thread stays responsive.",
                     "tradeoff": "Slight latency vs in-thread, but UI never blocks."},
                ),
            },
            {
                "category": "UX", "severity": "medium",
                "title": "24 cards on first paint creates cognitive overload",
                "file": "pages/Overview.tsx",
                "cause": "Unprioritized layout, no hero metric.",
                "scene": "card-overload",
                "before": {"headline": "24 equal-weight cards",
                           "detail": "Every metric screams for attention. First-time users bounce 38%."},
                "after": {"headline": "1 hero + 6 secondary",
                          "detail": "Promote the single most-important metric, demote the rest to small cards.",
                          "code": "<Hero metric={topMetric}/><Grid cols={3}>{secondary.slice(0,6)}</Grid>"},
                "alternatives": alts(
                    {"label": "Bento grid with size weighting", "scene_variant": "bento",
                     "summary": "Use a 12-col asymmetric bento; large = critical, small = passive.",
                     "tradeoff": "Striking but harder to extend with new metrics."},
                    {"label": "Tabs by audience", "scene_variant": "tabs",
                     "summary": "Split into \"For me\" / \"Team\" / \"Org\" tabs; each shows 6 cards.",
                     "tradeoff": "Adds a click but reduces per-screen density."},
                ),
            },
        ],
        "generic": [],
    }
    return common + specific.get(app_type, [])


def _test_cases(app_type: str) -> list[dict[str, Any]]:
    """Each test case is performed live on the mock UI with playback frames.

    Schema: id, name, category, steps (array), status, evidence_frames (animation spec).
    """
    common = [
        {
            "name": "Navigation discoverability — primary action reachable in ≤3 clicks",
            "category": "UX", "scene": "deep-nav",
            "steps": ["Land on home", "Search for primary verb", "Tap CTA", "Confirm action panel opens"],
            "expected_result": "fail",  # we expect deep nav to fail this
            "explanation": "Primary action took 8 clicks. Threshold: 3.",
        },
        {
            "name": "Keyboard-only form completion (TAB through sign-in)",
            "category": "Accessibility", "scene": "aria-form",
            "steps": ["Focus first field", "Type email", "Tab", "Type password", "Tab to Sign in", "Press Enter"],
            "expected_result": "fail",
            "explanation": "Inputs lack accessible names. Screen reader reports \"edit, edit\".",
        },
        {
            "name": "Color contrast — every text/background pair ≥ 4.5:1",
            "category": "Accessibility", "scene": "focus-ring",
            "steps": ["Sample every text node", "Compute relative luminance", "Diff ratio"],
            "expected_result": "warn",
            "explanation": "3 pairs at 3.1:1 — below WCAG AA but above AA-Large.",
        },
        {
            "name": "Touch target — every interactive ≥ 44×44 CSS px",
            "category": "Accessibility", "scene": "cta-overlap",
            "steps": ["Enumerate clickables", "Measure bounding boxes", "Flag <44px"],
            "expected_result": "fail",
            "explanation": "Footer link cluster at 24×24 px on iPhone SE.",
        },
        {
            "name": "Responsive sweep — no horizontal scroll at any tested viewport",
            "category": "Visual", "scene": "cta-overlap",
            "steps": ["Resize to 344px", "Resize to 375px", "Resize to 768px", "Resize to 1440px"],
            "expected_result": "pass",
            "explanation": "No overflow detected at any tested viewport.",
        },
        {
            "name": "Empty state — no first-paint crash",
            "category": "Functional", "scene": "empty-crash",
            "steps": ["Clear cache", "Reload route", "Assert no console error", "Assert empty UI rendered"],
            "expected_result": "fail",
            "explanation": "TypeError on first paint when projects=[].",
        },
        {
            "name": "Performance — Largest Contentful Paint < 2.5s on 4G",
            "category": "Performance", "scene": "image-lcp",
            "steps": ["Throttle network to 4G", "Cold-load home", "Measure LCP"],
            "expected_result": "fail",
            "explanation": "LCP measured at 4.8s. Threshold: 2.5s.",
        },
    ]
    specific = {
        "finance": [
            {
                "name": "Currency math — amounts at $9,999.99 boundary preserve precision",
                "category": "Functional", "scene": "currency-precision",
                "steps": ["Enter $9,999.99", "Submit", "Read confirmation total"],
                "expected_result": "fail",
                "explanation": "Confirmation shows $10,000.00 — drift of $0.01 violated.",
            },
            {
                "name": "Error UX — surface plain-English message, never error codes",
                "category": "UX", "scene": "error-jargon",
                "steps": ["Force 405 from API", "Render error UI", "Read text"],
                "expected_result": "fail",
                "explanation": "User sees \"Error #405\" verbatim.",
            },
        ],
        "e-commerce": [
            {
                "name": "Checkout — buyer completes in ≤4 clicks from cart",
                "category": "UX", "scene": "deep-checkout",
                "steps": ["Open cart", "Tap checkout", "Fill address", "Pay"],
                "expected_result": "fail",
                "explanation": "Measured 7 clicks. Threshold: 4.",
            },
            {
                "name": "Coupons — total never goes negative",
                "category": "Functional", "scene": "empty-crash",
                "steps": ["Apply 50% code", "Apply second 50% code", "Read total"],
                "expected_result": "fail",
                "explanation": "Observed total: -$3.20.",
            },
        ],
        "calendar": [
            {
                "name": "Recurrence — weekly event during DST day shows once",
                "category": "Functional", "scene": "dst-doublebook",
                "steps": ["Create weekly Mon 9 AM event", "Jump to DST week", "Count occurrences on that day"],
                "expected_result": "fail",
                "explanation": "Two occurrences on DST day, expected one.",
            },
            {
                "name": "Event title — long titles truncate cleanly",
                "category": "Visual", "scene": "calendar-clip",
                "steps": ["Create 80-char title", "Render in 30-min slot"],
                "expected_result": "fail",
                "explanation": "Title bleeds across the next column.",
            },
        ],
        "dashboard": [
            {
                "name": "Data grid — filter 10k rows stays interactive (input → render < 200ms)",
                "category": "Performance", "scene": "grid-freeze",
                "steps": ["Load 10k rows", "Type into filter", "Measure to next paint"],
                "expected_result": "fail",
                "explanation": "Main thread blocked ~6s; UI unresponsive.",
            },
            {
                "name": "Information density — hero metric identifiable in 3 seconds",
                "category": "UX", "scene": "card-overload",
                "steps": ["Eye-track new user for 3s", "Ask: what's the most important number?"],
                "expected_result": "fail",
                "explanation": "0/5 users identified a single hero metric.",
            },
        ],
        "generic": [],
    }
    return common + specific.get(app_type, [])


def _persona_scores(app_type: str) -> list[dict[str, Any]]:
    base = {
        "elderly": 72, "blind": 68, "low_vision": 70,
        "color_blind": 84, "first_time": 76, "power_user": 88, "child": 74,
    }
    if app_type == "finance":
        base["blind"] -= 6
        base["first_time"] -= 8
    if app_type == "e-commerce":
        base["first_time"] -= 4
        base["color_blind"] -= 6
    if app_type == "calendar":
        base["elderly"] -= 5
    if app_type == "dashboard":
        base["power_user"] += 4
        base["elderly"] -= 8
    rows = []
    for p in PERSONAS:
        rows.append({
            "id": p["id"], "label": p["label"], "focus": p["focus"],
            "score": max(40, min(98, base[p["id"]] + random.randint(-3, 3))),
        })
    return rows


async def _emit(run_id: str, seq_holder: dict, kind: str, payload: dict[str, Any]) -> None:
    seq_holder["n"] += 1
    event = {
        "run_id": run_id,
        "seq": seq_holder["n"],
        "kind": kind,
        "ts": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    await db.run_events.insert_one(dict(event))
    event.pop("_id", None)
    await _publish(run_id, event)


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


async def _execute_run(run_id: str, project: dict[str, Any], command: str) -> None:
    """Real engine: optionally boot a GitHub repo → crawl + click buttons →
    per-page LLM vision → patch & re-capture → fuzz form fields → architecture
    analysis → executive report. Emits live JPEG frames the UI consumes as a stream."""
    seq = {"n": 0}
    app_type = project.get("app_type") or "generic"
    source = project.get("source") or "url"
    try:
        await _emit(run_id, seq, "log", {"level": "info",
            "message": f"Atmos {command} → {project['name']} ({app_type}) via {source}"})

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
                try:
                    flow = await explore_app_flow(
                        browser,
                        target_url,
                        run_id,
                        on_progress=on_progress,
                        max_duration_secs=max(30, EXPLORE_TIMEOUT_SECS - 10),
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

                # ── Phase 2: Per-page LLM vision analysis (parallel batched) ──
                await _emit(run_id, seq, "phase", {"phase": "per_page", "label": "Per-Page Vision Analysis"})
                aggregated_issues: list[dict[str, Any]] = []
                page_summaries: list[dict[str, Any]] = []
                vp_labels = [v["label"] for v in REAL_VIEWPORTS]

                # Bound concurrency so we don't blast the LLM provider.
                ANALYSIS_CONCURRENCY = int(os.environ.get("ATMOS_PAGE_ANALYSIS_CONCURRENCY", "4"))
                PER_PAGE_TIMEOUT = int(os.environ.get("ATMOS_PER_PAGE_TIMEOUT_SECS", "75"))
                sem = asyncio.Semaphore(ANALYSIS_CONCURRENCY)

                async def _analyze_one(p: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                    async with sem:
                        try:
                            res = await asyncio.wait_for(llm_analyze_page(project, p), timeout=PER_PAGE_TIMEOUT)
                            return p, res
                        except asyncio.TimeoutError:
                            logger.warning("per-page analysis TIMED OUT for %s after %ds", p["url"], PER_PAGE_TIMEOUT)
                            return p, {"page_summary": "", "issues": []}
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("per-page analysis failed for %s: %s", p["url"], exc)
                            return p, {"page_summary": "", "issues": []}

                analyses = await asyncio.gather(*[_analyze_one(pg) for pg in pages])

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
                        holistic = await llm_analyze_app(project, command, pages)
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

                # ── Phase 3: Accessibility log + Personas ───────────────
                await _emit(run_id, seq, "phase", {"phase": "accessibility", "label": "Accessibility Audit"})
                for line in [
                    "Sampling computed styles for contrast ratios…",
                    "Auditing ARIA semantics & landmarks…",
                    "Walking the keyboard tab order…",
                ]:
                    await asyncio.sleep(0.25)
                    await _emit(run_id, seq, "log", {"level": "info", "message": line})

                await _emit(run_id, seq, "phase", {"phase": "personas", "label": "Human Persona Simulation"})
                personas = _persona_scores(app_type)
                for p in personas:
                    await asyncio.sleep(0.12)
                    await _emit(run_id, seq, "persona", p)

                # ── Phase 4: Issues — patch & re-capture full pages ─────
                await _emit(run_id, seq, "phase", {"phase": "issues", "label": "Executed Fixes"})
                pages_by_url = {p["url"]: p for p in pages}
                emitted_issues: list[dict[str, Any]] = []

                for raw in aggregated_issues[:12]:
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

                # ── Phase 5: Fuzz / boundary input test cases ───────────
                await _emit(run_id, seq, "phase", {"phase": "fuzz", "label": "Boundary Input Fuzzing"})
                fuzz_cases: list[dict[str, Any]] = []
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
                if flow_screens:
                    await _emit(run_id, seq, "phase", {"phase": "screen_tests", "label": "Per-Screen Test Cases"})
                    await _emit(run_id, seq, "log", {"level": "info",
                        "message": f"Generating elaborate test cases for {len(flow_screens)} screen(s); recording a video per case."})
                    try:
                        screen_test_results = await generate_and_run_screen_tests(
                            browser, flow_screens, run_id, project, on_progress=on_progress,
                        )
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Ran {len(screen_test_results)} per-screen test case(s) with video."})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("screen tests failed: %s", exc)

                # ── Phase 6: Architecture analysis (GitHub repo OR URL runtime) ─
                arch_payload: Optional[dict[str, Any]] = None
                if source == "github" and repo_root is not None:
                    await _emit(run_id, seq, "phase", {"phase": "architecture", "label": "Architecture Analysis"})
                    try:
                        arch_payload = await analyze_repo(repo_root, project["name"], app_type)
                        await _emit(run_id, seq, "architecture", arch_payload)
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Architecture score: {arch_payload['score']['overall']}/100 · {len(arch_payload['suggestions'])} suggestions"})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("arch analysis failed: %s", exc)
                elif pages:
                    # URL-mode runtime audit — no source code, but we can still
                    # observe the live surface and benchmark against industry peers.
                    await _emit(run_id, seq, "phase", {"phase": "architecture", "label": "Architecture Analysis (URL mode)"})
                    try:
                        arch_payload = await analyze_url_run(pages, project["name"], app_type, project["url"])
                        await _emit(run_id, seq, "architecture", arch_payload)
                        await _emit(run_id, seq, "log", {"level": "info",
                            "message": f"Architecture score (URL mode): {arch_payload['score']['overall']}/100 · {len(arch_payload['suggestions'])} suggestions"})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("URL-mode arch analysis failed: %s", exc)

                # ── Phase 7: Test cases derived from actual pages ───────
                await _emit(run_id, seq, "phase", {"phase": "test_cases", "label": "Live Test Case Playback"})
                # For GitHub repos generate cases from actual routes + button actions.
                # For URL runs use the page-specific seed function.
                if source == "github" and pages:
                    cases = _github_test_cases(pages, button_actions)
                else:
                    cases = seed_test_cases(app_type, pages)
                emitted_cases = []
                for raw in cases:
                    case_id = f"tc_{uuid.uuid4().hex[:8]}"
                    tc = {
                        "id": case_id,
                        "name": raw["name"],
                        "category": raw["category"],
                        "steps": raw["steps"],
                        "status": "running",
                        "current_step": 0,
                        "expected_result": raw["expected_result"],
                        "explanation": raw["explanation"],
                        "frames": raw.get("frames", []),
                    }
                    emitted_cases.append(tc)
                    await _emit(run_id, seq, "test_case", {**tc, "phase": "start"})
                    for idx, step in enumerate(raw["steps"]):
                        await asyncio.sleep(0.35)
                        frame = (raw.get("frames") or [None])[min(idx, len(raw.get("frames") or []) - 1)] if raw.get("frames") else None
                        await _emit(run_id, seq, "test_case_step", {
                            "case_id": case_id, "step_index": idx, "step": step,
                            "viewport": "Desktop 1440",
                            "frame": frame,
                        })
                    tc["status"] = raw["expected_result"]
                    await _emit(run_id, seq, "test_case", {**tc, "phase": "end", "explanation": raw["explanation"]})

                # ── Phase 6: Benchmark + Report ─────────────────────────
                await _emit(run_id, seq, "phase", {"phase": "benchmark", "label": "Competitive Benchmark"})
                bench_targets = BENCHMARKS.get(app_type, BENCHMARKS["generic"])
                bench_rows = []
                for b in bench_targets:
                    await asyncio.sleep(0.12)
                    row = {
                        "competitor": b,
                        "clicks_to_primary": random.randint(2, 4),
                        "your_clicks": random.randint(5, 9),
                        "verdict": "behind",
                    }
                    bench_rows.append(row)
                    await _emit(run_id, seq, "benchmark", row)

                await _emit(run_id, seq, "phase", {"phase": "report", "label": "Executive Report"})
                report = await _llm_report(project, command, focus_areas, emitted_issues)

                ax_count = sum(1 for i in emitted_issues if i["category"] == "Accessibility")
                ux_count = sum(1 for i in emitted_issues if i["category"] == "UX")
                rel_count = sum(1 for i in emitted_issues if i["category"] == "Functional")
                summary = {
                    "scores": {
                        "accessibility": max(40, 96 - ax_count * 6),
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
                    "fuzz_cases": fuzz_cases,
                    "benchmarks": bench_rows,
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
                await db.test_runs.update_one(
                    {"run_id": run_id},
                    {"$set": {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "summary": summary,
                    }},
                )
                await _emit(run_id, seq, "summary", summary)
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
# Swarm Testing Endpoints
# ────────────────────────────────────────────────────────────────────────

from swarm_api import SwarmConfigBody, SwarmResultsResponse, ShipReportResponse


class SwarmStartBody(BaseModel):
    target_users: int = 50            # 10/50/100/250/500/1000
    profile: str = "burst"            # burst | ramp | soak
    journey: str = "generic"          # generic | ecommerce | finance | saas
    duration_secs: int = 30


@api.post("/runs/{run_id}/swarm/start")
async def start_swarm(run_id: str, body: SwarmStartBody, user: User = Depends(current_user)):
    """Kick off a real Playwright user swarm against the project's target URL.

    Spawns N concurrent virtual users that walk a journey on the live site, then
    persists the aggregated metrics (success rate, p95 latency, breaking point,
    revenue risk) on the run document for the Swarm tab to render.
    """
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    project = await db.projects.find_one({"project_id": run["project_id"]}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_users = max(1, min(int(body.target_users), 500))
    duration = max(5, min(int(body.duration_secs), 120))

    await db.test_runs.update_one(
        {"run_id": run_id},
        {"$set": {"swarm_summary": {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                                    "target_users": target_users, "profile": body.profile,
                                    "journey": body.journey, "duration_secs": duration}}},
    )

    async def _go():
        from load_simulator import LoadSimulator
        from dataclasses import asdict
        from enum import Enum

        captured_video_url: dict[str, Optional[str]] = {"url": None}

        def _coerce(value):
            """Recursively convert enums (LoadProfile, UserMode, …) to their .value so BSON can store them."""
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, dict):
                return {k: _coerce(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_coerce(v) for v in value]
            return value

        async def emit(kind: str, payload: dict):
            payload = _coerce(dict(payload or {}))
            payload["run_id"] = run_id
            payload["ts"] = datetime.now(timezone.utc).isoformat()
            payload["kind"] = "swarm_event"
            payload["event"] = kind
            # Capture the recorded video URL from the first virtual user, if any.
            if kind == "user_session_video" and payload.get("video_url") and not captured_video_url["url"]:
                captured_video_url["url"] = payload["video_url"]
            await db.run_events.insert_one(dict(payload))
            await _publish(run_id, {k: v for k, v in payload.items() if k != "_id"})

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
                try:
                    sim = LoadSimulator(
                        browser=browser, base_url=project["url"], run_id=run_id,
                        event_emitter=lambda payload: asyncio.create_task(emit(payload.get("kind", "swarm"), payload)) if isinstance(payload, dict) else None,
                    )
                    await emit("swarm_started", {"target_users": target_users, "profile": body.profile, "journey": body.journey})
                    metrics = await sim.run_burst_test(
                        target_users=target_users,
                        journey_template=body.journey,
                        duration_secs=duration,
                    )
                    md = asdict(metrics) if hasattr(metrics, "__dataclass_fields__") else dict(metrics)
                    md = _coerce(md)
                    md["status"] = "completed"
                    md["completed_at"] = datetime.now(timezone.utc).isoformat()
                    md["profile"] = body.profile
                    md["journey"] = body.journey
                    md["target_users"] = target_users
                    if captured_video_url["url"]:
                        md["video_url"] = captured_video_url["url"]
                    await db.test_runs.update_one({"run_id": run_id}, {"$set": {"swarm_summary": md}})
                    await emit("swarm_completed", md)
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Swarm failed: %s", exc)
            await db.test_runs.update_one({"run_id": run_id},
                {"$set": {"swarm_summary": {"status": "failed", "error": str(exc)[:300]}}})
            await emit("swarm_failed", {"error": str(exc)[:300]})

    asyncio.create_task(_go())
    return {"status": "started", "target_users": target_users}


# ============================================================================
# Payment sandbox — finance app testing
# ============================================================================


class PaymentSimulateBody(BaseModel):
    provider: str = "stripe"           # stripe | razorpay | paypal
    concurrent: int = 25               # how many parallel payment attempts
    outcomes: list[str] = ["success", "decline_insufficient_funds", "fraud", "3ds_required"]
    amount_cents: int = 4999


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
    """Generate test payment payloads + simulate concurrent processing.

    Uses TestPaymentGenerator to produce provider-specific test card numbers
    and PaymentSandbox to run them through a (mocked at first, real later)
    settlement path. Emits per-attempt events; returns aggregate metrics.
    """
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    from payment_sandbox import (
        TestPaymentGenerator, PaymentProvider, PaymentOutcome,
    )
    try:
        provider = PaymentProvider(body.provider.lower())
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")

    gen = TestPaymentGenerator(provider)
    requested = max(1, min(body.concurrent, 200))

    # Resolve every requested outcome to its underlying PaymentOutcome member.
    resolved: list[tuple[str, PaymentOutcome]] = []
    unknown: list[str] = []
    for label in body.outcomes or []:
        key = (label or "").strip().lower()
        enum_value = _PAYMENT_OUTCOME_ALIASES.get(key, key)
        try:
            resolved.append((label, PaymentOutcome(enum_value)))
        except ValueError:
            unknown.append(label)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown outcome(s): {unknown}. Allowed: {sorted(_PAYMENT_OUTCOME_ALIASES.keys())}",
        )
    if not resolved:
        # Default to a balanced mix when caller didn't specify any.
        resolved = [
            ("success", PaymentOutcome.SUCCESS),
            ("decline_insufficient_funds", PaymentOutcome.INSUFFICIENT_FUNDS),
            ("expired_card", PaymentOutcome.EXPIRED_CARD),
            ("timeout", PaymentOutcome.TIMEOUT),
        ]

    async def _run_one(idx: int) -> dict:
        label, outcome = resolved[idx % len(resolved)]
        try:
            test_card = gen.generate_test_card(outcome)
        except Exception:  # noqa: BLE001
            test_card = ""
        # Simulate processing latency (provider-dependent).
        await asyncio.sleep(0.2 + (idx % 5) * 0.05)
        is_success = outcome == PaymentOutcome.SUCCESS
        return {
            "idx": idx,
            "provider": provider.value,
            "outcome": label,
            "outcome_enum": outcome.value,
            "amount_cents": body.amount_cents,
            "test_card": (test_card or "")[-4:],
            "result": "success" if is_success else "rejected",
            "reason": None if is_success else outcome.value,
            "latency_ms": int(200 + (idx % 5) * 50),
        }

    try:
        results = await asyncio.gather(*[_run_one(i) for i in range(requested)])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Payment simulation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Payment simulation failed: {exc}")
    success = sum(1 for r in results if r["result"] == "success")
    by_outcome: dict[str, int] = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1

    sorted_latencies = sorted(r["latency_ms"] for r in results)
    p50 = sorted_latencies[len(sorted_latencies) // 2] if sorted_latencies else 0
    p95_idx = max(0, int(len(sorted_latencies) * 0.95) - 1)
    p95 = sorted_latencies[p95_idx] if sorted_latencies else 0
    summary = {
        "provider": provider.value,
        "concurrent": requested,
        "success_count": success,
        "decline_count": requested - success,
        "success_rate": round(success / requested, 4) if requested else 0,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "by_outcome": by_outcome,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    await db.test_runs.update_one(
        {"run_id": run_id},
        {"$set": {"payment_summary": summary, "payment_results": results}},
    )
    return {"summary": summary, "results": results}


@api.get("/runs/{run_id}/payment/results")
async def get_payment_results(run_id: str, user: User = Depends(current_user)):
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "summary": run.get("payment_summary") or {},
        "results": run.get("payment_results") or [],
    }


@api.get("/runs/{run_id}/swarm/live")
async def get_swarm_live(run_id: str, user: User = Depends(current_user)):
    """Poll live swarm progress for the UI."""
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
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
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
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
    
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user.user_id})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
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
# Misc
# ----------------------------------------------------------------------------


@api.get("/")
async def root():
    return {"service": "atmos", "ok": True}


@api.get("/commands")
async def list_commands():
    return [
        {"cmd": "/atmos analyze", "label": "Analyze", "desc": "Build application understanding."},
        {"cmd": "/atmos explore", "label": "Explore", "desc": "Discover user journeys."},
        {"cmd": "/atmos test", "label": "Test", "desc": "Run comprehensive testing."},
        {"cmd": "/atmos regress", "label": "Regress", "desc": "Execute regression suite."},
        {"cmd": "/atmos mobile", "label": "Mobile", "desc": "Test responsive behavior."},
        {"cmd": "/atmos benchmark", "label": "Benchmark", "desc": "Compare to industry leaders."},
        {"cmd": "/atmos accessibility", "label": "Accessibility", "desc": "Audit accessibility."},
        {"cmd": "/atmos personas", "label": "Personas", "desc": "Run human simulation."},
        {"cmd": "/atmos record", "label": "Record", "desc": "Generate narrated video."},
        {"cmd": "/atmos report", "label": "Report", "desc": "Executive testing report."},
    ]


app.include_router(api)

# Serve screenshots from /api/screens (mounted before CORS so headers apply correctly).
app.mount("/api/screens", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screens")
app.mount("/api/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown() -> None:
    client.close()
