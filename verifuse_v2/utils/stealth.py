"""
VERIFUSE V2 — Stealth HTTP Session

UA rotation, random delays, exponential backoff, session cookies.
"""

from __future__ import annotations

import random
import time
import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


class StealthSession:
    """HTTP session with UA rotation, jitter delays, and retry backoff."""

    def __init__(self, rpm: float = 2.0, timeout: int = 30):
        self.rpm = rpm
        self.timeout = timeout
        self.session = requests.Session()

        # Mount retry adapter for transient errors
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._last_request_time: float = 0.0

    def _rotate_headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.google.com/",
        }

    def _wait_for_rate_limit(self) -> None:
        """Enforce RPM with jitter."""
        if self.rpm <= 0:
            return
        min_interval = 30.0 / self.rpm
        max_interval = 60.0 / self.rpm
        target_delay = random.uniform(min_interval, max_interval)
        elapsed = time.monotonic() - self._last_request_time
        remaining = target_delay - elapsed
        if remaining > 0:
            log.debug("Stealth delay: %.1fs", remaining)
            time.sleep(remaining)

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with stealth protections."""
        self._wait_for_rate_limit()
        headers = self._rotate_headers()
        headers.update(kwargs.pop("headers", {}))
        kwargs.setdefault("timeout", self.timeout)

        self._last_request_time = time.monotonic()
        response = self.session.get(url, headers=headers, **kwargs)
        return response

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> StealthSession:
        return self

    def __exit__(self, *args) -> None:
        self.close()
