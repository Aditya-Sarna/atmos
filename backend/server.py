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
