"""Backend integration tests for Atmos."""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ai-testing-agent.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="session")
def mongo_db():
    cli = MongoClient(MONGO_URL)
    return cli[DB_NAME]


@pytest.fixture(scope="session")
def auth_token(mongo_db):
    """Inject a test user + session and return Bearer token."""
    import datetime as dt
    user_id = f"test-user-{int(time.time()*1000)}"
    token = f"test_session_{int(time.time()*1000)}"
    mongo_db.users.insert_one({
        "user_id": user_id,
        "email": f"qa.{int(time.time())}@example.com",
        "name": "QA Atmos",
        "picture": None,
        "created_at": dt.datetime.utcnow().isoformat(),
    })
    mongo_db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": token,
        "expires_at": (dt.datetime.utcnow() + dt.timedelta(days=7)).isoformat(),
        "created_at": dt.datetime.utcnow().isoformat(),
    })
    yield {"token": token, "user_id": user_id}


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token['token']}", "Content-Type": "application/json"}


# --- Health ---------------------------------------------------------------
class TestHealth:
    def test_root(self):
        r = requests.get(f"{API}/")
        assert r.status_code == 200
        data = r.json()
        assert data == {"service": "atmos", "ok": True}

    def test_commands(self):
        r = requests.get(f"{API}/commands")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 10
        cmds = {c["cmd"] for c in data}
        for required in ["/atmos analyze", "/atmos test", "/atmos report", "/atmos mobile"]:
            assert required in cmds


# --- Auth -----------------------------------------------------------------
class TestAuth:
    def test_auth_me_unauthenticated_returns_401(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_auth_me_with_bearer(self, auth_headers, auth_token):
        r = requests.get(f"{API}/auth/me", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["user_id"] == auth_token["user_id"]
        assert "email" in data and "name" in data


# --- Projects + Runs ------------------------------------------------------
class TestProjectsAndRuns:
    def test_create_and_list_project(self, auth_headers):
        payload = {"name": "TEST_Stripe", "url": "https://stripe.com"}
        r = requests.post(f"{API}/projects", headers=auth_headers, json=payload)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["name"] == "TEST_Stripe"
        assert proj["url"].startswith("https://stripe.com")
        assert proj["app_type"] == "finance"
        assert "project_id" in proj
        pytest.project_id = proj["project_id"]

        # GET list verifies persistence and last_run=null
        r = requests.get(f"{API}/projects", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()
        match = [x for x in items if x["project"]["project_id"] == proj["project_id"]]
        assert len(match) == 1
        assert match[0]["last_run"] is None

    def test_invalid_command_returns_400(self, auth_headers):
        r = requests.post(
            f"{API}/projects/{pytest.project_id}/runs",
            headers=auth_headers,
            json={"command": "/atmos nope"},
        )
        assert r.status_code == 400

    def test_start_run_and_wait_for_completion(self, auth_headers):
        r = requests.post(
            f"{API}/projects/{pytest.project_id}/runs",
            headers=auth_headers,
            json={"command": "/atmos test"},
        )
        assert r.status_code == 200
        run_id = r.json()["run_id"]
        assert run_id.startswith("run_")
        pytest.run_id = run_id

        # Initial GET — run + project + events present, status=running
        r = requests.get(f"{API}/runs/{run_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["run"]["run_id"] == run_id
        assert data["project"]["project_id"] == pytest.project_id
        assert isinstance(data["events"], list)

        # Wait up to 60s for completion
        deadline = time.time() + 60
        status = None
        last_events = 0
        while time.time() < deadline:
            r = requests.get(f"{API}/runs/{run_id}", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()
            status = data["run"]["status"]
            last_events = len(data["events"])
            if status in ("completed", "failed"):
                break
            time.sleep(2)
        assert status == "completed", f"final status={status} events={last_events}"
        assert last_events > 10, f"only {last_events} events emitted"

        summary = data["run"]["summary"]
        assert summary is not None
        for key in ["scores", "counts", "personas", "issues", "benchmarks",
                    "focus_areas", "narrative", "critical_findings",
                    "recommendations", "competitive_insight"]:
            assert key in summary, f"missing {key}"
        for k in ("accessibility", "ux", "reliability"):
            assert k in summary["scores"]
            assert isinstance(summary["scores"][k], int)
        assert len(summary["personas"]) >= 5
        assert len(summary["issues"]) >= 5
        assert len(summary["benchmarks"]) >= 1


# --- Authorization isolation ---------------------------------------------
class TestAuthorizationIsolation:
    def test_other_user_cannot_access_project(self, mongo_db):
        import datetime as dt
        # Create a second user/session
        other_user = f"test-user-other-{int(time.time()*1000)}"
        other_token = f"test_session_other_{int(time.time()*1000)}"
        mongo_db.users.insert_one({
            "user_id": other_user, "email": f"other.{int(time.time())}@x.com",
            "name": "Other", "picture": None,
            "created_at": dt.datetime.utcnow().isoformat(),
        })
        mongo_db.user_sessions.insert_one({
            "user_id": other_user, "session_token": other_token,
            "expires_at": (dt.datetime.utcnow() + dt.timedelta(days=7)).isoformat(),
            "created_at": dt.datetime.utcnow().isoformat(),
        })
        h = {"Authorization": f"Bearer {other_token}"}
        r = requests.get(f"{API}/projects/{pytest.project_id}", headers=h)
        assert r.status_code == 404
        r = requests.get(f"{API}/runs/{pytest.run_id}", headers=h)
        assert r.status_code == 404
