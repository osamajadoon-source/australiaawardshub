"""
ai_writer.py — Auto-discovers available Gemini models then generates articles.
"""

import logging
import json
import re
import time

import requests

from config import GEMINI_API_KEY, SITE_NAME

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com"

# Model preference order — first available wins
PREFERRED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-pro",
]

_discovered_model = None   # cached after first discovery


def discover_model() -> str:
    """Query the ListModels endpoint and return the best available model name."""
    global _discovered_model
    if _discovered_model:
        return _discovered_model

    for api_ver in ["v1beta", "v1"]:
        try:
            url  = f"{BASE_URL}/{api_ver}/models"
            resp = requests.get(url, params={"key": GEMINI_API_KEY}, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"ListModels {api_ver} returned {resp.status_code}")
                continue

            models = resp.json().get("models", [])
            logger.info(f"ListModels ({api_ver}): {len(models)} models found")

            # Build a set of names that support generateContent
            available = set()
            for m in models:
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    # name is like "models/gemini-1.5-flash"
                    short = m["name"].replace("models/", "")
                    available.add(short)
                    logger.info(f"  Available: {short}")

            # Pick best model from preference list
            for preferred in PREFERRED_MODELS:
                if preferred in available:
                    _discovered_model = f"{BASE_URL}/{api_ver}/models/{preferred}:generateContent"
                    logger.info(f"Selected model: {preferred} ({api_ver})")
                    return _discovered_model

            # Fallback: use first available flash model
            for name in sorted(available):
                if "flash" in name or "pro" in name:
                    _discovered_model = f"{BASE_URL}/{api_ver}/models/{name}:generateContent"
                    logger.info(f"Fallback model: {name} ({api_ver})")
                    return _discovered_model

        except Exception as e:
            logger.warning(f"ListModels error ({api_ver}): {e}")

    # Hard fallback
    logger.error("Could not discover any model — using gemini-2.5-flash on v1beta")
    _discovered_model = f"{BASE_URL}/v1beta/models/gemini-2.5-flash:generateContent"
    return _discovered_model


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
    "- No AI phrases like delve into or leverage\n"
    "- Include real numbers from the source text\n"
    "- Do NOT invent facts\n\n"
    "Respond with a JSON object (no markdown, no backticks) with these exact keys:\n"
    "title, meta_description, h1, intro, overview, benefits, eligibility, "
    "documents, how_to_apply, deadline_section, faqs, conclusion, slug, "
    "category, tags, social_caption, newsletter_blurb\n\n"
    "For faqs use a list of 5 objects each with q and a keys.\n"
    "For tags use a list of 3 strings.\n"
    "For eligibility, documents, how_to_apply use HTML list tags."
)

META_PROMPT_TEMPLATE = (
    "Extract metadata from this scholarship. Use ONLY the source text.\n\n"
    "Title: {TITLE}\n"
    "Source text: {BODY}\n\n"
    "Respond with a JSON object (no markdown) with these exact keys:\n"
    "funding_type, amount_aud, open_to, study_fields, application_mode"
)


def _call_gemini(prompt: str, max_retries: int = 3) -> str:
    url    = discover_model()
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}
    }
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, params=params, json=payload, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            logger.warning(f"Gemini HTTP {resp.status_code} (attempt {attempt}): {resp.text[:300]}")
            # If 404, reset discovered model so next attempt re-discovers
            if resp.status_code == 404:
                global _discovered_model
                _discovered_model = None
        except Exception as e:
            logger.warning(f"Gemini error (attempt {attempt}): {e}")
        if attempt < max_retries:
            time.sleep(5 * attempt)
    return ""


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        logger.error(f"No JSON found. Raw: {cleaned[:200]}")
        return {}
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e} | Raw: {cleaned[start:start+300]}")
        return {}


def generate_article(scholarship: dict) -> dict | None:
    logger.info(f"Generating article for: {scholarship['title'][:60]}")

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

    article = _parse_json(raw)
    if not article or not article.get("title"):
        logger.error(f"Could not parse article. Raw start: {raw[:200]}")
        return None

    meta_raw  = _call_gemini(
        META_PROMPT_TEMPLATE
        .replace("{TITLE}", scholarship.get("title", ""))
        .replace("{BODY}",  scholarship.get("body_text", "")[:2000])
    )
    meta_data = _parse_json(meta_raw) if meta_raw else {}

    scholarship.update(article)
    scholarship.update(meta_data)

    slug = scholarship.get("slug", "")
    if not slug:
        from python_slugify import slugify
        slug = slugify(scholarship.get("title", "scholarship"))
    scholarship["slug"] = re.sub(r"[^a-z0-9\-]", "", slug.lower())[:80]

    all_text = " ".join([
        article.get("intro", ""), article.get("overview", ""),
        article.get("benefits", ""), article.get("eligibility", ""),
        article.get("how_to_apply", ""), article.get("conclusion", ""),
    ])
    scholarship["word_count"] = len(re.sub(r"<[^>]+>", "", all_text).split())
    logger.info(f"  Word count: {scholarship['word_count']}, slug: {scholarship['slug']}")

    return scholarship
