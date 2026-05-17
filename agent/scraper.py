"""
scraper.py — Fetches scholarship data from official .edu.au and .gov.au pages.
Only targets verified official sources defined in config.py.
"""

import time
import logging
import re
import json
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import trafilatura

from config import (
    SCHOLARSHIP_SOURCES, REQUEST_HEADERS, REQUEST_TIMEOUT,
    REQUEST_RETRIES, REQUEST_DELAY, CLOSED_PHRASES
)

logger = logging.getLogger(__name__)


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def fetch_page(url: str, retries: int = REQUEST_RETRIES) -> str | None:
    """Fetch a URL with retry logic. Returns HTML text or None."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt})")
        except requests.RequestException as e:
            logger.warning(f"Request error for {url}: {e} (attempt {attempt})")
        if attempt < retries:
            time.sleep(REQUEST_DELAY * attempt)
    return None


def extract_text(url: str, html: str) -> str:
    """Use trafilatura to extract main article text from HTML."""
    try:
        text = trafilatura.extract(html, url=url, include_tables=True, favor_recall=True)
        return text or ""
    except Exception as e:
        logger.debug(f"trafilatura failed for {url}: {e}")
        return ""


# ─── Scholarship link finder ──────────────────────────────────────────────────

SCHOLARSHIP_KEYWORDS = [
    "scholarship", "award", "bursary", "fellowship", "grant",
    "stipend", "postgraduate", "research award", "merit scholarship"
]

def find_scholarship_links(base_url: str, html: str) -> list[dict]:
    """
    Parse a scholarships listing page and extract links to individual
    scholarship detail pages.
    """
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        text = a.get_text(" ", strip=True)

        # Resolve relative URLs
        full_url = urljoin(base_url, href)

        # Only follow .edu.au and .gov.au links
        domain = urlparse(full_url).netloc
        if not (domain.endswith(".edu.au") or domain.endswith(".gov.au")):
            continue

        # Must look like a scholarship link
        combined = (text + " " + href).lower()
        if not any(kw in combined for kw in SCHOLARSHIP_KEYWORDS):
            continue

        # Skip fragment-only or javascript links
        if href.startswith("#") or href.startswith("javascript"):
            continue

        if full_url not in seen:
            seen.add(full_url)
            links.append({"url": full_url, "anchor_text": text})

    return links[:40]   # cap per source to avoid overload


# ─── Detail page extractor ────────────────────────────────────────────────────

DATE_PATTERNS = [
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})\b",
    r"\b(\d{1,2})[\/\-](\d{1,2})[\/\-](20\d{2})\b",
]

BENEFIT_PATTERNS = [
    r"AUD?\s?\$?[\d,]+",
    r"\$[\d,]+\s*(per year|annually|per annum|p\.a\.)?",
    r"full\s+tuition",
    r"living\s+(stipend|allowance|expenses)",
    r"return\s+airfare",
    r"oshc|overseas\s+student\s+health",
]


def extract_scholarship_details(url: str, html: str, anchor_text: str) -> dict | None:
    """
    Extract structured scholarship data from a detail page.
    Returns a dict or None if the page doesn't look like a valid scholarship.
    """
    text = extract_text(url, html)
    soup = BeautifulSoup(html, "lxml")

    if not text or len(text) < 200:
        return None

    text_lower = text.lower()

    # ── Skip closed scholarships ──────────────────────────────────────────────
    for phrase in CLOSED_PHRASES:
        if phrase in text_lower:
            logger.info(f"CLOSED: {url} contains '{phrase}'")
            return None

    # ── Title ─────────────────────────────────────────────────────────────────
    title = ""
    for tag in ["h1", "h2"]:
        el = soup.find(tag)
        if el:
            title = el.get_text(" ", strip=True)
            break
    if not title:
        title = anchor_text or "Scholarship"
    if len(title) < 5 or len(title) > 200:
        return None

    # ── Must contain scholarship content ──────────────────────────────────────
    if not any(kw in text_lower for kw in ["scholarship", "award", "fellowship", "stipend"]):
        return None

    # ── Extract dates ─────────────────────────────────────────────────────────
    deadline = ""
    for pattern in DATE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            deadline = " ".join(str(m) for m in matches[0])
            break

    # Look for deadline-specific phrases
    deadline_phrases = ["closing date", "deadline", "applications close", "apply by", "closes on"]
    for phrase in deadline_phrases:
        idx = text_lower.find(phrase)
        if idx != -1:
            snippet = text[idx:idx+80]
            for pattern in DATE_PATTERNS:
                m = re.search(pattern, snippet, re.IGNORECASE)
                if m:
                    deadline = m.group(0)
                    break
            if deadline:
                break

    # ── Extract financial benefits ────────────────────────────────────────────
    benefits = []
    for pattern in BENEFIT_PATTERNS:
        found = re.findall(pattern, text, re.IGNORECASE)
        benefits.extend(found[:3])
    benefits_str = "; ".join(dict.fromkeys(b.strip() for b in benefits[:5]))

    # ── Degree level ──────────────────────────────────────────────────────────
    level = []
    for lvl in ["PhD", "Masters", "Doctoral", "Postgraduate", "Bachelor", "Undergraduate", "Short course"]:
        if lvl.lower() in text_lower:
            level.append(lvl)
    level_str = " · ".join(dict.fromkeys(level[:3])) or "Postgraduate"

    # ── Domain → university name ───────────────────────────────────────────────
    domain = urlparse(url).netloc
    university = domain.replace("www.", "").replace(".edu.au", "").replace(".gov.au", "")
    university = university.replace(".", " ").replace("-", " ").title()

    return {
        "title":       title,
        "university":  university,
        "url":         url,
        "deadline":    deadline,
        "level":       level_str,
        "benefits":    benefits_str,
        "body_text":   text[:8000],   # send to AI writer
        "scraped_at":  datetime.utcnow().isoformat(),
        "published":   False,
    }


# ─── Main scrape orchestration ────────────────────────────────────────────────

def scrape_all_sources() -> list[dict]:
    """
    Iterate every source in SCHOLARSHIP_SOURCES.
    Returns a list of raw scholarship dicts ready for verification.
    """
    all_scholarships = []

    for source in SCHOLARSHIP_SOURCES:
        name = source["name"]
        url  = source["url"]
        logger.info(f"Scraping source: {name} — {url}")

        html = fetch_page(url)
        if not html:
            logger.warning(f"  Could not fetch {url}")
            continue

        links = find_scholarship_links(url, html)
        logger.info(f"  Found {len(links)} scholarship links")

        for link_info in links:
            link_url = link_info["url"]
            time.sleep(REQUEST_DELAY)

            detail_html = fetch_page(link_url)
            if not detail_html:
                continue

            details = extract_scholarship_details(
                link_url, detail_html, link_info["anchor_text"]
            )
            if details:
                details["source_name"] = name
                details["source_type"] = source["type"]
                all_scholarships.append(details)
                logger.info(f"  ✓ {details['title'][:60]}")

    logger.info(f"Scraping complete. Total candidates: {len(all_scholarships)}")
    return all_scholarships
