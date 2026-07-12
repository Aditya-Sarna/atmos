"""Role-based access control — admin-configurable read/write permissions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException

# All granular permissions (database-style read/write splits)
ALL_PERMISSIONS: list[dict[str, str]] = [
    {"id": "projects:read", "label": "View projects", "group": "Projects"},
    {"id": "projects:write", "label": "Create & edit projects", "group": "Projects"},
    {"id": "projects:delete", "label": "Delete projects", "group": "Projects"},
    {"id": "runs:read", "label": "View test runs & reports", "group": "Runs"},
    {"id": "runs:start", "label": "Start new test runs", "group": "Runs"},
    {"id": "runs:write", "label": "Apply patches & swarm tests", "group": "Runs"},
    {"id": "test_cases:read", "label": "View custom test cases", "group": "Test Cases"},
    {"id": "test_cases:write", "label": "Create & edit custom test cases", "group": "Test Cases"},
    {"id": "members:read", "label": "View team members", "group": "Team"},
    {"id": "members:write", "label": "Invite & remove members", "group": "Team"},
    {"id": "roles:manage", "label": "Manage roles & permissions", "group": "Team"},
    {"id": "settings:read", "label": "View org settings", "group": "Settings"},
    {"id": "settings:write", "label": "Edit org settings", "group": "Settings"},
]

PERMISSION_IDS = {p["id"] for p in ALL_PERMISSIONS}

DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": set(PERMISSION_IDS),
    "developer": {
        "projects:read", "projects:write",
        "runs:read", "runs:start", "runs:write",
        "test_cases:read", "test_cases:write",
        "members:read", "settings:read",
    },
    "designer": {
        "projects:read",
        "runs:read", "runs:start",
        "test_cases:read", "test_cases:write",
        "members:read", "settings:read",
    },
    "viewer": {
        "projects:read", "runs:read", "test_cases:read", "members:read", "settings:read",
    },
}

BUILTIN_ROLES = list(DEFAULT_ROLE_PERMISSIONS.keys())


async def ensure_org_for_user(db, user_id: str, email: str, name: str) -> dict[str, Any]:
    """Create org + admin membership on first login."""
    member = await db.org_members.find_one({"user_id": user_id}, {"_id": 0})
    if member:
        org = await db.organizations.find_one({"org_id": member["org_id"]}, {"_id": 0})
        return org or {}

    org_id = f"org_{uuid.uuid4().hex[:10]}"
    slug = email.split("@")[0].lower().replace(".", "-")[:24]
    org = {
        "org_id": org_id,
        "name": f"{name}'s Team",
        "slug": slug,
        "owner_user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.organizations.insert_one(org)

    # Seed default role permission docs (admin can customize)
    for role_id, perms in DEFAULT_ROLE_PERMISSIONS.items():
        await db.role_permissions.update_one(
            {"org_id": org_id, "role_id": role_id},
            {"$set": {
                "org_id": org_id,
                "role_id": role_id,
                "permissions": sorted(perms),
                "builtin": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

    await db.org_members.insert_one({
        "org_id": org_id,
        "user_id": user_id,
        "email": email,
        "role": "admin",
        "joined_at": datetime.now(timezone.utc).isoformat(),
    })
    return org


async def get_member(db, user_id: str) -> Optional[dict[str, Any]]:
    return await db.org_members.find_one({"user_id": user_id}, {"_id": 0})


async def get_role_permissions(db, org_id: str, role_id: str) -> set[str]:
    doc = await db.role_permissions.find_one({"org_id": org_id, "role_id": role_id}, {"_id": 0})
    if doc:
        return set(doc.get("permissions") or [])
    return set(DEFAULT_ROLE_PERMISSIONS.get(role_id, set()))


async def get_user_permissions(db, user_id: str) -> tuple[Optional[str], set[str]]:
    member = await get_member(db, user_id)
    if not member:
        return None, set()
    perms = await get_role_permissions(db, member["org_id"], member["role"])
    return member["org_id"], perms


async def require_permission(db, user_id: str, permission: str) -> dict[str, Any]:
    member = await get_member(db, user_id)
    if not member:
        raise HTTPException(status_code=403, detail="Not a team member")
    perms = await get_role_permissions(db, member["org_id"], member["role"])
    if permission not in perms:
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
    return member


async def can_access_project(db, user_id: str, project: dict[str, Any], permission: str = "projects:read") -> bool:
    """Project access: owner OR same org with permission."""
    if project.get("user_id") == user_id:
        return True
    member = await get_member(db, user_id)
    if not member:
        return False
    if project.get("org_id") and project["org_id"] != member["org_id"]:
        return False
    perms = await get_role_permissions(db, member["org_id"], member["role"])
    return permission in perms


async def project_query_for_user(db, user_id: str) -> dict[str, Any]:
    """Mongo filter: projects owned by user OR in user's org."""
    member = await get_member(db, user_id)
    if not member:
        return {"user_id": user_id}
    org_id = member["org_id"]
    return {"$or": [{"user_id": user_id}, {"org_id": org_id}]}


async def get_project_for_user(db, user_id: str, project_id: str, permission: str = "projects:read") -> dict[str, Any]:
    q = await project_query_for_user(db, user_id)
    q["project_id"] = project_id
    project = await db.projects.find_one(q, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("user_id") != user_id:
        member = await require_permission(db, user_id, permission)
        if project.get("org_id") and project["org_id"] != member["org_id"]:
            raise HTTPException(status_code=404, detail="Project not found")
    return project
