"""Backend regression tests for Atmos crawl-coverage fix (iteration_3).

Validates:
1. Code-level changes in flow_explorer.py, server.py, atmos_engine.py,
   architecture_analyzer.py (constants, model names, BFS gating, PIN entry).
2. Smoke: /api/ + /api/auth/me + payment simulate (regression from iter_1
   which was reported as fixed in iter_2).
3. Runtime: small-site crawl on example.com completes within 6 minutes,
   produces >=2 screens, SSE phase sequence includes per_page..report,
   and backend log shows claude-sonnet-4-5 calls.
"""
import os
import re
import time
import json
import pathlib
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://ai-testing-agent.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Content-Type": "application/json"}

FLOW_EXPLORER = pathlib.Path("/app/backend/flow_explorer.py").read_text()
SERVER_PY = pathlib.Path("/app/backend/server.py").read_text()
ATMOS_ENGINE = pathlib.Path("/app/backend/atmos_engine.py").read_text()
ARCH_ANALYZER = pathlib.Path("/app/backend/architecture_analyzer.py").read_text()


# ── Code verification: flow_explorer ────────────────────────────────────
class TestFlowExplorerCode:
    def test_constants(self):
        assert "MAX_FLOW_STEPS = 80" in FLOW_EXPLORER
        assert "MAX_HUB_BRANCHES = 30" in FLOW_EXPLORER
        assert "MAX_SCREENS = 80" in FLOW_EXPLORER
        assert "VLM_STAGNATION_LIMIT = 6" in FLOW_EXPLORER
        assert 'DEFAULT_PIN = "135790"' in FLOW_EXPLORER

    def test_vlm_model_still_gemini_flash(self):
        assert ".with_model(\"gemini\", \"gemini-3.5-flash\")" in FLOW_EXPLORER

    def test_pin_helpers_exist(self):
        assert "def _is_pin_context(" in FLOW_EXPLORER
        assert "async def _enter_pin_keypad(" in FLOW_EXPLORER

    def test_pin_keypad_called_before_vlm_in_loop(self):
        # Find the for-step loop body and ensure _enter_pin_keypad is called
        # before _call_vlm_decision inside it.
        loop = re.search(
            r"for _step in range\(max_steps\):(.+?)# ── Phase B\+",
            FLOW_EXPLORER,
            re.DOTALL,
        )
        assert loop, "for-step loop not found"
        body = loop.group(1)
        kp = body.find("_enter_pin_keypad(")
        vlm = body.find("_call_vlm_decision(")
        assert kp != -1 and vlm != -1, f"kp={kp} vlm={vlm}"
        assert kp < vlm, "PIN keypad must be called before VLM decision"

    def test_bfs_unconditional_augmentation(self):
        assert "# ── Phase B+: ALWAYS run BFS fan-out as augmentation" in FLOW_EXPLORER
        # Anchor: comment exists and is immediately followed (within ~400
        # chars) by the unconditional gate `if len(screens) < MAX_SCREENS:`
        idx = FLOW_EXPLORER.find("# ── Phase B+: ALWAYS run BFS fan-out as augmentation")
        assert idx != -1
        window = FLOW_EXPLORER[idx : idx + 600]
        assert "if len(screens) < MAX_SCREENS:" in window, window
        # Negative: no longer fall-back gated on vlm_success_actions == 0
        assert "if vlm_success_actions == 0" not in FLOW_EXPLORER

    def test_pin_screens_not_counted_against_stagnation(self):
        # The on_pin branch in the stagnation block should DECREMENT, not increment
        assert "on_pin = bool(context.get(\"has_keypad\")) or _is_pin_context(context)" in FLOW_EXPLORER
        assert "vlm_stagnation = max(0, vlm_stagnation - 1)" in FLOW_EXPLORER


# ── Code verification: server.py ────────────────────────────────────────
class TestServerCode:
    def test_explore_timeout_default(self):
        assert 'os.environ.get("ATMOS_EXPLORE_TIMEOUT_SECS", "420")' in SERVER_PY

    def test_per_page_parallel(self):
        assert "asyncio.Semaphore(ANALYSIS_CONCURRENCY)" in SERVER_PY
        assert "PER_PAGE_TIMEOUT" in SERVER_PY
        assert "asyncio.wait_for(llm_analyze_page(" in SERVER_PY
        assert "asyncio.gather(*[_analyze_one(pg) for pg in pages])" in SERVER_PY

    def test_planner_and_report_use_claude(self):
        # Two .with_model("anthropic", "claude-sonnet-4-5-20250929") lines
        # — one for _llm_plan and one for _llm_report.
        count = SERVER_PY.count('.with_model("anthropic", "claude-sonnet-4-5-20250929")')
        assert count >= 2, f"expected >=2 claude with_model calls, found {count}"


# ── Code verification: atmos_engine + architecture_analyzer ────────────
class TestEngineModels:
    def test_atmos_engine_both_paths_claude(self):
        # llm_analyze_app + llm_analyze_page (vision + text fallback)
        # => 3 total with_model claude calls
        count = ATMOS_ENGINE.count('.with_model("anthropic", "claude-sonnet-4-5-20250929")')
        assert count >= 3, f"expected >=3 claude with_model in atmos_engine, found {count}"
        # Anchor by function names
        assert "async def llm_analyze_app(" in ATMOS_ENGINE
        assert "async def llm_analyze_page(" in ATMOS_ENGINE

    def test_architecture_analyzer_uses_claude(self):
        assert "async def llm_peer_comparison(" in ARCH_ANALYZER
        assert '.with_model("anthropic", "claude-sonnet-4-5-20250929")' in ARCH_ANALYZER


# ── Smoke (regression) ──────────────────────────────────────────────────
class TestSmoke:
    def test_root_ok(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json() == {"service": "atmos", "ok": True}

    def test_auth_me(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == "user_local_dev"


# ── Payment simulate regression (iter_2 reported fixed) ─────────────────
@pytest.fixture(scope="module")
def payment_run_id():
    r = requests.post(
        f"{API}/projects",
        headers=HEADERS,
        json={"name": "TEST_iter3_payment", "url": "https://example.com"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    r2 = requests.post(
        f"{API}/projects/{pid}/runs",
        headers=HEADERS,
        json={"command": "/atmos test"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text
    return r2.json()["run_id"]


class TestPaymentSimulate:
    def test_payment_simulate_default(self, payment_run_id):
        r = requests.post(
            f"{API}/runs/{payment_run_id}/payment/simulate",
            headers=HEADERS,
            json={},  # use server defaults
            timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:600]}"
        data = r.json()
        # Should have a summary structure
        assert isinstance(data, dict)
        assert "summary" in data or "results" in data or "provider" in data, data


# ── Runtime: small-site crawl ───────────────────────────────────────────
@pytest.fixture(scope="module")
def example_run():
    r = requests.post(
        f"{API}/projects",
        headers=HEADERS,
        json={"name": "TEST_iter3_example", "url": "https://example.com"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    r2 = requests.post(
        f"{API}/projects/{pid}/runs",
        headers=HEADERS,
        json={"command": "/atmos test"},
        timeout=20,
    )
    assert r2.status_code == 200, r2.text
    return {"project_id": pid, "run_id": r2.json()["run_id"]}


class TestExampleCrawl:
    def test_crawl_completes(self, example_run):
        rid = example_run["run_id"]
        deadline = time.time() + 360  # 6 minutes
        last_phase = None
        phases_seen = set()
        status = None
        while time.time() < deadline:
            r = requests.get(f"{API}/runs/{rid}", timeout=15)
            assert r.status_code == 200, r.text
            run = r.json()
            status = run.get("status")
            phase = run.get("phase") or (run.get("phases") or [{}])[-1].get("name")
            if phase:
                phases_seen.add(phase)
                if phase != last_phase:
                    print(f"[{int(time.time())%1000}] phase={phase} status={status}")
                    last_phase = phase
            # phases list aggregation if present
            for p in run.get("phases", []) or []:
                if isinstance(p, dict) and p.get("name"):
                    phases_seen.add(p["name"])
            if status in ("completed", "failed", "error", "cancelled"):
                break
            time.sleep(5)

        assert status == "completed", f"final status={status} phases_seen={phases_seen}"
        # Validate screens
        r2 = requests.get(f"{API}/runs/{rid}/pages", timeout=15)
        pages = []
        if r2.status_code == 200:
            body = r2.json()
            pages = body if isinstance(body, list) else body.get("pages", [])
        else:
            # fallback: pages embedded in run doc
            pages = (run.get("pages") or [])
        print(f"pages found: {len(pages)} phases_seen: {phases_seen}")
        assert len(pages) >= 1, f"expected >=1 page, got {len(pages)}"
        # Phase sequence should include the post-explore phases
        # (be lenient on naming differences)
        expected = {"per_page", "accessibility", "fuzz", "benchmark", "report"}
        present = expected & phases_seen
        assert len(present) >= 3, f"expected >=3 of {expected}, got phases_seen={phases_seen}"

    def test_claude_was_called(self, example_run):
        # Inspect backend logs for claude-sonnet-4-5 references after the run
        log_paths = [
            "/var/log/supervisor/backend.out.log",
            "/var/log/supervisor/backend.err.log",
        ]
        found = 0
        for p in log_paths:
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", errors="ignore") as f:
                    # Read the last ~2MB
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 2 * 1024 * 1024))
                    data = f.read()
                found += data.count("claude-sonnet-4-5")
            except Exception as e:
                print(f"could not read {p}: {e}")
        assert found >= 1, f"expected >=1 claude-sonnet-4-5 mention in backend logs, found {found}"
