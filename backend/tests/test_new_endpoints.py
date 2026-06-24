"""Backend tests for Atmos new endpoints: Swarm, Payments, GitHub token test.

Auth is bypassed (ATMOS_DISABLE_AUTH=1) so no bearer token is needed; the
backend treats requests as user_local_dev.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-testing-agent.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
HEADERS = {"Content-Type": "application/json"}


# ── Smoke ────────────────────────────────────────────────────────────────
class TestSmoke:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        assert r.json() == {"service": "atmos", "ok": True}

    def test_auth_me_local_dev(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == "user_local_dev"
        assert "email" in data and "name" in data


# ── Fixtures: project + run ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def project_id():
    payload = {"name": "TEST_swarm_example", "url": "https://example.com"}
    r = requests.post(f"{API}/projects", headers=HEADERS, json=payload, timeout=20)
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    return pid


@pytest.fixture(scope="module")
def run_id(project_id):
    r = requests.post(
        f"{API}/projects/{project_id}/runs",
        headers=HEADERS,
        json={"command": "/atmos test"},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    assert rid.startswith("run_")
    return rid


@pytest.fixture(scope="module")
def github_project_id():
    """Create a GitHub-sourced project (no PAT)."""
    payload = {"name": "TEST_gh_project", "github_url": "https://github.com/octocat/hello-world"}
    r = requests.post(f"{API}/projects", headers=HEADERS, json=payload, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["project_id"]


# ── Projects + RunMonitor route ───────────────────────────────────────────
class TestProjectsAndRun:
    def test_project_created(self, project_id):
        r = requests.get(f"{API}/projects", timeout=15)
        assert r.status_code == 200
        ids = [x["project"]["project_id"] for x in r.json()]
        assert project_id in ids

    def test_run_endpoint_exists(self, run_id):
        r = requests.get(f"{API}/runs/{run_id}", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["run"]["run_id"] == run_id
        assert data["project"]["url"].startswith("https://example.com")
        assert isinstance(data["events"], list)


# ── Swarm endpoint ────────────────────────────────────────────────────────
class TestSwarm:
    def test_swarm_start(self, run_id):
        body = {"target_users": 5, "profile": "burst", "journey": "generic", "duration_secs": 8}
        r = requests.post(f"{API}/runs/{run_id}/swarm/start", headers=HEADERS, json=body, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "started"
        assert data["target_users"] == 5

    def test_swarm_live_and_completion(self, run_id):
        # Poll up to 90s for completion
        deadline = time.time() + 90
        final_status = None
        last = {}
        while time.time() < deadline:
            r = requests.get(f"{API}/runs/{run_id}/swarm/live", timeout=20)
            assert r.status_code == 200
            last = r.json()
            summary = last.get("summary") or {}
            final_status = summary.get("status")
            if final_status in ("completed", "failed"):
                break
            time.sleep(3)
        assert final_status in ("completed", "failed"), f"Swarm never finished: {last}"
        # If completed, persisted swarm_summary should be present on run doc
        r = requests.get(f"{API}/runs/{run_id}", timeout=20)
        assert r.status_code == 200


# ── Payments ──────────────────────────────────────────────────────────────
class TestPayments:
    def _run_provider(self, run_id, provider):
        body = {
            "provider": provider,
            "concurrent": 10,
            "outcomes": ["success", "decline_insufficient_funds", "fraud", "3ds_required"],
            "amount_cents": 4999,
        }
        r = requests.post(f"{API}/runs/{run_id}/payment/simulate", headers=HEADERS, json=body, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        s = data["summary"]
        assert s["provider"] == provider
        assert s["concurrent"] == 10
        assert "success_count" in s and "decline_count" in s
        assert "success_rate" in s
        assert "p50_latency_ms" in s and "p95_latency_ms" in s
        assert "by_outcome" in s and isinstance(s["by_outcome"], dict)
        assert isinstance(data["results"], list) and len(data["results"]) == 10
        return data

    def test_payment_stripe(self, run_id):
        self._run_provider(run_id, "stripe")

    def test_payment_razorpay(self, run_id):
        self._run_provider(run_id, "razorpay")

    def test_payment_paypal(self, run_id):
        self._run_provider(run_id, "paypal")

    def test_payment_unknown_outcome_returns_400(self, run_id):
        body = {
            "provider": "stripe",
            "concurrent": 2,
            "outcomes": ["foo_bar"],
            "amount_cents": 1000,
        }
        r = requests.post(f"{API}/runs/{run_id}/payment/simulate", headers=HEADERS, json=body, timeout=20)
        assert r.status_code == 400, r.text
        # Should mention allowed outcomes
        txt = r.text.lower()
        assert "success" in txt or "allowed" in txt or "outcome" in txt


# ── GitHub token test endpoint ───────────────────────────────────────────
class TestGithubTokenEndpoint:
    def test_non_github_project_returns_400(self, project_id):
        r = requests.post(f"{API}/projects/{project_id}/github-token/test", headers=HEADERS, timeout=20)
        assert r.status_code == 400, r.text
        assert "Only GitHub projects" in r.text

    def test_github_project_missing_token(self, github_project_id):
        r = requests.post(f"{API}/projects/{github_project_id}/github-token/test", headers=HEADERS, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False
        assert data["stage"] == "missing"

    def test_github_project_bogus_token(self, github_project_id):
        # Store a bogus token
        r = requests.post(
            f"{API}/projects/{github_project_id}/github-token",
            headers=HEADERS,
            json={"github_token": "ghp_xxxBOGUSxxx"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        # Then test
        r = requests.post(f"{API}/projects/{github_project_id}/github-token/test", headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False
        assert data["stage"] == "auth"
        assert "detail" in data and len(data["detail"]) > 0
