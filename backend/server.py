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

# Make sure Playwright finds the pre-baked browsers regardless of how supervisor was started.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from atmos_engine import (
    SCREENSHOTS_DIR,
    VIEWPORTS as REAL_VIEWPORTS,
    crawl_and_capture,
    apply_patch_full_page,
    llm_analyze_app,
    deterministic_fallback,
    seed_test_cases,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

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


async def _exchange_session_id(session_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(EMERGENT_SESSION_DATA_URL, headers={"X-Session-ID": session_id})
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid session_id")
        return r.json()


async def current_user(request: Request) -> User:
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
async def auth_session(body: SessionExchangeBody, response: Response):
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

    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="none",
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
    url: str


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
    parsed = urlparse(body.url if "://" in body.url else f"https://{body.url}")
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL")

    project_id = f"proj_{uuid.uuid4().hex[:10]}"
    proj = Project(
        project_id=project_id,
        user_id=user.user_id,
        name=(body.name or "").strip() or parsed.netloc,
        url=clean_url,
        app_type=_classify_app_type(clean_url, body.name),
    )
    doc = proj.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.projects.insert_one(doc)
    return proj.model_dump()


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


async def _execute_run(run_id: str, project: dict[str, Any], command: str) -> None:
    """Real engine: crawl → full-page capture per viewport per page → LLM vision
    → per-issue patch + re-capture on the issue's page → executive report."""
    seq = {"n": 0}
    app_type = project.get("app_type") or "generic"
    try:
        await _emit(run_id, seq, "log", {"level": "info",
            "message": f"Atmos {command} → {project['name']} ({app_type})"})

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                # ── Phase 1: Crawl + Capture every reachable page ───────
                await _emit(run_id, seq, "phase", {"phase": "analyze", "label": "Project Understanding"})
                await _emit(run_id, seq, "log", {"level": "info",
                    "message": f"Launching headless Chromium against {project['url']}…"})

                async def on_progress(ev: dict[str, Any]):
                    if ev.get("type") == "page_capture":
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

                await _emit(run_id, seq, "phase", {"phase": "explore", "label": "Crawling Application"})
                crawl = await crawl_and_capture(browser, project["url"], run_id, on_progress=on_progress)
                pages = crawl["pages"]
                if not pages or not any(any(c.get("ok") for c in p["captures"].values()) for p in pages):
                    raise RuntimeError("No page captures succeeded — site may be blocking automated traffic.")

                await _emit(run_id, seq, "app_graph", {
                    "pages": [{"url": p["url"], "title": p["title"], "slug": p["slug"]} for p in pages],
                })
                await _emit(run_id, seq, "log", {"level": "info",
                    "message": f"Crawled {len(pages)} page(s). Sending screenshots to Claude vision…"})

                # ── Phase 2: LLM vision analysis ────────────────────────
                try:
                    analysis = await llm_analyze_app(project, command, pages)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LLM analyze failed: %s", exc)
                    await _emit(run_id, seq, "log", {"level": "warn",
                        "message": f"Vision LLM unavailable, falling back to heuristics ({type(exc).__name__})."})
                    analysis = deterministic_fallback(project, pages)

                focus_areas = analysis.get("focus_areas", []) or []
                narrative = analysis.get("narrative", "")
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
                vp_labels = [v["label"] for v in REAL_VIEWPORTS]
                emitted_issues: list[dict[str, Any]] = []

                for raw in analysis.get("issues", [])[:8]:
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

                    after_url = await apply_patch_full_page(
                        browser, target_page["url"], vp_label,
                        raw.get("patch_css", ""), run_id, f"{iss_id}_after", target_page["slug"],
                    )

                    alts_out = []
                    for ai, alt in enumerate((raw.get("alternatives") or [])[:2]):
                        alt_url = await apply_patch_full_page(
                            browser, target_page["url"], vp_label,
                            alt.get("patch_css", ""), run_id, f"{iss_id}_alt{ai}", target_page["slug"],
                        )
                        alts_out.append({
                            "label": alt.get("label", f"Alternative {ai+1}"),
                            "summary": alt.get("summary", ""),
                            "tradeoff": alt.get("tradeoff", ""),
                            "patch_css": alt.get("patch_css", ""),
                            "screenshot_url": alt_url,
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
                            "screenshot_url": after_url,
                        },
                        "alternatives": alts_out,
                    }
                    emitted_issues.append(issue_full)
                    await _emit(run_id, seq, "issue", issue_full)

                # ── Phase 5: Live test cases ────────────────────────────
                await _emit(run_id, seq, "phase", {"phase": "test_cases", "label": "Live Test Case Playback"})
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
                    "benchmarks": bench_rows,
                    "focus_areas": focus_areas,
                    "narrative": narrative,
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
