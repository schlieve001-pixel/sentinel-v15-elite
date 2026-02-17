"""
VERIFUSE V2 — Polite Crawler
==============================
Ethical HTTP client with:
  - UA rotation + randomized delays
  - ETag / If-Modified-Since caching (separate SQLite DB)
  - Per-domain request tracking
  - Exponential backoff on errors

Cache DB: verifuse_v2/data/http_cache.db
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

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

CACHE_DB_PATH = os.environ.get(
    "VERIFUSE_CACHE_DB",
    str(Path(__file__).resolve().parent.parent / "data" / "http_cache.db"),
)


class PoliteCrawler:
    """HTTP session with UA rotation, jitter delays, ETag caching, and per-domain tracking."""

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
        self._domain_last_request: dict[str, float] = {}
        self._cache_conn: Optional[sqlite3.Connection] = None

    def _get_cache_conn(self) -> sqlite3.Connection:
        """Get or create cache database connection."""
        if self._cache_conn is None:
            cache_dir = Path(CACHE_DB_PATH).parent
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_conn = sqlite3.connect(CACHE_DB_PATH)
            self._cache_conn.execute("PRAGMA journal_mode=WAL")
            self._cache_conn.execute("PRAGMA busy_timeout=5000")
            self._cache_conn.execute("""
                CREATE TABLE IF NOT EXISTS http_cache (
                    url TEXT PRIMARY KEY,
                    etag TEXT,
                    last_modified TEXT,
                    last_fetched TEXT,
                    content_hash TEXT
                )
            """)
            self._cache_conn.commit()
        return self._cache_conn

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

    def _wait_for_rate_limit(self, url: str = "") -> None:
        """Enforce RPM with jitter + per-domain tracking."""
        if self.rpm <= 0:
            return

        # Global rate limit
        min_interval = 30.0 / self.rpm
        max_interval = 60.0 / self.rpm
        target_delay = random.uniform(min_interval, max_interval)
        elapsed = time.monotonic() - self._last_request_time
        remaining = target_delay - elapsed
        if remaining > 0:
            log.debug("Polite delay: %.1fs", remaining)
            time.sleep(remaining)

        # Per-domain rate limit (minimum 2s between requests to same domain)
        if url:
            domain = urlparse(url).netloc
            if domain in self._domain_last_request:
                domain_elapsed = time.monotonic() - self._domain_last_request[domain]
                domain_min = random.uniform(2.0, 5.0)
                if domain_elapsed < domain_min:
                    time.sleep(domain_min - domain_elapsed)

    def _record_request(self, url: str) -> None:
        """Track request timing globally and per-domain."""
        self._last_request_time = time.monotonic()
        domain = urlparse(url).netloc
        self._domain_last_request[domain] = self._last_request_time

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with stealth protections."""
        self._wait_for_rate_limit(url)
        headers = self._rotate_headers()
        headers.update(kwargs.pop("headers", {}))
        kwargs.setdefault("timeout", self.timeout)

        self._record_request(url)
        response = self.session.get(url, headers=headers, **kwargs)
        return response

    def conditional_get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """GET with ETag / If-Modified-Since caching.

        Returns None if server responds 304 (not modified).
        Returns the response if content has changed.
        """
        cache = self._get_cache_conn()
        row = cache.execute(
            "SELECT etag, last_modified FROM http_cache WHERE url = ?", [url]
        ).fetchone()

        headers = self._rotate_headers()
        headers.update(kwargs.pop("headers", {}))

        if row:
            etag, last_mod = row
            if etag:
                headers["If-None-Match"] = etag
            if last_mod:
                headers["If-Modified-Since"] = last_mod

        self._wait_for_rate_limit(url)
        kwargs.setdefault("timeout", self.timeout)
        self._record_request(url)

        response = self.session.get(url, headers=headers, **kwargs)

        if response.status_code == 304:
            log.debug("304 Not Modified: %s", url)
            return None

        if response.status_code == 200:
            # Update cache
            etag = response.headers.get("ETag")
            last_mod = response.headers.get("Last-Modified")
            content_hash = hashlib.sha256(response.content).hexdigest()
            now = datetime.now(timezone.utc).isoformat()

            cache.execute("""
                INSERT OR REPLACE INTO http_cache (url, etag, last_modified, last_fetched, content_hash)
                VALUES (?, ?, ?, ?, ?)
            """, [url, etag, last_mod, now, content_hash])
            cache.commit()

        return response

    def close(self) -> None:
        self.session.close()
        if self._cache_conn:
            self._cache_conn.close()
            self._cache_conn = None

    def __enter__(self) -> PoliteCrawler:
        return self

    def __exit__(self, *args) -> None:
        self.close()
