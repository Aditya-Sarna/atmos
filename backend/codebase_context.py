"""Codebase indexing for IDE extension — full workspace context for Atmos reasoning."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("atmos.codebase")

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    "venv", ".venv", "coverage", ".turbo", "target", "vendor",
}
IGNORE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".mp4", ".webm", ".lock"}
MAX_FILE_BYTES = int(os.environ.get("ATMOS_IDE_MAX_FILE_BYTES", "80000"))
MAX_FILES = int(os.environ.get("ATMOS_IDE_MAX_FILES", "120"))


def walk_workspace(root: str | Path, *, max_files: int = MAX_FILES) -> list[dict[str, Any]]:
    """Walk a local workspace and return file metadata + truncated content."""
    root = Path(root).resolve()
    if not root.is_dir():
        return []

    files: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for name in filenames:
            if len(files) >= max_files:
                break
            p = Path(dirpath) / name
            if p.suffix.lower() in IGNORE_EXTS:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES * 2:
                    files.append({"path": str(p.relative_to(root)), "size": p.stat().st_size, "truncated": True, "content": ""})
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
                files.append({
                    "path": str(p.relative_to(root)),
                    "size": p.stat().st_size,
                    "truncated": p.stat().st_size > MAX_FILE_BYTES,
                    "content": content,
                    "language": p.suffix.lstrip(".") or "txt",
                })
            except Exception:  # noqa: BLE001
                continue
    return files


def build_context_summary(files: list[dict[str, Any]], open_file: Optional[str] = None) -> str:
    """Compact summary for LLM prompts."""
    lines = [f"Workspace: {len(files)} files indexed"]
    if open_file:
        lines.append(f"Active file: {open_file}")
    by_ext: dict[str, int] = {}
    for f in files:
        ext = Path(f["path"]).suffix or "(none)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    lines.append("Stack: " + ", ".join(f"{k}({v})" for k, v in sorted(by_ext.items(), key=lambda x: -x[1])[:8]))
    if open_file:
        match = next((f for f in files if f["path"] == open_file or f["path"].endswith(open_file)), None)
        if match and match.get("content"):
            lines.append(f"\n--- {open_file} ---\n{match['content'][:4000]}")
    return "\n".join(lines)


async def store_ide_context(db, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = {
        "user_id": user_id,
        "workspace_root": payload.get("workspace_root"),
        "workspace_name": payload.get("workspace_name") or Path(payload.get("workspace_root") or "").name,
        "open_file": payload.get("open_file"),
        "selection": payload.get("selection"),
        "page_url": payload.get("page_url"),
        "files": payload.get("files") or [],
        "file_count": len(payload.get("files") or []),
    }
    await db.ide_contexts.update_one(
        {"user_id": user_id},
        {"$set": doc},
        upsert=True,
    )
    return doc


async def get_ide_context(db, user_id: str) -> Optional[dict[str, Any]]:
    return await db.ide_contexts.find_one({"user_id": user_id}, {"_id": 0})
