"""
VERIFUSE V2 — CountyScraper ABC + Base Infrastructure
======================================================
Abstract base class for county-level scrapers.

Separates fetching (HTTP/PDF download) from parsing (CountyParser in registry.py).
Uses PoliteCrawler for all HTTP requests.

Usage:
    Subclasses implement platform-specific logic.
    Runner instantiates the correct adapter based on counties.yaml platform field.
"""

from __future__ import annotations

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from verifuse_v2.utils.polite_crawler import PoliteCrawler

log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent.parent / "data" / "raw_pdfs"
DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


class CountyScraper(ABC):
    """Abstract base for county-level scrapers.

    Each adapter covers a platform (realforeclose, gts, county_page, govease, manual).
    """

    county: str = ""
    county_code: str = ""
    platform: str = ""  # "realforeclose" | "gts" | "county_page" | "govease" | "manual"

    def __init__(self, config: dict):
        """Initialize with county config from counties.yaml."""
        self.config = config
        self.county = config.get("name", "")
        self.county_code = config.get("code", "")
        self.platform = config.get("platform", "")
        self.base_url = config.get("base_url", "")
        self.public_trustee_url = config.get("public_trustee_url", "")
        self.pdf_patterns = config.get("pdf_patterns", [])
        self.enabled = config.get("enabled", False)
        self.crawler = PoliteCrawler(rpm=config.get("rpm", 2.0))

        # PDF storage directory
        self.pdf_dir = RAW_PDF_DIR / self.county_code
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def discover_pdfs(self) -> list[str]:
        """Find PDF URLs on the county website.

        Returns list of URLs pointing to surplus/excess fund PDFs.
        """
        ...

    @abstractmethod
    def fetch_html_data(self) -> list[dict]:
        """Scrape HTML tables for structured data.

        Returns list of dicts with fields matching leads table schema.
        """
        ...

    def download_pdfs(self) -> list[Path]:
        """Download discovered PDFs, deduplicating by content hash.

        Returns list of local file paths.
        """
        urls = self.discover_pdfs()
        downloaded = []

        for url in urls:
            try:
                resp = self.crawler.conditional_get(url)
                if resp is None:
                    log.debug("PDF unchanged (304): %s", url)
                    continue
                if resp.status_code != 200:
                    log.warning("Failed to download %s: HTTP %d", url, resp.status_code)
                    continue

                # Compute content hash for dedup
                content_hash = hashlib.sha256(resp.content).hexdigest()
                filename = f"{self.county_code}_{content_hash[:12]}.pdf"
                filepath = self.pdf_dir / filename

                if filepath.exists():
                    log.debug("PDF already exists: %s", filepath)
                    downloaded.append(filepath)
                    continue

                filepath.write_bytes(resp.content)
                log.info("Downloaded: %s -> %s", url, filepath)
                downloaded.append(filepath)

            except Exception as e:
                log.error("Error downloading %s: %s", url, e)

        return downloaded

    def run(self, dry_run: bool = False) -> dict:
        """Full scrape cycle: discover + download + parse.

        Returns summary dict with counts.
        """
        result = {
            "county": self.county,
            "county_code": self.county_code,
            "platform": self.platform,
            "pdfs_discovered": 0,
            "pdfs_downloaded": 0,
            "html_records": 0,
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Phase 1: Discover PDFs
            pdf_urls = self.discover_pdfs()
            result["pdfs_discovered"] = len(pdf_urls)

            if dry_run:
                log.info("[DRY RUN] %s: %d PDFs discovered", self.county, len(pdf_urls))
                return result

            # Phase 2: Download PDFs
            downloaded = self.download_pdfs()
            result["pdfs_downloaded"] = len(downloaded)

            # Phase 3: Scrape HTML data
            html_data = self.fetch_html_data()
            result["html_records"] = len(html_data)

        except Exception as e:
            log.error("Scraper error for %s: %s", self.county, e)
            result["errors"].append(str(e))

        return result

    def close(self):
        self.crawler.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
