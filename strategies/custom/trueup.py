"""
TrueUp.io My Jobs scraper — post-login UI.

Flow: login → My Jobs nav → Past week filter → click job links → save ATS URLs.
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
    StaleElementReferenceException,
)

from strategies.base import BaseStrategy
from core.logger import logger
from core.human_behavior import HumanBehavior

# ── URLs ──────────────────────────────────────────────────────────────────────
BASE_URL = "https://trueup.io"
MYJOBS_URL = "https://trueup.io/myjobs"
SIGNIN_URL = "https://trueup.io/sign-in?redirect_url=%2Fmyjobs"

# ── XPaths (My Jobs UI) ───────────────────────────────────────────────────────
XP_NAV_LOGIN_BTN = '//*[@id="main-nav"]/nav/div[2]/div[2]/button[1]'
XP_EMAIL_FIELD = '//*[@id="identifier-field"]'
XP_CONTINUE_EMAIL = '//*[@id="__next"]/div/main/div[2]/div/div/div[1]/div[2]/form/div[2]/button/span'
XP_PASSWORD_FIELD = '//*[@id="password-field"]'
XP_CONTINUE_PASSWORD = '//*[@id="__next"]/div/main/div[2]/div/div/div/div[2]/form/button[2]'

XP_NAV_JOBS = '//*[@id="main-nav"]/nav/nav/div[1]/ul/li[1]/a'
XP_DATE_FILTER_BTN = '//*[@id="__next"]/div/main/div/div/div/div[1]/div/form/div/div/button'
XP_MYJOBS_JOB_LINKS = (
    '//*[@id="__next"]/div/main/div/div/div/div[1]/div/div[2]/div/div/div'
    '/div[1]/div[2]/div[1]/div/a'
)
XP_MYJOBS_SHOW_MORE = (
    '//*[@id="__next"]/div/main/div/div/div/div[1]/div/div[2]/button'
)

OUTPUT_JSON = "output_jobs.json"
OTP_WAIT_SECONDS = 60


def _load_trueup_config() -> dict:
    """Load optional config/trueup.json."""
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
    if not url:
        return ""
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/jobs?/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    parts = [p for p in url.split("?")[0].rstrip("/").split("/") if p]
    base_id = parts[-1] if parts else ""
    if base_id and base_id.lower() not in ("job", "jobs", "careers", "career"):
        return base_id[-50:]
    return str(abs(hash(url)))[:16]


def _append_to_output(job: dict):
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


class TrueUpStrategy(BaseStrategy):
    """Scrape personalized My Jobs feed on TrueUp.io."""

    def __init__(self, driver, job_site=None, selectors=None, db_session=None):
        if job_site is None:
            class _FakeJobSite:
                company_name = "TrueUp"
                search_url_template = MYJOBS_URL
                id = None

            job_site = _FakeJobSite()

        super().__init__(driver, job_site, selectors or {})
        self.human = HumanBehavior(driver)

        cfg = _load_trueup_config()
        self._date_posted = (cfg.get("date_posted") or "Past week").strip()
        self._email = os.environ.get("TRUEUP_EMAIL", "")
        self._password = os.environ.get("TRUEUP_PASSWORD", "")

        if not self._email or not self._password:
            logger.warning("⚠️ TRUEUP_EMAIL / TRUEUP_PASSWORD not set")

        logger.info(
            "✅ TrueUpStrategy ready — date=%s  auth=%s",
            self._date_posted,
            "configured" if self._email else "MISSING",
        )

    def login(self) -> bool:
        logger.info("🔐 Opening %s", BASE_URL)
        try:
            self.driver.get(BASE_URL)
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            time.sleep(3)
        except Exception as exc:
            logger.error("❌ Could not open homepage: %s", exc)
            return False

        try:
            login_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_NAV_LOGIN_BTN))
            )
            try:
                login_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", login_btn)
            time.sleep(2)
        except Exception as exc:
            logger.warning("⚠️ Nav login failed: %s — going to sign-in", exc)

        self.driver.get(SIGNIN_URL)
        time.sleep(5)

        try:
            email_el = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_EMAIL_FIELD))
            )
            email_el.clear()
            self.human.human_type(email_el, self._email)
        except Exception as exc:
            logger.error("❌ Email field: %s", exc)
            return False

        try:
            cont = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_CONTINUE_EMAIL))
            )
            cont.click()
        except Exception:
            email_el.send_keys(Keys.RETURN)
        time.sleep(4)

        try:
            pwd_el = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_PASSWORD_FIELD))
            )
            pwd_el.clear()
            self.human.human_type(pwd_el, self._password)
        except Exception as exc:
            logger.error("❌ Password field: %s", exc)
            return False

        try:
            cont = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_CONTINUE_PASSWORD))
            )
            cont.click()
        except Exception:
            pwd_el.send_keys(Keys.RETURN)

        logger.warning("⏳ Enter OTP in browser — waiting %d seconds", OTP_WAIT_SECONDS)
        for remaining in range(OTP_WAIT_SECONDS, 0, -10):
            logger.info("   ... %d seconds left ...", remaining)
            time.sleep(10)
        time.sleep(3)
        logger.info("✅ Login complete — %s", self.driver.current_url)
        return True

    def navigate_to_my_jobs(self) -> bool:
        logger.info("📂 Opening My Jobs...")
        try:
            nav = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, XP_NAV_JOBS))
            )
            try:
                nav.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", nav)
            WebDriverWait(self.driver, 20).until(
                lambda d: "myjobs" in d.current_url or "jobs" in d.current_url
            )
            self.human.random_delay(2, 4)
            return True
        except Exception as exc:
            logger.warning("⚠️ Nav Jobs failed: %s — direct URL", exc)
            self.driver.get(MYJOBS_URL)
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            return True

    def apply_past_week_dropdown(self) -> bool:
        logger.info("  📅 Date filter: %s", self._date_posted)
        try:
            btn = WebDriverWait(self.driver, 12).until(
                EC.element_to_be_clickable((By.XPATH, XP_DATE_FILTER_BTN))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn
            )
            btn.click()
            self.human.random_delay(0.5, 1.0)

            needle = self._date_posted
            for xpath in (
                f'//*[@role="menuitem" and contains(., "{needle}")]',
                f'//*[contains(@role,"menu")]//*[contains(., "{needle}")]',
                '//*[contains(., "Past week")]',
            ):
                try:
                    opt = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    opt.click()
                    logger.info("  ✅ Date filter applied")
                    return True
                except TimeoutException:
                    continue
            logger.warning("  ⚠️ Date option not found — continuing")
            return False
        except Exception as exc:
            logger.warning("  ⚠️ Date dropdown: %s", exc)
            return False

    def find_jobs(self) -> list[dict]:
        if not self.navigate_to_my_jobs():
            return []
        self.apply_past_week_dropdown()
        self.human.random_delay(2, 3)
        return self._collect_myjobs_cards()

    def apply(self, job: dict) -> bool:
        logger.info("ℹ️ apply() skipped — Step 1 only collects URLs")
        return True

    def _myjobs_show_more_visible(self) -> bool:
        try:
            for btn in self.driver.find_elements(By.XPATH, XP_MYJOBS_SHOW_MORE):
                if btn.is_displayed() and btn.is_enabled():
                    return True
        except Exception:
            pass
        return False

    def _count_myjobs_job_links(self) -> int:
        try:
            return len(self.driver.find_elements(By.XPATH, XP_MYJOBS_JOB_LINKS))
        except Exception:
            return 0

    def _wait_for_more_job_cards(self, prev_count: int, timeout: int = 20) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: self._count_myjobs_job_links() > prev_count
            )
            return True
        except TimeoutException:
            return False

    def _click_myjobs_show_more(self) -> bool:
        if not self._myjobs_show_more_visible():
            return False
        try:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XP_MYJOBS_SHOW_MORE))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", btn
            )
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            logger.info("  ➕ Show more clicked")
            self.human.random_delay(2, 4)
            return True
        except Exception as exc:
            logger.warning("  ⚠️ Show more click failed: %s", exc)
            return False

    def _gather_new_myjobs_links(self, seen_hrefs: set[str]) -> list[tuple[str, str]]:
        pending: list[tuple[str, str]] = []
        for link_el in self.driver.find_elements(By.XPATH, XP_MYJOBS_JOB_LINKS):
            try:
                href = (link_el.get_attribute("href") or "").strip()
                if not href or href in seen_hrefs or not link_el.is_displayed():
                    continue
                pending.append((href, (link_el.text or "").strip()))
            except StaleElementReferenceException:
                continue
        return pending

    def _click_myjobs_link_by_href(self, href: str, main_window: str) -> str:
        from selenium.webdriver.common.action_chains import ActionChains

        link_el = None
        for el in self.driver.find_elements(By.XPATH, XP_MYJOBS_JOB_LINKS):
            try:
                if (el.get_attribute("href") or "").strip() == href:
                    link_el = el
                    break
            except StaleElementReferenceException:
                continue
        if not link_el:
            return ""

        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", link_el
        )
        self.human.random_delay(0.4, 0.8)

        try:
            ActionChains(self.driver).move_to_element(link_el).click().perform()
        except Exception:
            try:
                link_el.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", link_el)

        WebDriverWait(self.driver, 12).until(lambda d: len(d.window_handles) > 1)
        for handle in self.driver.window_handles:
            if handle != main_window:
                self.driver.switch_to.window(handle)
                break
        time.sleep(2)
        ats_url = self.driver.current_url
        self.driver.close()
        self.driver.switch_to.window(main_window)
        self.human.random_delay(1.0, 2.0)
        return ats_url

    def _cleanup_extra_windows(self, main_window: str):
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

    def _collect_myjobs_cards(self) -> list[dict]:
        collected: list[dict] = []
        seen_hrefs: set[str] = set()
        seen_ids: set[str] = set()
        main_window = self.driver.current_window_handle
        batch_num = 0

        while batch_num < 100:
            batch_num += 1
            pending = self._gather_new_myjobs_links(seen_hrefs)
            logger.info(
                "  📄 Batch %d — %d new links (%d saved)",
                batch_num, len(pending), len(collected),
            )

            if not pending:
                if batch_num == 1:
                    logger.warning("  ⚠️ No job links on page")
                break

            for trueup_href, title in pending:
                job_id = _job_id_from_url(trueup_href) or str(hash(trueup_href))
                if job_id in seen_ids or trueup_href in seen_hrefs:
                    continue

                try:
                    ats_url = self._click_myjobs_link_by_href(trueup_href, main_window)
                except TimeoutException:
                    logger.warning("   ⚠️ No new tab — skip")
                    self._cleanup_extra_windows(main_window)
                    continue
                except Exception as exc:
                    logger.warning("   ⚠️ Click failed: %s", exc)
                    self._cleanup_extra_windows(main_window)
                    continue

                if not ats_url or ("trueup.io" in ats_url and "myjobs" in ats_url):
                    continue

                record = {
                    "job_id": _job_id_from_url(ats_url) or job_id,
                    "title": title or f"Job {job_id}",
                    "trueup_url": trueup_href,
                    "ats_url": ats_url,
                    "source_keyword": "myjobs",
                    "scraped_at": datetime.now().isoformat(),
                }
                seen_hrefs.add(trueup_href)
                seen_ids.add(record["job_id"])
                collected.append(record)
                _append_to_output(record)
                logger.info("   ✅ [%d] %s", len(collected), ats_url[:100])

            if not self._myjobs_show_more_visible():
                logger.info("  ⏹ Done — no Show more button")
                break

            before = self._count_myjobs_job_links()
            if not self._click_myjobs_show_more():
                break
            if not self._wait_for_more_job_cards(before):
                logger.warning("  ⚠️ List did not grow after Show more")
                break

        logger.info("  ✅ Collected %d jobs (%d batches)", len(collected), batch_num)
        return collected
