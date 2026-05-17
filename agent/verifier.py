"""
verifier.py — Filters scraped scholarships:
  1. Deduplication against published.json
  2. Active-date verification
  3. Quality threshold check
"""

import json
import logging
import re
from datetime import datetime, date
from pathlib import Path

from config import PUBLISHED_JSON, CLOSED_PHRASES, MIN_WORD_COUNT

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}


def load_published() -> dict:
    """Load the published.json index. Returns dict keyed by slug."""
    if PUBLISHED_JSON.exists():
        try:
            with open(PUBLISHED_JSON) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_published(data: dict) -> None:
    PUBLISHED_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(PUBLISHED_JSON, "w") as f:
        json.dump(data, f, indent=2)


def parse_deadline(deadline_str: str) -> date | None:
    """Attempt to parse a free-form deadline string into a date object."""
    if not deadline_str:
        return None

    text = deadline_str.strip().lower()

    # Pattern: 30 April 2026
    m = re.search(r"(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})", text)
    if m:
        try:
            return date(int(m.group(3)), MONTH_MAP[m.group(2)], int(m.group(1)))
        except ValueError:
            pass

    # Pattern: April 30, 2026
    m = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(20\d{2})", text)
    if m:
        try:
            return date(int(m.group(3)), MONTH_MAP[m.group(1)], int(m.group(2)))
        except ValueError:
            pass

    # Pattern: 2026-04-30
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


def is_active(scholarship: dict) -> bool:
    """Return True if the scholarship appears to be open or upcoming."""
    text_lower = (scholarship.get("body_text", "") + " " + scholarship.get("title", "")).lower()

    # Hard reject if closed phrases present
    for phrase in CLOSED_PHRASES:
        if phrase in text_lower:
            logger.debug(f"Rejected (closed phrase): {scholarship['title'][:50]}")
            return False

    # Parse deadline
    deadline = parse_deadline(scholarship.get("deadline", ""))
    if deadline:
        today = date.today()
        if deadline < today:
            logger.info(f"Rejected (past deadline {deadline}): {scholarship['title'][:50]}")
            return False
        scholarship["deadline_date"] = deadline.isoformat()
        scholarship["days_remaining"] = (deadline - today).days

    return True


def is_duplicate(scholarship: dict, published: dict) -> bool:
    """Check if we've already published a page for this scholarship."""
    url = scholarship.get("url", "")
    title = scholarship.get("title", "").lower().strip()

    # Check by URL
    for entry in published.values():
        if entry.get("source_url") == url:
            logger.info(f"Duplicate (URL): {url[:60]}")
            return True

    # Check by title similarity (simple token overlap)
    title_tokens = set(re.sub(r"[^\w\s]", "", title).split())
    for entry in published.values():
        pub_title = entry.get("title", "").lower()
        pub_tokens = set(re.sub(r"[^\w\s]", "", pub_title).split())
        if len(title_tokens) > 0 and len(pub_tokens) > 0:
            overlap = len(title_tokens & pub_tokens) / max(len(title_tokens), len(pub_tokens))
            if overlap > 0.80:
                logger.info(f"Duplicate (title ~{overlap:.0%}): {scholarship['title'][:50]}")
                return True

    return False


def meets_quality(scholarship: dict) -> bool:
    """Basic quality gate: body must have enough text."""
    body = scholarship.get("body_text", "")
    words = len(body.split())
    if words < 150:
        logger.debug(f"Rejected (only {words} words): {scholarship['title'][:50]}")
        return False
    if not scholarship.get("title"):
        return False
    return True


def urgency_score(scholarship: dict) -> int:
    """
    0-100 score for how urgent/valuable this scholarship is.
    Higher = publish first.
    """
    score = 50
    days = scholarship.get("days_remaining", 180)
    if days < 30:
        score += 30
    elif days < 60:
        score += 15
    elif days < 90:
        score += 5
    
    # Boost for full funding
    body = scholarship.get("body_text", "").lower()
    if "full" in body and "tuition" in body:
        score += 10
    if "stipend" in body or "living allowance" in body:
        score += 8
    if "government" in scholarship.get("source_type", ""):
        score += 10
    if "australia awards" in scholarship.get("title", "").lower():
        score += 15

    return min(score, 100)


def verify_and_rank(scholarships: list[dict]) -> list[dict]:
    """
    Run full verification pipeline. Returns verified, unique, ranked list.
    """
    published = load_published()
    verified  = []

    for s in scholarships:
        if not meets_quality(s):
            continue
        if not is_active(s):
            continue
        if is_duplicate(s, published):
            continue
        s["urgency_score"] = urgency_score(s)
        verified.append(s)

    # Sort by urgency descending
    verified.sort(key=lambda x: x["urgency_score"], reverse=True)
    logger.info(f"Verified scholarships ready to publish: {len(verified)}")
    return verified
