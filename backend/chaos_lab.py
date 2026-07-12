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
            for url in urls:
                if time.monotonic() >= stop_at:
                    break
                tasks.append(asyncio.create_task(one(url)))
                if len(tasks) >= concurrency * 3:
                    await asyncio.gather(*tasks)
                    tasks = []
            await asyncio.sleep(0.05)
        if tasks:
            await asyncio.gather(*tasks)

    total = ok + errors
    return {
        "ok": ok,
        "errors": errors,
        "total": total,
        "success_rate": (ok / total) if total else 0.0,
        "latency_p50_ms": _pct(latencies, 50),
        "latency_p95_ms": _pct(latencies, 95),
        "latency_p99_ms": _pct(latencies, 99),
        "per_url": {
            u: {
                "ok": v["ok"],
                "err": v["err"],
                "latency_p95_ms": _pct(v["latencies"], 95),
                "requests": v["ok"] + v["err"],
            }
            for u, v in per_url.items()
        },
    }


async def _playwright_sample(
    browser: Browser,
    urls: list[str],
    users: int,
    *,
    include_payments: bool = False,
    payment_provider: str = "stripe",
) -> dict[str, Any]:
    """Small Playwright cohort for journey fidelity + payment field probes."""
    users = max(1, min(users, MAX_PLAYWRIGHT_USERS))
    latencies: list[float] = []
    ok = 0
    errors = 0
    payment_attempts = 0
    payment_ok = 0

    from payment_sandbox import PaymentOutcome, TestPaymentGenerator, PaymentProvider

    try:
        provider = PaymentProvider(payment_provider.lower())
    except Exception:  # noqa: BLE001
        provider = PaymentProvider.STRIPE
    gen = TestPaymentGenerator(provider)

    async def user_journey(idx: int) -> None:
        nonlocal ok, errors, payment_attempts, payment_ok
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,
        )
        page = await ctx.new_page()
        try:
            url = urls[idx % len(urls)]
            t0 = time.perf_counter()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(400)
            ms = (time.perf_counter() - t0) * 1000
            latencies.append(ms)
            status = resp.status if resp else 0
            if status and status >= 500:
                errors += 1
            else:
                ok += 1

            if include_payments:
                # Probe for payment-looking fields and fill Stripe test card when present
                card = page.locator(
                    "input[name*='card' i], input[autocomplete='cc-number'], "
                    "input[placeholder*='card' i], input[id*='card' i]"
                )
                if await card.count() > 0:
                    payment_attempts += 1
                    outcome = random.choice(
                        [PaymentOutcome.SUCCESS, PaymentOutcome.DECLINE, PaymentOutcome.INSUFFICIENT_FUNDS]
                    )
                    number = gen.generate_test_card(outcome)
                    try:
                        await card.first.fill(number, timeout=4000)
                        exp = page.locator("input[name*='exp' i], input[autocomplete='cc-exp']")
                        if await exp.count() > 0:
                            await exp.first.fill("12/34", timeout=2000)
                        cvc = page.locator("input[name*='cvc' i], input[autocomplete='cc-csc']")
                        if await cvc.count() > 0:
                            await cvc.first.fill("123", timeout=2000)
                        payment_ok += 1 if outcome == PaymentOutcome.SUCCESS else 0
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            errors += 1
        finally:
            await ctx.close()

    await asyncio.gather(*[user_journey(i) for i in range(users)])
    total = ok + errors
    return {
        "ok": ok,
        "errors": errors,
        "total": total,
        "success_rate": (ok / total) if total else 0.0,
        "latency_p95_ms": _pct(latencies, 95),
        "payment_attempts": payment_attempts,
        "payment_filled": payment_ok,
        "playwright_users": users,
    }


def _update_nodes_from_probe(
    graph: dict[str, Any],
    http_result: dict[str, Any],
    pw_result: dict[str, Any],
) -> list[dict[str, Any]]:
    per_url = http_result.get("per_url") or {}
    nodes = []
    for n in graph.get("nodes") or []:
        node = dict(n)
        if node.get("kind") == "route" and node.get("url") in per_url:
            stats = per_url[node["url"]]
            req = max(1, stats.get("requests") or 0)
            sr = stats.get("ok", 0) / req
            p95 = stats.get("latency_p95_ms") or 0
            node["requests"] = req
            node["errors"] = stats.get("err", 0)
            node["success_rate"] = round(sr, 3)
            node["latency_p95_ms"] = round(p95, 1)
            if sr < 0.5 or p95 > DEFAULT_BREAK_P95_MS * 1.5:
                node["health"] = "broken"
            elif sr < 0.85 or p95 > DEFAULT_BREAK_P95_MS:
                node["health"] = "critical"
            elif sr < 0.95 or p95 > 2000:
                node["health"] = "degraded"
            else:
                node["health"] = "healthy"
        elif node.get("kind") == "client":
            sr = pw_result.get("success_rate", 1.0)
            node["success_rate"] = round(sr, 3)
            node["latency_p95_ms"] = round(pw_result.get("latency_p95_ms") or 0, 1)
            node["health"] = "healthy" if sr >= 0.9 else "degraded" if sr >= 0.7 else "critical"
        elif node.get("kind") == "payment":
            attempts = pw_result.get("payment_attempts") or 0
            if attempts:
                node["requests"] = attempts
                node["health"] = "healthy" if (pw_result.get("payment_filled") or 0) > 0 else "degraded"
            else:
                node["health"] = "idle"
        elif node.get("kind") in {"api", "data", "edge"}:
            # Infer from aggregate HTTP
            sr = http_result.get("success_rate", 1.0)
            p95 = http_result.get("latency_p95_ms") or 0
            node["success_rate"] = round(sr, 3)
            node["latency_p95_ms"] = round(p95, 1)
            node["health"] = (
                "broken" if sr < 0.5
                else "critical" if sr < 0.85 or p95 > DEFAULT_BREAK_P95_MS
                else "degraded" if sr < 0.95 or p95 > 2000
                else "healthy"
            )
        nodes.append(node)
    graph["nodes"] = nodes
    return nodes


def _stage_broken(
    success_rate: float,
    p95: float,
    *,
    break_success_rate: float,
    break_p95_ms: float,
) -> tuple[bool, Optional[str]]:
    if success_rate < break_success_rate:
        return True, f"success_rate {success_rate:.0%} < {break_success_rate:.0%}"
    if p95 > break_p95_ms:
        return True, f"p95 {p95:.0f}ms > {break_p95_ms:.0f}ms"
    return False, None


async def run_chaos_lab(
    browser: Browser,
    *,
    base_url: str,
    pages: Optional[list[str]] = None,
    scope: str = "app",
    mode: str = "fixed",  # fixed | crash
    users: int = 50,
    max_users: int = 500,
    step_factor: float = 2.0,
    hold_secs: float = 10.0,
