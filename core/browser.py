import os
import re
import time
import subprocess
try:
    import fcntl
    _HAS_FCNTL = True
except Exception:
    _HAS_FCNTL = False

from config.settings import settings
from core.logger import logger
from core.proxy_manager import proxy_manager


class BrowserService:
    def __init__(self):
        self.driver = None
        self.lock_file = None

    def _acquire_lock(self):
        """Ensures only one instance touches the profile. On Windows (no fcntl) locking is skipped."""
        profile_path = settings.chrome_profile_path
        os.makedirs(profile_path, exist_ok=True)
        lock_path = os.path.join(profile_path, "profile.lock")

        self.lock_file = None
        if not _HAS_FCNTL:
            logger.info("fcntl not available on this platform; skipping profile locking.")
            return

        self.lock_file = open(lock_path, 'w')
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info(f"Acquired lock on profile: {profile_path}")
        except IOError:
            logger.critical(f"Could not acquire lock on {lock_path}. Is another instance running?")
            raise RuntimeError("Browser profile is locked by another process.")

    def _release_lock(self):
        if not _HAS_FCNTL:
            return
        if self.lock_file:
            try:
                fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            except Exception:
                pass
            self.lock_file.close()
            logger.info("Released profile lock.")

    @staticmethod
    def _get_chrome_major_version():
        """Detect the installed Chrome major version number."""
        # Windows: check registry (HKCU first — Chrome is often installed per-user)
        if os.name == "nt":
            try:
                import winreg
                hives = [
                    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Google\Chrome\BLBeacon"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Google\Chrome\BLBeacon"),
                ]
                for hive, key_path in hives:
                    try:
                        with winreg.OpenKey(hive, key_path) as k:
                            ver, _ = winreg.QueryValueEx(k, "version")
                            major = int(str(ver).split(".")[0])
                            logger.info("Detected Chrome version via registry: %s (major=%d)", ver, major)
                            return major
                    except FileNotFoundError:
                        continue
            except Exception as exc:
                logger.debug("Registry Chrome version detection failed: %s", exc)

        # Fallback: run chrome --version
        candidates = [
            "google-chrome", "google-chrome-stable", "chromium-browser",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for exe in candidates:
            try:
                result = subprocess.run(
                    [exe, "--version"], capture_output=True, text=True, timeout=5
                )
                m = re.search(r"(\d+)\.\d+\.\d+", result.stdout + result.stderr)
                if m:
                    major = int(m.group(1))
                    logger.info("Detected Chrome major version via binary: %d", major)
                    return major
            except Exception:
                continue

        logger.warning("Could not detect Chrome major version — using unversioned ChromeDriver.")
        return None

    def start_browser(self):
        self._acquire_lock()

        # ── Detect installed Chrome version ───────────────────────────────────
        chrome_major = self._get_chrome_major_version()
        if chrome_major:
            logger.info("Pinning ChromeDriver to Chrome major version: %d", chrome_major)

        # ── Shared Chrome flags (NO --user-data-dir) ──────────────────────────
        # The chrome_profile directory causes Chrome to crash immediately on
        # Windows when it contains stale session locks. We skip it so the
        # browser starts clean; login is performed via the TrueUp strategy
        # on every run.
        shared_args = [
            "--no-first-run",
            "--no-service-autorun",
            "--password-store=basic",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        proxy_arg = proxy_manager.get_proxy_option()
        if proxy_arg:
            shared_args.append(proxy_arg)
        if settings.HEADLESS:
            shared_args.append("--headless=new")

        # ── Primary: undetected_chromedriver (bypasses Cloudflare detection) ──
        try:
            import undetected_chromedriver as _uc

            uc_opts = _uc.ChromeOptions()
            for arg in shared_args:
                uc_opts.add_argument(arg)

            uc_kwargs = {"options": uc_opts, "use_subprocess": True}
            if chrome_major:
                uc_kwargs["version_main"] = chrome_major

            self.driver = _uc.Chrome(**uc_kwargs)

            # Wait then double-ping — uc sessions can die silently after launch
            time.sleep(3)
            _ = self.driver.current_url
            time.sleep(1)
            _ = self.driver.current_url

            logger.info(
                "Browser started successfully (undetected-chromedriver, version_main=%s).",
                chrome_major
            )
        except Exception as e_uc:
            logger.warning(
                "uc.Chrome failed (%s). Falling back to webdriver-manager.", e_uc
            )
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

        # ── Fallback: plain selenium + webdriver-manager ──────────────────────
        if not self.driver:
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service as ChromeService
                from selenium.webdriver import ChromeOptions as _Opts
                from webdriver_manager.chrome import ChromeDriverManager

                wdm_kwargs = {}
                if chrome_major:
                    wdm_kwargs["driver_version"] = f"{chrome_major}"

                service = ChromeService(ChromeDriverManager(**wdm_kwargs).install())

                fallback_opts = _Opts()
                for arg in shared_args:
                    fallback_opts.add_argument(arg)

                self.driver = webdriver.Chrome(service=service, options=fallback_opts)

                time.sleep(1)
                _ = self.driver.current_url
                logger.info(
                    "Browser started successfully (webdriver-manager fallback, Chrome %s).",
                    chrome_major or "auto"
                )
            except Exception as e2:
                logger.error("All browser start methods failed: %s", e2)
                self._release_lock()
                raise RuntimeError(f"Could not start Chrome browser: {e2}") from e2

        if self.driver and not settings.HEADLESS:
            try:
                self.driver.maximize_window()
            except Exception as e:
                logger.warning(f"Could not maximize window: {e}")

        return self.driver

    def stop_browser(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                self.driver = None

        self._release_lock()


browser_service = BrowserService()
