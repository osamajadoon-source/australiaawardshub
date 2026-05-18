"""
main.py — Master orchestration for the daily scholarship agent.
"""

import logging
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    MAX_ARTICLES_PER_DAY, DATA_DIR, OUTPUT_DIR, LOG_DIR,
    SCHOLARSHIPS_JSON
)
from scraper import scrape_all_sources
from verifier import verify_and_rank, load_published
from ai_writer import generate_article
from publisher import publish_scholarship, update_sitemap, update_rss
from github_uploader import upload_generated_files

LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"agent_{datetime.utcnow().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("main")


def save_scholarships_cache(scholarships):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCHOLARSHIPS_JSON, "w", encoding="utf-8") as f:
        json.dump(scholarships, f, indent=2, default=str)


def write_run_report(report):
    report_file = LOG_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Run report saved: {report_file}")


def run_agent():
    start_time = datetime.utcnow()
    report = {
        "run_started":     start_time.isoformat(),
        "scraped":         0,
        "verified":        0,
        "generated":       0,
        "published":       0,
        "uploaded":        0,
        "errors":          [],
        "published_slugs": [],
    }

    logger.info("=" * 60)
    logger.info("SCHOLARSHIP AGENT — DAILY RUN STARTED")
    logger.info(f"Time: {start_time.isoformat()}")
    logger.info("=" * 60)

    # ── STEP 1: Scrape ────────────────────────────────────────────
    logger.info("\n[STEP 1] Scraping official scholarship sources...")
    try:
        raw_scholarships = scrape_all_sources()
        report["scraped"] = len(raw_scholarships)
        save_scholarships_cache(raw_scholarships)
        logger.info(f"Scraped {len(raw_scholarships)} candidate scholarships")
    except Exception as e:
        logger.error(f"Scraping failed: {e}\n{traceback.format_exc()}")
        report["errors"].append(f"Scraping: {e}")
        raw_scholarships = []

    if not raw_scholarships:
        logger.warning("No scholarships scraped. Exiting.")
        report["run_completed"] = datetime.utcnow().isoformat()
        write_run_report(report)
        return report

    # ── STEP 2: Verify ────────────────────────────────────────────
    logger.info("\n[STEP 2] Verifying scholarships...")
    try:
        verified = verify_and_rank(raw_scholarships)
        report["verified"] = len(verified)
        logger.info(f"Verified: {len(verified)} scholarships pass all checks")
    except Exception as e:
        logger.error(f"Verification failed: {e}\n{traceback.format_exc()}")
        report["errors"].append(f"Verification: {e}")
        verified = []

    if not verified:
        logger.warning("No new scholarships to publish today.")
        report["run_completed"] = datetime.utcnow().isoformat()
        write_run_report(report)
        return report

    # ── STEP 3: Generate articles ─────────────────────────────────
    logger.info(f"\n[STEP 3] Generating up to {MAX_ARTICLES_PER_DAY} articles with Gemini...")
    generated = []
    for scholarship in verified[:MAX_ARTICLES_PER_DAY]:
        logger.info(f"\nProcessing: {scholarship['title'][:60]}")
        try:
            article = generate_article(scholarship)
            if not article:
                logger.warning(f"  Article generation returned None — skipping")
                report["errors"].append(f"Generation failed: {scholarship['title'][:50]}")
                continue
            wc = article.get("word_count", 0)
            if wc < 800:
                logger.warning(f"  Article too short ({wc} words) — skipping")
                continue
            generated.append(article)
            logger.info(f"  Article generated OK: {wc} words, slug={article.get('slug','?')}")
        except Exception as e:
            logger.error(f"  Error generating article: {e}\n{traceback.format_exc()}")
            report["errors"].append(f"AI error ({scholarship['title'][:40]}): {e}")

    report["generated"] = len(generated)

    # ── STEP 4: Publish HTML ──────────────────────────────────────
    logger.info(f"\n[STEP 4] Building HTML pages...")
    published_files = []
    for article in generated:
        try:
            filename = publish_scholarship(article)
            if filename:
                published_files.append(filename)
                report["published_slugs"].append(article.get("slug", ""))
                logger.info(f"  Published: {filename}")
        except Exception as e:
            logger.error(f"  HTML build error: {e}\n{traceback.format_exc()}")
            report["errors"].append(f"HTML build: {e}")

    report["published"] = len(published_files)

    # ── STEP 5: Update sitemap + RSS ──────────────────────────────
    if published_files:
        logger.info("\n[STEP 5] Updating sitemap and RSS feed...")
        try:
            all_published = load_published()
            update_sitemap(all_published, OUTPUT_DIR / "sitemap.xml")
            update_rss(all_published, OUTPUT_DIR / "feed.xml")
            published_files += ["sitemap.xml", "feed.xml"]
        except Exception as e:
            logger.error(f"Sitemap/RSS update error: {e}")

    # ── STEP 6: Push to GitHub ────────────────────────────────────
    logger.info("\n[STEP 6] Uploading to GitHub...")
    if published_files:
        try:
            upload_results = upload_generated_files(published_files)
            report["uploaded"] = upload_results["success"]
            logger.info(f"GitHub upload: {upload_results['success']} succeeded, {upload_results['failed']} failed")
        except Exception as e:
            logger.error(f"GitHub upload failed: {e}")
            report["errors"].append(f"GitHub: {e}")
    else:
        logger.info("Nothing to upload.")

    end_time = datetime.utcnow()
    duration = (end_time - start_time).seconds
    report["run_completed"] = end_time.isoformat()
    report["duration_seconds"] = duration

    logger.info("\n" + "=" * 60)
    logger.info("RUN COMPLETE")
    logger.info(f"  Scraped:    {report['scraped']}")
    logger.info(f"  Verified:   {report['verified']}")
    logger.info(f"  Generated:  {report['generated']}")
    logger.info(f"  Published:  {report['published']}")
    logger.info(f"  Uploaded:   {report['uploaded']}")
    logger.info(f"  Errors:     {len(report['errors'])}")
    logger.info(f"  Duration:   {duration}s")
    logger.info("=" * 60)

    write_run_report(report)
    return report


if __name__ == "__main__":
    run_agent()
