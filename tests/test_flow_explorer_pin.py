"""Unit test for flow_explorer._enter_pin_keypad.

Renders a static HTML page with a 6-digit PIN keypad (10 digit buttons +
'Continue') and a heading 'Create your secret PIN.', then verifies that
_enter_pin_keypad taps each digit of DEFAULT_PIN='135790' in order.
"""
import os
import asyncio
import pytest
from pathlib import Path

# Make backend importable
import sys
sys.path.insert(0, "/app/backend")

from flow_explorer import _enter_pin_keypad, DEFAULT_PIN  # noqa: E402


KEYPAD_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>PIN</title>
<style>button{font-size:24px;padding:12px;margin:4px;}</style>
<script>
window._taps = [];
function tap(d){ window._taps.push(d); document.getElementById('disp').textContent += d; }
</script></head>
<body>
  <h1>Create your secret PIN.</h1>
  <div>Enter a 6-digit PIN to secure your wallet.</div>
  <div id="disp" data-testid="pin-display"></div>
  <div id="keypad">
    <button onclick="tap('1')">1</button>
    <button onclick="tap('2')">2</button>
    <button onclick="tap('3')">3</button>
    <button onclick="tap('4')">4</button>
    <button onclick="tap('5')">5</button>
    <button onclick="tap('6')">6</button>
    <button onclick="tap('7')">7</button>
    <button onclick="tap('8')">8</button>
    <button onclick="tap('9')">9</button>
    <button onclick="tap('0')">0</button>
    <button>Continue</button>
  </div>
</body></html>
"""


@pytest.mark.asyncio
async def test_enter_pin_keypad_taps_all_six_digits(tmp_path):
    from playwright.async_api import async_playwright

    # Write the HTML fixture to a temp file
    fixture = tmp_path / "pin.html"
    fixture.write_text(KEYPAD_HTML)
    url = f"file://{fixture}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url)
        memory: dict[str, str] = {}
        steps = await _enter_pin_keypad(page, memory)
        # Read the in-page tap log
        taps = await page.evaluate("window._taps")
        disp = await page.text_content("#disp")
        await browser.close()

    # Assertions
    assert DEFAULT_PIN == "135790"
    assert len(steps) == 6, f"expected 6 steps, got {len(steps)}: {steps}"
    assert [s["text"] for s in steps] == list(DEFAULT_PIN)
    assert taps == list(DEFAULT_PIN), f"taps={taps}"
    assert disp == DEFAULT_PIN
    # memory["pin"] should be set
    assert memory.get("pin") == DEFAULT_PIN
