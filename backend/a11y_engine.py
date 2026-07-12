"""Real accessibility audit — contrast, ARIA names, landmarks, keyboard tab order."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Optional

from playwright.async_api import Browser, Page

from atmos_engine import VIEWPORTS, _new_context, _settle

logger = logging.getLogger("atmos.a11y")
ProgressFn = Callable[[dict[str, Any]], Any]


async def _contrast_sample(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          function lum(c) {
            const a = c.map(v => {
              v /= 255;
              return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2];
          }
          function parse(color) {
            const m = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
            return m ? [+m[1], +m[2], +m[3]] : null;
          }
          function ratio(fg, bg) {
            const L1 = lum(fg), L2 = lum(bg);
            const hi = Math.max(L1, L2), lo = Math.min(L1, L2);
            return (hi + 0.05) / (lo + 0.05);
          }
          const nodes = [...document.querySelectorAll('p, span, a, button, label, h1, h2, h3, li, td, th')].slice(0, 120);
          const fails = [];
          for (const el of nodes) {
            const style = getComputedStyle(el);
            const fg = parse(style.color);
            let bgEl = el;
            let bg = null;
            while (bgEl && !bg) {
              const b = parse(getComputedStyle(bgEl).backgroundColor);
              if (b && getComputedStyle(bgEl).backgroundColor !== 'rgba(0, 0, 0, 0)'
                  && getComputedStyle(bgEl).backgroundColor !== 'transparent') bg = b;
              bgEl = bgEl.parentElement;
            }
            if (!fg || !bg) continue;
            const r = ratio(fg, bg);
            const size = parseFloat(style.fontSize) || 14;
            const bold = (parseInt(style.fontWeight, 10) || 400) >= 700;
            const need = (size >= 18 || (size >= 14 && bold)) ? 3.0 : 4.5;
            if (r < need) {
              const text = (el.innerText || '').trim().slice(0, 40);
              if (text) fails.push({ text, ratio: Math.round(r * 100) / 100, need, size });
            }
            if (fails.length >= 12) break;
          }
          return { sampled: nodes.length, fails };
        }"""
    )


async def _aria_names(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const inputs = [...document.querySelectorAll('input:not([type=hidden]), select, textarea, button, a[href], [role=button]')];
          const missing = [];
          for (const el of inputs) {
            const tag = el.tagName.toLowerCase();
            const name = el.getAttribute('aria-label')
              || el.getAttribute('aria-labelledby')
              || (el.id && document.querySelector('label[for=\"' + el.id + '\"]')?.innerText)
              || (tag === 'button' || tag === 'a' ? (el.innerText || '').trim() : null)
              || el.getAttribute('title')
              || el.getAttribute('placeholder');
            const r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) continue;
            if (!name || !String(name).trim()) {
              missing.push(el.name || el.id || tag || el.getAttribute('type') || 'control');
            }
          }
          return { total: inputs.length, missing: missing.slice(0, 15) };
        }"""
    )


async def _landmarks(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const main = !!document.querySelector('main, [role=main]');
          const nav = !!document.querySelector('nav, [role=navigation]');
          const header = !!document.querySelector('header, [role=banner]');
          return { main, nav, header, ok: main || nav };
        }"""
    )


async def _keyboard_tab_order(page: Page, max_tabs: int = 16) -> dict[str, Any]:
    await page.keyboard.press("Home")
    focused: list[str] = []
    trapped = False
    for i in range(max_tabs):
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(40)
        info = await page.evaluate(
            """() => {
              const el = document.activeElement;
              if (!el || el === document.body) return { tag: 'body', label: '' };
              const label = el.getAttribute('aria-label') || el.innerText || el.getAttribute('name') || el.id || el.tagName;
              return { tag: el.tagName.toLowerCase(), label: String(label).trim().slice(0, 48) };
            }"""
        )
        key = f"{info.get('tag')}:{info.get('label')}"
        if key in focused and i > 3 and focused.count(key) >= 2:
            trapped = True
            break
        focused.append(key)
    interactive = [f for f in focused if not f.startswith("body:")]
    return {
        "tabs": len(focused),
        "interactive_hits": len(interactive),
        "trapped": trapped,
        "sample": focused[:8],
        "ok": len(interactive) >= 2 and not trapped,
    }


async def _touch_targets(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const els = [...document.querySelectorAll('a[href], button, [role=button], input, select')];
          const small = [];
          for (const el of els) {
            const r = el.getBoundingClientRect();
            if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight) continue;
            if (r.width < 24 || r.height < 24) {
              small.push({
                label: (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40),
                w: Math.round(r.width), h: Math.round(r.height),
              });
            }
            if (small.length >= 10) break;
          }
          return { small, ok: small.length === 0 };
        }"""
    )


async def audit_page_a11y(page: Page, url: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await _settle(page)
    except Exception as exc:  # noqa: BLE001
        return {
            "url": url,
            "score": 40,
            "checks": [],
            "findings": [{"severity": "high", "title": "Page failed to load for a11y audit", "detail": str(exc)}],
        }

    contrast = await _contrast_sample(page)
    aria = await _aria_names(page)
    landmarks = await _landmarks(page)
    keyboard = await _keyboard_tab_order(page)
    targets = await _touch_targets(page)

    def add_check(name: str, ok: bool, detail: str, severity: str = "medium") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            findings.append({
                "id": f"a11y_{uuid.uuid4().hex[:8]}",
                "category": "Accessibility",
                "severity": severity,
                "title": name,
                "cause": detail,
                "page_url": url,
            })

    fail_n = len(contrast.get("fails") or [])
    add_check(
        "Color contrast (sampled text)",
        fail_n == 0,
        f"{fail_n} low-contrast text samples (WCAG AA ~4.5:1)" if fail_n else f"Sampled {contrast.get('sampled', 0)} nodes — no AA failures detected",
        "high" if fail_n >= 3 else "medium",
    )
    miss = aria.get("missing") or []
    add_check(
        "Accessible names on controls",
        len(miss) == 0,
        f"Unlabeled controls: {', '.join(miss)}" if miss else f"All sampled controls named ({aria.get('total', 0)})",
        "high" if len(miss) >= 2 else "medium",
    )
    add_check(
        "Landmarks (main/nav)",
        bool(landmarks.get("ok")),
        "Has main/nav landmarks" if landmarks.get("ok") else "Missing main and navigation landmarks",
        "medium",
    )
    add_check(
        "Keyboard tab order",
        bool(keyboard.get("ok")),
        (
            f"Tab trap suspected after {keyboard.get('tabs')} tabs"
            if keyboard.get("trapped")
            else f"{keyboard.get('interactive_hits')} interactive focuses in {keyboard.get('tabs')} tabs"
        ),
        "high" if keyboard.get("trapped") else "medium",
    )
    small = targets.get("small") or []
    add_check(
        "Touch target size (≥24px)",
        bool(targets.get("ok")),
        f"{len(small)} undersized targets" + (f" e.g. {small[0]['label']}" if small else ""),
        "medium",
    )

    passed = sum(1 for c in checks if c["ok"])
    score = max(35, min(98, round(40 + (passed / max(len(checks), 1)) * 55 - fail_n * 3 - len(miss) * 4)))
    return {
        "url": url,
        "score": score,
        "checks": checks,
        "findings": findings,
        "contrast_fails": contrast.get("fails") or [],
        "keyboard": keyboard,
    }


async def run_accessibility_audit(
    browser: Browser,
    base_url: str,
    pages: list[dict[str, Any]],
    *,
    deep: bool = False,
    mobile_preferred: bool = False,
    on_progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    """Audit up to N pages with real DOM / keyboard checks."""
    urls = []
    for p in pages:
        u = p.get("url")
        if u and u not in urls:
            urls.append(u)
    if not urls:
        urls = [base_url]
    limit = 6 if deep else 3
    urls = urls[:limit]

    if mobile_preferred:
        vp = next((v for v in VIEWPORTS if v.get("mobile")), VIEWPORTS[0])
    else:
        vp = next((v for v in VIEWPORTS if v["label"] == "Desktop 1440"), VIEWPORTS[0])
    ctx = await _new_context(browser, vp, record_video=False)
    page = await ctx.new_page()

    page_reports: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    try:
        for url in urls:
            if on_progress:
                await on_progress({"type": "a11y_log", "message": f"Auditing accessibility on {url}"})
            report = await audit_page_a11y(page, url)
            page_reports.append(report)
            all_findings.extend(report.get("findings") or [])
            if on_progress:
                await on_progress({
                    "type": "a11y_page",
                    "url": url,
                    "score": report["score"],
                    "findings": len(report.get("findings") or []),
                })
    finally:
        await ctx.close()

    avg = round(sum(r["score"] for r in page_reports) / max(len(page_reports), 1))
    summary = (
        f"Accessibility audit across {len(page_reports)} page(s): score {avg}/100, "
        f"{len(all_findings)} finding(s). "
        + ("Deep mode." if deep else "Standard sample.")
    )
    result = {
        "score": avg,
        "pages": page_reports,
        "findings": all_findings[:40],
        "summary": summary,
        "deep": deep,
    }
    if on_progress:
        await on_progress({"type": "a11y_report", **result})
    return result
