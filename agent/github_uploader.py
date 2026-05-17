"""
github_uploader.py — Commits and pushes generated HTML files to GitHub.
Uses the GitHub REST API (no local git required in CI).
Also supports local GitPython mode.
"""

import base64
import logging
import json
from pathlib import Path

import requests

from config import (
    GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO,
    GITHUB_BRANCH, OUTPUT_DIR, DATA_DIR
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "Content-Type": "application/json",
}


# ─── GitHub REST API helpers ──────────────────────────────────────────────────

def get_file_sha(path: str) -> str | None:
    """Get the SHA of an existing file in the repo (needed to update it)."""
    url = f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{path}"
    resp = requests.get(url, headers=HEADERS, params={"ref": GITHUB_BRANCH})
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None


def push_file(local_path: Path, repo_path: str, commit_message: str) -> bool:
    """
    Create or update a file in the GitHub repo via REST API.
    Returns True on success.
    """
    try:
        content_bytes = local_path.read_bytes()
        content_b64   = base64.b64encode(content_bytes).decode("utf-8")
    except IOError as e:
        logger.error(f"Cannot read file {local_path}: {e}")
        return False

    sha = get_file_sha(repo_path)

    payload = {
        "message": commit_message,
        "content": content_b64,
        "branch":  GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    url = f"{GITHUB_API}/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{repo_path}"
    resp = requests.put(url, headers=HEADERS, json=payload)

    if resp.status_code in (200, 201):
        logger.info(f"  ✓ Pushed: {repo_path}")
        return True
    else:
        logger.error(f"  ✗ Push failed for {repo_path}: {resp.status_code} {resp.text[:200]}")
        return False


# ─── Batch uploader ───────────────────────────────────────────────────────────

def upload_generated_files(filenames: list[str]) -> dict:
    """
    Upload a list of filenames from OUTPUT_DIR to the GitHub repo root.
    Also uploads updated sitemap.xml, feed.xml, and published.json.

    Returns summary dict with success/fail counts.
    """
    results = {"success": 0, "failed": 0, "files": []}

    if not GITHUB_TOKEN or not GITHUB_USERNAME or not GITHUB_REPO:
        logger.error("GitHub credentials not configured. Set GITHUB_TOKEN, GITHUB_USERNAME, GITHUB_REPO in .env")
        return results

    # ── HTML scholarship pages ────────────────────────────────────────────────
    for fname in filenames:
        local = OUTPUT_DIR / fname
        if not local.exists():
            logger.warning(f"File not found: {local}")
            results["failed"] += 1
            continue

        success = push_file(
            local_path     = local,
            repo_path      = fname,          # goes to repo root
            commit_message = f"feat: add scholarship page {fname} [auto]",
        )
        if success:
            results["success"] += 1
            results["files"].append(fname)
        else:
            results["failed"] += 1

    # ── Sitemap ───────────────────────────────────────────────────────────────
    sitemap_local = OUTPUT_DIR / "sitemap.xml"
    if sitemap_local.exists():
        push_file(sitemap_local, "sitemap.xml", "chore: update sitemap [auto]")

    # ── RSS feed ──────────────────────────────────────────────────────────────
    rss_local = OUTPUT_DIR / "feed.xml"
    if rss_local.exists():
        push_file(rss_local, "feed.xml", "chore: update RSS feed [auto]")

    # ── Published index (for duplicate checking next run) ─────────────────────
    pub_json = DATA_DIR / "published.json"
    if pub_json.exists():
        push_file(pub_json, "data/published.json", "chore: update published index [auto]")

    logger.info(f"Upload complete: {results['success']} succeeded, {results['failed']} failed")
    return results


# ─── GitPython fallback (for local use) ──────────────────────────────────────

def upload_via_gitpython(filenames: list[str], repo_local_path: str) -> bool:
    """
    Alternative: commit and push using GitPython when running locally
    with a cloned repo. Set repo_local_path to the repo root directory.
    """
    try:
        import git
        repo = git.Repo(repo_local_path)
        repo.config_writer().set_value("user", "name",  "Scholarship Agent").release()
        repo.config_writer().set_value("user", "email", "agent@australiaawardshub.com").release()

        for fname in filenames:
            src = OUTPUT_DIR / fname
            dst = Path(repo_local_path) / fname
            dst.write_bytes(src.read_bytes())
            repo.index.add([str(dst)])

        # Also copy sitemap/feed
        for fname in ["sitemap.xml", "feed.xml"]:
            src = OUTPUT_DIR / fname
            if src.exists():
                dst = Path(repo_local_path) / fname
                dst.write_bytes(src.read_bytes())
                repo.index.add([str(dst)])

        repo.index.commit(f"feat: add {len(filenames)} scholarship page(s) [auto]")

        origin = repo.remote(name="origin")
        origin.push()
        logger.info("GitPython push succeeded")
        return True
    except Exception as e:
        logger.error(f"GitPython push failed: {e}")
        return False
