"""
config.py — Central configuration for the scholarship agent.
All settings drawn from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── AI ────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL        = "gemini-2.0-flash"          # fast + cheap for daily runs

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME     = os.getenv("GITHUB_USERNAME", "")
GITHUB_REPO         = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH       = os.getenv("GITHUB_BRANCH", "main")
GITHUB_REPO_URL     = f"https://{GITHUB_USERNAME}:{GITHUB_TOKEN}@github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"

# ── Site ──────────────────────────────────────────────────────────────────────
SITE_URL            = os.getenv("SITE_URL", "https://australiaawardshub.com")
SITE_NAME           = os.getenv("SITE_NAME", "Australia Awards Hub")
OG_IMAGE            = f"{SITE_URL}/banner.png"
GA_ID               = "G-ZL2YCR2ZTZ"
ADSENSE_PUB         = "ca-pub-8464180506412741"

# ── Quality thresholds ────────────────────────────────────────────────────────
MIN_WORD_COUNT      = int(os.getenv("MIN_WORD_COUNT", "1200"))
MAX_ARTICLES_PER_DAY = int(os.getenv("MAX_ARTICLES_PER_DAY", "3"))

# ── Paths ─────────────────────────────────────────────────────────────────────
import pathlib
ROOT_DIR            = pathlib.Path(__file__).parent.parent
DATA_DIR            = ROOT_DIR / "data"
OUTPUT_DIR          = ROOT_DIR / "output"
LOG_DIR             = DATA_DIR / "logs"
SCHOLARSHIPS_JSON   = DATA_DIR / "scholarships.json"
PUBLISHED_JSON      = DATA_DIR / "published.json"

# ── Official scholarship source URLs ─────────────────────────────────────────
SCHOLARSHIP_SOURCES = [
    # Government
    {"name": "Australia Awards",      "url": "https://www.australiaawards.gov.au/scholarships/", "type": "government"},
    {"name": "Study in Australia",    "url": "https://www.studyinaustralia.gov.au/english/australian-education/scholarships", "type": "government"},

    # Go8 Universities
    {"name": "University of Melbourne","url": "https://scholarships.unimelb.edu.au/search?eligibility=International", "type": "university"},
    {"name": "University of Sydney",   "url": "https://www.sydney.edu.au/scholarships/international.html",             "type": "university"},
    {"name": "ANU",                    "url": "https://www.anu.edu.au/study/scholarships",                              "type": "university"},
    {"name": "University of Queensland","url":"https://scholarships.uq.edu.au/search?keywords=international",          "type": "university"},
    {"name": "Monash University",      "url": "https://www.monash.edu/scholarships/find?citizenshipStatus=International","type":"university"},
    {"name": "UNSW Sydney",            "url": "https://www.unsw.edu.au/study/international/scholarships",               "type": "university"},
    {"name": "University of Adelaide", "url": "https://www.adelaide.edu.au/scholarships/undergrad/international",      "type": "university"},
    {"name": "University of WA",       "url": "https://www.uwa.edu.au/study/scholarships",                             "type": "university"},

    # Other universities
    {"name": "QUT",                    "url": "https://www.qut.edu.au/study/fees-and-scholarships/scholarships",       "type": "university"},
    {"name": "Curtin University",      "url": "https://www.curtin.edu.au/study/scholarships/",                         "type": "university"},
    {"name": "Deakin University",      "url": "https://www.deakin.edu.au/study/fees-and-scholarships/scholarships",    "type": "university"},
    {"name": "RMIT University",        "url": "https://www.rmit.edu.au/study-with-us/international-students/scholarships-for-international-students","type":"university"},
    {"name": "Griffith University",    "url": "https://www.griffith.edu.au/study/fees-scholarships/scholarships",      "type": "university"},
    {"name": "Macquarie University",   "url": "https://www.mq.edu.au/study/international-students/scholarships",       "type": "university"},
    {"name": "La Trobe University",    "url": "https://www.latrobe.edu.au/scholarships/international",                 "type": "university"},
    {"name": "James Cook University",  "url": "https://www.jcu.edu.au/fees-and-scholarships/scholarships",             "type": "university"},
    {"name": "Flinders University",    "url": "https://www.flinders.edu.au/scholarships",                              "type": "university"},
    {"name": "CDU",                    "url": "https://www.cdu.edu.au/scholarships",                                   "type": "university"},
]

# Phrases that indicate a scholarship is closed/expired
CLOSED_PHRASES = [
    "applications are closed",
    "applications have closed",
    "closed for applications",
    "no longer accepting",
    "this scholarship has ended",
    "applications closed",
    "scholarship is closed",
    "deadline has passed",
    "not currently open",
    "currently not available",
    "scholarship expired",
]

# ── HTTP request headers ───────────────────────────────────────────────────────
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
REQUEST_TIMEOUT  = 20
REQUEST_RETRIES  = 3
REQUEST_DELAY    = 2   # seconds between requests
