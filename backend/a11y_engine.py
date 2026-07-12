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

