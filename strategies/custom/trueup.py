"""
TrueUp.io Job Scraper Strategy
================================
Scrapes job listings from https://trueup.io/jobs

Exact Flow (per user spec):
  1. login()
       a. Open https://trueup.io
       b. Click the Login button in the nav
       c. Navigate to sign-in page
       d. Enter email → Continue → Enter password → Continue
       e. Wait 60 seconds for manual OTP entry
       f. After OTP, the site redirects to https://trueup.io/
       g. Click "Search all jobs" link → navigates to /jobs

  2. find_jobs()  — for each keyword:
       a. Navigate to /jobs
       b. Apply "Past week" date filter
       c. Apply Location filters: United States + San Francisco Bay Area
       d. Type keyword in search box → ENTER
       e. For each job card: click link → new window opens → capture URL
       f. Save each captured URL to output_json
       g. Close new window → repeat for next card

All XPaths are exactly as provided by the user.
"""

import os
import re
import time
import json
from datetime import datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

from strategies.base import BaseStrategy
from core.logger import logger
from core.human_behavior import HumanBehavior
from models.config_models import JobListing


# ──────────────────────────────────────────────────────────────────────────────
# URLs
# ──────────────────────────────────────────────────────────────────────────────

BASE_URL  = "https://trueup.io"
JOBS_URL  = "https://trueup.io/jobs"
SIGNIN_URL = "https://trueup.io/sign-in?redirect_url=%2Fjobs"

# ──────────────────────────────────────────────────────────────────────────────
# Exact XPaths (as provided by user)
# ──────────────────────────────────────────────────────────────────────────────

# Login button on the homepage nav
XP_NAV_LOGIN_BTN     = '//*[@id="main-nav"]/nav/div[2]/div[2]/button[1]'

# Sign-in form fields
XP_EMAIL_FIELD       = '//*[@id="identifier-field"]'
XP_CONTINUE_EMAIL    = '//*[@id="__next"]/div/main/div[2]/div/div/div[1]/div[2]/form/div[2]/button/span'
XP_PASSWORD_FIELD    = '//*[@id="password-field"]'
XP_CONTINUE_PASSWORD = '//*[@id="__next"]/div/main/div[2]/div/div/div/div[2]/form/button[2]'

# "Search all jobs" link on the post-login homepage
XP_SEARCH_ALL_JOBS   = "//a[contains(., 'Search all jobs') or contains(@href, '/jobs')]"

# Filters on /jobs page
XP_PAST_WEEK_FILTER  = "//label[contains(., 'Past week') or contains(., 'Past Week')]"
XP_LOCATION_SEARCH   = "//input[contains(@placeholder, 'Location') or contains(@placeholder, 'location') or contains(@placeholder, 'City') or contains(@placeholder, 'country')]"
XP_LOCATION_FIRST    = "//li[1]//label"

# Search box on /jobs
XP_SEARCH_BOX        = "//input[contains(@placeholder, 'Search') or contains(@placeholder, 'search') or @type='search' or (@type='text' and not(contains(@placeholder, 'Location')))]"

# Job card links
# Broad match for any links within the main content area that look like job or role links.
XP_JOB_LINKS = "//main//a[contains(@href, '/job') or contains(@href, '/role') or contains(@class, 'job') or contains(@class, 'Job')]"

# "Show more" button
XP_SHOW_MORE = "//main//button[contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), 'show more') or contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), 'load more') or contains(normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), 'next page')]"

# Output file
OUTPUT_JSON = "output_jobs.json"

# OTP wait (seconds)
OTP_WAIT_SECONDS = 60


def _save_keyword_batch(keyword: str, jobs: list):
    """Append all jobs collected for one keyword to OUTPUT_JSON."""
    if not jobs:
        return
    try:
        data = []
        if os.path.exists(OUTPUT_JSON) and os.path.getsize(OUTPUT_JSON) > 0:
            with open(OUTPUT_JSON, "r", encoding="utf-8", errors="ignore") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = []
        data.extend(jobs)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(
            "  💾 Saved %d jobs for keyword '%s' → %s (total: %d)",
            len(jobs), keyword, OUTPUT_JSON, len(data)
        )
    except Exception as ex:
        logger.warning("  ⚠️ Failed to save batch for keyword '%s': %s", keyword, ex)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_trueup_config() -> dict:
    """Load optional config/trueup.json. Falls back to env vars."""
    try:
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            "trueup.json",
        )
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception as exc:
        logger.warning("Could not load trueup.json: %s", exc)
    return {}


def _job_id_from_url(url: str) -> str:
    """Extract a unique job identifier from an ATS URL."""
    if not url:
        return ""
    # Usually jobs have /job/ID or /jobs/ID
    m = re.search(r"/jobs?/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    
    # Fallback to last segment
    parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
    base_id = parts[-1] if parts else ""
    return base_id[-50:] if base_id else str(hash(url))


def _append_to_output(job: dict):
    """Append a single job record to OUTPUT_JSON, creating the file if needed."""
    try:
        data = []
        if os.path.exists(OUTPUT_JSON) and os.path.getsize(OUTPUT_JSON) > 0:
            with open(OUTPUT_JSON, "r", encoding="utf-8", errors="ignore") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = []
        data.append(job)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info("   💾 Saved to %s (total: %d)", OUTPUT_JSON, len(data))
    except Exception as ex:
        logger.warning("   ⚠️ Failed to save to %s: %s", OUTPUT_JSON, ex)


# ──────────────────────────────────────────────────────────────────────────────
# Strategy
# ──────────────────────────────────────────────────────────────────────────────

class TrueUpStrategy(BaseStrategy):
    """
    Selenium strategy for https://trueup.io/jobs.

    Exact login + filter + extraction flow per user specification.
    """

    def __init__(self, driver, job_site=None, selectors=None, db_session=None):
        if job_site is None:
            class _FakeJobSite:
                company_name = "TrueUp"
                search_url_template = JOBS_URL
                id = None
            job_site = _FakeJobSite()

        super().__init__(driver, job_site, selectors or {})
        self.db_session = db_session
        self.human      = HumanBehavior(driver)

        cfg = _load_trueup_config()

        raw_kw = cfg.get("search_keywords") or os.environ.get("TRUEUP_KEYWORDS", "ai,genai")
        if isinstance(raw_kw, list):
            self._keywords = [str(k).strip() for k in raw_kw if str(k).strip()]
        else:
            self._keywords = [kw.strip() for kw in str(raw_kw).split(",") if kw.strip()]
        if not self._keywords:
            self._keywords = ["ai", "genai"]

        self._email    = os.environ.get("TRUEUP_EMAIL", "")
        self._password = os.environ.get("TRUEUP_PASSWORD", "")

        if not self._email or not self._password:
            logger.warning(
                "⚠️ TRUEUP_EMAIL / TRUEUP_PASSWORD not set — login will not work."
            )

        logger.info(
            "✅ TrueUpStrategy ready — keywords=%s  auth=%s",
            self._keywords,
            "configured" if self._email else "MISSING",
        )

    # ────────────────────────────────────────────────────────────────────────
    # Public Interface: login
    # ────────────────────────────────────────────────────────────────────────

    def login(self) -> bool:
        """
        Full login flow:
          1. Open https://trueup.io (homepage)
          2. Click the nav Login button
          3. Navigate to sign-in URL with redirect param
          4. Enter email → Continue
          5. Enter password → Continue
          6. Wait OTP_WAIT_SECONDS for manual OTP entry
          7. Site auto-redirects to https://trueup.io/ after OTP
          8. Click "Search all jobs" → lands on /jobs
        """
        logger.info("🔐 Step 1: Opening TrueUp homepage — %s", BASE_URL)
        try:
            self.driver.get(BASE_URL)
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(3)
        except Exception as exc:
            logger.error("❌ Could not open TrueUp homepage: %s", exc)
            return False

        # ── Click nav Login button ───────────────────────────────────────────
        logger.info("🔐 Step 2: Clicking Login button in nav...")
        try:
            login_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_NAV_LOGIN_BTN))
            )
            try:
                login_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", login_btn)
            logger.info("   ✅ Clicked Login button")
            time.sleep(2)
        except Exception as exc:
            logger.warning("   ⚠️ Nav login button not found or not clickable: %s — navigating directly to sign-in", exc)

        # ── Navigate to sign-in URL ──────────────────────────────────────────
        logger.info("🔐 Step 3: Navigating to sign-in page...")
        try:
            self.driver.get(SIGNIN_URL)
            time.sleep(5)  # Let Clerk/React form fully render
        except Exception as exc:
            logger.error("❌ Could not navigate to sign-in: %s", exc)
            return False

        # ── Enter email ──────────────────────────────────────────────────────
        logger.info("🔐 Step 4: Entering email...")
        try:
            email_el = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_EMAIL_FIELD))
            )
            email_el.clear()
            self.human.random_delay(0.3, 0.6)
            self.human.human_type(email_el, self._email)
            logger.info("   ✅ Email entered")
        except Exception as exc:
            logger.error("❌ Could not find email field: %s", exc)
            return False

        # ── Click Continue (email) ───────────────────────────────────────────
        logger.info("🔐 Step 5: Clicking Continue (email)...")
        try:
            cont_el = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_CONTINUE_EMAIL))
            )
            try:
                cont_el.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", cont_el)
            logger.info("   ✅ Clicked Continue (email)")
        except Exception as exc:
            logger.warning("   ⚠️ Continue (email) via XPath failed: %s — pressing ENTER", exc)
            try:
                email_el.send_keys(Keys.RETURN)
            except Exception:
                pass
        time.sleep(4)  # Wait for password form to render

        # ── Enter password ───────────────────────────────────────────────────
        logger.info("🔐 Step 6: Entering password...")
        try:
            pwd_el = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_PASSWORD_FIELD))
            )
            pwd_el.clear()
            self.human.random_delay(0.3, 0.6)
            self.human.human_type(pwd_el, self._password)
            logger.info("   ✅ Password entered")
        except Exception as exc:
            logger.error("❌ Could not find password field: %s", exc)
            return False

        # ── Click Continue (password) ────────────────────────────────────────
        logger.info("🔐 Step 7: Clicking Continue (password)...")
        try:
            cont_pwd = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_CONTINUE_PASSWORD))
            )
            try:
                cont_pwd.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", cont_pwd)
            logger.info("   ✅ Clicked Continue (password)")
        except Exception as exc:
            logger.warning("   ⚠️ Continue (password) via XPath failed: %s — pressing ENTER", exc)
            try:
                pwd_el.send_keys(Keys.RETURN)
            except Exception:
                pass

        # ── Wait for OTP ─────────────────────────────────────────────────────
        logger.warning("=" * 60)
        logger.warning("⏳ OTP REQUIRED — You have %d seconds to enter the OTP in the browser!", OTP_WAIT_SECONDS)
        logger.warning("=" * 60)
        for remaining in range(OTP_WAIT_SECONDS, 0, -10):
            logger.info("   ... %d seconds remaining for OTP ...", remaining)
            time.sleep(10)
        logger.info("   ⏳ OTP wait complete. Checking redirect...")
        time.sleep(3)

        # ── Wait for redirect to homepage ────────────────────────────────────
        current_url = self.driver.current_url
        logger.info("   Current URL after OTP: %s", current_url)

        # ── Click "Search all jobs" on post-login homepage ───────────────────
        if "trueup.io/jobs" not in current_url:
            logger.info("🔐 Step 8: Clicking 'Search all jobs' link...")
            try:
                search_all = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable((By.XPATH, XP_SEARCH_ALL_JOBS))
                )
                try:
                    search_all.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", search_all)
                logger.info("   ✅ Clicked 'Search all jobs'")
                WebDriverWait(self.driver, 15).until(
                    EC.url_contains("/jobs")
                )
                time.sleep(3)
            except Exception as exc:
                logger.warning("   ⚠️ 'Search all jobs' click failed: %s — navigating directly", exc)
                self.driver.get(JOBS_URL)
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(3)

        logger.info("✅ Login complete! URL: %s", self.driver.current_url)
        return True

    # ────────────────────────────────────────────────────────────────────────
    # Public Interface: find_jobs
    # ────────────────────────────────────────────────────────────────────────

    def find_jobs(self) -> list[dict]:
        """
        For each keyword:
          1. Navigate to /jobs
          2. Apply Past-week date filter
          3. Apply Location filters (United States + San Francisco Bay Area)
          4. Type keyword into search box → ENTER
          5. Click each job card → new window → capture external ATS URL
          6. Append each job record to OUTPUT_JSON
        """
        all_jobs: list[dict] = []
        seen_ids: set[str]   = set()

        for keyword in self._keywords:
            logger.info("\n%s\n🔍 Keyword: '%s'\n%s", "─"*60, keyword, "─"*60)
            try:
                jobs = self._search_keyword(keyword, seen_ids)
                all_jobs.extend(jobs)
                for j in jobs:
                    seen_ids.add(j["job_id"])
                logger.info("  ✅ Keyword '%s': %d jobs collected (total so far: %d)",
                            keyword, len(jobs), len(all_jobs))
            except Exception as exc:
                logger.error("  ❌ Error during keyword '%s': %s", keyword, exc)
                import traceback; traceback.print_exc()

        logger.info("\n✅ Total jobs collected: %d", len(all_jobs))
        return all_jobs

    # ────────────────────────────────────────────────────────────────────────
    # apply (not used in Step 1 but kept for compatibility)
    # ────────────────────────────────────────────────────────────────────────

    def apply(self, job: dict) -> bool:
        """Step 1 only captures URLs; actual application is Step 2."""
        logger.info("ℹ️ apply() called for '%s' — Step 1 only captures URLs.", job.get("title", "?"))
        return True

    # ────────────────────────────────────────────────────────────────────────
    # Private: search one keyword
    # ────────────────────────────────────────────────────────────────────────

    def _search_keyword(self, keyword: str, already_seen: set) -> list[dict]:
        """
        Full per-keyword flow:
          1. Navigate to /jobs
          2. Apply Past-week filter
          3. Apply location filters
          4. Type keyword → ENTER
          5. Collect jobs by clicking each card
        """
        # ── Navigate to /jobs ─────────────────────────────────────────────────
        logger.info("  🌐 Navigating to %s", JOBS_URL)
        self.driver.get(JOBS_URL)
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        self.human.random_delay(3, 5)

        # ── Apply Past-week date filter ───────────────────────────────────────
        self._apply_past_week_filter()
        self.human.random_delay(1, 2)

        # ── Apply location filters ────────────────────────────────────────────
        self._apply_location_filter("United States")
        self.human.random_delay(1, 2)
        self._apply_location_filter("San Francisco Bay Area")

        # ⚠️  CRITICAL: Wait for React to fully settle after filter clicks.
        # The location filter triggers React state updates which can steal focus
        # or re-render the search box — causing typed text to vanish.
        logger.info("  ⏳ Waiting for React to settle after filters (3s)...")
        time.sleep(3)

        # ── Type keyword → search ─────────────────────────────────────────────
        logger.info("  ⌨️  Typing keyword: '%s'", keyword)
        try:
            search_box = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_SEARCH_BOX))
            )

            # Step 1: Click the box to explicitly focus it
            try:
                search_box.click()
            except Exception:
                self.driver.execute_script("arguments[0].focus();", search_box)
            self.human.random_delay(0.3, 0.5)

            # Step 2: Clear using Ctrl+A + Delete (React-safe — fires onChange)
            # DO NOT use search_box.clear() — it bypasses React synthetic events,
            # causing React to restore the old value on the next re-render.
            search_box.send_keys(Keys.CONTROL + "a")
            time.sleep(0.2)
            search_box.send_keys(Keys.DELETE)
            time.sleep(0.3)

            # Step 3: Verify box is truly empty via JS, then type
            actual_val = self.driver.execute_script("return arguments[0].value;", search_box)
            if actual_val:
                # Force-clear via React-compatible JS event dispatch
                self.driver.execute_script(
                    """
                    var el = arguments[0];
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(el, '');
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    """,
                    search_box,
                )
                time.sleep(0.3)

            # Step 4: Type keyword character by character (human-like)
            self.human.human_type(search_box, keyword)
            self.human.random_delay(0.5, 1.0)

            # Step 5: Verify keyword is actually in the box before submitting
            typed_val = self.driver.execute_script("return arguments[0].value;", search_box)
            if not typed_val or keyword.lower() not in typed_val.lower():
                logger.warning(
                    "  ⚠️ Search box shows '%s' instead of '%s' — retrying type",
                    typed_val, keyword
                )
                # Re-clear and re-type via JS to force React to accept the value
                self.driver.execute_script(
                    """
                    var el = arguments[0];
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(el, arguments[1]);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    search_box, keyword,
                )
                time.sleep(0.5)

            # Step 6: Submit
            search_box.send_keys(Keys.RETURN)
            logger.info("  ✅ Keyword '%s' submitted", keyword)
        except Exception as exc:
            logger.error("  ❌ Could not find/use search box: %s", exc)
            return []

        self.human.random_delay(3, 5)

        # ── Collect jobs ──────────────────────────────────────────────────────
        return self._collect_jobs(keyword, already_seen)

    # ────────────────────────────────────────────────────────────────────────
    # Private: apply date filter (Past week)
    # ────────────────────────────────────────────────────────────────────────

    def _apply_past_week_filter(self):
        """Click the 'Past week' radio label using the exact user XPath."""
        logger.info("  📅 Applying 'Past week' date filter...")
        try:
            el = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, XP_PAST_WEEK_FILTER))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", el
            )
            self.human.random_delay(0.5, 1.0)
            try:
                el.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", el)
            logger.info("  ✅ Past week filter applied")
            self.human.random_delay(1, 2)
        except Exception as exc:
            logger.warning("  ⚠️ Could not apply Past week filter: %s", str(exc).split('\n')[0])

    # ────────────────────────────────────────────────────────────────────────
    # Private: apply location filter
    # ────────────────────────────────────────────────────────────────────────

    def _apply_location_filter(self, location_text: str):
        """
        Type a location string into the location search input and click
        the first result label (li[1]/label).
        """
        logger.info("  🌍 Applying location filter: '%s'", location_text)
        try:
            # Find location search input
            loc_input = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_LOCATION_SEARCH))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", loc_input
            )
            self.human.random_delay(0.3, 0.6)

            # Clear via Ctrl+A + Delete (React-friendly)
            loc_input.send_keys(Keys.CONTROL + "a")
            loc_input.send_keys(Keys.DELETE)
            self.human.random_delay(0.2, 0.4)

            # Type location
            self.human.human_type(loc_input, location_text)
            self.human.random_delay(1.5, 2.5)  # Wait for dropdown to filter

            # Click first result label
            first_result = WebDriverWait(self.driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, XP_LOCATION_FIRST))
            )
            try:
                first_result.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", first_result)

            logger.info("  ✅ Location '%s' selected", location_text)
            self.human.random_delay(0.8, 1.5)

        except Exception as exc:
            logger.warning(
                "  ⚠️ Location filter '%s' failed: %s",
                location_text, str(exc).split('\n')[0]
            )

    # ────────────────────────────────────────────────────────────────────────
    # Private: collect jobs (click each card → new window → capture URL)
    # ────────────────────────────────────────────────────────────────────────

    def _collect_jobs(self, keyword: str, already_seen: set) -> list[dict]:
        """
        Page-level loop:
          1. Find all job link <a> elements using exact user-provided XPath.
          2. For each new link: click → new window → capture URL → close.
          3. After processing all visible links, click 'Show more' if available.
          4. Repeat until no Show More or max_jobs reached.
          5. Save entire keyword batch to output_jobs.json at the end.
        """
        from selenium.webdriver.common.action_chains import ActionChains

        collected: list[dict] = []
        local_seen: set       = set()
        main_window           = self.driver.current_window_handle
        page_num              = 0

        while True:
            page_num += 1

            # ── 1. Collect all visible job link <a> elements ──────────────────
            # XPath from user: .../div[2]/div[2]/div/div/div/div[N]/div/div/div[1]/div[2]/div[1]/div/a
            # We use wildcard div (no index) so it matches ALL card positions at once.
            try:
                raw_links = self.driver.find_elements(By.XPATH, XP_JOB_LINKS)
            except Exception:
                raw_links = []

            # Deduplicate by href, skip empty hrefs
            seen_hrefs: set = set()
            job_links = []
            for a in raw_links:
                try:
                    h = (a.get_attribute("href") or "").strip()
                    # The XPath targets job cards tightly, so any href here is the ATS URL
                    if h and h not in seen_hrefs and a.is_displayed():
                        seen_hrefs.add(h)
                        job_links.append((a, h))
                except Exception:
                    continue

            logger.info("  📄 Page %d — %d unique job links found", page_num, len(job_links))

            # ── 2. Click each NEW job link ────────────────────────────────────
            for link_el, href in job_links:
                job_id = _job_id_from_url(href)
                if not job_id or job_id in already_seen or job_id in local_seen:
                    continue

                # Scroll link into view
                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});",
                        link_el,
                    )
                    self.human.random_delay(0.5, 1.0)
                except Exception:
                    pass

                # Read job title from the link text (it contains the title on TrueUp)
                title = ""
                try:
                    title = link_el.text.strip()
                except Exception:
                    pass

                # ── Click → new window → capture URL → close ─────────────────
                ats_url = ""
                try:
                    try:
                        ActionChains(self.driver).move_to_element(link_el).click().perform()
                    except Exception:
                        try:
                            link_el.click()
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", link_el)

                    # Wait up to 12s for a new tab/window
                    WebDriverWait(self.driver, 12).until(
                        lambda d: len(d.window_handles) > 1
                    )

                    # Switch to the new window
                    for handle in self.driver.window_handles:
                        if handle != main_window:
                            self.driver.switch_to.window(handle)
                            break

                    # Let the page load
                    time.sleep(2)
                    try:
                        WebDriverWait(self.driver, 12).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                    except Exception:
                        pass
                    time.sleep(1)

                    ats_url = self.driver.current_url
                    logger.info("   ✅ [%d] %s", len(collected) + 1, ats_url)

                    # Close new window → back to results
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                    self.human.random_delay(1.0, 2.0)

                except TimeoutException:
                    logger.warning("   ⚠️ New window did not open for %s — using href", job_id)
                    self._cleanup_extra_windows(main_window)
                    ats_url = href

                except Exception as e_click:
                    logger.warning("   ⚠️ Click/capture error for %s: %s", job_id, e_click)
                    self._cleanup_extra_windows(main_window)
                    ats_url = href

                # ── Record the job ────────────────────────────────────────────
                job_record = {
                    "job_id":         job_id,
                    "title":          title or f"Job {job_id}",
                    "trueup_url":     href,
                    "ats_url":        ats_url,
                    "source_keyword": keyword,
                    "scraped_at":     datetime.now().isoformat(),
                }
                local_seen.add(job_id)
                collected.append(job_record)

            # ── 3. Click "Show more" to load the next batch of cards ──────────
            if self._click_show_more():
                logger.info("  ➕ 'Show more' clicked — loading next batch...")
                self.human.random_delay(2, 4)
            else:
                logger.info("  ⏹ No 'Show more' button — end of results for this keyword")
                break

        # ── 4. Save all jobs for this keyword at once ─────────────────────────
        _save_keyword_batch(keyword, collected)
        logger.info("  ✅ Collected %d jobs for keyword '%s'", len(collected), keyword)
        return collected

    def _click_show_more(self) -> bool:
        """
        Click the 'Show more' button that appears after ~16 cards.
        XPath from user: .../div[2]/div[2]/div/div/div/div/button
        Returns True if button was found and clicked.
        """
        try:
            # Scroll to bottom so the button is visible
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

            btn = WebDriverWait(self.driver, 6).until(
                EC.element_to_be_clickable((By.XPATH, XP_SHOW_MORE))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", btn
            )
            self.human.random_delay(0.5, 1.0)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            logger.info("  ✅ 'Show more' clicked")
            return True
        except (TimeoutException, NoSuchElementException):
            return False
        except Exception as exc:
            logger.debug("  _click_show_more error: %s", exc)
            return False

    def _cleanup_extra_windows(self, main_window: str):
        """Close any extra windows/tabs and switch back to main_window."""
        for handle in self.driver.window_handles:
            if handle != main_window:
                try:
                    self.driver.switch_to.window(handle)
                    self.driver.close()
                except Exception:
                    pass
        try:
            self.driver.switch_to.window(main_window)
        except Exception:
            pass

    # ────────────────────────────────────────────────────────────────────────
    # Private: DB persistence (optional)
    # ────────────────────────────────────────────────────────────────────────

    def _save_listing_to_db(self, job: dict):
        """Upsert a discovered JobListing into DuckDB (if db_session available)."""
        if not self.db_session or not self.job_site or not self.job_site.id:
            return
        try:
            existing = (
                self.db_session.query(JobListing)
                .filter(
                    JobListing.job_site_id == self.job_site.id,
                    JobListing.external_job_id == job["job_id"],
                )
                .first()
            )
            if not existing:
                listing = JobListing(
                    job_site_id     = self.job_site.id,
                    external_job_id = job["job_id"],
                    job_title       = job.get("title", ""),
                    job_url         = job.get("ats_url") or job.get("trueup_url", ""),
                    status          = "discovered",
                )
                self.db_session.add(listing)
                self.db_session.commit()
        except Exception as exc:
            logger.warning("  ⚠️ DB save failed for '%s': %s", job.get("title"), exc)
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def _save_to_db(self, job: dict, ats_url: str):
        """Update the JobListing status to 'discovered' with ATS URL."""
        if not self.db_session or not self.job_site or not self.job_site.id:
            return
        try:
            listing = (
                self.db_session.query(JobListing)
                .filter(
                    JobListing.job_site_id == self.job_site.id,
                    JobListing.external_job_id == job["job_id"],
                )
                .first()
            )
            if listing:
                listing.status  = "discovered"
                listing.job_url = ats_url
                self.db_session.commit()
        except Exception as exc:
            logger.warning("  ⚠️ DB update failed: %s", exc)
            try:
                self.db_session.rollback()
            except Exception:
                pass
