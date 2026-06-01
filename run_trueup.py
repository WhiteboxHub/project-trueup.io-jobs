"""
run_trueup.py  —  Standalone TrueUp launcher
=============================================
Step 1: Login → My Jobs feed → Past week → click cards → save URLs

Flow:
  1. Login (email, password, manual OTP)
  2. Nav → Jobs (my jobs feed)
  3. Date dropdown → Past week
  4. Click each job card → capture ATS URL from new tab → output_jobs.json

Usage:
    python run_trueup.py
    python run_trueup.py --login-only   # just login and stop
"""

import sys
import os
import argparse

# ── Project root on path ──────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── Load .env before anything that reads env vars ─────────────────────────────
try:
    from dotenv import load_dotenv
    env_file = os.path.join(ROOT, ".env")
    if not os.path.isfile(env_file):
        env_file = os.path.join(ROOT, ".env.us_machine")
    if os.path.isfile(env_file):
        load_dotenv(env_file, override=False)
        print(f"[run_trueup] Loaded env from: {env_file}")
except ImportError:
    pass

from core.logger import logger
from core.browser import browser_service
from strategies.custom.trueup import TrueUpStrategy, OUTPUT_JSON


def main():
    parser = argparse.ArgumentParser(description="TrueUp Step-1 Launcher")
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Login only — skip job scraping",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🚀  TrueUp Job Extractor — Step 1")
    logger.info("=" * 60)
    logger.info("📁  Output will be saved to: %s", os.path.abspath(OUTPUT_JSON))

    # Kill ghost browser sessions that may hold the profile directory
    logger.info("🧹 Killing ghost browser processes...")
    if os.name == "nt":
        os.system("taskkill /F /IM chrome.exe  /T >nul 2>&1")
        os.system("taskkill /F /IM chromedriver.exe /T >nul 2>&1")
        import time; time.sleep(2)

    driver = None
    try:
        # ── Start browser ─────────────────────────────────────────────────────
        logger.info("🌐 Starting browser...")
        driver = browser_service.start_browser()
        if not driver:
            logger.error("❌ Could not start browser. Exiting.")
            sys.exit(1)
        logger.info("✅ Browser started")

        # Close any extra restored background tabs
        try:
            import time
            handles = driver.window_handles
            if len(handles) > 1:
                primary = driver.current_window_handle
                for h in handles:
                    if h != primary:
                        driver.switch_to.window(h)
                        driver.close()
                driver.switch_to.window(primary)
                driver.execute_script("window.focus();")
        except Exception as te:
            logger.warning("Could not sanitize extra tabs: %s", te)

        # ── Instantiate strategy ──────────────────────────────────────────────
        strategy = TrueUpStrategy(driver=driver)

        # ── Login flow ────────────────────────────────────────────────────────
        logger.info("🔐 Starting login flow...")
        ok = strategy.login()
        if not ok:
            logger.error("❌ Login failed. Check TRUEUP_EMAIL / TRUEUP_PASSWORD in .env or trueup.json")
            return

        logger.info("✅ Login complete! Current URL: %s", driver.current_url)

        if args.login_only:
            logger.info("--login-only flag set — stopping.")
            input("\n⏸  Browser open. Press ENTER to close...")
            return

        # ── Run job discovery ─────────────────────────────────────────────────
        logger.info("\n🔍 Starting job discovery (Step 1)...")
        jobs = strategy.find_jobs()

        logger.info("\n" + "=" * 60)
        logger.info("✅  Step 1 Complete!")
        logger.info("   Total jobs captured : %d", len(jobs))
        logger.info("   Output file         : %s", os.path.abspath(OUTPUT_JSON))
        logger.info("=" * 60)

        # Print preview of first 10
        for i, job in enumerate(jobs[:10], 1):
            logger.info(
                "  [%d] %s — %s",
                i,
                job.get("title", "?"),
                job.get("ats_url") or job.get("trueup_url", "?"),
            )
        if len(jobs) > 10:
            logger.info("  ... and %d more (see %s)", len(jobs) - 10, OUTPUT_JSON)

    except KeyboardInterrupt:
        logger.info("\n⏹  Interrupted by user.")
    except Exception as exc:
        logger.error("❌ Unexpected error: %s", exc)
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            input("\n⏸  Press ENTER to close the browser...")
            browser_service.stop_browser()
            logger.info("✅ Browser closed.")


if __name__ == "__main__":
    main()
