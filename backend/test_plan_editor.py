"""AI test plan editor — generate editable plan before run execution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from user_llm_proxy import user_llm_json

logger = logging.getLogger("atmos.test_plan")

DEFAULT_CASE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "finance": [
        {"id": "tp_pay", "name": "Payment flow completes", "category": "Functional", "enabled": True,
         "steps": ["Navigate to payment", "Fill test card", "Submit", "Assert confirmation"]},
        {"id": "tp_trust", "name": "Trust signals visible", "category": "UX", "enabled": True,
         "steps": ["Land on checkout", "Verify security badges", "Verify SSL/trust copy"]},
    ],
    "e-commerce": [
        {"id": "tp_cart", "name": "Add to cart → checkout", "category": "Functional", "enabled": True,
         "steps": ["Find product", "Add to cart", "Open cart", "Proceed to checkout"]},
        {"id": "tp_mobile", "name": "Mobile checkout layout", "category": "Visual", "enabled": True,
         "steps": ["Open on iPhone viewport", "Verify CTA not obscured", "Verify cart summary visible"]},
    ],
    "generic": [
        {"id": "tp_home", "name": "Home page loads and primary CTA visible", "category": "UX", "enabled": True,
         "steps": ["Navigate to /", "Assert primary CTA visible within 5s"]},
        {"id": "tp_a11y", "name": "Keyboard navigation works", "category": "Accessibility", "enabled": True,
         "steps": ["Tab through interactive elements", "Assert focus visible"]},
    ],
}


async def generate_test_plan(
    db,
    user_id: str,
    project: dict[str, Any],
    command: str,
    *,
    codebase_summary: Optional[str] = None,
    page_url: Optional[str] = None,
) -> dict[str, Any]:
    app_type = project.get("app_type") or "generic"
    base_cases = DEFAULT_CASE_TEMPLATES.get(app_type, []) + DEFAULT_CASE_TEMPLATES["generic"]

    ctx_block = f"Codebase context:\n{codebase_summary}\n" if codebase_summary else ""
    prompt = (
        f"Product: {project.get('name')} ({app_type})\n"
        f"URL: {page_url or project.get('url')}\n"
        f"Command: {command}\n"
        f"{ctx_block}"
        "Return ONLY minified JSON:\n"
        '{"narrative":"1 sentence plan intro","focus_areas":["..."],"test_cases":['
        '{"id":"tp_x","name":"...","category":"UX|Visual|Functional|Accessibility","enabled":true,'
        '"steps":["step1","step2"],"rationale":"why"}]}\n'
        "Generate 6-10 specific test cases for THIS product. JSON only."
    )

    llm_plan = await user_llm_json(db, user_id, prompt, session_id=f"plan_{project.get('project_id')}")

    cases = llm_plan.get("test_cases") or []
    if not cases:
        cases = [{**c, "rationale": "Default template"} for c in base_cases]

    for i, c in enumerate(cases):
        c.setdefault("id", f"tp_{uuid.uuid4().hex[:6]}")
        c.setdefault("enabled", True)
        c.setdefault("category", "UX")
        c.setdefault("steps", [])
        c["order"] = i

    plan_id = f"plan_{uuid.uuid4().hex[:10]}"
    plan = {
        "plan_id": plan_id,
        "project_id": project["project_id"],
        "user_id": user_id,
        "command": command,
        "status": "draft",
        "narrative": llm_plan.get("narrative", f"Test plan for {project.get('name')}"),
        "focus_areas": llm_plan.get("focus_areas") or [],
        "test_cases": cases,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.test_plans.insert_one(dict(plan))
    plan.pop("_id", None)
    return plan


async def update_test_plan(db, plan_id: str, user_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    allowed = {"narrative", "focus_areas", "test_cases", "status", "command"}
    patch = {k: v for k, v in updates.items() if k in allowed}
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.test_plans.update_one(
        {"plan_id": plan_id, "user_id": user_id},
        {"$set": patch},
    )
    if result.matched_count == 0:
        return None
    return await db.test_plans.find_one({"plan_id": plan_id}, {"_id": 0})


def enabled_cases_from_plan(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not plan:
        return []
    return [c for c in (plan.get("test_cases") or []) if c.get("enabled", True)]
