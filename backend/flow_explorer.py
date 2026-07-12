"""Agentic, stateful flow explorer with Visual/VLM Gemini 3.5 Flash-style Crawler.

Drives the app like a human using both a highly advanced VLM (Gemini 3.5 Flash-style)
and a robust deterministic single-page BFS fallback.

For every distinct screen reached, it records the exact replayable action path
so the test-case runner can replay any path in a fresh video-recording context.
We capture screenshots at every step and use the VLM to decide the best path.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import json
import time
import uuid
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page

from atmos_engine import (
    SCREENSHOTS_DIR,
    VIEWPORTS,
    NAV_TIMEOUT_MS,
    _new_context,
    _settle,
    _safe_name,
    _enumerate_buttons,
    _click_button_by_text,
)

logger = logging.getLogger("atmos.flow")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_FLOW_STEPS = 80
MAX_HUB_BRANCHES = 30
MAX_SCREENS = 80
SETTLE_MS = 600
DEFAULT_PIN = "135790"
VLM_MAX_ACTIONS_PER_STEP = 6
VLM_STAGNATION_LIMIT = 6

FORWARD_CTAS = [
    "get started", "getting started", "get going", "create wallet",
    "create a wallet", "create new wallet", "create account", "create",
    "continue", "continue anyway", "proceed", "next", "let's go", "lets go",
    "start", "begin", "i agree", "agree", "accept all", "accept", "confirm",
    "verify", "submit", "done", "finish", "complete", "save",
    "skip for now", "skip for demo", "skip", "maybe later", "not now", "later",
    "allow", "enable", "unlock", "got it", "ok", "okay", "yes",
]

NAV_TARGETS = {
    "spin", "scan", "receive", "send", "contacts", "contact", "wallet", "home",
    "swap", "buy", "sell", "earn", "stake", "rewards", "history", "activity",
    "settings", "profile", "cards", "pay", "request", "invite", "explore",
    "discover", "games", "play", "dashboard", "transfer", "deposit", "withdraw",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pathname(url: str) -> str:
    try:
        return urlparse(url).path or "/"
    except Exception:
        return "/"


async def _page_text(page: Page) -> dict[str, Any]:
    try:
        return await page.evaluate(
            """() => {
                const h = (document.querySelector('h1,h2,[role=heading]')?.innerText || '').trim();
                const title = document.title || '';
                const body = (document.body?.innerText || '').replace(/\\s+/g,' ').trim().slice(0,300);
                return { heading: h.slice(0,90), title: title.slice(0,90), body };
            }"""
        )
    except Exception:
        return {"heading": "", "title": "", "body": ""}


async def _signature(page: Page) -> str:
    try:
        data = await page.evaluate(
            """() => {
                const labels = Array.from(document.querySelectorAll(
                    'button,[role=button],a[href],[role=tab],input,textarea,select'
                )).map(e=>(e.innerText||e.getAttribute('aria-label')||e.placeholder||e.name||e.type||'')
                    .trim().toLowerCase()).filter(Boolean).slice(0,40).sort();
                const inputs = document.querySelectorAll('input,textarea,select').length;
                const h = (document.querySelector('h1,h2,[role=heading]')?.innerText||'').trim().toLowerCase().slice(0,60);
                return { labels, inputs, h };
            }"""
        )
    except Exception:
        data = {"labels": [], "inputs": 0, "h": ""}
    raw = f"{_pathname(page.url)}|{data['inputs']}|{data['h']}|{'|'.join(data['labels'])}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


async def _enumerate_inputs(page: Page) -> list[dict[str, Any]]:
    try:
        fields = await page.evaluate(
            """() => {
                const all = Array.from(document.querySelectorAll('input, textarea'));
                const out = [];
                all.forEach((el, idx) => {
                    if (['hidden','submit','button','file'].includes(el.type)) return;
                    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') return;
                    const label = (
                        (el.id && document.querySelector(`label[for="${el.id}"]`)?.innerText) ||
                        el.closest('label')?.innerText ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('placeholder') || ''
                    ).trim();
                    let selector = '';
                    if (el.name) selector = `[name="${el.name}"]`;
                    else if (el.id) selector = `#${CSS.escape(el.id)}`;
                    else if (el.getAttribute('aria-label')) selector = `[aria-label="${el.getAttribute('aria-label')}"]`;
                    else if (el.getAttribute('placeholder')) selector = `[placeholder="${el.getAttribute('placeholder')}"]`;
                    else selector = `__index__:${idx}`;
                    out.push({
                        selector, dom_index: idx,
                        name: el.name || el.id || '',
                        type: (el.type || el.tagName.toLowerCase()).toLowerCase(),
                        placeholder: el.getAttribute('placeholder') || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        autocomplete: el.getAttribute('autocomplete') || '',
                        maxlength: el.maxLength >= 0 ? el.maxLength : '',
                        minlength: el.minLength >= 0 ? el.minLength : '',
                        required: !!el.required,
                        pattern: el.pattern || '',
                        inputmode: el.getAttribute('inputmode') || '',
                        label_text: label.slice(0, 80),
                    });
                });
                return out.slice(0, 24);
            }"""
        )
        return fields or []
    except Exception:
        return []


def _is_pin_field(f: dict[str, Any]) -> bool:
    hay = " ".join([f.get("name",""), f.get("placeholder",""), f.get("aria_label",""),
                    f.get("label_text",""), f.get("autocomplete",""), f.get("inputmode","")]).lower()
    if f.get("type") == "password":
        return True
    if any(k in hay for k in ("pin","passcode","pass code","secret code","otp","code")):
        return True
    ml = f.get("maxlength")
    if f.get("type") in ("tel","number","text") and isinstance(ml, int) and 3 <= ml <= 8 \
            and (f.get("inputmode") == "numeric" or "numeric" in hay):
        return True
    return False


def _value_for_field(f: dict[str, Any], memory: dict[str, str]) -> str:
    hay = " ".join([f.get("name",""), f.get("placeholder",""), f.get("aria_label",""),
                    f.get("label_text",""), f.get("autocomplete",""), f.get("type","")]).lower()
    t = f.get("type", "")
    if _is_pin_field(f):
        pin = memory.setdefault("pin", DEFAULT_PIN)
        ml = f.get("maxlength")
        if isinstance(ml, int) and 4 <= ml <= 8:
            pin = (DEFAULT_PIN * 3)[:ml]
            memory["pin"] = pin
        return pin
    if t == "email" or "email" in hay:      return "atmos.tester@example.com"
    if t == "tel"   or "phone" in hay:      return "5551234567"
    if t == "number" or "amount" in hay:    return "10"
    if "name" in hay or "username" in hay:  return "Atmos Tester"
    if "search" in hay or t == "search":    return "test"
    if t == "url"   or "url" in hay:        return "https://example.com"
    return "Atmos Tester"


async def _fill_field(page: Page, selector: str, value: str) -> bool:
    try:
        if selector.startswith("__index__:"):
            loc = page.locator("input, textarea").nth(int(selector.split(":", 1)[1]))
        else:
            loc = page.locator(selector).first
        await loc.fill("", timeout=1500)
        await loc.fill(value, timeout=2500)
        return True
    except Exception:
        return False


async def _fill_screen(page: Page, memory: dict[str, str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for f in await _enumerate_inputs(page):
        hay = (f.get("label_text","") + " " + f.get("placeholder","") + " " +
               f.get("aria_label","") + " " + f.get("name","")).lower()
        if any(k in hay for k in ("confirm","re-enter","reenter","again","repeat")):
            value = memory.get("pin", DEFAULT_PIN) if _is_pin_field(f) else _value_for_field(f, memory)
        else:
            value = _value_for_field(f, memory)
        if await _fill_field(page, f["selector"], value):
            steps.append({"op":"fill","selector":f["selector"],"value":value,
                          "field": f.get("label_text") or f.get("name") or f.get("type")})
    return steps


async def _enter_pin_keypad(page: Page, memory: dict[str, str]) -> list[dict[str, Any]]:
    """Tap digit buttons on a custom PIN keypad (no <input> elements)."""
    txt = await _page_text(page)
    hay = (txt.get("heading","") + " " + txt.get("body","")).lower()
    if not any(k in hay for k in ("pin","passcode","pass code","secret code","code")):
        return []
    if await _enumerate_inputs(page):
        return []
    try:
        digit_count = await page.evaluate(
            """() => Array.from(document.querySelectorAll('button,[role=button]'))
                .filter(b => /^[0-9]$/.test((b.innerText||'').trim())).length"""
        )
    except Exception:
        digit_count = 0
    if digit_count < 3:
        return []
    pin = memory.setdefault("pin", DEFAULT_PIN)
    steps: list[dict[str, Any]] = []
    for digit in pin:
        try:
            await page.get_by_role("button", name=digit, exact=True).first.click(timeout=1500, no_wait_after=True)
            steps.append({"op":"click","text":digit,"role":"button"})
            await page.wait_for_timeout(120)
        except Exception:
            break
    return steps


def _is_pin_context(ctx: dict[str, Any]) -> bool:
    """Heuristic: is the current screen a PIN / passcode entry surface?"""
    hay = (str(ctx.get("heading", "")) + " " + str(ctx.get("body", ""))).lower()
    return any(k in hay for k in ("pin", "passcode", "pass code", "secret code", "otp", "enter code"))


def _pick_forward(buttons: list[dict[str, Any]], already: set[str]) -> Optional[dict[str, Any]]:
    lowered = {b["text"].strip().lower(): b for b in buttons if b.get("text")}
    for cta in FORWARD_CTAS:
        if cta in lowered and cta not in already:
            return lowered[cta]
    for cta in FORWARD_CTAS:
        for text, b in lowered.items():
            if cta in text and text not in already:
                return b
    return None


async def _looks_like_hub(page: Page) -> bool:
    try:
        n = await page.evaluate(
            """() => {
                const navs = Array.from(document.querySelectorAll('nav,[role=tablist],[class*="tab"],[class*="bottom"],footer'));
                let max = 0;
                for (const nav of navs) {
                    const c = nav.querySelectorAll('button,a,[role=tab],[role=button]').length;
                    if (c > max) max = c;
                }
                return max;
            }"""
        )
        return (n or 0) >= 3
    except Exception:
        return False


async def _capture_screen_png(page: Page, run_id: str, slug: str, vp_label: str) -> dict[str, Any]:
    fname = f"{run_id}_{_safe_name(slug)}_{_safe_name(vp_label)}_screen.png"
    try:
        png = await page.screenshot(full_page=True, timeout=15000)
        (SCREENSHOTS_DIR / fname).write_bytes(png)
        return {"ok": True, "url_path": f"/api/screens/{fname}",
                "image_hash": hashlib.sha1(png).hexdigest()[:16]}
    except Exception as exc:
        logger.warning("screen capture failed (%s): %s", slug, exc)
        return {"ok": False}


async def _emit_live(on_progress, page: Page, label: str) -> None:
    if not on_progress:
        return
    try:
        png = await page.screenshot(full_page=False, type="jpeg", quality=70, timeout=4000)
        await on_progress({"type":"live_frame","kind":"explore","label":label,
                           "image_b64": base64.b64encode(png).decode("ascii")})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


async def replay_path(page: Page, path: list[dict[str, Any]]) -> Page:
    """Tolerantly replay an action path onto an open page."""
    for step in path:
        op = step.get("op")
        try:
            if op == "goto":
                await page.goto(step["url"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await _settle(page)
            elif op == "fill":
                await _fill_field(page, step["selector"], step.get("value", ""))
            elif op == "click":
                await _click_button_by_text(page, {"text": step.get("text",""), "rect": step.get("rect")})
                await page.wait_for_timeout(SETTLE_MS)
            elif op == "press":
                await page.keyboard.press(step.get("key", "Enter"))
            await page.wait_for_timeout(150)
        except Exception:
            continue
    await _settle(page)
    return page


# ---------------------------------------------------------------------------
# public helpers
# ---------------------------------------------------------------------------


def _screen_name(txt: dict[str, Any], pathname: str, index: int) -> str:
    return (txt.get("heading") or txt.get("title") or pathname.strip("/") or "home").strip()[:80] \
           or f"screen {index}"


# ---------------------------------------------------------------------------
# Gemini 3.5 Flash style VLM guided exploration
# ---------------------------------------------------------------------------

async def _extract_elements_meta(page: Page) -> list[dict[str, Any]]:
    """Extract interactive elements coordinates and text for Gemini's spatial mapping."""
    try:
        return await page.evaluate(
            """() => {
                const elms = Array.from(document.querySelectorAll(
                    'button, a, [role=button], input, textarea, select, [role=tab], [onclick], [tabindex]'
                ));
                return elms.map((el, i) => {
                    const aria = (el.getAttribute('aria-label') || '').trim();
                    const title = (el.getAttribute('title') || '').trim();
                    const placeholder = (el.getAttribute('placeholder') || '').trim();
                    const alt = (el.getAttribute('alt') || '').trim();
                    const testId = (el.getAttribute('data-testid') || '').trim();
                    const text = (el.innerText || aria || placeholder || title || alt || '').trim();
                    const rect = el.getBoundingClientRect();
                    const cls = (el.className && typeof el.className === 'string') ? el.className : '';
                    const iconHint = [aria, title, alt, testId, cls].join(' ').trim().slice(0, 120);
                    const navContainer = el.closest('nav,[role=navigation],[role=tablist],footer,[class*=bottom],[class*=tab]');
                    const contextHint = (
                        navContainer?.getAttribute('aria-label') ||
                        navContainer?.getAttribute('class') ||
                        navContainer?.getAttribute('id') ||
                        ''
                    ).slice(0, 120);
                    let selector = '';
                    if (el.id) selector = `#${CSS.escape(el.id)}`;
                    else if (el.name) selector = `[name="${el.name}"]`;
                    else if (aria) selector = `[aria-label="${aria}"]`;
                    else if (el.getAttribute('placeholder')) selector = `[placeholder="${el.getAttribute('placeholder')}"]`;
                    return {
                        id: i,
                        tagName: el.tagName.toLowerCase(),
                        text: text.slice(0, 60),
                        type: el.type || '',
                        selector,
                        x: Math.round(rect.left + rect.width / 2),
                        y: Math.round(rect.top + rect.height / 2),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        visible: rect.width > 0 && rect.height > 0,
                        icon_hint: iconHint,
                        context_hint: contextHint,
                        is_icon_like: !text && (!!aria || !!title || !!alt || /icon|svg|glyph|tab|nav/i.test(cls)),
                        in_nav: !!navContainer
                    };
                }).filter(e => e.visible && (
                    e.text || e.icon_hint || e.tagName === 'input' || e.tagName === 'textarea' || e.in_nav
                ));
            }"""
        )
    except Exception:
        return []


async def _screen_context(page: Page) -> dict[str, Any]:
    try:
        return await page.evaluate(
            """() => {
                const heading = (document.querySelector('h1,h2,[role=heading]')?.innerText || '').trim().slice(0, 100);
                const title = (document.title || '').slice(0, 100);
                const body = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 360);
                const hasForm = !!document.querySelector('form,input,textarea,select');
                const keypadDigits = Array.from(document.querySelectorAll('button,[role=button]'))
                  .filter(b => /^[0-9]$/.test((b.innerText || '').trim())).length;
                return {
                    heading,
                    title,
                    body,
                    has_form: hasForm,
                    has_keypad: keypadDigits >= 3,
                    pathname: location.pathname || '/',
                };
            }"""
        )
    except Exception:
        return {
            "heading": "",
            "title": "",
            "body": "",
            "has_form": False,
            "has_keypad": False,
            "pathname": _pathname(page.url),
        }


async def _call_vlm_decision(
    page: Page,
    elements: list[dict[str, Any]],
    action_history: list[dict[str, Any]],
    screen_context: dict[str, Any],
    failed_targets: list[str],
    stagnation_count: int,
    *,
    db=None,
    user_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Ask the user's IDE vision model which UI targets to explore next."""
    if db is None or not user_id:
        logger.warning("VLM explore skipped: no IDE LLM bridge (db/user_id)")
        return None

    try:
        # 1. Take a screenshot for vision
        png = await page.screenshot(full_page=False, type="jpeg", quality=60, timeout=10000)
        b64_image = base64.b64encode(png).decode("ascii")

        # 2. Compile element list
        elements_txt = ""
        for e in elements:
            elements_txt += (
                f"  - ID: {e['id']} | Tag: {e['tagName']} | Text: {e['text']} | "
                f"IconHint: {e.get('icon_hint', '')} | Ctx: {e.get('context_hint', '')} | "
                f"Selector: {e['selector']} | At: ({e['x']},{e['y']}) | Size: {e.get('width', 0)}x{e.get('height', 0)}\n"
            )

        history_txt = "\n".join([
            f"  - {h.get('op')}: {h.get('text') or h.get('selector') or ''} -> {h.get('value', '')}"
            for h in action_history[-8:]
        ])

        prompt = f"""You are Gemini 3.5 Flash, the advanced multimodal AI web auditing agent. 
Analyze the current screenshot and the list of available interactive elements below. Your goal is to explore every screen of the app, complete onboarding flows, bypass PIN codes, and find deeper pages.

Current URL: {page.url}
Pathname: {screen_context.get('pathname', '')}
Heading: {screen_context.get('heading', '')}
Title: {screen_context.get('title', '')}
Body excerpt: {screen_context.get('body', '')}
Has form fields: {screen_context.get('has_form', False)}
Has keypad: {screen_context.get('has_keypad', False)}
Stagnation count: {stagnation_count}
Failed targets: {failed_targets[-12:]}

Recent Action History:
{history_txt}

Interactive Elements Map:
{elements_txt}

Guidelines:
- If we are on a PIN/Keypad screen: enter digits sequentially to unlock (e.g. click '1', '3', '5', '7').
- If we see text fields: type placeholder values (User Name -> 'Atmos Tester', Email -> 'atmos.tester@example.com').
- Look for next action to take (e.g. 'Get Started', 'Proceed', 'Dashboard' tabs).
- On icon-only screens: rely on IconHint, Ctx, nav placement, and coordinates to open next screens.
- Choose a short sequence of up to 3 actions that moves forward, not loops.
- Avoid targets listed in Failed targets.

Your response must be a single RAW minified JSON block matching this schema (JSON ONLY, no markdown):
{{
    "intent": "brief reason",
    "done": false,
    "actions": [
        {{"action": "fill" | "click" | "press", "element_id": number_or_null, "selector": "", "text": "", "value": "", "key": ""}}
    ]
}}
"""
        from user_llm_proxy import user_llm_text
        text = await user_llm_text(
            db, user_id, prompt,
            system="You are a multimodal web exploration agent. Respond in raw JSON only.",
            images_b64=[b64_image],
            purpose="flow_vlm",
            expect_json=True,
        )

        # Squeeze out raw JSON
        raw_json = text.strip()
        if "```" in raw_json:
            parts = raw_json.split("```")
            raw_json = parts[1] if len(parts) >= 2 else raw_json
            raw_json = raw_json.replace("json", "", 1).strip()

        # Recover first JSON object if the model added any leading/trailing text.
        first = raw_json.find("{")
        last = raw_json.rfind("}")
        if first >= 0 and last > first:
            raw_json = raw_json[first:last + 1]
        
        parsed = json.loads(raw_json.strip())
        logger.info("VLM chosen action: %s", parsed)
        return parsed

    except Exception as exc:
        logger.warning("VLM decision call failed: %s", exc)
        return None


async def _execute_vlm_action(page: Page, action: dict[str, Any], elements: list[dict[str, Any]]) -> tuple[bool, Optional[dict[str, Any]]]:
    """Tolerantly click or fill the element chosen by the VLM."""
    try:
        op = action.get("action")
        el_id = action.get("element_id")
        selector = action.get("selector")
        text = action.get("text", "")
        value = action.get("value", "")

        matched = None
        if el_id is not None:
            matched = next((e for e in elements if e["id"] == el_id), None)
        if not matched and text:
            matched = next((e for e in elements if e["text"].strip().lower() == text.strip().lower()), None)
        if not matched and selector:
            matched = next((e for e in elements if e["selector"] == selector), None)

        if op == "click":
            if matched:
                await page.mouse.click(matched["x"], matched["y"])
                logger.info("Clicked coordinates (%d, %d) for text: %s", matched["x"], matched["y"], matched["text"])
                return True, {"op": "click", "text": matched["text"], "rect": {"x": matched["x"], "y": matched["y"]}, "role": matched["tagName"]}
            elif selector:
                await page.click(selector, timeout=3000)
                return True, {"op": "click", "selector": selector}
            elif text:
                await _click_button_by_text(page, {"text": text})
                return True, {"op": "click", "text": text}

        elif op == "fill":
            target_selector = selector
            if matched and matched["selector"]:
                target_selector = matched["selector"]
            
            if target_selector:
                await page.fill(target_selector, value, timeout=3000)
                return True, {"op": "fill", "selector": target_selector, "value": value}
            elif matched:
                # Fallback to nth input focus-fill
                loc = page.locator("button, a, [role=button], input, textarea, select, [role=tab]").nth(matched["id"])
                await loc.fill(value)
                return True, {"op": "fill", "selector": f"nth:{matched['id']}", "value": value}

        elif op == "press":
            key = action.get("key") or "Enter"
            await page.keyboard.press(key)
            return True, {"op": "press", "key": key}

        return False, None
    except Exception as exc:
        logger.warning("Failed executing VLM action: %s", exc)
        return False, None


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def explore_app_flow(
    browser: Browser,
    base_url: str,
    run_id: str,
    *,
    on_progress=None,
    viewport: Optional[dict[str, Any]] = None,
    max_steps: int = MAX_FLOW_STEPS,
    max_duration_secs: int = 90,
    db=None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Drive the app using the user's IDE vision model for exploration."""
    vp = viewport or VIEWPORTS[0]
    vp_label = vp["label"]
    base_url = base_url.rstrip("/")

    ctx: BrowserContext = await _new_context(browser, vp, record_video=True)
    page = await ctx.new_page()

    screens: list[dict[str, Any]] = []
    pages_out: list[dict[str, Any]] = []
    button_actions: list[dict[str, Any]] = []
    by_sig: dict[str, dict[str, Any]] = {}
    memory: dict[str, str] = {}
    clicked_by_sig: dict[str, set[str]] = {}
    started_at = time.monotonic()

    def _timed_out() -> bool:
        return (time.monotonic() - started_at) >= max_duration_secs

    async def _register(p: Page, path: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        sig = await _signature(p)
        if sig in by_sig or len(screens) >= MAX_SCREENS:
            return by_sig.get(sig)
        txt = await _page_text(p)
        pathname = _pathname(p.url)
        idx = len(screens)
        name = _screen_name(txt, pathname, idx)
