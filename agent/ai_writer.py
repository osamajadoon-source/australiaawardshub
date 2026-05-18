"""
ai_writer.py — Uses Google Gemini REST API directly (no SDK version issues).
"""

import logging
import json
import re
import time

import requests

from config import GEMINI_API_KEY, SITE_NAME

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

ARTICLE_PROMPT = """You are a senior education journalist writing for {site_name}, an independent Australian scholarship reference website. Write a complete, human-sounding SEO article about the following scholarship.

SCHOLARSHIP DATA:
Title: {title}
University/Provider: {university}
Degree Level: {level}
Financial Benefits: {benefits}
Deadline: {deadline}
Source URL: {url}
Raw page text: {body_text}

REQUIREMENTS:
- Write in Australian English (enrol, programme, organisation)
- Minimum 1200 words
- Professional but warm tone
- No AI-sounding phrases like "delve into", "leverage", "in conclusion"
- Use "you" for the applicant
- Include real numbers/dollar amounts from the source text
- Do NOT invent facts

OUTPUT FORMAT - respond with valid JSON only, no markdown backticks:
{
  "title": "SEO page title (60 chars max)",
  "meta_description": "Meta description (155 chars max)",
  "h1": "Main article heading",
  "intro": "2-3 paragraph introduction",
  "overview": "2-3 paragraphs about the scholarship",
  "benefits": "2-3 paragraphs about what is covered",
  "eligibility": "<ul><li>eligibility criteria</li></ul>",
  "documents": "<ul><li>required documents</li></ul>",
  "how_to_apply": "<ol><li>application steps</li></ol>",
  "deadline_section": "1-2 paragraphs about deadline",
  "faqs": [
    {"q": "Question one?", "a": "Answer one."},
    {"q": "Question two?", "a": "Answer two."},
    {"q": "Question three?", "a": "Answer three."},
    {"q": "Question four?", "a": "Answer four."},
    {"q": "Question five?", "a": "Answer five."}
  ],
  "conclusion": "1-2 concluding paragraphs",
  "slug": "url-friendly-slug",
  "category": "postgraduate-scholarships",
  "tags": ["tag1", "tag2", "tag3"],
  "social_caption": "Social media caption (max 280 chars)",
  "newsletter_blurb": "2-sentence newsletter summary"
}"""

META_PROMPT = """Extract metadata from this scholarship. Use ONLY information from the source text.

Title: {title}
Source text: {body_text}

Return valid JSON only:
{
  "funding_type": "Full | Partial | Stipend only | Tuition only",
  "amount_aud": "e.g. AUD $39,500/year or empty string",
  "open_to": "e.g. All nationalities",
  "study_fields": "e.g. All fields",
  "application_mode": "e.g. Automatic | Separate application | Annual round"
}"""


def _call_gemini(prompt: str, max_retries: int = 3) -> str:
    """Call Gemini REST API directly - no SDK needed."""
    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                GEMINI_URL,
                params=params,
                json=payload,
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                logger.warning(
                    f"Gemini HTTP {resp.status_code} (attempt {attempt}): {resp.text[:200]}"
                )
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
        return {}
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {cleaned[:300]}")
        return {}


def generate_article(scholarship: dict) -> dict | None:
    logger.info(f"Generating article for: {scholarship['title'][:60]}")

    prompt = ARTICLE_PROMPT.format(
        site_name  = SITE_NAME,
        title      = scholarship.get("title", ""),
        university = scholarship.get("university", ""),
        level      = scholarship.get("level", ""),
        benefits   = scholarship.get("benefits", ""),
        deadline   = scholarship.get("deadline", "Not specified"),
        url        = scholarship.get("url", ""),
        body_text  = scholarship.get("body_text", "")[:5000],
    )

    raw = _call_gemini(prompt)
    if not raw:
        logger.error("Gemini returned empty response")
        return None

    article = _parse_json(raw)
    if not article or not article.get("title"):
        logger.error("Could not parse Gemini response")
        return None

    meta_raw  = _call_gemini(META_PROMPT.format(
        title     = scholarship.get("title", ""),
        body_text = scholarship.get("body_text", "")[:2000],
    ))
    meta_data = _parse_json(meta_raw) if meta_raw else {}

    scholarship.update(article)
    scholarship.update(meta_data)

    slug = scholarship.get("slug", "")
    if not slug:
        from python_slugify import slugify
        slug = slugify(scholarship["title"])
    scholarship["slug"] = re.sub(r"[^a-z0-9\-]", "", slug.lower())[:80]

    all_text = " ".join([
        article.get("intro", ""), article.get("overview", ""),
        article.get("benefits", ""), article.get("eligibility", ""),
        article.get("how_to_apply", ""), article.get("conclusion", ""),
    ])
    scholarship["word_count"] = len(re.sub(r"<[^>]+>", "", all_text).split())
    logger.info(f"  Word count: {scholarship['word_count']}")

    return scholarship
