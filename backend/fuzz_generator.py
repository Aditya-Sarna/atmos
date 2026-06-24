"""Massive boundary / fuzz test-case generator.

Given a discovered page that contains form inputs, generate an exhaustive set
of boundary, malformed, and adversarial cases keyed to each input's type,
attribute hints, and surrounding label text. Then *execute* each case live
against the real running app via Playwright, capture the visible result, and
emit it as a streamable test-case event.

Public entry-point:
    cases = await run_fuzz_suite(browser, url, run_id, on_progress=...)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from pathlib import Path

from playwright.async_api import Browser, Page

logger = logging.getLogger("atmos.fuzz")

import os as _os
_SCREENSHOTS_DIR = Path(_os.environ.get(
    "ATMOS_SCREENSHOTS_DIR",
    str(Path(__file__).resolve().parent / "screenshots"),
))
_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

PUBLISH_FN = Optional[Callable[[dict[str, Any]], Awaitable[None]]]

# ---------------------------------------------------------------------------
# Cases — keyed by input archetype. Each entry: (label, value, expectation)
# expectation = "reject" (form should refuse), "accept_but_warn", "accept_silently"
# ---------------------------------------------------------------------------

NUMERIC_CASES: list[tuple[str, str, str]] = [
    ("Negative number",          "-5",                   "reject"),
    ("Zero",                     "0",                    "accept_but_warn"),
    ("Float in integer field",   "3.14",                 "reject"),
    ("Comma decimal (EU)",       "3,14",                 "accept_but_warn"),
    ("Leading zeros",            "0000042",              "accept_but_warn"),
    ("Plus prefix",              "+99",                  "accept_silently"),
    ("Scientific notation",      "1e308",                "reject"),
    ("Infinity",                 "Infinity",             "reject"),
    ("NaN",                      "NaN",                  "reject"),
    ("Hex literal",              "0xFF",                 "reject"),
    ("Massive integer",          "9" * 50,               "reject"),
    ("Unicode digits (Arabic)",  "١٢٣",                  "accept_but_warn"),
    ("Unicode digits (Bengali)", "১২৩",                  "accept_but_warn"),
    ("Unicode digits (Devanagari)", "१२३",               "accept_but_warn"),
    ("Fullwidth digits",         "１２３",                 "accept_but_warn"),
    ("Emoji number",             "1️⃣2️⃣",                "reject"),
    ("Currency symbol $",        "$10",                  "reject"),
    ("Currency symbol €",        "€10",                  "reject"),
    ("Negative scientific",      "-1e-9",                "reject"),
    ("Percentage suffix",        "50%",                  "reject"),
    ("Mixed alpha-num",          "123abc",               "reject"),
    ("Spaces in number",         "1 234 567",            "reject"),
    ("Whitespace padded",        "   42   ",             "accept_but_warn"),
    ("RTL embedded",             "\u202E42\u202C",       "accept_but_warn"),
    ("Null char",                "1\x002",               "reject"),
    ("Newline embedded",         "1\n2",                 "reject"),
    ("MAX_SAFE_INTEGER + 1",     "9007199254740993",     "accept_but_warn"),
    ("Binary literal",           "0b1010",               "reject"),
    ("Octal literal",            "0o17",                 "reject"),
    ("Underscore separated",     "1_000_000",            "reject"),
    ("Long decimal",             "0." + "1" * 30,        "accept_but_warn"),
    ("Exponent without base",    "e10",                  "reject"),
    ("Multiple dots",            "1.2.3",                "reject"),
    ("Multiple minus",           "--5",                  "reject"),
    ("Plus minus",               "+-5",                  "reject"),
    ("Hex with 0x",              "0x1f",                 "reject"),
    ("Whitespace only",          "   ",                  "reject"),
    ("Tab char",                 "\t42",                 "accept_but_warn"),
    ("Roman numerals",           "XIV",                  "reject"),
    ("Words for numbers",        "twenty",               "reject"),
    ("Comma thousands US",       "1,234,567",            "accept_but_warn"),
    ("Apostrophe thousands CH",  "1'234'567",            "reject"),
    ("Negative zero",            "-0",                   "accept_silently"),
    ("Float ending in dot",      "5.",                   "accept_but_warn"),
    ("Float starting with dot",  ".5",                   "accept_but_warn"),
    ("Very small float",         "1e-300",               "accept_but_warn"),
    ("Very large float",         "1e300",                "reject"),
    ("Mixed sign",               "+5-3",                 "reject"),
    ("BOM prefix",                "\ufeff42",            "accept_but_warn"),
    ("Boolean text",             "true",                 "reject"),
]

AGE_CASES: list[tuple[str, str, str]] = [
    ("Negative age",             "-1",                   "reject"),
    ("Zero age",                 "0",                    "reject"),
    ("Toddler",                  "2",                    "accept_but_warn"),
    ("Just under 13",            "12",                   "accept_but_warn"),
    ("COPPA boundary 13",        "13",                   "accept_silently"),
    ("Just under 18",            "17",                   "accept_but_warn"),
    ("Boundary 18",              "18",                   "accept_silently"),
    ("21",                       "21",                   "accept_silently"),
    ("65",                       "65",                   "accept_silently"),
    ("Centenarian",              "120",                  "accept_but_warn"),
    ("Implausible age",          "200",                  "reject"),
    ("Massive age",              "99999",                "reject"),
    ("Float age",                "21.5",                 "reject"),
    ("Negative century",         "-100",                 "reject"),
    ("Letters",                  "abc",                  "reject"),
    ("Empty",                    "",                     "reject"),
]

DATE_CASES: list[tuple[str, str, str]] = [
    ("DOB in future",            "2030-01-01",           "reject"),
    ("DOB in far future",        "3000-01-01",           "reject"),
    ("DOB before 1900",          "1850-01-01",           "reject"),
    ("Today",                    "today",                "accept_silently"),
    ("Feb 29 non-leap (2023)",   "2023-02-29",           "reject"),
    ("Feb 29 leap (2024)",       "2024-02-29",           "accept_silently"),
    ("Feb 30",                   "2024-02-30",           "reject"),
    ("Feb 31",                   "2024-02-31",           "reject"),
    ("Apr 31",                   "2024-04-31",           "reject"),
    ("Month 0",                  "2024-00-01",           "reject"),
    ("Month 13",                 "2024-13-01",           "reject"),
    ("Day 0",                    "2024-01-00",           "reject"),
    ("Day 32",                   "2024-01-32",           "reject"),
    ("DST spring-forward",       "2024-03-10",           "accept_silently"),
    ("DST fall-back",            "2024-11-03",           "accept_silently"),
    ("Malformed date",           "not-a-date",           "reject"),
    ("DD-MM-YYYY",               "31-12-2024",           "accept_but_warn"),
    ("MM/DD/YYYY",               "12/31/2024",           "accept_but_warn"),
    ("ISO with timezone",        "2024-01-15T10:00:00Z", "accept_silently"),
    ("Negative year",            "-0001-01-01",          "reject"),
    ("Two-digit year",           "24-01-01",             "reject"),
    ("Y2K38 boundary",           "2038-01-19",           "accept_silently"),
    ("Pre-epoch",                "1969-12-31",           "accept_but_warn"),
    ("Unix epoch zero",          "1970-01-01",           "accept_silently"),
    ("Year 9999",                "9999-12-31",           "accept_but_warn"),
    ("Empty",                    "",                     "reject"),
    ("Spaces",                   "  ",                   "reject"),
    ("Time only",                "14:30",                "reject"),
    ("Date with TZ offset",      "2024-01-15+05:30",     "reject"),
    ("Hebrew calendar date",     "5784-01-01",           "accept_but_warn"),
    ("Excel serial number",      "45000",                "reject"),
    ("RFC 2822 date",            "Mon, 15 Jan 2024 10:00:00 GMT", "accept_but_warn"),
]

EMAIL_CASES: list[tuple[str, str, str]] = [
    ("Plain email",              "user@example.com",     "accept_silently"),
    ("Subdomain",                "user@mail.example.com","accept_silently"),
    ("Plus alias (Gmail)",       "user+tag@example.com", "accept_silently"),
    ("Dot in local part",        "first.last@example.com", "accept_silently"),
    ("Dashes",                   "user-name@example.com","accept_silently"),
    ("Quoted local part",        '"user name"@example.com', "accept_but_warn"),
    ("Missing @",                "userexample.com",      "reject"),
    ("Missing TLD",              "user@example",         "reject"),
    ("Double @",                 "u@s@example.com",      "reject"),
    ("Empty local part",         "@example.com",         "reject"),
    ("Empty domain",             "user@",                "reject"),
    ("Leading dot",              ".user@example.com",    "reject"),
    ("Trailing dot",             "user@example.com.",    "reject"),
    ("Consecutive dots",         "u..ser@example.com",   "reject"),
    ("Spaces",                   "user @example.com",    "reject"),
    ("Newline in email",         "user@\nexample.com",   "reject"),
    ("Emoji in local",           "u🎉ser@example.com",   "accept_but_warn"),
    ("Emoji domain",             "user@🎉.com",           "accept_but_warn"),
    ("Long local (300 chars)",   "a" * 300 + "@x.com",   "reject"),
    ("Long domain",              "user@" + "a" * 256 + ".com", "reject"),
    ("XSS payload",              '"<img src=x onerror=alert(1)>"@x.com', "reject"),
    ("Script tag",               "<script>@x.com",       "reject"),
    ("SQL payload",              "user'; DROP TABLE users; --@x.com", "reject"),
    ("CRLF injection",           "user@x.com\r\nBcc:admin@y.com", "reject"),
    ("Header injection",         "user@x.com\nCc:b@y.com", "reject"),
    ("Unicode TLD (Cyrillic)",   "user@example.рф",      "accept_silently"),
    ("IDN punycode",             "user@xn--80akhbyknj4f.рф", "accept_silently"),
    ("Unicode domain",           "user@münchen.de",      "accept_silently"),
    ("Disposable mail",          "user@mailinator.com",  "accept_but_warn"),
    ("IP literal domain",        "user@[127.0.0.1]",     "accept_but_warn"),
    ("IPv6 literal",             "user@[IPv6:::1]",      "accept_but_warn"),
    ("Trailing whitespace",      "user@example.com ",    "accept_but_warn"),
    ("Tab in middle",            "user\t@example.com",   "reject"),
    ("UPPER + lower",            "USER@example.com",     "accept_silently"),
    ("Single-char TLD",          "user@x.c",             "accept_but_warn"),
    ("Numeric local",            "123@example.com",      "accept_silently"),
    ("Numeric TLD",              "user@example.123",     "reject"),
    ("Empty",                    "",                     "reject"),
    ("Just @",                   "@",                    "reject"),
]

TEXT_CASES: list[tuple[str, str, str]] = [
    ("Empty string",             "",                     "reject"),
    ("Single space",             " ",                    "reject"),
    ("Only whitespace",          "   \t\n  ",            "reject"),
    ("Single char",              "a",                    "accept_silently"),
    ("Normal English",           "Hello world",          "accept_silently"),
    ("Long sentence",            "A" * 500,              "accept_silently"),
    ("10k chars",                "A" * 10_000,           "accept_but_warn"),
    ("1M chars",                 "A" * 1_000_000,        "reject"),
    ("Newlines",                 "line1\nline2\nline3",  "accept_silently"),
    ("CRLF",                     "line1\r\nline2",       "accept_silently"),
    ("Tabs",                     "col1\tcol2\tcol3",     "accept_silently"),
    ("Null byte",                "abc\x00def",           "reject"),
    ("Bell char",                "abc\x07def",           "accept_but_warn"),
    ("RTL override",             "abc\u202Edef",         "accept_but_warn"),
    ("Mixed RTL/LTR",            "Hello مرحبا world",     "accept_silently"),
    ("Right-to-left text",       "مرحبا بالعالم",        "accept_silently"),
    ("Chinese",                  "你好世界",              "accept_silently"),
    ("Japanese",                 "こんにちは世界",         "accept_silently"),
    ("Korean",                   "안녕하세요 세계",        "accept_silently"),
    ("Hindi",                    "नमस्ते दुनिया",            "accept_silently"),
    ("Greek",                    "Γειά σου κόσμε",       "accept_silently"),
    ("Russian",                  "Привет мир",            "accept_silently"),
    ("Zero-width chars",         "a\u200Bb\u200Bc",      "accept_but_warn"),
    ("Zero-width joiner",        "a\u200Db\u200Dc",      "accept_but_warn"),
    ("Combining marks",          "n" + "\u0301" * 50,    "accept_but_warn"),
    ("Emoji bomb",               "🚀" * 100,              "accept_but_warn"),
    ("Mixed emoji + text",       "Hello 👋 World 🌍",      "accept_silently"),
    ("Flag emoji",               "🇺🇸🇯🇵🇫🇷",                "accept_silently"),
    ("ZWJ skin tone",            "👨‍👩‍👧‍👦",                 "accept_silently"),
    ("HTML",                     "<b>hi</b>",            "accept_but_warn"),
    ("Script tag",               "<script>alert(1)</script>", "reject"),
    ("Img onerror",              "<img src=x onerror=alert(1)>", "reject"),
    ("SVG XSS",                  "<svg onload=alert(1)>", "reject"),
    ("JavaScript URL",           "javascript:alert(1)",  "reject"),
    ("Data URL",                 "data:text/html,<script>alert(1)</script>", "reject"),
    ("SQL injection",            "' OR 1=1 --",          "reject"),
    ("SQL union",                "' UNION SELECT * FROM users --", "reject"),
    ("Path traversal",           "../../etc/passwd",     "reject"),
    ("Windows path traversal",   "..\\..\\windows\\system32", "reject"),
    ("Command injection",        "; rm -rf /",           "reject"),
    ("LDAP injection",           "*)(uid=*",             "reject"),
    ("XPath injection",          "' or '1'='1",          "reject"),
    ("XXE payload",              "<!ENTITY xxe SYSTEM 'file:///etc/passwd'>", "reject"),
    ("Template injection",       "{{7*7}}",              "reject"),
    ("SSRF localhost",           "http://localhost:6379","reject"),
    ("SSRF metadata",            "http://169.254.169.254/", "reject"),
    ("Format string",            "%s%s%s%s%s%n",         "accept_but_warn"),
    ("BOM prefix",               "\ufeffhello",          "accept_but_warn"),
    ("Latin-1 only",             "café résumé",          "accept_silently"),
    ("JSON payload",             '{"x":1}',              "accept_silently"),
    ("JSON injection",           '","admin":true,"x":"', "accept_but_warn"),
    ("CRLF header injection",    "x\r\nSet-Cookie: a=b", "reject"),
    ("Backtick",                 "`whoami`",             "accept_but_warn"),
    ("Markdown injection",       "[click](javascript:alert(1))", "accept_but_warn"),
    ("Polyglot XSS",             "javascript:/*--></title></style></textarea></script></xmp><svg/onload='+/\"`/+/onmouseover=1/+/[*/[]/+alert(1)//'>", "reject"),
]

PHONE_CASES: list[tuple[str, str, str]] = [
    ("E.164 US",                 "+15555550100",         "accept_silently"),
    ("E.164 UK",                 "+442071838750",        "accept_silently"),
    ("E.164 IN",                 "+919876543210",        "accept_silently"),
    ("E.164 JP",                 "+81312345678",         "accept_silently"),
    ("National only US",         "5555550100",           "accept_but_warn"),
    ("With dashes",              "555-555-0100",         "accept_but_warn"),
    ("With dots",                "555.555.0100",         "accept_but_warn"),
    ("With parens",              "(555) 555-0100",       "accept_but_warn"),
    ("With country code",        "1-555-555-0100",       "accept_but_warn"),
    ("Letters",                  "1-800-FLOWERS",        "reject"),
    ("Mixed alpha",              "555-WORD-123",         "reject"),
    ("Too short",                "555",                  "reject"),
    ("Too long",                 "1" * 30,               "reject"),
    ("Plus only",                "+",                    "reject"),
    ("Plus letters",             "+ABC",                 "reject"),
    ("Spaces only",              "   ",                  "reject"),
    ("Empty",                    "",                     "reject"),
    ("Unicode digits",           "+١٥٥٥٥٥٥٠١٠٠",         "accept_but_warn"),
    ("Extension format",         "+15555550100 ext 123", "accept_but_warn"),
    ("Premium-rate",             "+1900XXXXXXX",         "accept_but_warn"),
    ("Short code",               "70707",                "accept_but_warn"),
    ("XSS payload",              "<script>alert(1)</script>", "reject"),
    ("Multiple plus",            "++15555550100",        "reject"),
    ("Leading 0",                "0555-0100",            "reject"),
]

PASSWORD_CASES: list[tuple[str, str, str]] = [
    ("Empty",                    "",                     "reject"),
    ("Too short (1)",            "a",                    "reject"),
    ("Too short (4)",            "abcd",                 "reject"),
    ("Too short (7)",            "abcdefg",              "reject"),
    ("Min length (8)",           "abcdefgh",             "accept_but_warn"),
    ("Only digits",              "12345678",             "accept_but_warn"),
    ("Only letters",             "abcdefgh",             "accept_but_warn"),
    ("Only symbols",             "!@#$%^&*",             "accept_but_warn"),
    ("Common: password",         "password",             "accept_but_warn"),
    ("Common: 123456",           "123456",               "accept_but_warn"),
    ("Common: qwerty",           "qwerty",               "accept_but_warn"),
    ("Common: admin",            "admin",                "accept_but_warn"),
    ("Common: password123",      "password123",          "accept_but_warn"),
    ("Sequential",               "abcd1234",             "accept_but_warn"),
    ("Repeated chars",           "aaaaaaaaaa",           "accept_but_warn"),
    ("Strong mixed",             "Tr0ub4dor&3-Atmos!",   "accept_silently"),
    ("Very strong (64 chars)",   "P@" + "a" * 62,        "accept_silently"),
    ("Over 128 chars",           "P@" + "a" * 130,       "accept_but_warn"),
    ("256 chars",                "P@" + "a" * 254,       "reject"),
    ("Whitespace edges",         "  goodpass  ",         "accept_but_warn"),
    ("Whitespace only",          "        ",             "reject"),
    ("Unicode emoji",            "🔑secret-Pass-1",       "accept_but_warn"),
    ("Unicode CJK",              "秘密パスワード123",      "accept_silently"),
    ("Null byte",                "good\x00pass",         "reject"),
    ("Newline embedded",         "good\npass",           "reject"),
    ("SQL injection",            "' OR '1'='1' --",      "reject"),
    ("Script tag",               "<script>alert(1)</script>", "reject"),
    ("Pwned: Letmein!",          "Letmein!",             "accept_but_warn"),
    ("Includes username",        "atmos.qa@example.com1",  "accept_but_warn"),
]

URL_CASES: list[tuple[str, str, str]] = [
    ("HTTPS",                    "https://example.com",  "accept_silently"),
    ("HTTPS with path",          "https://example.com/path", "accept_silently"),
    ("HTTPS with query",         "https://example.com/?q=1&r=2", "accept_silently"),
    ("HTTPS with port",          "https://example.com:8443", "accept_silently"),
    ("HTTP (insecure)",          "http://example.com",   "accept_but_warn"),
    ("No scheme",                "example.com",          "accept_but_warn"),
    ("FTP",                      "ftp://example.com",    "accept_but_warn"),
    ("Mailto",                   "mailto:user@example.com", "accept_but_warn"),
    ("Tel",                      "tel:+15555550100",     "accept_but_warn"),
    ("JavaScript URL",           "javascript:alert(1)",  "reject"),
    ("Data URL",                 "data:text/html,<h1>x", "reject"),
    ("file://",                  "file:///etc/passwd",   "reject"),
    ("vbscript://",              "vbscript:msgbox(1)",   "reject"),
    ("XSS in path",              "https://x.com/<script>", "accept_but_warn"),
    ("Fragment XSS",             "https://x.com/#<img onerror=alert(1)>", "accept_but_warn"),
    ("CRLF injection",           "https://x.com/%0d%0aSet-Cookie:a=b", "reject"),
    ("Internal localhost",       "http://localhost:6379","reject"),
    ("AWS metadata",             "http://169.254.169.254/latest/meta-data/", "reject"),
    ("GCP metadata",             "http://metadata.google.internal/", "reject"),
    ("IPv6",                     "https://[::1]:8080",   "accept_but_warn"),
    ("Open redirect",            "https://attacker.com/@example.com/", "reject"),
    ("URL with userinfo",        "https://user:pass@example.com", "accept_but_warn"),
    ("Empty",                    "",                     "reject"),
    ("Just scheme",              "https://",             "reject"),
    ("Unicode IDN",              "https://münchen.de",   "accept_silently"),
    ("Punycode IDN",             "https://xn--mnchen-3ya.de", "accept_silently"),
    ("Homograph attack",         "https://exаmple.com",  "accept_but_warn"),
]


# ---------------------------------------------------------------------------
# Field detection
# ---------------------------------------------------------------------------


async def _enumerate_fields(page: Page) -> list[dict[str, Any]]:
    try:
        return await page.evaluate(
            """() => {
                const out = [];
                const els = Array.from(document.querySelectorAll('input, textarea'));
                for (const el of els) {
                    if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button' || el.type === 'file') continue;
                    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
                    const lbl = (
                        (el.id && document.querySelector(`label[for="${el.id}"]`)?.innerText) ||
                        el.closest('label')?.innerText ||
                        el.getAttribute('aria-label') ||
                        el.getAttribute('placeholder') || ''
                    ).trim();
                    out.push({
                        name: el.name || el.id || '',
                        type: (el.type || el.tagName.toLowerCase()).toLowerCase(),
                        placeholder: el.getAttribute('placeholder') || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        autocomplete: el.getAttribute('autocomplete') || '',
                        min: el.min || '', max: el.max || '',
                        minlength: el.minLength >= 0 ? el.minLength : '',
                        maxlength: el.maxLength >= 0 ? el.maxLength : '',
                        required: !!el.required,
                        pattern: el.pattern || '',
                        label_text: lbl.slice(0, 80),
                    });
                    if (out.length >= 30) break;
                }
                return out;
            }"""
        )
    except Exception:  # noqa: BLE001
        return []


def _classify_field(f: dict[str, Any]) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (archetype_label, cases_to_run)."""
    hay = " ".join([
        f.get("name", ""), f.get("placeholder", ""),
        f.get("aria_label", ""), f.get("autocomplete", ""),
        f.get("label_text", ""), f.get("type", ""),
    ]).lower()

    t = f.get("type", "")
    if t == "email" or "email" in hay:
        return "Email", EMAIL_CASES
    if t == "password" or "password" in hay:
        return "Password", PASSWORD_CASES
    if t == "tel" or "phone" in hay or "mobile" in hay:
        return "Phone", PHONE_CASES
    if t == "url" or "website" in hay or "url" in hay:
        return "URL", URL_CASES
    if t == "date" or "dob" in hay or "birth" in hay or "date" in hay:
        return "Date", DATE_CASES
    if "age" in hay:
        return "Age", AGE_CASES
    if t == "number":
        return "Numeric", NUMERIC_CASES
    return "Text", TEXT_CASES


# ---------------------------------------------------------------------------
# Live execution
# ---------------------------------------------------------------------------


async def _emit_frame(
    publish: PUBLISH_FN,
    page: Page,
    label: str,
    *,
    save_as: Optional[str] = None,
) -> Optional[str]:
    """Capture a live JPEG, optionally save to disk, and publish as live_frame.
    Returns the /api/screens/<filename> URL if saved, else None."""
    screenshot_url: Optional[str] = None
    try:
        png = await page.screenshot(full_page=False, type="jpeg", quality=70, timeout=4000)
    except Exception:  # noqa: BLE001
        return None
    if save_as:
        try:
            (_SCREENSHOTS_DIR / save_as).write_bytes(png)
            screenshot_url = f"/api/screens/{save_as}"
        except Exception:  # noqa: BLE001
            pass
    if publish:
        try:
            await publish({
                "type": "live_frame",
                "kind": "fuzz",
                "label": label,
                "image_b64": base64.b64encode(png).decode("ascii"),
                "screenshot_url": screenshot_url,
            })
        except Exception:  # noqa: BLE001
            pass
    return screenshot_url


async def _detect_validation_outcome(page: Page) -> dict[str, Any]:
    """Probe the page for any visible validation feedback."""
    try:
        return await page.evaluate(
            """() => {
                const invalid = Array.from(document.querySelectorAll(':invalid')).length;
                const aria = Array.from(document.querySelectorAll('[aria-invalid="true"]')).length;
                const errEls = Array.from(document.querySelectorAll(
                    '.error, .invalid, [class*="error"], [class*="invalid"], [role="alert"]'
                )).filter(e => e.offsetParent || getComputedStyle(e).position === 'fixed');
                const errTexts = errEls.slice(0, 3).map(e => (e.innerText || '').trim().slice(0, 200));
                return {
                    invalid_count: invalid,
                    aria_invalid: aria,
                    error_texts: errTexts,
                    visible_error: errTexts.length > 0,
                };
            }"""
        )
    except Exception:  # noqa: BLE001
        return {"invalid_count": 0, "aria_invalid": 0, "error_texts": [], "visible_error": False}


def _grade(expectation: str, outcome: dict[str, Any]) -> str:
    """Return 'pass'|'fail'|'warn' based on whether the form behaved as expected."""
    rejected = outcome.get("invalid_count", 0) > 0 or outcome.get("aria_invalid", 0) > 0 or outcome.get("visible_error")
    if expectation == "reject":
        return "pass" if rejected else "fail"
    if expectation == "accept_silently":
        return "pass" if not rejected else "warn"
    # accept_but_warn — either is OK, but we prefer the form to *warn*.
    return "pass" if not rejected else "warn"


async def run_fuzz_suite(
    browser: Browser,
    url: str,
    run_id: str,
    *,
    on_progress: PUBLISH_FN = None,
    max_fields: int = 6,
    max_cases_per_field: int = 50,
) -> list[dict[str, Any]]:
    """For the given URL, enumerate every form field, run a barrage of boundary
    cases against each, and return a list of test-case results."""
    ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
    page = await ctx.new_page()
    cases_out: list[dict[str, Any]] = []
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=18_000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fuzz: cannot load %s: %s", url, exc)
            return cases_out
        try:
            await page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:  # noqa: BLE001
            pass

        fields = await _enumerate_fields(page)
        if not fields:
            return cases_out

        for field in fields[:max_fields]:
            archetype, raw_cases = _classify_field(field)
            field_label = field.get("label_text") or field.get("name") or field.get("placeholder") or archetype

            for raw in raw_cases[:max_cases_per_field]:
                label, value, expectation = raw
                case_id = f"fz_{uuid.uuid4().hex[:8]}"
                # Reset the page state cheaply: clear focus.
                try:
                    await page.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
                except Exception:  # noqa: BLE001
                    pass

                # Find this specific input by stable handle each iteration.
                selector = None
                if field.get("name"):
                    selector = f"[name={field['name']!r}]"
                # Fallback: by aria-label / placeholder
                if not selector and field.get("aria_label"):
                    selector = f"[aria-label={field['aria_label']!r}]"
                if not selector and field.get("placeholder"):
                    selector = f"[placeholder={field['placeholder']!r}]"

                handle = None
                try:
                    if selector:
                        handle = await page.query_selector(selector)
                except Exception:  # noqa: BLE001
                    handle = None

                emit_case = {
                    "id": case_id,
                    "name": f"{archetype} · {field_label} → {label}",
                    "category": "Functional",
                    "steps": [
                        f"Focus '{field_label}'",
                        f"Type: {value if len(value) < 60 else value[:60] + '…'}",
                        "Blur field & read validation",
                    ],
                    "expected_result": expectation,
                    "field": field_label,
                    "field_archetype": archetype,
                    "value_sent": value if len(value) < 200 else value[:200] + "…",
                    "status": "running",
                }
                if on_progress:
                    await on_progress({"type": "fuzz_case", "phase": "start", **emit_case})

                outcome: dict[str, Any] = {}
                if handle is None:
                    grade = "warn"
                    outcome = {"error_texts": ["Field selector not stable across reloads"], "visible_error": False}
                else:
                    try:
                        await handle.fill("", timeout=1500)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        # date inputs need fill('YYYY-MM-DD'); special-case "today"
                        send_value = value
                        if archetype == "Date" and value == "today":
                            import datetime as _dt
                            send_value = _dt.date.today().isoformat()
                        await handle.fill(send_value, timeout=2000)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(250)
                        outcome = await _detect_validation_outcome(page)
                        grade = _grade(expectation, outcome)
                    except Exception as exc:  # noqa: BLE001
                        grade = "warn"
                        outcome = {"error_texts": [f"Playwright fill failed: {exc!s}"], "visible_error": False}

                fuzz_fname = f"{run_id}_fuzz_{case_id}.jpg"
                screenshot_url = await _emit_frame(
                    on_progress, page, f"{archetype}: {label}", save_as=fuzz_fname
                )

                done_case = {
                    **emit_case,
                    "status": grade,
                    "screenshot_url": screenshot_url,
                    "explanation": (
                        f"Expected: {expectation}. "
                        + ("Form rejected the value." if outcome.get("visible_error") or outcome.get("invalid_count") else "Form accepted the value silently.")
                        + (f" Errors shown: {' | '.join(outcome['error_texts'])}" if outcome.get("error_texts") else "")
                    ),
                }
                cases_out.append(done_case)
                if on_progress:
                    await on_progress({"type": "fuzz_case", "phase": "end", **done_case})

                # Tiny pause so the live stream doesn't strobe.
                await asyncio.sleep(0.05)

    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
    return cases_out


# ---------------------------------------------------------------------------
# Live fuzz execution against discovered flow screens (with video)
# ---------------------------------------------------------------------------


async def fuzz_flow_screens(
    browser: Browser,
    screens: list[dict],
    run_id: str,
    *,
    on_progress: PUBLISH_FN = None,
    max_cases_per_screen: int = 50,
    timeout_per_case_secs: int = 30,
) -> list[dict]:
    """Execute fuzz cases against real inputs on discovered flow screens.

    For each screen, replays its action path in a fresh context (with video),
    then:
    - If the screen has <input> fields: runs boundary cases via fill() against
      the actual DOM elements.
    - If the screen is a keypad (keypad_screen=True): tries multiple PIN
      sequences by clicking digit buttons.

    Returns a flat list of executed case results, each with a video_url.
    """
    results: list[dict] = []
    for screen in screens:
        if _timed_out_global(results, max_total=48):
            break
        fields = screen.get("fields") or []
        is_keypad = screen.get("keypad_screen", False)
        if not fields and not is_keypad:
            continue  # nothing to fuzz on this screen

        cases_to_run: list[dict] = []
        if fields:
            for f in fields[:4]:
                archetype, raw_cases = _classify_field(f)
                field_label = f.get("label_text") or f.get("name") or f.get("placeholder") or archetype
                for lbl, value, expectation in raw_cases[:max_cases_per_screen]:
                    cases_to_run.append({
                        "type": "field",
                        "selector": f.get("selector",""),
                        "field_label": field_label,
                        "archetype": archetype,
                        "label": lbl,
                        "value": value,
                        "expectation": expectation,
                    })
        if is_keypad:
            # Keypad fuzz: try various PIN sequences that should be rejected
            # or accepted depending on length/type.
            keypad_cases = [
                ("Too short (1 digit)",    "1",          "reject"),
                ("Too short (2 digits)",   "12",         "reject"),
                ("Correct length",         "1357",       "accept_silently"),
                ("Sequential ascending",   "1234",       "accept_silently"),
                ("Sequential descending",  "9876",       "accept_silently"),
                ("All same digit",         "0000",       "accept_but_warn"),
                ("Mismatch attempt (wrong confirm)", "9999", "reject"),
                ("Extra digits",           "123456789",  "accept_but_warn"),
            ]
            for lbl, digits, expectation in keypad_cases:
                cases_to_run.append({
                    "type": "keypad",
                    "field_label": "PIN keypad",
                    "archetype": "PIN",
                    "label": lbl,
                    "value": digits,
                    "expectation": expectation,
                })

        for case in cases_to_run[:max_cases_per_screen]:
            case_id = f"ffz_{uuid.uuid4().hex[:8]}"
            emit_case = {
                "id": case_id,
                "name": f"{case['archetype']} · {case['field_label']} → {case['label']}  [{screen.get('name','')}]",
                "category": "Functional",
                "steps": [
                    f"Replay path to '{screen.get('name')}'",
                    f"Enter '{case['field_label']}': {case['value'][:60] if len(case['value']) < 60 else case['value'][:60] + '…'}",
                    "Submit & detect validation",
                ],
                "expected_result": case["expectation"],
                "field": case["field_label"],
                "field_archetype": case["archetype"],
                "value_sent": case["value"][:200],
                "status": "running",
            }
            if on_progress:
                await on_progress({"type": "fuzz_case", "phase": "start", **emit_case})

            grade = "warn"
            screenshot_url: Optional[str] = None
            video_url: Optional[str] = None
            outcome: dict = {}

            try:
                from atmos_engine import _new_context, VIEWPORTS  # avoid circular at module level
                vp = VIEWPORTS[0]
                ctx_v = await _new_context(browser, vp, record_video=True)
                fpage = await ctx_v.new_page()
                try:
                    from flow_explorer import replay_path  # local import to avoid circular
                    await replay_path(fpage, screen.get("path", []))

                    if case["type"] == "field":
                        sel = case.get("selector","")
                        if sel:
                            if sel.startswith("__index__:"):
                                handle = fpage.locator("input, textarea").nth(int(sel.split(":",1)[1]))
                            else:
                                handle = fpage.locator(sel).first
                            try:
                                await handle.fill("", timeout=1500)
                                send_value = case["value"]
                                if case["archetype"] == "Date" and send_value == "today":
                                    import datetime as _dt
                                    send_value = _dt.date.today().isoformat()
                                await handle.fill(send_value, timeout=2000)
                                await fpage.keyboard.press("Tab")
                                await fpage.wait_for_timeout(300)
                                # Try to submit
                                for cta in ("continue","next","submit","confirm","save","done","verify"):
                                    try:
                                        await fpage.get_by_role("button", name=cta, exact=False).first.click(timeout=1000, no_wait_after=True)
                                        break
                                    except Exception:
                                        continue
                                await fpage.wait_for_timeout(400)
                                outcome = await _detect_validation_outcome(fpage)
                                grade = _grade(case["expectation"], outcome)
                            except Exception as exc:
                                grade = "warn"
                                outcome = {"error_texts": [str(exc)[:120]], "visible_error": False}

                    elif case["type"] == "keypad":
                        digits = case["value"]
                        for digit in digits[:8]:
                            try:
                                await fpage.get_by_role("button", name=digit, exact=True).first.click(
                                    timeout=1200, no_wait_after=True)
                                await fpage.wait_for_timeout(100)
                            except Exception:
                                pass
                        await fpage.wait_for_timeout(400)
                        outcome = await _detect_validation_outcome(fpage)
                        grade = _grade(case["expectation"], outcome)

                    # Screenshot
                    fuzz_fname = f"{run_id}_ffz_{case_id}.jpg"
                    screenshot_url = await _emit_frame(on_progress, fpage, emit_case["name"], save_as=fuzz_fname)

                    # Close page first to finalise video
                    video = fpage.video
                    await fpage.close()
                    if video:
                        try:
                            from pathlib import Path as _Path
                            raw_v = await video.path()
                            if raw_v and _Path(raw_v).exists():
                                vname = f"{run_id}_ffz_{case_id}_{vp['label'].replace(' ','_')}.webm"
                                (_SCREENSHOTS_DIR / vname).write_bytes(_Path(raw_v).read_bytes())
                                video_url = f"/api/screens/{vname}"
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug("fuzz screen case failed: %s", exc)
                    try:
                        await fpage.close()
                    except Exception:
                        pass
                finally:
                    try:
                        await ctx_v.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("fuzz screen context failed: %s", exc)

            done = {
                **emit_case,
                "status": grade,
                "screenshot_url": screenshot_url,
                "video_url": video_url,
                "explanation": (
                    f"Expected: {case['expectation']}. "
                    + ("Form rejected the input." if outcome.get("visible_error") or outcome.get("invalid_count")
                       else "App accepted input without complaint.")
                    + (f" Errors: {' | '.join(outcome['error_texts'][:2])}" if outcome.get("error_texts") else "")
                ),
            }
            results.append(done)
            if on_progress:
                await on_progress({"type": "fuzz_case", "phase": "end", **done})
            await asyncio.sleep(0.05)

    return results


def _timed_out_global(results: list, max_total: int = 48) -> bool:
    return len(results) >= max_total
