#!/usr/bin/env python3
"""
Daily PhD & Research Position Finder — Australia Awards Hub
=============================================================
Finds ONE new PhD / research position per run from official Australian
university (.edu.au) websites and adds it to phd-research-positions.html
plus data/phd-positions.json. Runs via GitHub Actions on a daily schedule
and always lands in a Pull Request for human review — it never commits
straight to main.

WHY GOOGLE PROGRAMMABLE SEARCH (not raw HTML scraping)
-------------------------------------------------------
Most university "find a scholarship / find a project" pages are either:
  (a) general policy pages that barely change day to day, or
  (b) JavaScript search tools (Vue/React) that return an empty shell to
      any plain HTTP request — a simple scraper sees nothing useful.
Every university also structures its pages differently, so a bespoke
scraper per site breaks constantly and is a lot to maintain.

Google's own index already renders JS pages and normalises all of this,
so instead of scraping raw HTML we query Google Programmable Search,
restricted to a curated list of official university domains, and only
look at fresh results. This is far more robust and needs no per-site
maintenance when a university redesigns its site.

ONE-TIME SETUP (see SETUP.md for full walkthrough with screenshots-worth
of detail):
  1. Create a free Google Programmable Search Engine restricted to the
     domains in UNI_DOMAINS below: https://programmablesearchengine.google.com/
  2. Get a Google Custom Search JSON API key (free tier: 100 queries/day):
     https://developers.google.com/custom-search/v1/introduction
  3. Add two repository secrets in GitHub:
       GOOGLE_CSE_API_KEY
       GOOGLE_CSE_ID
"""

import datetime
import html
import json
import os
import re
import sys
import urllib.request

DATA_FILE = "data/phd-positions.json"
OUTPUT_HTML = "phd-research-positions.html"

# Curated, maintainable list of official university domains.
# Add more any time — this is intentionally a specific list rather than
# a blanket "*.edu.au" so results stay high-quality and on-topic.
UNI_DOMAINS = [
    "anu.edu.au", "unimelb.edu.au", "sydney.edu.au", "unsw.edu.au",
    "monash.edu", "uq.edu.au", "adelaide.edu.au", "uwa.edu.au",
    "qut.edu.au", "rmit.edu.au", "uts.edu.au", "mq.edu.au",
    "griffith.edu.au", "deakin.edu.au", "curtin.edu.au", "flinders.edu.au",
]

# Rotated across runs so the same phrase doesn't dominate every day.
# Anchored to specific PROJECT listings (supervisor named, one topic,
# a closing date) rather than general "browse our scholarships" pages.
SEARCH_QUERIES = [
    '"PhD project" supervisor apply',
    '"PhD project" "closing date" OR "expression of interest"',
    '"available PhD project" research',
    '"PhD opportunity" supervisor project',
    'PhD position "project description" supervisor',
    '"we are seeking a PhD" project apply',
    '"PhD topic" supervisor apply now',
    '"PhD vacancy" project research',
]

# A real, individual open project/position almost always mentions at least
# one of these. Generic "explore our scholarships" program pages usually
# mention none of them — this is what separates a specific PhD project
# from a general funding-scheme page.
PROJECT_SIGNAL_TERMS = [
    "supervisor", "closing date", "expression of interest", "project title",
    "phd project", "research project", "apply by", "start date",
    "project description", "phd topic", "phd vacancy",
]

# Generic scholarship-scheme pages that describe eligibility/funding for a
# whole program rather than one specific project — filtered out even if
# they slip through the signal-term check above.
GENERIC_TITLE_PATTERNS = [
    "scholarships", "scholarship program", "how to apply for scholarships",
    "graduate research scholarships", "list of scholarships",
]

# Pages that show up in results but aren't individual listings —
# filtered out so we don't post a generic policy page as "today's PhD".
EXCLUDE_URL_PATTERNS = [
    "/privacy", "/accessibility", "/sitemap", "/search?", "/login",
    "/news/", "/events/",
]


def tavily_search(query, api_key, max_results=10):
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_domains": UNI_DOMAINS,
        "days": 14,  # only listings indexed in the last 14 days
    }
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def load_posted():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_posted(entries):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def university_label(url):
    labels = {
        "anu.edu.au": "ANU", "unimelb.edu.au": "Melbourne",
        "sydney.edu.au": "Sydney", "unsw.edu.au": "UNSW",
        "monash.edu": "Monash", "uq.edu.au": "UQ",
        "adelaide.edu.au": "Adelaide", "uwa.edu.au": "UWA",
        "qut.edu.au": "QUT", "rmit.edu.au": "RMIT",
        "uts.edu.au": "UTS", "mq.edu.au": "Macquarie",
        "griffith.edu.au": "Griffith", "deakin.edu.au": "Deakin",
        "curtin.edu.au": "Curtin", "flinders.edu.au": "Flinders",
    }
    for domain, label in labels.items():
        if domain in url:
            return label
    return "Australian University"


def is_excluded(url):
    return any(pattern in url for pattern in EXCLUDE_URL_PATTERNS)


def is_specific_project(title, content):
    text = f"{title} {content}".lower()

    # Reject generic scholarship-scheme pages outright.
    if any(pattern in text for pattern in GENERIC_TITLE_PATTERNS):
        # ...unless it also has strong project-specific signals (some pages
        # legitimately mention "scholarships" while still being one project).
        if not any(term in text for term in PROJECT_SIGNAL_TERMS):
            return False

    # Require at least one real project-specific signal to qualify at all.
    return any(term in text for term in PROJECT_SIGNAL_TERMS)


def pick_new_candidates(posted_urls, api_key, count=4):
    # Rotate which query leads based on day of year, so results vary.
    day_offset = datetime.date.today().toordinal()
    queries = SEARCH_QUERIES[day_offset % len(SEARCH_QUERIES):] + \
        SEARCH_QUERIES[:day_offset % len(SEARCH_QUERIES)]

    found = []
    seen_today = set()

    for q in queries:
        if len(found) >= count:
            break
        try:
            results = tavily_search(q, api_key)
        except Exception as e:
            print(f"Search failed for query '{q}': {e}", file=sys.stderr)
            continue

        for item in results.get("results", []):
            if len(found) >= count:
                break
            link = item.get("url", "")
            title = item.get("title", "")
            content = item.get("content", "")
            if link in posted_urls or link in seen_today or is_excluded(link):
                continue
            if not any(d in link for d in UNI_DOMAINS):
                continue
            if not is_specific_project(title, content):
                continue
            seen_today.add(link)
            found.append({
                "title": item.get("title", "").strip()[:160],
                "url": link,
                "snippet": item.get("content", "").strip()[:280],
                "university": university_label(link),
                "found_date": datetime.date.today().isoformat(),
            })
    return found


def render_card(entry):
    title = html.escape(entry["title"])
    uni = html.escape(entry["university"])
    snippet = html.escape(entry["snippet"])
    url = html.escape(entry["url"], quote=True)
    date = entry["found_date"]
    return f'''      <article class="phd-card">
        <div class="phd-card-top">
          <span class="phd-uni-tag">{uni}</span>
          <span class="phd-date-tag">Added {date}</span>
        </div>
        <h3><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h3>
        <p>{snippet}</p>
        <a href="{url}" target="_blank" rel="noopener noreferrer" class="phd-apply-link">View official listing →</a>
      </article>'''


PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PhD &amp; Research Positions — Australia Awards Hub</title>
<meta name="description" content="Daily-updated PhD and research positions from official Australian university websites — ANU, Melbourne, Sydney, UNSW, Monash, UQ and more.">
<link rel="icon" type="image/png" href="logo.png">
<style>
:root{{
  --paper:#f7f2e8; --paper-2:#efe9da; --paper-3:#e6dfc8;
  --ink:#1a1816; --ink-2:#3a342c; --ink-3:#6a6157; --ink-4:#9a9085;
  --line:#e3dccb; --line-2:#d4ccb8;
  --forest:#1f3a2e; --forest-2:#2c5544; --forest-light:#4a7a62;
  --terracotta:#b14a2d; --terracotta-2:#c75f3f; --terracotta-light:#d97355;
  --sage:#e8e3d4; --sage-2:#ddd7c4;
  --amber:#b88717; --green:#2c7a4b; --red:#9a3a1f;
  --serif:"Source Serif 4","Source Serif Pro",Georgia,serif;
  --sans:"Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  --radius:10px; --radius-lg:14px;
  --max:1240px; --pad:clamp(20px,4vw,56px);
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:var(--sans);background:var(--paper);color:var(--ink);line-height:1.7;-webkit-font-smoothing:antialiased;}}
.container-wide{{max-width:var(--max);margin:0 auto;padding:0 var(--pad);}}
a{{color:inherit;}}
.phd-hero{{background:linear-gradient(135deg,var(--forest),var(--forest-2));color:var(--paper);padding:64px 0 48px;}}
.phd-hero h1{{font-family:var(--serif);font-size:clamp(28px,4vw,44px);margin-bottom:12px;}}
.phd-hero p{{max-width:640px;opacity:.9;}}
.phd-updated-note{{display:inline-block;margin-top:18px;background:rgba(255,255,255,.12);padding:6px 14px;border-radius:999px;font-size:13px;}}
.phd-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;padding:48px 0 72px;}}
.phd-card{{background:#fff;border:1px solid var(--line);border-radius:var(--radius-lg);padding:22px;display:flex;flex-direction:column;gap:10px;}}
.phd-card-top{{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink-3);}}
.phd-uni-tag{{background:var(--sage);color:var(--forest);padding:3px 10px;border-radius:999px;font-weight:700;letter-spacing:.02em;}}
.phd-card h3{{font-family:var(--serif);font-size:18px;line-height:1.4;}}
.phd-card h3 a{{text-decoration:none;color:var(--ink);}}
.phd-card h3 a:hover{{color:var(--terracotta);}}
.phd-card p{{font-size:14px;color:var(--ink-2);flex:1;}}
.phd-apply-link{{font-size:13px;font-weight:700;color:var(--terracotta);text-decoration:none;}}
.phd-empty{{padding:48px 0;color:var(--ink-3);font-style:italic;}}
</style>
</head>
<body>

<header class="site-header" id="mainNav" style="background:var(--paper);border-bottom:1px solid var(--line);padding:16px 0;">
  <div class="container-wide" style="display:flex;align-items:center;gap:16px;">
    <a href="/" style="display:flex;align-items:center;gap:10px;text-decoration:none;">
      <img src="logo.png" alt="Australia Awards Hub" width="40" height="40" style="object-fit:contain;display:block">
      <span style="font-family:var(--serif);font-weight:700;color:var(--ink);">Australia Awards Hub</span>
    </a>
  </div>
</header>

<section class="phd-hero">
  <div class="container-wide">
    <h1>PhD &amp; Research Positions</h1>
    <p>A running list of PhD and research positions sourced from official Australian university websites. One new listing reviewed and added most days.</p>
    <span class="phd-updated-note">Last updated: {last_updated}</span>
  </div>
</section>

<div class="container-wide">
  <div class="phd-grid">
<!-- PHD_CARDS_START -->
<!-- PHD_CARDS_END -->
  </div>
</div>

<footer style="border-top:1px solid var(--line);padding:32px 0;text-align:center;color:var(--ink-3);font-size:13px;">
  <div class="container-wide">
    Independent editorial reference. Not affiliated with the Commonwealth of Australia, DFAT, or any listed institution.
    <br><a href="/" style="color:var(--terracotta);text-decoration:none;">← Back to home</a>
  </div>
</footer>

</body>
</html>
'''


def update_html(entries):
    entries_sorted = sorted(entries, key=lambda e: e["found_date"], reverse=True)
    cards_html = "\n".join(render_card(e) for e in entries_sorted) if entries_sorted else \
        '      <p class="phd-empty">No listings yet — check back soon.</p>'
    today = datetime.date.today().isoformat()

    if os.path.exists(OUTPUT_HTML):
        with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
            page = f.read()
        page = re.sub(
            r"(<!-- PHD_CARDS_START -->)(.*?)(<!-- PHD_CARDS_END -->)",
            lambda m: m.group(1) + "\n" + cards_html + "\n" + m.group(3),
            page,
            flags=re.DOTALL,
        )
        page = re.sub(
            r"Last updated: [^<]*",
            f"Last updated: {today}",
            page,
        )
        new_page = page
    else:
        new_page = PAGE_TEMPLATE.format(last_updated=today).replace(
            "<!-- PHD_CARDS_START -->\n<!-- PHD_CARDS_END -->",
            f"<!-- PHD_CARDS_START -->\n{cards_html}\n<!-- PHD_CARDS_END -->",
        )

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(new_page)


DAILY_POST_COUNT = 4


def main():
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("Missing TAVILY_API_KEY — add it as a repo secret.", file=sys.stderr)
        sys.exit(1)

    posted = load_posted()
    posted_urls = {e["url"] for e in posted}

    candidates = pick_new_candidates(posted_urls, api_key, count=DAILY_POST_COUNT)
    if not candidates:
        print("No new candidates found today — nothing to commit.")
        return

    posted.extend(candidates)
    save_posted(posted)
    update_html(posted)
    print(f"Added {len(candidates)} new listing(s):")
    for c in candidates:
        print(f"  - {c['title']} ({c['university']}) -> {c['url']}")


if __name__ == "__main__":
    main()
