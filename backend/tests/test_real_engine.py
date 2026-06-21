"""Tests for the real Playwright + vision-LLM engine in Atmos."""
import os
import time
import datetime as dt
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-testing-agent.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo_db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def auth(mongo_db):
    user_id = f"test-user-{int(time.time()*1000)}"
    token = f"test_session_{int(time.time()*1000)}"
    mongo_db.users.insert_one({
        "user_id": user_id,
        "email": f"qa.real.{int(time.time())}@example.com",
        "name": "QA Real",
        "picture": None,
        "created_at": dt.datetime.utcnow().isoformat(),
    })
    mongo_db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (dt.datetime.utcnow() + dt.timedelta(days=7)).isoformat(),
        "created_at": dt.datetime.utcnow().isoformat(),
    })
    return {"token": token, "user_id": user_id}


@pytest.fixture
def headers(auth):
    return {"Authorization": f"Bearer {auth['token']}", "Content-Type": "application/json"}


# --- Health / Mount -------------------------------------------------------
class TestHealthAndMount:
    def test_root(self):
        r = requests.get(f"{API}/")
        assert r.status_code == 200
        assert r.json() == {"service": "atmos", "ok": True}

    def test_commands_returns_10(self):
        r = requests.get(f"{API}/commands")
        assert r.status_code == 200
        assert len(r.json()) == 10

    def test_screens_mount_serves_existing_png(self):
        fname = "run_5e32a27f13_Desktop_1440_baseline.png"
        r = requests.get(f"{API}/screens/{fname}")
        assert r.status_code == 200
        assert r.headers.get("content-type") == "image/png"
        assert len(r.content) > 5000


# --- Pre-existing real run on github.com ----------------------------------
class TestExistingRealRun(object):
    """run_5e32a27f13 already exists in DB and should show real PNG URLs."""

    def test_existing_run_has_real_screenshots(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": "run_5e32a27f13"}, {"_id": 0})
        assert run is not None, "Expected seeded run_5e32a27f13 in DB"
        assert run["status"] == "completed"
        summary = run["summary"]
        assert summary is not None
        issues = summary.get("issues", [])
        assert len(issues) >= 1
        for iss in issues:
            for key in ("id", "category", "severity", "title", "viewport",
                        "before", "after", "alternatives"):
                assert key in iss, f"missing {key} in issue"
            assert iss["before"]["screenshot_url"].startswith("/api/screens/")
            assert iss["after"]["screenshot_url"].startswith("/api/screens/")
            assert isinstance(iss["after"].get("code"), str)
            assert len(iss["alternatives"]) >= 1
            for alt in iss["alternatives"]:
                assert alt["screenshot_url"].startswith("/api/screens/")
                assert "patch_css" in alt

    def test_existing_run_screenshot_urls_serve_png(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": "run_5e32a27f13"}, {"_id": 0})
        urls = set()
        for iss in run["summary"]["issues"][:3]:
            urls.add(iss["before"]["screenshot_url"])
            urls.add(iss["after"]["screenshot_url"])
            for alt in iss["alternatives"]:
                urls.add(alt["screenshot_url"])
        for path in list(urls)[:8]:
            r = requests.get(f"{BASE_URL}{path}")
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            assert r.headers.get("content-type") == "image/png"
            assert len(r.content) > 5000, f"{path} only {len(r.content)} bytes"


# --- Fresh real run against example.com -----------------------------------
class TestFreshRun:
    def test_fresh_run_against_example_com(self, headers):
        # Create a project
        r = requests.post(f"{API}/projects", headers=headers,
                          json={"name": "TEST_example", "url": "https://example.com"})
        assert r.status_code == 200, r.text
        project_id = r.json()["project_id"]

        # Start a run
        r = requests.post(f"{API}/projects/{project_id}/runs",
                          headers=headers, json={"command": "/atmos test"})
        assert r.status_code == 200, r.text
        run_id = r.json()["run_id"]

        # Wait up to 3 minutes
        deadline = time.time() + 180
        status = None
        data = None
        while time.time() < deadline:
            r = requests.get(f"{API}/runs/{run_id}", headers=headers, timeout=10)
            assert r.status_code == 200
            data = r.json()
            status = data["run"]["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(3)

        assert status == "completed", f"final status={status}"
        summary = data["run"]["summary"]
        assert summary is not None

        # captures (4 viewports)
        captures = summary.get("captures", [])
        assert isinstance(captures, list) and len(captures) == 4
        ok_caps = [c for c in captures if c.get("ok")]
        assert len(ok_caps) >= 1, "no viewports captured"
        for c in ok_caps:
            r = requests.get(f"{BASE_URL}{c['url_path']}")
            assert r.status_code == 200
            assert len(r.content) > 5000

        # issues
        issues = summary.get("issues", [])
        assert len(issues) >= 1, "no issues produced"

        checked_after = 0
        checked_alt = 0
        for iss in issues:
            for key in ("id", "category", "severity", "title", "viewport",
                        "before", "after", "alternatives"):
                assert key in iss

            # before
            before_url = iss["before"]["screenshot_url"]
            assert before_url.startswith("/api/screens/")
            r = requests.get(f"{BASE_URL}{before_url}")
            assert r.status_code == 200 and len(r.content) > 5000

            # after — may be None if patch capture failed; if present must serve
            after_url = iss["after"].get("screenshot_url")
            assert isinstance(iss["after"].get("code"), str)
            if after_url:
                r = requests.get(f"{BASE_URL}{after_url}")
                assert r.status_code == 200 and len(r.content) > 5000
                checked_after += 1

            # alternatives — at least 1, each has patch_css
            assert len(iss["alternatives"]) >= 1
            for alt in iss["alternatives"]:
                assert "patch_css" in alt
                if alt.get("screenshot_url"):
                    r = requests.get(f"{BASE_URL}{alt['screenshot_url']}")
                    assert r.status_code == 200 and len(r.content) > 5000
                    checked_alt += 1

        # We should have verified at least one real after + one real alternative shot
        assert checked_after >= 1, "no after screenshots verified"
        assert checked_alt >= 1, "no alternative screenshots verified"
