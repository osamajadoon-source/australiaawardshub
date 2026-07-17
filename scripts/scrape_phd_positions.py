#!/usr/bin/env python3
"""
Daily PhD & Research Position Finder — Australia Awards Hub
=============================================================
Finds up to DAILY_POST_COUNT new individual PhD / research PROJECT
listings per run from official Australian university (.edu.au) websites.

For each one it creates its OWN page on this site (phd-<slug>.html) using
only factual, non-copyrighted data (title, supervisor, university, source
link) — never copied text from the source page. The description section
is deliberately left as a short placeholder for a human reviewer to write
an original paragraph before merging the PR. This avoids duplicate-content
and copyright problems while still giving each listing a real page that
can rank and be read on this site.

phd-research-positions.html is rebuilt as an INDEX linking to each
individual page — it does not contain the descriptions itself.

Runs via GitHub Actions on a daily schedule and always lands in a Pull
Request for human review — it never commits straight to main.

WHY TAVILY (not raw HTML scraping)
------------------------------------
Most university "find a scholarship / find a project" pages are either
general policy pages that barely change day to day, or JavaScript search
tools that return an empty shell to a plain HTTP request. Every university
also structures pages differently, so a bespoke scraper per site breaks
constantly. Tavily's search API already handles both problems and lets us
restrict results to a curated list of official university domains.

ONE-TIME SETUP: see SETUP.md. Requires one repo secret: TAVILY_API_KEY.
"""

import datetime
import html
import json
import os
import re
import sys
import urllib.request

DATA_FILE = "data/phd-positions.json"
HUB_HTML = "phd-research-positions.html"

UNI_DOMAINS = [
    "anu.edu.au", "unimelb.edu.au", "sydney.edu.au", "unsw.edu.au",
    "monash.edu", "uq.edu.au", "adelaide.edu.au", "uwa.edu.au",
    "qut.edu.au", "rmit.edu.au", "uts.edu.au", "mq.edu.au",
    "griffith.edu.au", "deakin.edu.au", "curtin.edu.au", "flinders.edu.au",
]

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

PROJECT_SIGNAL_TERMS = [
    "supervisor", "closing date", "expression of interest", "project title",
    "phd project", "research project", "apply by", "start date",
    "project description", "phd topic", "phd vacancy",
]

GENERIC_TITLE_PATTERNS = [
    "scholarships", "scholarship program", "how to apply for scholarships",
    "graduate research scholarships", "list of scholarships",
    "phd opportunities", "research opportunities", "project opportunities",
    "find an available", "find a phd", "find a project", "find a research project",
    "browse projects", "available projects", "search projects",
    "how to apply", "application process", "call for phd projects",
    # student testimonials/case studies — not open positions
    "'s story", "phd story", "case study", "success story", "profile:",
    "student profile", "alumni",
]

EXCLUDE_URL_PATTERNS = [
    "/privacy", "/accessibility", "/sitemap", "/search?", "/login",
    "/news/", "/events/",
]

DAILY_POST_COUNT = 4


def tavily_search(query, api_key, max_results=10):
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_domains": UNI_DOMAINS,
        "days": 14,
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
    title_lower = title.lower()
    text = f"{title} {content}".lower()

    # A title alone matching these is a strong signal this is a browse/search
    # page, not one project — reject regardless of what the content mentions.
    if any(pattern in title_lower for pattern in GENERIC_TITLE_PATTERNS):
        return False

    # Multiple "Supervisor" mentions almost always means a listing page
    # showing many projects (one supervisor line per project), not a
    # single position with one supervisor.
    if text.count("supervisor") >= 2:
        return False

    return any(term in text for term in PROJECT_SIGNAL_TERMS)


def extract_supervisor(content):
    """Best-effort extraction of a supervisor name from the snippet.
    Returns None if nothing confident is found — the reviewer can fill
    this in by hand during PR review, same as the description."""
    m = re.search(r"Supervisor[s]?\s*[:\-]?\s*([A-Z][a-zA-Z.\-' ]{2,60})", content)
    if m:
        name = m.group(1).strip().rstrip(".")
        name = re.split(r"\s{2,}|\n", name)[0]
        if 3 <= len(name) <= 80:
            return name
    return None


def slugify(text, max_len=60):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")[:max_len].strip("-")
    return text or "phd-position"


def unique_slug(base_slug, existing_slugs):
    slug = f"phd-{base_slug}"
    candidate = slug
    n = 2
    while candidate in existing_slugs:
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def pick_new_candidates(posted_urls, existing_slugs, api_key, count=4):
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
            title = item.get("title", "").strip()[:160]
            content = item.get("content", "").strip()

            if link in posted_urls or link in seen_today or is_excluded(link):
                continue
            if not any(d in link for d in UNI_DOMAINS):
                continue
            if not is_specific_project(title, content):
                continue

            seen_today.add(link)
            slug = unique_slug(slugify(title), existing_slugs)
            existing_slugs.add(slug)

            found.append({
                "title": title,
                "url": link,
                "snippet": content[:280],
                "university": university_label(link),
                "supervisor": extract_supervisor(content),
                "slug": slug,
                "found_date": datetime.date.today().isoformat(),
            })
    return found


POSITION_PAGE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} | PhD Position — Australia Awards Hub</title>
  <meta name="description" content="{meta_description}" />
  <link rel="canonical" href="https://australiaawardshub.com/{slug}" />
  <link rel="icon" type="image/png" href="logo.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{ --cream: #F5EDE0; --amber: #F5A300; --amber-dark: #e09600; --dark: #1A1208; --white: #ffffff; --muted: #6b5c47; --border: #e8ddd0; --radius: 12px; }}
    body {{ font-family: 'Inter', sans-serif; background: var(--cream); color: var(--dark); line-height: 1.6; }}
    nav.simple-nav {{ background: var(--cream); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; padding: 0 2rem; display: flex; align-items: center; justify-content: space-between; height: 64px; }}
    .nav-logo {{ display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--dark); font-weight: 600; font-size: 1rem; font-family: 'Playfair Display', serif; }}
    .nav-logo img {{ width: 36px; height: 36px; object-fit: contain; display: block; }}
    .nav-links {{ display: flex; align-items: center; gap: 1.5rem; }}
    .nav-links a {{ text-decoration: none; color: var(--dark); font-size: 0.9rem; }}
    .hero {{ background: var(--amber); padding: 2.75rem 2rem 2.25rem; }}
    .hero-inner {{ max-width: 1100px; margin: 0 auto; }}
    .breadcrumb {{ font-size: 0.82rem; color: rgba(26,18,8,0.65); margin-bottom: 1.25rem; }}
    .breadcrumb a {{ color: rgba(26,18,8,0.65); text-decoration: none; }}
    .badge {{ display: inline-block; background: rgba(255,255,255,0.3); border: 1px solid rgba(255,255,255,0.45); color: var(--dark); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 0.3rem 0.85rem; border-radius: 50px; margin-bottom: 1rem; }}
    .hero h1 {{ font-family: 'Playfair Display', serif; font-size: clamp(1.7rem, 3.4vw, 2.6rem); color: var(--dark); line-height: 1.2; margin-bottom: 1rem; max-width: 760px; }}
    .hero-desc {{ font-size: 0.98rem; color: rgba(26,18,8,0.8); max-width: 640px; margin-bottom: 1.5rem; }}
    .hero-stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: rgba(255,255,255,0.35); border-radius: var(--radius); overflow: hidden; margin-bottom: 1.5rem; max-width: 720px; }}
    .stat {{ background: rgba(255,255,255,0.2); padding: 0.9rem 1.1rem; }}
    .stat-label {{ font-size: 0.66rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(26,18,8,0.55); margin-bottom: 0.3rem; }}
    .stat-value {{ font-size: 0.9rem; font-weight: 600; color: var(--dark); line-height: 1.3; }}
    .btn-primary {{ background: var(--dark); color: var(--white); padding: 0.65rem 1.4rem; border-radius: 50px; text-decoration: none; font-size: 0.9rem; font-weight: 500; display: inline-block; }}
    .page-body {{ max-width: 1100px; margin: 0 auto; padding: 2.5rem 2rem; display: grid; grid-template-columns: 1fr 300px; gap: 3rem; align-items: start; }}
    article h2 {{ font-family: 'Playfair Display', serif; font-size: 1.35rem; margin: 1.75rem 0 0.75rem; color: var(--dark); }}
    article h2:first-child {{ margin-top: 0; }}
    article p {{ font-size: 0.97rem; color: #3a2f22; margin-bottom: 0.9rem; }}
    .cta-block {{ margin-top: 2rem; padding: 1.5rem; background: #fff8ec; border-radius: var(--radius); text-align: center; }}
    .cta-block p {{ margin-bottom: 0.75rem; font-size: 0.95rem; }}
    aside {{ position: sticky; top: 80px; }}
    .sidebar-card {{ background: var(--white); border-radius: var(--radius); padding: 1.5rem; box-shadow: 0 2px 12px rgba(0,0,0,0.07); margin-bottom: 1.25rem; }}
    .sidebar-card h3 {{ font-family: 'Playfair Display', serif; font-size: 1.05rem; margin-bottom: 1rem; }}
    .detail-row {{ display: flex; flex-direction: column; padding: 0.6rem 0; border-bottom: 1px solid var(--border); }}
    .detail-row:last-of-type {{ border-bottom: none; }}
    .detail-label {{ font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.2rem; }}
    .detail-value {{ font-size: 0.9rem; font-weight: 500; color: var(--dark); }}
    .sidebar-apply {{ display: block; background: var(--dark); color: var(--white); text-align: center; padding: 0.7rem 1rem; border-radius: 50px; text-decoration: none; font-size: 0.88rem; font-weight: 500; margin-top: 1rem; }}
    footer {{ background: var(--dark); color: rgba(255,255,255,0.7); text-align: center; padding: 1.5rem 2rem; font-size: 0.83rem; }}
    footer a {{ color: rgba(255,255,255,0.7); text-decoration: none; margin: 0 0.5rem; }}
    @media (max-width: 768px) {{ .hero-stats {{ grid-template-columns: repeat(2, 1fr); }} .page-body {{ grid-template-columns: 1fr; }} aside {{ position: static; }} }}
  </style>
  <meta property="og:title" content="{title} | PhD Position" />
  <meta property="og:description" content="{meta_description}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="https://australiaawardshub.com/{slug}" />
  <meta property="og:image" content="https://australiaawardshub.com/banner.png" />
</head>
<body>

<nav class="simple-nav">
  <a href="/" class="nav-logo"><img src="logo.png" alt="Australia Awards Hub" />Australia Awards Hub</a>
  <div class="nav-links">
    <a href="/phd-research-positions">All PhD Positions</a>
    <a href="/">Home</a>
  </div>
</nav>

<section class="hero">
  <div class="hero-inner">
    <div class="breadcrumb"><a href="/">Home</a> &rsaquo; <a href="/phd-research-positions">PhD &amp; Research Positions</a> &rsaquo; {university}</div>
    <span class="badge">PhD Position &middot; {university}</span>
    <h1>{title}</h1>
    <p class="hero-desc">{intro_sentence}</p>
    <div class="hero-stats">
      <div class="stat"><div class="stat-label">University</div><div class="stat-value">{university}</div></div>
      <div class="stat"><div class="stat-label">Supervisor</div><div class="stat-value">{supervisor_display}</div></div>
      <div class="stat"><div class="stat-label">Status</div><div class="stat-value">Listed {found_date}</div></div>
    </div>
    <a href="{source_url}" target="_blank" rel="noopener noreferrer nofollow" class="btn-primary">View official listing &rarr;</a>
  </div>
</section>

<div class="page-body">
  <article>
    <h2>About this position</h2>
    <p>This PhD position is offered by {university}, sourced from the university's own listings. For the full project description, eligibility criteria, funding details, and how to apply, use the official link below or in the box on the right.</p>

    <h2>How to apply</h2>
    <p>Applications for this position are handled directly by {university} — not by Australia Awards Hub. Visit the official listing to see the current application process, required documents, and closing date.</p>
  </article>

  <aside>
    <div class="sidebar-card">
      <h3>Position details</h3>
      <div class="detail-row"><span class="detail-label">University</span><span class="detail-value">{university}</span></div>
      <div class="detail-row"><span class="detail-label">Supervisor</span><span class="detail-value">{supervisor_display}</span></div>
      <div class="detail-row"><span class="detail-label">Listed</span><span class="detail-value">{found_date}</span></div>
      <a href="{source_url}" target="_blank" rel="noopener noreferrer nofollow" class="sidebar-apply">View official listing &rarr;</a>
    </div>
    <div class="sidebar-card">
      <h3>More positions</h3>
      <a href="/phd-research-positions" class="sidebar-apply" style="background:var(--amber);color:var(--dark);">Browse all PhD positions</a>
    </div>
  </aside>
</div>

<footer>
  Independent editorial reference. Not affiliated with {university} or any Australian government body.
  <br><a href="/">&larr; Back to home</a> &middot; <a href="/phd-research-positions">All PhD positions</a>
</footer>

</body>
</html>
'''


def render_position_page(entry):
    title = html.escape(entry["title"])
    university = html.escape(entry["university"])
    supervisor_display = html.escape(entry["supervisor"]) if entry.get("supervisor") else "See official listing"
    source_url = html.escape(entry["url"], quote=True)
    slug = entry["slug"]
    found_date = entry["found_date"]
    meta_description = html.escape(
        f"{entry['title']} — a PhD position at {entry['university']}. "
        f"View details and apply via the official university listing."
    )[:300]
    intro_sentence = html.escape(
        f"A PhD research position at {entry['university']}, currently open to applicants. "
        f"See the official listing for full eligibility, funding, and application details."
    )

    return POSITION_PAGE_TEMPLATE.format(
        title=title,
        university=university,
        supervisor_display=supervisor_display,
        source_url=source_url,
        slug=slug,
        found_date=found_date,
        meta_description=meta_description,
        intro_sentence=intro_sentence,
    )


def write_position_pages(entries):
    for entry in entries:
        path = f"{entry['slug']}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_position_page(entry))


HUB_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PhD &amp; Research Positions — Australia Awards Hub</title>
<meta name="description" content="Daily-updated PhD and research positions from official Australian university websites — ANU, Melbourne, Sydney, UNSW, Monash, UQ and more.">
<link rel="canonical" href="https://australiaawardshub.com/phd-research-positions" />
<link rel="icon" type="image/png" href="logo.png">
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
:root{{ --cream: #F5EDE0; --amber: #F5A300; --dark: #1A1208; --white: #ffffff; --muted: #6b5c47; --border: #e8ddd0; --radius: 12px; }}
body{{font-family:'Inter',sans-serif;background:var(--cream);color:var(--dark);line-height:1.6;}}
.wide{{max-width:1100px;margin:0 auto;padding:0 2rem;}}
nav.simple-nav{{background:var(--cream);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;padding:0 2rem;display:flex;align-items:center;justify-content:space-between;height:64px;}}
.nav-logo{{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--dark);font-weight:600;font-size:1rem;font-family:'Playfair Display',serif;}}
.nav-logo img{{width:36px;height:36px;object-fit:contain;display:block;}}
.hero{{background:var(--amber);padding:3rem 2rem 2.5rem;}}
.hero h1{{font-family:'Playfair Display',serif;font-size:clamp(1.9rem,3.6vw,2.8rem);margin-bottom:0.75rem;}}
.hero p{{max-width:640px;font-size:1rem;color:rgba(26,18,8,0.8);}}
.updated-note{{display:inline-block;margin-top:1rem;background:rgba(255,255,255,0.3);padding:0.35rem 0.9rem;border-radius:999px;font-size:0.82rem;}}
.phd-list{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px;padding:3rem 0 4.5rem;}}
.phd-row{{background:var(--white);border:1px solid var(--border);border-radius:var(--radius);padding:1.4rem;display:flex;flex-direction:column;gap:0.6rem;}}
.phd-row-top{{display:flex;justify-content:space-between;align-items:center;font-size:0.75rem;color:var(--muted);}}
.uni-tag{{background:var(--cream);color:var(--dark);padding:2px 10px;border-radius:999px;font-weight:700;letter-spacing:0.02em;}}
.phd-row h3{{font-family:'Playfair Display',serif;font-size:1.05rem;line-height:1.4;}}
.phd-row h3 a{{text-decoration:none;color:var(--dark);}}
.phd-row h3 a:hover{{color:var(--amber-dark,#e09600);}}
.phd-row-link{{font-size:0.85rem;font-weight:600;color:#b14a2d;text-decoration:none;}}
.phd-empty{{padding:3rem 0;color:var(--muted);font-style:italic;}}
footer{{background:var(--dark);color:rgba(255,255,255,0.7);text-align:center;padding:1.5rem 2rem;font-size:0.83rem;}}
footer a{{color:rgba(255,255,255,0.7);text-decoration:none;margin:0 0.5rem;}}
</style>
</head>
<body>

<nav class="simple-nav">
  <a href="/" class="nav-logo"><img src="logo.png" alt="Australia Awards Hub" />Australia Awards Hub</a>
</nav>

<section class="hero">
  <div class="wide">
    <h1>PhD &amp; Research Positions</h1>
    <p>Individual PhD and research project listings sourced from official Australian university websites. New positions reviewed and added most days.</p>
    <span class="updated-note">Last updated: {last_updated}</span>
  </div>
</section>

<div class="wide">
  <div class="phd-list">
<!-- PHD_ROWS_START -->
<!-- PHD_ROWS_END -->
  </div>
</div>

<footer>
  Independent editorial reference. Not affiliated with the Commonwealth of Australia, DFAT, or any listed institution.
  <br><a href="/">&larr; Back to home</a>
</footer>

</body>
</html>
'''


def render_hub_row(entry):
    title = html.escape(entry["title"])
    uni = html.escape(entry["university"])
    date = entry["found_date"]
    slug = entry["slug"]
    return f'''      <article class="phd-row">
        <div class="phd-row-top">
          <span class="uni-tag">{uni}</span>
          <span>Added {date}</span>
        </div>
        <h3><a href="/{slug}">{title}</a></h3>
        <a href="/{slug}" class="phd-row-link">View position details &rarr;</a>
      </article>'''


def update_hub(entries):
    entries_sorted = sorted(entries, key=lambda e: e["found_date"], reverse=True)
    rows_html = "\n".join(render_hub_row(e) for e in entries_sorted) if entries_sorted else \
        '      <p class="phd-empty">No listings yet — check back soon.</p>'
    today = datetime.date.today().isoformat()

    if os.path.exists(HUB_HTML):
        with open(HUB_HTML, "r", encoding="utf-8") as f:
            page = f.read()
        page = re.sub(
            r"(<!-- PHD_ROWS_START -->)(.*?)(<!-- PHD_ROWS_END -->)",
            lambda m: m.group(1) + "\n" + rows_html + "\n" + m.group(3),
            page,
            flags=re.DOTALL,
        )
        page = re.sub(r"Last updated: [^<]*", f"Last updated: {today}", page)
        new_page = page
    else:
        new_page = HUB_TEMPLATE.format(last_updated=today).replace(
            "<!-- PHD_ROWS_START -->\n<!-- PHD_ROWS_END -->",
            f"<!-- PHD_ROWS_START -->\n{rows_html}\n<!-- PHD_ROWS_END -->",
        )

    with open(HUB_HTML, "w", encoding="utf-8") as f:
        f.write(new_page)


def write_github_output(new_count, candidates):
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as f:
        f.write(f"new_count={new_count}\n")
        summary_lines = "\n".join(
            f"- {c['university']}: {c['title']} -> https://australiaawardshub.com/{c['slug']}"
            for c in candidates
        )
        f.write("new_titles<<PHD_EOF\n")
        f.write(summary_lines + "\n" if summary_lines else "(none)\n")
        f.write("PHD_EOF\n")


def main():
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("Missing TAVILY_API_KEY — add it as a repo secret.", file=sys.stderr)
        sys.exit(1)

    posted = load_posted()
    posted_urls = {e["url"] for e in posted}
    existing_slugs = {e["slug"] for e in posted if "slug" in e}

    candidates = pick_new_candidates(posted_urls, existing_slugs, api_key, count=DAILY_POST_COUNT)
    if not candidates:
        print("No new candidates found today — nothing to commit.")
        write_github_output(0, [])
        return

    write_position_pages(candidates)

    posted.extend(candidates)
    save_posted(posted)
    update_hub(posted)

    write_github_output(len(candidates), candidates)

    print(f"Added {len(candidates)} new position page(s):")
    for c in candidates:
        print(f"  - /{c['slug']}.html  ({c['university']}) -> {c['url']}")


if __name__ == "__main__":
    main()
