"""
RealForeclose Platform Adapter
================================
Covers counties using {subdomain}.realforeclose.com:
  Eagle, El Paso, Larimer, Mesa, Summit, Weld

Scrapes calendar page -> auction preview -> rowA/rowB table parsing.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from verifuse_v2.scrapers.base_scraper import CountyScraper

log = logging.getLogger(__name__)


class RealForecloseAdapter(CountyScraper):
    """Adapter for realforeclose.com platform."""

    platform = "realforeclose"

    def __init__(self, config: dict):
        super().__init__(config)
        # Build base URL from county code if not explicitly set
        if not self.base_url:
            subdomain = config.get("realforeclose_subdomain", self.county_code)
            self.base_url = f"https://{subdomain}.realforeclose.com"

    def discover_pdfs(self) -> list[str]:
        """Scrape realforeclose calendar for auction result PDFs."""
        pdf_urls = []

        try:
            # Try the main foreclosure listings page
            resp = self.crawler.get(f"{self.base_url}/index.cfm")
            if resp.status_code != 200:
                log.warning("[%s] RealForeclose main page returned %d", self.county, resp.status_code)
                return pdf_urls

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find PDF links (surplus, excess, overbid documents)
            for link in soup.find_all("a", href=True):
                href = link["href"].lower()
                text = (link.get_text() or "").lower()
                if any(kw in href or kw in text for kw in ["surplus", "excess", "overbid", ".pdf"]):
                    full_url = urljoin(self.base_url, link["href"])
                    if full_url.lower().endswith(".pdf"):
                        pdf_urls.append(full_url)

            # Also check the calendar/results page
            for path in ["/index.cfm?zession=auction_results", "/index.cfm?zession=sales_results"]:
                try:
                    resp2 = self.crawler.get(f"{self.base_url}{path}")
                    if resp2.status_code == 200:
                        soup2 = BeautifulSoup(resp2.text, "html.parser")
                        for link in soup2.find_all("a", href=True):
                            if link["href"].lower().endswith(".pdf"):
                                full_url = urljoin(self.base_url, link["href"])
                                pdf_urls.append(full_url)
                except Exception:
                    continue

        except Exception as e:
            log.error("[%s] RealForeclose discover error: %s", self.county, e)

        # Deduplicate
        pdf_urls = list(dict.fromkeys(pdf_urls))
        log.info("[%s] RealForeclose: %d PDFs discovered", self.county, len(pdf_urls))
        return pdf_urls

    def fetch_html_data(self) -> list[dict]:
        """Scrape HTML auction tables from realforeclose.com."""
        records = []

        try:
            # Try to find sale results in HTML tables
            for path in ["/index.cfm?zession=auction_results", "/index.cfm"]:
                resp = self.crawler.get(f"{self.base_url}{path}")
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Look for auction result tables (rowA/rowB pattern)
                for table in soup.find_all("table"):
                    rows = table.find_all("tr", class_=re.compile(r"row[AB]", re.I))
                    for row in rows:
                        cells = row.find_all("td")
                        if len(cells) >= 4:
                            record = self._parse_row(cells)
                            if record:
                                records.append(record)

        except Exception as e:
            log.error("[%s] RealForeclose HTML scrape error: %s", self.county, e)

        log.info("[%s] RealForeclose: %d HTML records", self.county, len(records))
        return records

    def _parse_row(self, cells: list) -> dict | None:
        """Parse a single table row into a lead dict."""
        try:
            texts = [c.get_text(strip=True) for c in cells]
            # Common RealForeclose table format:
            # [case_number, address, sale_date, bid_amount, ...]
            if len(texts) < 4:
                return None

            return {
                "case_number": texts[0] if texts[0] else None,
                "property_address": texts[1] if len(texts) > 1 else None,
                "sale_date": texts[2] if len(texts) > 2 else None,
                "county": self.county,
                "source_name": f"realforeclose:{self.county_code}",
                "platform": "realforeclose",
            }
        except Exception:
            return None
