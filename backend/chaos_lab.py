"""Chaos Lab — architecture-aware live stress + crash testing.

Replaces theatrical swarm/payment panels with:
- Scope: entire app or IDE/user-selected pages
- Modes: fixed concurrency OR crash-test (ramp until break)
- Hybrid load: HTTP volume + Playwright sample journeys
- Live architecture diagram health streamed as events
- Payment edge probes on checkout/payment routes (real browser fills)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import Browser

logger = logging.getLogger("atmos.chaos")

ProgressFn = Callable[[dict[str, Any]], Any]

# Hard caps — Playwright cannot run 10k browsers; HTTP carries volume.
MAX_PLAYWRIGHT_USERS = int(__import__("os").environ.get("ATMOS_CHAOS_MAX_PW", "25"))
MAX_HTTP_CONCURRENCY = int(__import__("os").environ.get("ATMOS_CHAOS_MAX_HTTP", "400"))
DEFAULT_BREAK_SUCCESS = 0.85
DEFAULT_BREAK_P95_MS = 5000.0


@dataclass
class ArchNode:
    id: str
    label: str
    kind: str  # client | route | api | payment | data | edge
    url: Optional[str] = None
    health: str = "idle"  # idle | healthy | degraded | critical | broken
    success_rate: float = 1.0
    latency_p95_ms: float = 0.0
    requests: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChaosStageResult:
    users: int
    success_rate: float
    error_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    broken: bool
    break_reason: Optional[str] = None
    node_health: list[dict[str, Any]] = field(default_factory=list)
    payment_summary: Optional[dict[str, Any]] = None
    duration_secs: float = 0.0


def _pct(latencies: list[float], p: float) -> float:
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return float(s[idx])


def _normalize_pages(base_url: str, pages: Optional[list[str]]) -> list[str]:
    base = base_url.rstrip("/")
    if not pages:
        return [base + "/"]
    out: list[str] = []
    for p in pages:
        p = (p or "").strip()
        if not p:
            continue
        if p.startswith("http"):
            out.append(p)
        else:
            out.append(urljoin(base + "/", p.lstrip("/")))
    # de-dupe preserve order
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq or [base + "/"]


def build_architecture_graph(
    *,
    base_url: str,
    pages: list[str],
    ide_files: Optional[list[dict[str, Any]]] = None,
    include_payments: bool = False,
) -> dict[str, Any]:
    """Build a live diagram model from selected pages + IDE context hints."""
    nodes: list[ArchNode] = [
        ArchNode(id="edge", label="Edge / CDN", kind="edge"),
        ArchNode(id="client", label="Client (browser)", kind="client"),
    ]
    edges: list[dict[str, str]] = [
        {"from": "client", "to": "edge"},
    ]

    for i, url in enumerate(pages):
        path = urlparse(url).path or "/"
        nid = f"route_{i}"
        nodes.append(ArchNode(id=nid, label=path, kind="route", url=url))
        edges.append({"from": "edge", "to": nid})
        edges.append({"from": nid, "to": "api"})

    nodes.append(ArchNode(id="api", label="Application API", kind="api"))
    nodes.append(ArchNode(id="data", label="Data / persistence", kind="data"))
    edges.append({"from": "api", "to": "data"})

    if include_payments or any(
        any(k in (urlparse(u).path or "").lower() for k in ("pay", "checkout", "billing", "cart"))
        for u in pages
    ):
        nodes.append(ArchNode(id="payment", label="Payments", kind="payment"))
        edges.append({"from": "api", "to": "payment"})

    # IDE layer hints
    layers: dict[str, int] = {}
    for f in ide_files or []:
        path = (f.get("path") or "").lower()
        for hint, layer in (
            ("components", "presentation"),
            ("pages", "routes"),
            ("api", "transport"),
            ("server", "server"),
            ("models", "domain"),
            ("db", "data"),
            ("prisma", "data"),
            ("stripe", "payment"),
        ):
            if hint in path:
                layers[layer] = layers.get(layer, 0) + 1

    return {
        "nodes": [n.to_dict() for n in nodes],
        "edges": edges,
        "layers": layers,
        "scope_pages": pages,
        "base_url": base_url,
    }


async def _http_probe_batch(
    urls: list[str],
    concurrency: int,
    *,
    hold_secs: float = 8.0,
) -> dict[str, Any]:
    """Hammer URLs with HTTP GET volume; return per-URL + aggregate latencies."""
    concurrency = max(1, min(concurrency, MAX_HTTP_CONCURRENCY))
    latencies: list[float] = []
    errors = 0
    ok = 0
    per_url: dict[str, dict[str, Any]] = {u: {"ok": 0, "err": 0, "latencies": []} for u in urls}
    stop_at = time.monotonic() + hold_secs
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as client:
        async def one(url: str) -> None:
            nonlocal ok, errors
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.get(url)
                    ms = (time.perf_counter() - t0) * 1000
                    latencies.append(ms)
                    per_url[url]["latencies"].append(ms)
                    if 200 <= r.status_code < 500:
                        ok += 1
                        per_url[url]["ok"] += 1
                    else:
                        errors += 1
                        per_url[url]["err"] += 1
                except Exception:  # noqa: BLE001
                    ms = (time.perf_counter() - t0) * 1000
                    latencies.append(ms)
                    errors += 1
                    per_url[url]["err"] += 1

        tasks = []
        # Keep the pool saturated until hold expires
        while time.monotonic() < stop_at:
