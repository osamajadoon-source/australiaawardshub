"""
scheduler.py — Local scheduler for running the agent without GitHub Actions.
Use this if you want to run on your own machine or a VPS.

Run: python agent/scheduler.py
"""

import schedule
import time
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import run_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("scheduler")


def job():
    logger.info("Scheduled run starting...")
    report = run_agent()
    logger.info(f"Run finished. Published: {report.get('published', 0)}")


# Run once immediately on start, then daily at 09:00 local time
if __name__ == "__main__":
    logger.info("Scholarship Agent Scheduler started. Running now + daily at 09:00.")
    job()  # immediate run
    schedule.every().day.at("09:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
