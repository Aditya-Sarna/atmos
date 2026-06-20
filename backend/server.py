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

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

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
    common = [
        {"category": "Visual", "severity": "high", "title": "Primary CTA overlaps footer on iPhone SE",
         "file": "components/Footer.tsx", "cause": "Flex container overflow at <380px"},
        {"category": "Accessibility", "severity": "critical", "title": "Sign-in form inputs missing aria-label",
         "file": "pages/auth/SignIn.tsx", "cause": "Missing accessible name on email/password fields"},
        {"category": "UX", "severity": "medium", "title": "8 clicks to reach primary action",
         "file": "router.tsx", "cause": "Deep nav hierarchy; entry point hidden under menu"},
        {"category": "Visual", "severity": "low", "title": "Focus ring invisible on dark surfaces",
         "file": "styles/focus.css", "cause": "outline color matches background-color"},
        {"category": "Functional", "severity": "high", "title": "Empty state crashes on stale cache",
         "file": "hooks/useProjects.ts", "cause": "Unhandled null on first paint"},
        {"category": "Performance", "severity": "medium", "title": "Hero image at 2.4 MB blocks LCP",
         "file": "public/hero.png", "cause": "Unoptimized asset, no responsive srcSet"},
    ]
    specific = {
        "finance": [
            {"category": "Functional", "severity": "critical", "title": "Currency precision loss at >$9,999.99",
             "file": "lib/money.ts", "cause": "Number.parseFloat rounds at boundary"},
            {"category": "UX", "severity": "high", "title": "Transaction error #405 shown verbatim to user",
             "file": "components/PaymentError.tsx", "cause": "Backend code surfaced without translation"},
        ],
        "e-commerce": [
            {"category": "UX", "severity": "high", "title": "Checkout flow requires 7 clicks (industry: 4)",
             "file": "pages/Checkout.tsx", "cause": "Address & shipping forced into separate steps"},
            {"category": "Functional", "severity": "medium", "title": "Coupon stacking allows negative totals",
             "file": "lib/coupons.ts", "cause": "Missing floor at zero in discount reducer"},
        ],
        "calendar": [
            {"category": "Functional", "severity": "high", "title": "DST transition double-books recurring event",
             "file": "lib/recurrence.ts", "cause": "Naive datetime arithmetic across DST"},
            {"category": "Visual", "severity": "medium", "title": "Long event titles clip without ellipsis",
             "file": "components/EventCard.tsx", "cause": "overflow:visible on grid cell"},
        ],
        "dashboard": [
            {"category": "Performance", "severity": "high", "title": "Large datasets freeze main thread at 10k rows",
             "file": "components/DataGrid.tsx", "cause": "No virtualization; full re-render on filter"},
            {"category": "UX", "severity": "medium", "title": "24 cards on first paint creates cognitive overload",
             "file": "pages/Overview.tsx", "cause": "Unprioritized layout, no hero metric"},
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
    seq = {"n": 0}
    try:
        plan = await _llm_plan(project, command)
        focus_areas: list[str] = plan.get("focus_areas") or []
        narrative: str = plan.get("narrative") or ""
        app_type = project.get("app_type") or "generic"

        await _emit(run_id, seq, "log", {
            "level": "info",
            "message": f"Atmos {command} → {project['name']} ({app_type})",
        })
        await asyncio.sleep(0.35)
        await _emit(run_id, seq, "log", {"level": "info", "message": narrative})
        await asyncio.sleep(0.35)
        await _emit(run_id, seq, "plan", {"focus_areas": focus_areas})
        await asyncio.sleep(0.4)

        await _emit(run_id, seq, "phase", {"phase": "analyze", "label": "Project Understanding"})
        for line in [
            "Detecting frontend framework…",
            "Mapping routes & components…",
            "Building application graph…",
            f"App archetype: {app_type}",
        ]:
            await asyncio.sleep(0.3)
            await _emit(run_id, seq, "log", {"level": "info", "message": line})

        await _emit(run_id, seq, "phase", {"phase": "explore", "label": "Autonomous UI Exploration"})
        actions = [
            ("click", "Primary CTA"),
            ("hover", "Top nav → Settings"),
            ("input", "Search field"),
            ("keyboard", "Tab order through form"),
            ("drag", "Reorder list item"),
            ("long-press", "Context menu"),
        ]
        for a, t in actions:
            await asyncio.sleep(0.4)
            await _emit(run_id, seq, "screenshot", {
                "action": a, "target": t, "viewport": "Desktop 1440",
                "caption": f"{a.title()} on {t}",
            })

        await _emit(run_id, seq, "phase", {"phase": "mobile", "label": "Responsive Sweep"})
        for vp in random.sample(VIEWPORTS, k=6):
            await asyncio.sleep(0.25)
            await _emit(run_id, seq, "viewport", {
                "viewport": vp["label"], "w": vp["w"], "h": vp["h"],
                "status": random.choice(["ok", "ok", "ok", "warn", "ok"]),
            })

        await _emit(run_id, seq, "phase", {"phase": "accessibility", "label": "Accessibility Audit"})
        for line in [
            "Computing WCAG contrast ratios…",
            "Auditing ARIA semantics…",
            "Simulating screen reader pass…",
            "Checking keyboard focus order…",
        ]:
            await asyncio.sleep(0.3)
            await _emit(run_id, seq, "log", {"level": "info", "message": line})

        await _emit(run_id, seq, "phase", {"phase": "personas", "label": "Human Persona Simulation"})
        personas = _persona_scores(app_type)
        for p in personas:
            await asyncio.sleep(0.3)
            await _emit(run_id, seq, "persona", p)

        await _emit(run_id, seq, "phase", {"phase": "issues", "label": "Root-Cause Analysis"})
        issues = _seed_issues(app_type)
        emitted_issues = []
        for issue in issues:
            await asyncio.sleep(0.35)
            issue_full = {"id": f"iss_{uuid.uuid4().hex[:8]}", **issue}
            emitted_issues.append(issue_full)
            await _emit(run_id, seq, "issue", issue_full)

        await _emit(run_id, seq, "phase", {"phase": "benchmark", "label": "Competitive Benchmark"})
        bench_targets = BENCHMARKS.get(app_type, BENCHMARKS["generic"])
        bench_rows = []
        for b in bench_targets:
            await asyncio.sleep(0.3)
            row = {
                "competitor": b,
                "clicks_to_primary": random.randint(2, 4),
                "your_clicks": random.randint(5, 9),
                "verdict": "behind",
            }
            bench_rows.append(row)
            await _emit(run_id, seq, "benchmark", row)

        await _emit(run_id, seq, "phase", {"phase": "report", "label": "Executive Report"})
        report = await _llm_report(project, command, focus_areas, issues)

        ax_count = sum(1 for i in issues if i["category"] == "Accessibility")
        ux_count = sum(1 for i in issues if i["category"] == "UX")
        rel_count = sum(1 for i in issues if i["category"] == "Functional")
        summary = {
            "scores": {
                "accessibility": max(40, 96 - ax_count * 6),
                "ux": max(40, 94 - ux_count * 7),
                "reliability": max(40, 95 - rel_count * 8),
            },
            "counts": {
                "functional": sum(1 for i in issues if i["category"] == "Functional"),
                "visual": sum(1 for i in issues if i["category"] == "Visual"),
                "accessibility": ax_count,
                "performance": sum(1 for i in issues if i["category"] == "Performance"),
                "ux": ux_count,
            },
            "personas": personas,
            "issues": emitted_issues,
            "benchmarks": bench_rows,
            "focus_areas": focus_areas,
            "narrative": narrative,
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

    except Exception as exc:  # noqa: BLE001
        logger.exception("Run failed: %s", exc)
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
