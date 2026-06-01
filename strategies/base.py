from abc import ABC, abstractmethod

from core.safe_actions import SafeActions
from core.logger import logger


class BaseStrategy(ABC):
    def __init__(self, driver, job_site, selectors):
        self.driver = driver
        self.job_site = job_site
        self.selectors = selectors
        self.actions = SafeActions(driver)

    @abstractmethod
    def login(self):
        pass

    @abstractmethod
    def find_jobs(self):
        pass

    @abstractmethod
    def apply(self, job):
        pass

    def validate_content(self, required_selectors):
        for selector in required_selectors:
            if not self.actions.check_exists(selector):
                logger.error("Validation failed: missing '%s'", selector)
                return False
        return True
