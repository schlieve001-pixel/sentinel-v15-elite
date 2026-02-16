"""
County Page Adapter (Generic)
==============================
Covers counties with standard public trustee web pages:
  Denver, Jefferson, Pueblo, Pitkin, Routt, Grand, + ~40 rural counties

Generic: fetches public trustee page, finds PDF links with surplus/excess/overbid keywords.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from verifuse_v2.scrapers.base_scraper import CountyScraper

log = logging.getLogger(__name__)

# Keywords that indicate surplus/excess fund documents
SURPLUS_KEYWORDS = [
    "surplus", "excess", "overbid", "over bid", "unclaimed",
    "foreclosure sale result", "public trustee sale",
    "post-sale", "postsale", "post sale",
]


class CountyPageAdapter(CountyScraper):
    """Generic adapter for county public trustee web pages."""

    platform = "county_page"

    def discover_pdfs(self) -> list[str]:
        """Scan public trustee page for PDF links with surplus keywords."""
        pdf_urls = []
        urls_to_check = []

        # Build list of URLs to scan
        if self.public_trustee_url:
            urls_to_check.append(self.public_trustee_url)
        if self.base_url and self.base_url != self.public_trustee_url:
            urls_to_check.append(self.base_url)

        if not urls_to_check:
            log.warning("[%s] CountyPage: no URLs configured", self.county)
            return pdf_urls

        for page_url in urls_to_check:
            try:
                resp = self.crawler.conditional_get(page_url)
                if resp is None:
                    log.debug("[%s] Page unchanged: %s", self.county, page_url)
                    continue
                if resp.status_code != 200:
                    log.warning("[%s] Page returned %d: %s", self.county, resp.status_code, page_url)
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Find all links
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    text = (link.get_text() or "").lower()
                    href_lower = href.lower()

                    # Check if PDF
                    is_pdf = href_lower.endswith(".pdf")

                    # Check if matches surplus keywords
                    has_keyword = any(
                        kw in href_lower or kw in text for kw in SURPLUS_KEYWORDS
                    )

                    if is_pdf and has_keyword:
                        full_url = urljoin(page_url, href)
                        pdf_urls.append(full_url)
                    elif is_pdf and not has_keyword:
                        # Still collect PDFs from public trustee pages — they may contain surplus data
                        # but only if they match the configured pdf_patterns
                        if self.pdf_patterns:
                            import fnmatch
                            filename = href.split("/")[-1].lower()
                            if any(fnmatch.fnmatch(filename, pat.lower()) for pat in self.pdf_patterns):
                                pdf_urls.append(urljoin(page_url, href))

                # Also follow links to sub-pages that might contain PDFs
                for link in soup.find_all("a", href=True):
                    text = (link.get_text() or "").lower()
                    if any(kw in text for kw in ["surplus", "excess", "foreclosure", "public trustee"]):
                        sub_url = urljoin(page_url, link["href"])
                        if sub_url.endswith((".html", ".htm", ".php", ".aspx", "/")):
                            try:
                                sub_resp = self.crawler.get(sub_url)
                                if sub_resp.status_code == 200:
                                    sub_soup = BeautifulSoup(sub_resp.text, "html.parser")
                                    for sub_link in sub_soup.find_all("a", href=True):
                                        if sub_link["href"].lower().endswith(".pdf"):
                                            pdf_urls.append(urljoin(sub_url, sub_link["href"]))
                            except Exception:
                                continue

            except Exception as e:
                log.error("[%s] CountyPage discover error for %s: %s", self.county, page_url, e)

        pdf_urls = list(dict.fromkeys(pdf_urls))
        log.info("[%s] CountyPage: %d PDFs discovered", self.county, len(pdf_urls))
        return pdf_urls

    def fetch_html_data(self) -> list[dict]:
        """Scrape HTML tables from county page.

        Most county pages don't have structured HTML data — they publish PDFs.
        This is a best-effort attempt to find tabular data.
        """
        records = []

        urls_to_check = []
        if self.public_trustee_url:
            urls_to_check.append(self.public_trustee_url)
        if self.base_url and self.base_url != self.public_trustee_url:
            urls_to_check.append(self.base_url)

        for page_url in urls_to_check:
            try:
                resp = self.crawler.get(page_url)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Look for tables with dollar amounts
                for table in soup.find_all("table"):
                    text = table.get_text()
                    if "$" in text and any(kw in text.lower() for kw in SURPLUS_KEYWORDS):
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
                                record["source_name"] = f"county_page:{self.county_code}"
                                record["platform"] = "county_page"
                                records.append(record)

            except Exception as e:
                log.error("[%s] CountyPage HTML error for %s: %s", self.county, page_url, e)

        log.info("[%s] CountyPage: %d HTML records", self.county, len(records))
        return records
