"""
ai_writer.py — Uses Google Gemini REST API directly.
"""

import logging
import json
import re
import time

import requests

from config import GEMINI_API_KEY, SITE_NAME

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1/models/"
    "gemini-1.5-flash:generateContent"
)

# NOTE: No .format() used on these prompts — variables injected manually below
ARTICLE_PROMPT_TEMPLATE = (
    "You are a senior education journalist writing for {SITE_NAME}, "
    "an independent Australian scholarship reference website. "
    "Write a complete, human-sounding SEO article about this scholarship.\n\n"
    "SCHOLARSHIP DATA:\n"
    "Title: {TITLE}\n"
    "University/Provider: {UNIVERSITY}\n"
    "Degree Level: {LEVEL}\n"
    "Financial Benefits: {BENEFITS}\n"
    "Deadline: {DEADLINE}\n"
    "Source URL: {URL}\n"
    "Raw page text: {BODY}\n\n"
    "REQUIREMENTS:\n"
    "- Write in Australian English\n"
    "- Minimum 1200 words\n"
    "- Professional but warm tone\n"
    "- No AI phrases like 'delve into' or 'leverage'\n"
    "- Include real numbers from the source text\n"
    "- Do NOT invent facts\n\n"
    "Respond with a JSON object (no markdown, no backticks) containing these exact keys:\n"
    "title, meta_description, h1, intro, overview, benefits, eligibility, "
    "documents, how_to_apply, deadline_section, faqs, conclusion, slug, "
    "category, tags, social_caption, newsletter_blurb\n\n"
    "For 'faqs' use a list of objects with 'q' and 'a' keys (5 FAQs).\n"
    "For 'tags' use a list of 3 strings.\n"
    "For eligibility/documents/how_to_apply use HTML list tags."
)

META_PROMPT_TEMPLATE = (
    "Extract metadata from this scholarship. Use ONLY the source text.\n\n"
    "Title: {TITLE}\n"
    "Source text: {BODY}\n\n"
    "Respond with a JSON object (no markdown) with these exact keys:\n"
    "funding_type, amount_aud, open_to, study_fields, application_mode"
)


def _call_gemini(prompt: str, max_retries: int = 3) -> str:
    """Call Gemini REST API directly."""
    params  = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
    }
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(GEMINI_URL, params=params, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            logger.warning(f"Gemini HTTP {resp.status_code} (attempt {attempt}): {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Gemini error (attempt {attempt}): {e}")
        if attempt < max_retries:
            time.sleep(5 * attempt)
    return ""


def _parse_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        logger.error(f"No JSON object found in response: {cleaned[:200]}")
        return {}
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e} | Raw: {cleaned[start:start+300]}")
        return {}


def generate_article(scholarship: dict) -> dict | None:
    logger.info(f"Generating article for: {scholarship['title'][:60]}")

    # Build prompts using simple string replacement (no .format())
    article_prompt = (
        ARTICLE_PROMPT_TEMPLATE
        .replace("{SITE_NAME}",  SITE_NAME)
        .replace("{TITLE}",      scholarship.get("title", ""))
        .replace("{UNIVERSITY}", scholarship.get("university", ""))
        .replace("{LEVEL}",      scholarship.get("level", ""))
        .replace("{BENEFITS}",   scholarship.get("benefits", ""))
        .replace("{DEADLINE}",   scholarship.get("deadline", "Not specified"))
        .replace("{URL}",        scholarship.get("url", ""))
        .replace("{BODY}",       scholarship.get("body_text", "")[:5000])
    )

    raw = _call_gemini(article_prompt)
    if not raw:
        logger.error("Gemini returned empty response")
        return None

    logger.debug(f"Raw Gemini response (first 300): {raw[:300]}")
    article = _parse_json(raw)
    if not article or not article.get("title"):
        logger.error(f"Could not parse article JSON. Raw start: {raw[:200]}")
        return None

    # Get extra metadata
    meta_prompt = (
        META_PROMPT_TEMPLATE
        .replace("{TITLE}", scholarship.get("title", ""))
        .replace("{BODY}",  scholarship.get("body_text", "")[:2000])
    )
    meta_raw  = _call_gemini(meta_prompt)
    meta_data = _parse_json(meta_raw) if meta_raw else {}

    scholarship.update(article)
    scholarship.update(meta_data)

    # Ensure valid slug
    slug = scholarship.get("slug", "")
    if not slug:
        from python_slugify import slugify
        slug = slugify(scholarship.get("title", "scholarship"))
    scholarship["slug"] = re.sub(r"[^a-z0-9\-]", "", slug.lower())[:80]

    # Word count
    all_text = " ".join([
        article.get("intro", ""),
        article.get("overview", ""),
        article.get("benefits", ""),
        article.get("eligibility", ""),
        article.get("how_to_apply", ""),
        article.get("conclusion", ""),
    ])
    scholarship["word_count"] = len(re.sub(r"<[^>]+>", "", all_text).split())
    logger.info(f"  Word count: {scholarship['word_count']}, slug: {scholarship['slug']}")

    return scholarship
