"""GitHub-repo connection mode.

Clone a target GitHub repository, detect its tech stack, install dependencies,
and boot the dev server locally so the rest of the Atmos engine (crawler,
fuzzer, live-stream) can drive it WITHOUT the user needing to host the app.

Public entry-point:
    async with boot_repo(github_url, on_log=...) as local_url:
        ...  # crawl/test against http://localhost:<port>

The context manager guarantees the process is killed and the workdir is
removed on exit, even if the caller raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import socket
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger("atmos.github_runner")

LogFn = Callable[[str, str], Awaitable[None]]  # (level, message)

CLONE_TIMEOUT = 120
INSTALL_TIMEOUT = 600
BOOT_TIMEOUT = 90


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


_GH_RX = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?(?:#.*)?$",
)


def parse_github_url(url: str) -> Optional[dict[str, str]]:
    """Return {owner, repo, clone_url} or None if not a recognisable GH URL."""
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("git@github.com:"):
        path = url.split(":", 1)[1].removesuffix(".git").strip("/")
        if path.count("/") != 1:
            return None
        owner, repo = path.split("/", 1)
        return {"owner": owner, "repo": repo, "clone_url": f"https://github.com/{owner}/{repo}.git"}
    m = _GH_RX.match(url)
    if not m:
        return None
    owner = m.group("owner")
    repo = m.group("repo")
    return {"owner": owner, "repo": repo, "clone_url": f"https://github.com/{owner}/{repo}.git"}


# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------


@dataclass
class DetectedStack:
    kind: str                          # "node" | "python" | "static" | "unknown"
    workdir: Path                      # absolute path to the package to boot
    install_cmd: Optional[list[str]] = None
    boot_cmd: Optional[list[str]] = None
    port: int = 3000
    ready_path: str = "/"
    env: dict[str, str] = field(default_factory=dict)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _find_package_dir(root: Path) -> Path:
    """Pick the most likely 'app' directory. Prefers ./frontend, ./web, ./client,
    or the first descendant that contains a package.json/requirements.txt."""
    preferred = ["frontend", "web", "client", "app", "site"]
    for name in preferred:
        candidate = root / name
        if candidate.is_dir() and (
            (candidate / "package.json").exists()
            or (candidate / "requirements.txt").exists()
            or (candidate / "pyproject.toml").exists()
        ):
            return candidate
    # Otherwise, root if it has a manifest.
    for marker in ("package.json", "requirements.txt", "pyproject.toml", "index.html"):
        if (root / marker).exists():
            return root
    # Fallback: shallow walk
    for child in sorted(root.iterdir()):
        if child.is_dir() and any((child / m).exists() for m in ("package.json", "requirements.txt", "index.html")):
            return child
    return root


def detect_stack(repo_root: Path) -> DetectedStack:
    work = _find_package_dir(repo_root)
    pkg = _read_json(work / "package.json")
    port = _free_port()

    if pkg:
        scripts = (pkg.get("scripts") or {})
        # Use the first matching dev/start script.
        chosen_script = next((s for s in ("dev", "start", "serve") if s in scripts), None)
        install_cmd = None
        if (work / "pnpm-lock.yaml").exists():
            install_cmd = ["pnpm", "install", "--frozen-lockfile"]
            run_prefix = ["pnpm", "run"]
        elif (work / "yarn.lock").exists():
            install_cmd = ["yarn", "install", "--frozen-lockfile"]
            run_prefix = ["yarn"]
        else:
            install_cmd = ["npm", "install", "--legacy-peer-deps", "--no-audit", "--no-fund"]
            run_prefix = ["npm", "run"]
        boot_cmd = run_prefix + [chosen_script] if chosen_script else [run_prefix[0], "start"]
        return DetectedStack(
            kind="node",
            workdir=work,
            install_cmd=install_cmd,
            boot_cmd=boot_cmd,
            port=port,
            env={
                "PORT": str(port),
                "HOST": "127.0.0.1",
                "HOSTNAME": "127.0.0.1",
                "BROWSER": "none",
                "CI": "true",
                "NEXT_TELEMETRY_DISABLED": "1",
                # CRA / vite often respect these
                "WDS_SOCKET_PORT": str(port),
            },
        )

    if (work / "requirements.txt").exists() or (work / "pyproject.toml").exists():
        install_cmd = ["pip", "install", "-r", str(work / "requirements.txt")] \
            if (work / "requirements.txt").exists() else ["pip", "install", "."]
        # Best-guess: a FastAPI/Flask app at server.py, app.py or main.py.
        entry = next((c for c in ("server.py", "app.py", "main.py") if (work / c).exists()), None)
        boot_cmd = ["uvicorn", f"{entry.removesuffix('.py')}:app", "--host", "127.0.0.1", "--port", str(port)] \
            if entry else ["python", "-m", "http.server", str(port)]
        return DetectedStack(
            kind="python",
            workdir=work,
            install_cmd=install_cmd,
            boot_cmd=boot_cmd,
            port=port,
        )

    if (work / "index.html").exists():
        return DetectedStack(
            kind="static",
            workdir=work,
            install_cmd=None,
            boot_cmd=["python", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            port=port,
        )

    return DetectedStack(kind="unknown", workdir=work, port=port)


# ---------------------------------------------------------------------------
# Process control
# ---------------------------------------------------------------------------


async def _stream_output(proc: asyncio.subprocess.Process, on_log: Optional[LogFn], tag: str) -> None:
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            return
        msg = line.decode("utf-8", errors="replace").rstrip()
        logger.info("[%s] %s", tag, msg)
        if on_log:
            with contextlib.suppress(Exception):
                await on_log("info", f"{tag}: {msg[:240]}")


async def _wait_for_http(url: str, *, timeout: float) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=5.0) as http:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await http.get(url)
                if r.status_code < 500:
                    return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.8)
    return False


async def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    on_log: Optional[LogFn],
    timeout: int,
    display_cmd: Optional[list[str]] = None,
) -> int:
    if on_log:
        await on_log("info", f"$ {' '.join(display_cmd or cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env={**os.environ, **env},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    streamer = asyncio.create_task(_stream_output(proc, on_log, cmd[0]))
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124
    finally:
        streamer.cancel()
        with contextlib.suppress(Exception):
            await streamer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def boot_repo(
    github_url: str,
    *,
    on_log: Optional[LogFn] = None,
    github_token: Optional[str] = None,
) -> AsyncIterator[tuple[str, DetectedStack, Path]]:
    """Clone, install, and boot a GitHub repo. Yields (local_url, stack, repo_root).

    Always cleans up the cloned directory and the booted process on exit.
    """
    parsed = parse_github_url(github_url)
    if not parsed:
        raise ValueError(f"Not a recognisable GitHub URL: {github_url!r}")

    workdir = Path(tempfile.mkdtemp(prefix="atmos_repo_"))
    proc: Optional[asyncio.subprocess.Process] = None

    try:
        # 1) Clone (shallow)
        clone_url = parsed["clone_url"]
        display_clone_url = clone_url
        if github_token:
            # GitHub PATs are safest in the username field as x-access-token.
            clone_url = f"https://x-access-token:{github_token}@github.com/{parsed['owner']}/{parsed['repo']}.git"
        if on_log:
            await on_log("info", f"Cloning {parsed['owner']}/{parsed['repo']}…")
        rc = await _run(
            ["git", "clone", "--depth", "1", clone_url, str(workdir)],
            cwd=Path.cwd(), env={"GIT_TERMINAL_PROMPT": "0"}, on_log=on_log, timeout=CLONE_TIMEOUT,
            display_cmd=["git", "clone", "--depth", "1", display_clone_url, str(workdir)],
        )
        if rc != 0:
            raise RuntimeError(f"git clone failed (exit {rc})")

        # 2) Detect stack
        stack = detect_stack(workdir)
        if on_log:
            await on_log("info", f"Detected stack: {stack.kind} at {stack.workdir.relative_to(workdir) or '.'}")
        if stack.kind == "unknown":
            raise RuntimeError("Could not detect a runnable application in this repo.")

        # 3) Install
        if stack.install_cmd:
            if on_log:
                await on_log("info", "Installing dependencies (this can take a minute)…")
            rc = await _run(stack.install_cmd, cwd=stack.workdir, env=stack.env, on_log=on_log, timeout=INSTALL_TIMEOUT)
            if rc != 0:
                raise RuntimeError(f"dependency install failed (exit {rc})")

        # 4) Boot
        assert stack.boot_cmd is not None
        if on_log:
            await on_log("info", f"Booting: {' '.join(stack.boot_cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *stack.boot_cmd,
            cwd=str(stack.workdir),
            env={**os.environ, **stack.env},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        boot_streamer = asyncio.create_task(_stream_output(proc, on_log, "boot"))

        local_url = f"http://127.0.0.1:{stack.port}"
        ready = await _wait_for_http(local_url + stack.ready_path, timeout=BOOT_TIMEOUT)
        if not ready:
            raise RuntimeError(f"App at {local_url} did not respond within {BOOT_TIMEOUT}s")
        if on_log:
            await on_log("info", f"App is up at {local_url}")

        try:
            yield local_url, stack, workdir
        finally:
            boot_streamer.cancel()
            with contextlib.suppress(Exception):
                await boot_streamer
    finally:
        if proc and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
        # Keep the cloned repo on disk only while in use; remove on exit.
        with contextlib.suppress(Exception):
            shutil.rmtree(workdir, ignore_errors=True)
