"""Tenant / ownership guards for multi-user isolation."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from rbac import get_project_for_user, project_query_for_user, require_permission


async def require_run_for_user(db, run_id: str, user_id: str, *, permission: Optional[str] = None) -> dict[str, Any]:
    """Load a run owned by the user, or visible via org project membership."""
    run = await db.test_runs.find_one({"run_id": run_id, "user_id": user_id}, {"_id": 0})
    if run:
        if permission:
            # Owner still needs the capability when acting on org-scoped features
            member = await db.org_members.find_one({"user_id": user_id}, {"_id": 1})
            if member:
                await require_permission(db, user_id, permission)
        return run

    run = await db.test_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Org-shared: run's project must be visible; enforce permission for non-owners
    q = await project_query_for_user(db, user_id)
    q["project_id"] = run["project_id"]
    proj = await db.projects.find_one(q, {"_id": 0})
    if not proj:
        raise HTTPException(status_code=404, detail="Run not found")
    if permission:
        await require_permission(db, user_id, permission)
    return run


async def require_project_for_user(
    db, project_id: str, user_id: str, *, permission: str = "projects:read"
) -> dict[str, Any]:
    """Delegate to rbac — owners skip permission; org peers need it."""
    return await get_project_for_user(db, user_id, project_id, permission=permission)
