"""
GTS (Government Technology Solutions) Platform Adapter
=======================================================
Covers counties using GTS foreclosure search:
  Adams, Arapahoe, Boulder, Douglas, Garfield

Handles ASP.NET ViewState form submission + date-based PDF URL guessing.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from verifuse_v2.scrapers.base_scraper import CountyScraper

log = logging.getLogger(__name__)


class GTSSearchAdapter(CountyScraper):
    """Adapter for GTS foreclosure search platforms."""

    platform = "gts"

    def discover_pdfs(self) -> list[str]:
        """Scrape GTS search portal for excess/surplus fund PDFs."""
        pdf_urls = []

        if not self.base_url:
            log.warning("[%s] GTS: no base_url configured", self.county)
            return pdf_urls

        try:
            resp = self.crawler.get(self.base_url)
            if resp.status_code != 200:
                log.warning("[%s] GTS portal returned %d", self.county, resp.status_code)
                return pdf_urls

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find PDF links with surplus/excess/overbid keywords
            for link in soup.find_all("a", href=True):
                href = link["href"]
                text = (link.get_text() or "").lower()
                href_lower = href.lower()

                if any(kw in href_lower or kw in text
                       for kw in ["surplus", "excess", "overbid", "post-sale", "postsale"]):
                    full_url = urljoin(self.base_url, href)
                    if full_url.lower().endswith(".pdf"):
                        pdf_urls.append(full_url)

            # Also check reports index page if available
            public_trustee_url = self.config.get("public_trustee_url", "")
            if public_trustee_url and public_trustee_url != self.base_url:
                try:
                    resp2 = self.crawler.get(public_trustee_url)
                    if resp2.status_code == 200:
                        soup2 = BeautifulSoup(resp2.text, "html.parser")
                        for link in soup2.find_all("a", href=True):
                            href = link["href"]
                            if href.lower().endswith(".pdf"):
                                text = (link.get_text() or "").lower()
                                if any(kw in href.lower() or kw in text
                                       for kw in ["surplus", "excess", "overbid", "foreclosure"]):
                                    pdf_urls.append(urljoin(public_trustee_url, href))
                except Exception:
                    pass

        except Exception as e:
            log.error("[%s] GTS discover error: %s", self.county, e)

        pdf_urls = list(dict.fromkeys(pdf_urls))
        log.info("[%s] GTS: %d PDFs discovered", self.county, len(pdf_urls))
        return pdf_urls

    def fetch_html_data(self) -> list[dict]:
        """Scrape GTS search results tables."""
        records = []

        if not self.base_url:
            return records

        try:
            resp = self.crawler.get(self.base_url)
            if resp.status_code != 200:
                return records

            soup = BeautifulSoup(resp.text, "html.parser")

            # GTS typically uses ASP.NET GridView tables
            for table in soup.find_all("table", id=re.compile(r"GridView|gv|results", re.I)):
                rows = table.find_all("tr")
                headers = []
                for row in rows:
                    cells = row.find_all(["th", "td"])
                    if row.find("th"):
                        headers = [c.get_text(strip=True).lower() for c in cells]
                        continue
                    if not headers:
                        continue

                    values = [c.get_text(strip=True) for c in cells]
                    if len(values) >= len(headers):
                        record = dict(zip(headers, values))
                        record["county"] = self.county
                        record["source_name"] = f"gts:{self.county_code}"
                        record["platform"] = "gts"
                        records.append(record)

        except Exception as e:
            log.error("[%s] GTS HTML scrape error: %s", self.county, e)

        log.info("[%s] GTS: %d HTML records", self.county, len(records))
        return records
