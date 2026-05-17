"""
ai_writer.py — Uses Google Gemini to generate SEO scholarship articles.
Returns a structured dict with all content needed for HTML generation.
"""

import logging
import json
import re
import time

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL, SITE_URL, SITE_NAME

logger = logging.getLogger(__name__)

# Configure Gemini once at import time
genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)


# ─── Prompt templates ─────────────────────────────────────────────────────────

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
- Professional but warm tone — like a helpful university advisor
- No AI-sounding phrases ("delve into", "in today's world", "leverage", "in conclusion")
- Use "you" for the applicant, "we" for the site
- Sentence case for all headings
- Include real numbers/dollar amounts from the source text
- Do NOT invent facts — only use information from the source text above

OUTPUT FORMAT (respond with valid JSON only, no markdown backticks):
{{
  "title": "SEO page title (60 chars max)",
  "meta_description": "Meta description (155 chars max)",
  "h1": "Main article heading",
  "intro": "2-3 paragraph introduction (engaging, states the key benefit immediately)",
  "overview": "2-3 paragraphs — what the scholarship is, who offers it, its history/prestige",
  "benefits": "2-3 paragraphs — exactly what the scholarship covers, dollar amounts, duration",
  "eligibility": "Bullet-point list as HTML <ul><li>...</li></ul> — exact eligibility criteria",
  "documents": "Bullet-point list as HTML <ul><li>...</li></ul> — required documents",
  "how_to_apply": "Step-by-step numbered list as HTML <ol><li>...</li></ol>",
  "deadline_section": "1-2 paragraphs about the deadline and timeline",
  "faqs": [
    {{"q": "Question one?", "a": "Answer one."}},
    {{"q": "Question two?", "a": "Answer two."}},
    {{"q": "Question three?", "a": "Answer three."}},
    {{"q": "Question four?", "a": "Answer four."}},
    {{"q": "Question five?", "a": "Answer five."}}
  ],
  "conclusion": "1-2 paragraphs wrapping up, encouraging application",
  "slug": "url-friendly-slug-from-title",
  "category": "one of: government-scholarships | research-scholarships | merit-scholarships | undergraduate-scholarships | postgraduate-scholarships",
  "tags": ["tag1", "tag2", "tag3"],
  "seo_score_notes": "Brief note on what makes this article SEO-strong",
  "social_caption": "Twitter/LinkedIn caption for sharing this article (max 280 chars)",
  "newsletter_blurb": "2-sentence summary for email newsletter"
}}"""


META_ONLY_PROMPT = """Extract and return JSON metadata for this scholarship. Use ONLY information from the source text.

Title: {title}
University: {university}
Source text (first 2000 chars): {body_text}

Return valid JSON only:
{{
  "funding_type": "Full | Partial | Stipend only | Tuition only",
  "amount_aud": "e.g. AUD $39,500/year or empty string if unknown",
  "open_to": "e.g. All nationalities | Citizens of developing countries",
  "study_fields": "e.g. All fields | Engineering | Health",
  "application_mode": "e.g. Automatic with admission | Separate application | Annual round"
}}"""


# ─── Gemini caller ────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, max_retries: int = 3) -> str:
    """Call Gemini API with retry on quota/network errors."""
    for attempt in range(1, max_retries + 1):
        try:
            response = _model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.warning(f"Gemini error (attempt {attempt}): {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)
    return ""


def _parse_json(text: str) -> dict:
    """Strip markdown fences and parse JSON safely."""
    # Remove ```json ... ``` wrappers
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find first { ... last }
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {cleaned[:300]}")
        return {}


# ─── Public API ───────────────────────────────────────────────────────────────

def generate_article(scholarship: dict) -> dict | None:
    """
    Call Gemini to write a full SEO article for one scholarship.
    Returns enriched scholarship dict or None on failure.
    """
    logger.info(f"Generating article for: {scholarship['title'][:60]}")

    prompt = ARTICLE_PROMPT.format(
        site_name    = SITE_NAME,
        title        = scholarship.get("title", ""),
        university   = scholarship.get("university", ""),
        level        = scholarship.get("level", ""),
        benefits     = scholarship.get("benefits", ""),
        deadline     = scholarship.get("deadline", "Not specified"),
        url          = scholarship.get("url", ""),
        body_text    = scholarship.get("body_text", "")[:5000],
    )

    raw = _call_gemini(prompt)
    if not raw:
        logger.error("Gemini returned empty response")
        return None

    article = _parse_json(raw)
    if not article or not article.get("title"):
        logger.error("Could not parse Gemini response")
        return None

    # Get extra metadata
    meta_prompt = META_ONLY_PROMPT.format(
        title     = scholarship.get("title", ""),
        university= scholarship.get("university", ""),
        body_text = scholarship.get("body_text", "")[:2000],
    )
    meta_raw  = _call_gemini(meta_prompt)
    meta_data = _parse_json(meta_raw) if meta_raw else {}

    # Merge everything
    scholarship.update(article)
    scholarship.update(meta_data)

    # Ensure slug is valid
    slug = scholarship.get("slug", "")
    if not slug:
        from python_slugify import slugify
        slug = slugify(scholarship["title"])
    scholarship["slug"] = re.sub(r"[^a-z0-9\-]", "", slug.lower())[:80]

    # Word count check
    all_text = " ".join([
        article.get("intro", ""),
        article.get("overview", ""),
        article.get("benefits", ""),
        article.get("eligibility", ""),
        article.get("documents", ""),
        article.get("how_to_apply", ""),
        article.get("deadline_section", ""),
        article.get("conclusion", ""),
    ])
    wc = len(re.sub(r"<[^>]+>", "", all_text).split())
    scholarship["word_count"] = wc
    logger.info(f"  Article word count: {wc}")

    return scholarship
