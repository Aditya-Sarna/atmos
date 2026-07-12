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
