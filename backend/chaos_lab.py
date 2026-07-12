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
