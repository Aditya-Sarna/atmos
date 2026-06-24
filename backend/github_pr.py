"""Open a Pull Request on the submitted GitHub repository carrying an Atmos patch.

A "patch" is either:
  * a CSS file Atmos generated for a visual issue (saved to atmos-patches/<id>.css
    and linked via a comment in the PR body), OR
  * a file_create / file_replace produced by the architecture analyzer.

The caller supplies a GitHub Personal Access Token (PAT). For safety, the PAT
is never logged and never persisted to disk.
"""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("atmos.github_pr")


@dataclass
class PatchSpec:
    kind: str                       # "css_patch" | "file_create" | "file_replace"
    title: str
    body: str
    file_path: Optional[str] = None  # required for file_*
    css: Optional[str] = None        # required for css_patch


def _sanitize_branch(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9._/-]+", "-", name).strip("-/")
    return ("atmos/" + n)[:60] if not n.startswith("atmos/") else n[:60]


def open_pull_request(
    repo_full_name: str,   # "owner/repo"
    *,
    token: str,
    patch: PatchSpec,
    base_branch: str = "main",
) -> dict[str, Any]:
    """Apply `patch` on a new branch and open a PR. Returns {url, number, branch}.

    Raises RuntimeError on any failure (caller surfaces to user).
    """
    try:
        from github import Github, GithubException  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyGithub is not installed in this environment") from exc

    if not token:
        raise RuntimeError("Missing GitHub token for this project.")
    if "/" not in repo_full_name:
        raise RuntimeError(f"Bad repo: {repo_full_name!r}")

    gh = Github(token, per_page=10, timeout=20)
    repo = gh.get_repo(repo_full_name)

    # Fall back to repo default branch if `base_branch` doesn't exist.
    try:
        base_ref = repo.get_branch(base_branch)
    except Exception:  # noqa: BLE001
        base_branch = repo.default_branch
        base_ref = repo.get_branch(base_branch)

    branch_name = _sanitize_branch(f"atmos/{patch.title}")
    # Ensure uniqueness
    suffix = 1
    final_branch = branch_name
    while True:
        try:
            repo.get_branch(final_branch)
            suffix += 1
            final_branch = f"{branch_name}-{suffix}"
            if suffix > 20:
                raise RuntimeError("Could not allocate a fresh branch name.")
        except Exception:  # noqa: BLE001
            break

    repo.create_git_ref(ref=f"refs/heads/{final_branch}", sha=base_ref.commit.sha)

    # Materialise the patch as a file commit on that branch.
    if patch.kind == "css_patch":
        if not patch.css:
            raise RuntimeError("css_patch missing css body")
        target_path = patch.file_path or f"atmos-patches/{_safe_slug(patch.title)}.css"
        commit_msg = f"Atmos: add CSS patch — {patch.title}"
        content = _wrap_css(patch.css, title=patch.title, explanation=patch.body)
        _put_file(repo, target_path, content, commit_msg, final_branch)

    elif patch.kind in ("file_create", "file_replace"):
        if not patch.file_path:
            raise RuntimeError(f"{patch.kind} requires file_path")
        commit_msg = f"Atmos: {patch.kind.replace('_', ' ')} — {patch.title}"
        _put_file(repo, patch.file_path, patch.body, commit_msg, final_branch)

    else:
        raise RuntimeError(f"Unknown patch kind: {patch.kind}")

    pr_body = textwrap.dedent(f"""
    **Atmos auto-generated patch**

    {patch.body or '_no description_'}

    ---
    *This PR was opened by Atmos after the user clicked ✓ Apply on a finding.
    Review the diff, run your test suite, and merge if it looks right.*
    """).strip()
    pr = repo.create_pull(
        title=f"Atmos: {patch.title}",
        body=pr_body,
        head=final_branch,
        base=base_branch,
    )
    return {"url": pr.html_url, "number": pr.number, "branch": final_branch}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")[:60] or "patch"


def _wrap_css(css: str, *, title: str, explanation: str) -> str:
    header = f"/* Atmos patch — {title}\n   {explanation}\n*/\n\n"
    return header + css.strip() + "\n"


def _put_file(repo, path: str, content: str, message: str, branch: str) -> None:
    """Create or update a file on the given branch."""
    try:
        existing = repo.get_contents(path, ref=branch)
        repo.update_file(path=path, message=message, content=content, sha=existing.sha, branch=branch)
    except Exception:  # noqa: BLE001
        repo.create_file(path=path, message=message, content=content, branch=branch)
