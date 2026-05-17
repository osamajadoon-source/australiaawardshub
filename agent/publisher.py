"""
publisher.py — Converts article data into production-ready HTML pages
matching the Australia Awards Hub design system.
"""

import json
import logging
import re
from datetime import datetime, date
from pathlib import Path

from config import (
    SITE_URL, SITE_NAME, OG_IMAGE, GA_ID, ADSENSE_PUB,
    OUTPUT_DIR, PUBLISHED_JSON
)
from verifier import load_published, save_published

logger = logging.getLogger(__name__)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─── Schema markup generator ──────────────────────────────────────────────────

def build_schema(scholarship: dict) -> str:
    slug = scholarship.get("slug", "")
    title = scholarship.get("title", "")
    desc  = scholarship.get("meta_description", "")
    url   = f"{SITE_URL}/{slug}"
    pub_date = datetime.utcnow().strftime("%Y-%m-%d")

    article_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "url": url,
        "datePublished": pub_date,
        "dateModified": pub_date,
        "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
        "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
        "image": {"@type": "ImageObject", "url": OG_IMAGE},
        "inLanguage": "en-AU",
    }

    breadcrumb_schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home",        "item": SITE_URL},
            {"@type": "ListItem", "position": 2, "name": "Scholarships","item": f"{SITE_URL}/#scholarships"},
            {"@type": "ListItem", "position": 3, "name": title,          "item": url},
        ]
    }

    faqs = scholarship.get("faqs", [])
    faq_schema = ""
    if faqs:
        faq_items = [
            {
                "@type": "Question",
                "name": faq.get("q", ""),
                "acceptedAnswer": {"@type": "Answer", "text": faq.get("a", "")}
            }
            for faq in faqs
        ]
        faq_obj = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq_items}
        faq_schema = f'<script type="application/ld+json">{json.dumps(faq_obj)}</script>'

    return (
        f'<script type="application/ld+json">{json.dumps(article_schema)}</script>\n'
        f'<script type="application/ld+json">{json.dumps(breadcrumb_schema)}</script>\n'
        f'{faq_schema}'
    )


# ─── FAQ HTML ─────────────────────────────────────────────────────────────────

def build_faq_html(faqs: list[dict]) -> str:
    if not faqs:
        return ""
    items = ""
    for faq in faqs:
        q = faq.get("q", "")
        a = faq.get("a", "")
        items += f"""<div class="faq-item">
  <button class="faq-q">{q}<span class="fi">+</span></button>
  <div class="faq-a"><p>{a}</p></div>
</div>\n"""
    return items


# ─── Main HTML builder ────────────────────────────────────────────────────────

def build_html(scholarship: dict) -> str:
    slug        = scholarship.get("slug", "unknown")
    title       = scholarship.get("title", "Scholarship")
    meta_desc   = scholarship.get("meta_description", "")
    h1          = scholarship.get("h1", title)
    university  = scholarship.get("university", "")
    level       = scholarship.get("level", "")
    deadline    = scholarship.get("deadline", "")
    days_rem    = scholarship.get("days_remaining", "")
    source_url  = scholarship.get("url", "#")
    category    = scholarship.get("category", "postgraduate-scholarships")
    tags        = scholarship.get("tags", [])
    amount      = scholarship.get("amount_aud", "")
    open_to     = scholarship.get("open_to", "")
    fund_type   = scholarship.get("funding_type", "")
    app_mode    = scholarship.get("application_mode", "")

    page_url    = f"{SITE_URL}/{slug}"
    pub_date    = datetime.utcnow().strftime("%-d %B %Y")

    # Deadline pill colour
    pill_class = "tone-calm"
    if isinstance(days_rem, int):
        if days_rem < 30:
            pill_class = "tone-urgent"
        elif days_rem < 60:
            pill_class = "tone-soon"

    days_label = f"{days_rem} days remaining" if isinstance(days_rem, int) else "Open"

    # Build tag chips
    tag_chips = "".join(f'<span class="chip">{t}</span>' for t in tags[:5])

    # FAQs
    faq_html = build_faq_html(scholarship.get("faqs", []))

    # Schema
    schema = build_schema(scholarship)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title} | {SITE_NAME}</title>
<meta name="description" content="{meta_desc}"/>
<link rel="canonical" href="{page_url}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{meta_desc}"/>
<meta property="og:type" content="article"/>
<meta property="og:url" content="{page_url}"/>
<meta property="og:image" content="{OG_IMAGE}"/>
<meta property="og:image:width" content="1734"/>
<meta property="og:image:height" content="907"/>
<meta property="article:published_time" content="{datetime.utcnow().isoformat()}Z"/>
<link rel="icon" type="image/png" href="logo.png"/>
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{GA_ID}');</script>
{schema}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap">
<style>
:root{{--cream:#FAF3E7;--cream-2:#F2E7D2;--ink:#231812;--ink-soft:#5C4A3E;--terra:#C75A3C;--terra-d:#A8442C;--forest:#1F3A2E;--line:rgba(35,24,18,0.12);--sh:0 1px 2px rgba(35,24,18,.06),0 8px 24px rgba(35,24,18,.06);}}
*{{box-sizing:border-box;margin:0;padding:0}}html{{scroll-behavior:smooth}}
body{{font-family:'Plus Jakarta Sans',system-ui,sans-serif;background:var(--cream);color:var(--ink);line-height:1.7;-webkit-font-smoothing:antialiased}}
.c{{max-width:860px;margin:0 auto;padding:0 24px}}.cw{{max-width:1100px;margin:0 auto;padding:0 24px}}
nav{{position:sticky;top:0;z-index:200;background:rgba(250,243,231,.92);backdrop-filter:blur(16px);border-bottom:1px solid var(--line);transition:box-shadow .3s}}
nav.scrolled{{box-shadow:0 2px 20px rgba(35,24,18,.10)}}
.ni{{display:flex;align-items:center;justify-content:space-between;padding:14px 0}}
.logo{{font-family:'Fraunces',serif;font-weight:600;font-size:20px;display:flex;align-items:center;gap:12px;text-decoration:none;color:var(--ink)}}
.logo img{{width:52px;height:52px;object-fit:contain}}
.nav-links{{display:flex;gap:4px;list-style:none;align-items:center}}
.nav-links a{{color:var(--ink);text-decoration:none;font-weight:500;font-size:14px;padding:8px 12px;border-radius:8px;transition:background .2s}}
.nav-links a:hover{{background:var(--cream-2);color:var(--terra)}}
.btn-nav{{display:inline-block;padding:9px 18px;border-radius:999px;font-weight:600;font-size:13px;text-decoration:none;background:var(--terra);color:var(--cream)}}
.hero{{background:linear-gradient(135deg,var(--forest),#2c5544);color:white;padding:56px 0 48px}}
.bc{{font-size:13px;opacity:.7;margin-bottom:14px}}.bc a{{color:white;text-decoration:none}}
.hero-meta{{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}}
.hero-tag{{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);padding:5px 13px;border-radius:999px;font-size:12px;font-weight:600}}
.deadline-pill{{display:inline-flex;align-items:center;gap:5px;font-family:'Plus Jakarta Sans',monospace;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:5px 10px;border-radius:999px}}
.tone-calm{{background:rgba(44,122,75,.15);color:#5fc987;border:1px solid rgba(95,201,135,.3)}}
.tone-soon{{background:rgba(184,135,23,.15);color:#E8C84A;border:1px solid rgba(232,200,74,.3)}}
.tone-urgent{{background:rgba(177,74,45,.2);color:#ff9977;border:1px solid rgba(255,153,119,.3)}}
.page-body{{padding:48px 0 80px}}
.article-layout{{display:grid;grid-template-columns:1fr 280px;gap:48px;align-items:start}}
.sidebar{{position:sticky;top:88px}}
.sidebar-card{{background:white;border:1px solid var(--line);border-radius:16px;padding:22px;margin-bottom:16px;box-shadow:var(--sh)}}
.sidebar-card h4{{font-family:'Fraunces',serif;font-size:16px;font-weight:600;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid var(--line)}}
.fact-row{{display:flex;justify-content:space-between;align-items:flex-start;padding:8px 0;border-bottom:1px solid rgba(35,24,18,.06);font-size:13.5px;gap:12px}}
.fact-row:last-child{{border-bottom:none;padding-bottom:0}}
.fact-row dt{{color:var(--ink-soft);flex-shrink:0}}.fact-row dd{{margin:0;font-weight:600;text-align:right;font-size:13px}}
.apply-btn{{display:block;background:var(--terra);color:white;text-align:center;padding:14px;border-radius:12px;font-weight:700;font-size:15px;text-decoration:none;margin-top:16px;transition:background .2s}}
.apply-btn:hover{{background:var(--terra-d)}}
article h1{{font-family:'Fraunces',serif;font-size:clamp(26px,4vw,40px);font-weight:500;line-height:1.15;letter-spacing:-.015em;margin-bottom:16px;color:var(--ink)}}
article h2{{font-family:'Fraunces',serif;font-size:26px;font-weight:600;margin:40px 0 14px;letter-spacing:-.01em;line-height:1.2}}
article h3{{font-family:'Fraunces',serif;font-size:19px;font-weight:600;margin:26px 0 10px}}
article p{{font-size:16px;line-height:1.78;margin-bottom:18px;color:var(--ink)}}
article ul,article ol{{margin:0 0 20px 22px;font-size:16px}}
article li{{margin-bottom:8px;padding-left:4px;line-height:1.65}}
article a{{color:var(--terra-d);text-decoration:underline;text-underline-offset:3px}}
.callout{{background:var(--cream-2);border-radius:14px;padding:20px 24px;margin:28px 0;border-left:4px solid var(--terra)}}
.callout p{{margin:0;font-size:15px;color:var(--ink-soft)}}
.pub-meta{{font-family:'Plus Jakarta Sans',monospace;font-size:12px;color:var(--ink-soft);letter-spacing:.03em;margin-bottom:24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.chip{{background:var(--cream-2);border-radius:999px;padding:4px 12px;font-size:12px;font-weight:600;color:var(--ink-soft)}}
.tag-row{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:28px}}
.faq-item{{border-bottom:1px solid var(--line)}}
.faq-q{{width:100%;background:none;border:none;padding:15px 0;font-family:inherit;font-size:15px;font-weight:600;color:var(--ink);cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:16px;text-align:left}}
.fi{{font-size:20px;color:var(--terra);flex-shrink:0;transition:transform .2s}}
.faq-a{{display:none;padding:0 0 14px}}.faq-a p{{margin:0;font-size:15px;color:var(--ink-soft);line-height:1.7}}
.faq-item.open .faq-a{{display:block}}.faq-item.open .fi{{transform:rotate(45deg)}}
.related-links h3{{font-family:'Fraunces',serif;font-size:18px;font-weight:600;margin:0 0 14px}}
.rl{{display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid var(--line);text-decoration:none;color:var(--ink);font-size:14px;font-weight:500;transition:color .2s}}
.rl:last-child{{border-bottom:none}}.rl:hover{{color:var(--terra)}}
footer{{padding:32px 0 24px;border-top:1px solid var(--line);margin-top:56px}}
.fb{{display:flex;justify-content:space-between;font-size:13px;color:var(--ink-soft);flex-wrap:wrap;gap:12px}}
@media(max-width:900px){{.article-layout{{grid-template-columns:1fr}}.sidebar{{position:static}}.nav-links{{display:none}}}}
</style>
</head>
<body>
<nav id="mainNav">
<div class="cw ni">
<a href="/" class="logo"><img src="logo.png" alt="{SITE_NAME}" width="52" height="52"/>{SITE_NAME}</a>
<ul class="nav-links">
<li><a href="/#scholarships">Scholarships</a></li>
<li><a href="/australian-visa-guide">Visa Guide</a></li>
<li><a href="/blog">Guides</a></li>
<li><a href="/about">About</a></li>
</ul>
<a href="/dilp-guide-product" class="btn-nav">&#128216; DILP Guide</a>
</div>
</nav>

<div class="hero">
<div class="c">
<div class="bc"><a href="/">Home</a> &#8250; <a href="/#scholarships">Scholarships</a> &#8250; {university}</div>
<h1>{h1}</h1>
<div class="hero-meta">
{f'<span class="hero-tag">{level}</span>' if level else ''}
{f'<span class="hero-tag">{fund_type}</span>' if fund_type else ''}
{f'<span class="hero-tag">{open_to}</span>' if open_to else ''}
<span class="deadline-pill {pill_class}">&#9679; {days_label}</span>
</div>
</div>
</div>

<div class="page-body">
<div class="cw">
<div class="article-layout">

<article>
<div class="pub-meta">
<span>Published {pub_date}</span>
<span>&#183;</span>
<span>{scholarship.get('word_count', 1200)}+ words</span>
<span>&#183;</span>
<span>Verified source</span>
</div>
<div class="tag-row">{tag_chips}</div>

{scholarship.get('intro', '')}

<h2>Scholarship overview</h2>
{scholarship.get('overview', '')}

<h2>What the scholarship covers</h2>
{scholarship.get('benefits', '')}

<h2>Eligibility requirements</h2>
{scholarship.get('eligibility', '')}

<h2>Required documents</h2>
{scholarship.get('documents', '')}

<h2>How to apply</h2>
{scholarship.get('how_to_apply', '')}

<h2>Application deadline</h2>
{scholarship.get('deadline_section', '')}

<div class="callout">
<p><strong>Official source:</strong> Always verify scholarship details on the official page before applying. Scholarship details change — confirm the latest requirements at <a href="{source_url}" target="_blank" rel="noopener">{university}'s official scholarships page</a>.</p>
</div>

<h2>Frequently asked questions</h2>
{faq_html}

<h2>Conclusion</h2>
{scholarship.get('conclusion', '')}

<div class="related-links">
<h3>Related scholarships &amp; guides</h3>
<a href="/australia-awards-scholarship-2027" class="rl"><span>Australia Awards Scholarships 2027 &#8212; full funding guide</span><span>&#8594;</span></a>
<a href="/fully-funded-scholarships-australia" class="rl"><span>All fully funded scholarships in Australia</span><span>&#8594;</span></a>
<a href="/how-to-get-scholarship-australia" class="rl"><span>How to get a scholarship in Australia &#8212; step-by-step</span><span>&#8594;</span></a>
<a href="/rtp-scholarship-australia" class="rl"><span>Research Training Program &#8212; open to all nationalities</span><span>&#8594;</span></a>
</div>
</article>

<aside class="sidebar">
<div class="sidebar-card">
<h4>Quick facts</h4>
<dl>
{f'<div class="fact-row"><dt>Provider</dt><dd>{university}</dd></div>' if university else ''}
{f'<div class="fact-row"><dt>Value</dt><dd>{amount}</dd></div>' if amount else ''}
{f'<div class="fact-row"><dt>Funding</dt><dd>{fund_type}</dd></div>' if fund_type else ''}
{f'<div class="fact-row"><dt>Level</dt><dd>{level}</dd></div>' if level else ''}
{f'<div class="fact-row"><dt>Open to</dt><dd>{open_to}</dd></div>' if open_to else ''}
{f'<div class="fact-row"><dt>Application</dt><dd>{app_mode}</dd></div>' if app_mode else ''}
{f'<div class="fact-row"><dt>Deadline</dt><dd>{deadline}</dd></div>' if deadline else ''}
<div class="fact-row"><dt>Verified</dt><dd>{pub_date}</dd></div>
</dl>
<a href="{source_url}" class="apply-btn" target="_blank" rel="noopener">Apply now &#8594;</a>
</div>
<div class="sidebar-card">
<h4>Also consider</h4>
<a href="/melbourne-graduate-research-scholarship" style="display:block;font-size:13.5px;font-weight:600;color:var(--terra-d);text-decoration:none;padding:8px 0;border-bottom:1px solid var(--line)">Melbourne MGRS &#8212; $39,500/yr &#8594;</a>
<a href="/sydney-usydis-scholarship" style="display:block;font-size:13.5px;font-weight:600;color:var(--terra-d);text-decoration:none;padding:8px 0;border-bottom:1px solid var(--line)">Sydney USYDIS &#8212; $42,754/yr &#8594;</a>
<a href="/australia-awards-scholarship-2027" style="display:block;font-size:13.5px;font-weight:600;color:var(--terra-d);text-decoration:none;padding:8px 0">Australia Awards &#8212; fully funded &#8594;</a>
</div>
</aside>
</div>
</div>
</div>

<footer>
<div class="cw">
<div class="fb">
<span>&#169; 2026 {SITE_NAME} &#8212; Independent scholarship reference. Not affiliated with the Australian Government or any listed institution.</span>
<a href="/" style="color:var(--terra);text-decoration:none">&#8592; All scholarships</a>
</div>
</div>
</footer>

<script>
document.querySelectorAll('.faq-q').forEach(b=>{{b.addEventListener('click',()=>b.closest('.faq-item').classList.toggle('open'))}});
window.addEventListener('scroll',()=>{{document.getElementById('mainNav').classList.toggle('scrolled',window.scrollY>40)}},{{passive:true}});
</script>
<script>
(function(){{var _l=false;function _a(){{if(_l)return;_l=true;var s=document.createElement('script');s.async=true;s.crossOrigin='anonymous';s.src='https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_PUB}';document.head.appendChild(s);}}window.addEventListener('scroll',_a,{{once:true,passive:true}});setTimeout(_a,3000);}})();
</script>
<script>
(function(){{var i=document.createElement('iframe');i.src='https://australiaawardshub-chatbot.vercel.app/widget';i.id='aah-chat';i.style.cssText='position:fixed;bottom:0;right:0;width:420px;height:680px;max-width:100vw;max-height:100vh;border:none;z-index:99999;pointer-events:none;background:transparent';i.onload=function(){{i.style.pointerEvents='none';}};window.addEventListener('message',function(e){{if(e.data&&e.data.aahOpen!==undefined){{i.style.pointerEvents=e.data.aahOpen?'all':'none';}}}});document.body.appendChild(i);}})();
</script>
</body>
</html>"""
    return html


# ─── Save + record ────────────────────────────────────────────────────────────

def publish_scholarship(scholarship: dict) -> str | None:
    """
    Generate and save the HTML file.
    Returns the filename on success, None on failure.
    """
    slug = scholarship.get("slug")
    if not slug:
        logger.error("No slug — cannot publish")
        return None

    html = build_html(scholarship)
    filename = f"{slug}.html"
    filepath = OUTPUT_DIR / filename

    try:
        filepath.write_text(html, encoding="utf-8")
        logger.info(f"HTML saved: {filepath}")
    except IOError as e:
        logger.error(f"File write error: {e}")
        return None

    # Record in published.json
    published = load_published()
    published[slug] = {
        "slug":        slug,
        "title":       scholarship.get("title", ""),
        "source_url":  scholarship.get("url", ""),
        "university":  scholarship.get("university", ""),
        "deadline":    scholarship.get("deadline", ""),
        "published_at":datetime.utcnow().isoformat(),
        "filename":    filename,
        "word_count":  scholarship.get("word_count", 0),
        "category":    scholarship.get("category", ""),
    }
    save_published(published)
    return filename


# ─── Sitemap + RSS ────────────────────────────────────────────────────────────

def update_sitemap(published: dict, sitemap_path: Path) -> None:
    """Regenerate sitemap.xml from published.json entries."""
    urls = []
    for slug, entry in published.items():
        pub_date = entry.get("published_at", datetime.utcnow().isoformat())[:10]
        urls.append(
            f"  <url>\n"
            f"    <loc>{SITE_URL}/{slug}</loc>\n"
            f"    <lastmod>{pub_date}</lastmod>\n"
            f"    <changefreq>monthly</changefreq>\n"
            f"    <priority>0.7</priority>\n"
            f"  </url>"
        )

    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )
    sitemap_path.write_text(sitemap, encoding="utf-8")
    logger.info(f"Sitemap updated: {sitemap_path} ({len(urls)} URLs)")


def update_rss(published: dict, rss_path: Path) -> None:
    """Generate RSS feed from latest 20 published articles."""
    items = sorted(published.values(), key=lambda x: x.get("published_at", ""), reverse=True)[:20]

    rss_items = ""
    for entry in items:
        slug  = entry.get("slug", "")
        title = entry.get("title", "")
        url   = f"{SITE_URL}/{slug}"
        pub   = entry.get("published_at", "")[:10]
        rss_items += (
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid isPermaLink='true'>{url}</guid>\n"
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <description>{entry.get('university', '')} — {entry.get('deadline', '')}</description>\n"
            f"  </item>\n"
        )

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n<channel>\n'
        f'  <title>{SITE_NAME}</title>\n'
        f'  <link>{SITE_URL}</link>\n'
        f'  <description>Latest Australian scholarship articles</description>\n'
        f'  <language>en-au</language>\n'
        + rss_items
        + '</channel>\n</rss>'
    )
    rss_path.write_text(rss, encoding="utf-8")
    logger.info(f"RSS updated: {rss_path}")
