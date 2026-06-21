"""Atmos multi-page crawler engine tests (iteration: page_url + app_graph)."""
import io
import os
import requests
import pytest
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

EXISTING_RUN = "run_9bdb36733a"
EXISTING_TOKEN = "crawl_session_1782024481138"


@pytest.fixture(scope="module")
def mongo_db():
    return MongoClient(MONGO_URL)[DB_NAME]


# Backend health
class TestHealth:
    def test_root(self):
        r = requests.get(f"{API}/")
        assert r.status_code == 200
        assert r.json() == {"service": "atmos", "ok": True}


# Validate existing completed multi-page run
class TestExistingMultiPageRun:
    def test_run_completed_with_app_graph(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": EXISTING_RUN}, {"_id": 0})
        assert run is not None, "expected seeded multi-page run"
        assert run["status"] == "completed"
        summary = run["summary"]
        ag = summary.get("app_graph", [])
        assert isinstance(ag, list) and len(ag) >= 2
        for p in ag:
            caps = p.get("captures", {})
            assert "iPhone SE" in caps and "Desktop 1440" in caps
            for vp_label in ("iPhone SE", "Desktop 1440"):
                cap = caps[vp_label]
                assert cap.get("ok") is True
                assert cap.get("url_path", "").startswith("/api/screens/")

    def test_issues_carry_page_url_and_full_payload(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": EXISTING_RUN}, {"_id": 0})
        summary = run["summary"]
        issues = summary["issues"]
        assert len(issues) >= 1
        ag_urls = {p["url"] for p in summary["app_graph"]}
        viewports = {"iPhone SE", "Desktop 1440"}
        for iss in issues:
            assert iss.get("page_url") in ag_urls
            assert isinstance(iss.get("page_title", ""), str)
            assert iss.get("viewport") in viewports
            assert iss["before"]["screenshot_url"].startswith("/api/screens/")
            assert iss["after"]["screenshot_url"].startswith("/api/screens/")
            assert len(iss.get("alternatives", [])) >= 1
            for alt in iss["alternatives"]:
                assert alt.get("screenshot_url", "").startswith("/api/screens/")
                assert "patch_css" in alt

    def test_issues_distributed_across_pages(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": EXISTING_RUN}, {"_id": 0})
        issues = run["summary"]["issues"]
        per_page = {}
        for i in issues:
            per_page[i["page_url"]] = per_page.get(i["page_url"], 0) + 1
        # both home + form page should appear
        assert "https://httpbin.org" in per_page
        assert "https://httpbin.org/forms/post" in per_page
        assert per_page["https://httpbin.org"] >= 1
        assert per_page["https://httpbin.org/forms/post"] >= 1


# Verify full-page screenshots are tall (height > 800)
class TestFullPageScreenshots:
    def test_static_mount_serves_png_and_image_is_tall(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": EXISTING_RUN}, {"_id": 0})
        # Spot-check a Desktop 1440 baseline from app_graph
        url_path = None
        for p in run["summary"]["app_graph"]:
            cap = p["captures"].get("Desktop 1440") or {}
            if cap.get("url_path"):
                url_path = cap["url_path"]
                break
        assert url_path is not None
        r = requests.get(f"{BASE_URL}{url_path}")
        assert r.status_code == 200
        assert r.headers.get("content-type") == "image/png"
        assert len(r.content) > 5000

        # Validate height > 800 with PIL
        from PIL import Image
        img = Image.open(io.BytesIO(r.content))
        assert img.height > 800, f"expected full-page tall capture, got h={img.height}"

    def test_after_screenshots_are_tall(self, mongo_db):
        run = mongo_db.test_runs.find_one({"run_id": EXISTING_RUN}, {"_id": 0})
        from PIL import Image
        tall_count = 0
        for iss in run["summary"]["issues"][:3]:
            url_path = iss["after"]["screenshot_url"]
            r = requests.get(f"{BASE_URL}{url_path}")
            assert r.status_code == 200
            img = Image.open(io.BytesIO(r.content))
            if img.height > 800:
                tall_count += 1
        assert tall_count >= 1, "at least one after image should be full-page tall"
