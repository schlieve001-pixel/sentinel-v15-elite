"""
VeriFuse Outcome Harvester — Post-Sale Data Recovery
======================================================
Targets "outcome" data: overbid funds, sold foreclosures, unclaimed surplus.
These are the records the calendar/search scrapers MISS because they only
look at future or active sales, not past results.

TRIGGERED BY: The Oracle flagging SUSPICIOUS_ZERO on major markets.

TARGETS:
  Jefferson  — jeffco.us/4675/Overbid-Funds (contact-only, fallback to sale policy)
  Arapahoe   — foreclosuresearch.arapahoegov.com/Foreclosure/report?t=1 (Presale PDFs)
               foreclosuresearch.arapahoegov.com/Foreclosure/report?t=3 (Final Sale PDFs)
  Adams      — apps.adcogov.org/PTForeclosureSearch/ (Status=Sold + Sold Date Range)
  Douglas    — douglas.co.us/documents/public-trustee-unclaimed-funds.pdf/
  Denver     — denvergov.org foreclosure excess funds PDFs

USAGE:
  from verifuse.scrapers.outcome_harvester import OutcomeHarvester
  harvester = OutcomeHarvester()
  records = harvester.harvest("Jefferson", start_year=2020, end_year=2026)
"""

import io
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from .hunter_engine import (
    StealthSession,
    DataValidator,
    clean_money,
    clean_owner,
    normalize_address,
    parse_date,
    generate_asset_hash,
)

log = logging.getLogger("verifuse.harvester")


class OutcomeHarvester:
    """
    Post-sale data harvester for counties where the main scraper returns 0.
    Each county gets a dedicated harvest method targeting outcome data sources.
    """

    def __init__(self, session: Optional[StealthSession] = None):
        self.session = session or StealthSession()
        self.validator = DataValidator()
        self.results: List[Dict] = []
        self.errors: List[str] = []

    def harvest(self, county: str, start_year: int = 2020,
                end_year: int = 2026) -> Dict:
        """
        Route to the correct county harvester.
        Returns: {records, raw, extracted, rejected, errors, time}
        """
        t0 = time.time()

        method = {
            "Jefferson": self._harvest_jefferson,
            "Arapahoe": self._harvest_arapahoe,
            "Adams": self._harvest_adams,
            "Douglas": self._harvest_douglas,
            "Denver": self._harvest_denver,
            "El Paso": self._harvest_el_paso,
        }.get(county)

        if not method:
            return {
                "records": [], "raw": 0, "extracted": 0, "rejected": 0,
                "rejection_details": [], "errors": [],
                "status": "NO_HARVESTER", "time": 0,
            }

        self.results = []
        self.errors = []
        self.validator = DataValidator()

        try:
            method(start_year, end_year)
        except Exception as e:
            log.error(f"[HARVESTER:{county}] Fatal: {e}")
            self.errors.append(f"{county}: {e}")

        # Validate all harvested records
        raw_count = len(self.results)
        validated = []
        rejected_count = 0
        for rec in self.results:
            if rec.get("_type") == "pdf_link":
                validated.append(rec)
                continue
            result = self.validator.validate(rec, county)
            if result is not None:
                validated.append(result)
            else:
                rejected_count += 1

        rejection_details = [
            r for r in self.validator.rejections if r["county"] == county
        ]

        elapsed = round(time.time() - t0, 1)
        extracted = raw_count - rejected_count

        return {
            "records": validated,
            "raw": raw_count,
            "extracted": extracted,
            "rejected": rejected_count,
            "rejection_details": rejection_details,
            "errors": self.errors,
            "status": "HARVESTED" if extracted > 0 else "HARVEST_EMPTY",
            "time": elapsed,
        }

    # ====================================================================
    # JEFFERSON COUNTY — Overbid Funds
    # ====================================================================

    def _harvest_jefferson(self, start_year: int, end_year: int):
        """
        Jefferson County overbid funds.

        The /4675/Overbid-Funds page is contact-only (no data).
        Strategy:
          1. Hit the Sale Policy page for any linked surplus data
          2. Hit the Foreclosures landing page for downloadable reports
          3. Parse any tables or PDF links found
        """
        county = "Jefferson"
        base = "https://www.jeffco.us"

        # Target 1: Overbid Funds page (check for any new PDF links)
        urls_to_scrape = [
            f"{base}/4675/Overbid-Funds",
            f"{base}/2322/Sale-Policy",
            f"{base}/2266/Foreclosures",
            f"{base}/807/Public-Trustee",
        ]

        for url in urls_to_scrape:
            resp = self.session.get(url)
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Look for PDF/Excel links with surplus/overbid keywords
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].lower()
                text = a_tag.get_text(strip=True).lower()
                combined = href + " " + text

                if any(kw in combined for kw in
                       ("surplus", "overbid", "excess", "unclaimed",
                        "available funds", "overage")):
                    full_url = urljoin(url, a_tag["href"])
                    log.info(f"[HARVESTER:{county}] Found link: {text} → {full_url}")

                    if href.endswith(".pdf"):
                        self._parse_pdf_for_surplus(full_url, county)
                    else:
                        # Follow the page and parse
                        self._scrape_page_for_surplus(full_url, county)

            # Also parse any tables on the page directly
            self._parse_tables(soup, url, county)

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    # ====================================================================
    # ARAPAHOE COUNTY — Reports Hub
    # ====================================================================

    def _harvest_arapahoe(self, start_year: int, end_year: int):
        """
        Arapahoe County presale/final sale lists.

        Strategy:
          1. Hit report?t=1 (Pre Sale List) for weekly PDFs
          2. Hit report?t=3 (Final Sale Continuance) for outcome PDFs
          3. Download and parse the most recent PDFs
          4. Fallback: Use search form with implicit sold/deeded filter
        """
        county = "Arapahoe"
        base = "https://foreclosuresearch.arapahoegov.com"

        # Gather PDF links from both report pages
        pdf_links = []
        for report_type in [1, 3]:
            url = f"{base}/Foreclosure/report?t={report_type}"
            resp = self.session.get(url)
            if not resp:
                self.errors.append(f"Failed to fetch report page t={report_type}")
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.get_text(strip=True)
                if href.lower().endswith(".pdf") or "report_files" in href.lower():
                    full_url = urljoin(url, href)
                    # Filter by year
                    year_match = re.search(r"20\d{2}", href + text)
                    if year_match:
                        year = int(year_match.group())
                        if year < start_year or year > end_year:
                            continue
                    pdf_links.append((full_url, text, report_type))

        log.info(f"[HARVESTER:{county}] Found {len(pdf_links)} report PDFs")

        # Parse the most recent PDFs (cap at 6 to be respectful)
        for pdf_url, label, rtype in pdf_links[:6]:
            log.info(f"[HARVESTER:{county}] Parsing PDF: {label}")
            self._parse_pdf_for_surplus(pdf_url, county)

        # Fallback: try the main search page directly
        search_url = f"{base}/Foreclosure/"
        resp = self.session.get(search_url)
        if resp:
            soup = BeautifulSoup(resp.text, "lxml")
            self._parse_tables(soup, search_url, county)

            # Try to find and submit a search form for "Sold" properties
            self._submit_arapahoe_search(soup, search_url, start_year, end_year)

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    def _submit_arapahoe_search(self, soup: BeautifulSoup, source_url: str,
                                 start_year: int, end_year: int):
        """Try to submit Arapahoe search with status filter."""
        form = soup.find("form")
        if not form:
            return

        # Look for status dropdown
        status_select = soup.find("select", {"name": re.compile(r"status", re.I)})
        if not status_select:
            # Try by ID
            status_select = soup.find("select", {"id": re.compile(r"status", re.I)})

        # Build form data
        form_data = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Set status to Sold/Deeded if dropdown found
        if status_select:
            select_name = status_select.get("name")
            # Find "Sold" or "Deeded" option
            for option in status_select.find_all("option"):
                val = option.get("value", "")
                text = option.get_text(strip=True).lower()
                if text in ("sold", "deeded", "completed"):
                    form_data[select_name] = val
                    log.info(f"[HARVESTER:Arapahoe] Setting status='{text}' ({val})")
                    break

        # Set date range
        date_inputs = soup.find_all("input", {"type": re.compile(r"text|date", re.I)})
        for inp in date_inputs:
            name = inp.get("name", "").lower()
            inp_id = inp.get("id", "").lower()
            label = name + " " + inp_id
            if any(kw in label for kw in ("start", "from", "begin", "sold")):
                form_data[inp.get("name")] = f"01/01/{start_year}"
            elif any(kw in label for kw in ("end", "to", "through")):
                form_data[inp.get("name")] = f"12/31/{end_year}"

        # Submit
        action = form.get("action", "")
        post_url = urljoin(source_url, action) if action else source_url
        resp = self.session.post(post_url, data=form_data)
        if resp:
            soup2 = BeautifulSoup(resp.text, "lxml")
            self._parse_tables(soup2, post_url, "Arapahoe")

    # ====================================================================
    # ADAMS COUNTY — Force Status=Sold
    # ====================================================================

    def _harvest_adams(self, start_year: int, end_year: int):
        """
        Adams County foreclosure search with Status=Sold.

        The main GTS scraper fails because it defaults to active cases.
        Fix: Explicitly set Foreclosure Status = "Sold" + Sold Date Range.
        """
        county = "Adams"
        search_url = "https://apps.adcogov.org/PTForeclosureSearch/"

        resp = self.session.get(search_url)
        if not resp:
            self.errors.append("Failed to fetch Adams search page")
            return

        soup = BeautifulSoup(resp.text, "lxml")

        # Build form data with hidden fields
        form_data = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            if name:
                form_data[name] = inp.get("value", "")

        # Find the status dropdown and set to "Sold"
        status_select = None
        for select in soup.find_all("select"):
            select_name = select.get("name", "")
            select_id = select.get("id", "")
            # Check if any option contains "Sold"
            options = select.find_all("option")
            has_sold = any("sold" in (o.get_text(strip=True).lower())
                          for o in options)
            if has_sold:
                status_select = select
                break

        if status_select:
            select_name = status_select.get("name")
            for option in status_select.find_all("option"):
                if option.get_text(strip=True).lower() == "sold":
                    form_data[select_name] = option.get("value", "Sold")
                    log.info(f"[HARVESTER:{county}] Set status dropdown "
                             f"'{select_name}' = '{option.get('value')}'")
                    break
        else:
            log.warning(f"[HARVESTER:{county}] No status dropdown found")

        # Find date inputs and set Sold Date Range
        all_inputs = soup.find_all("input")
        for inp in all_inputs:
            name = (inp.get("name") or "").lower()
            inp_id = (inp.get("id") or "").lower()
            label = name + " " + inp_id

            # Target "Sold Date" fields specifically
            if "sold" in label and ("begin" in label or "start" in label
                                    or "from" in label or "1" in label):
                form_data[inp.get("name")] = f"01/01/{start_year}"
                log.info(f"[HARVESTER:{county}] Set {inp.get('name')} = 01/01/{start_year}")
            elif "sold" in label and ("end" in label or "through" in label
                                      or "to" in label or "2" in label):
                form_data[inp.get("name")] = f"12/31/{end_year}"
                log.info(f"[HARVESTER:{county}] Set {inp.get('name')} = 12/31/{end_year}")

        # Find submit button
        submit = soup.find("input", {"type": "submit"})
        if submit and submit.get("name"):
            form_data[submit["name"]] = submit.get("value", "Search")

        # Also try clicking any "Search" button
        for btn in soup.find_all("button"):
            if "search" in btn.get_text(strip=True).lower():
                if btn.get("name"):
                    form_data[btn["name"]] = btn.get("value", "")

        # Determine form action
        form = soup.find("form")
        action = form.get("action", "") if form else ""
        post_url = urljoin(search_url, action) if action else search_url

        log.info(f"[HARVESTER:{county}] Submitting search: Status=Sold, "
                 f"Sold Date {start_year}-{end_year}")

        resp2 = self.session.post(post_url, data=form_data)
        if resp2:
            soup2 = BeautifulSoup(resp2.text, "lxml")
            self._parse_tables(soup2, post_url, county)

            # Try "Deeded" status too (separate search)
            if status_select:
                for option in status_select.find_all("option"):
                    if option.get_text(strip=True).lower() == "deeded":
                        form_data[status_select.get("name")] = option.get("value", "Deeded")
                        log.info(f"[HARVESTER:{county}] Second pass: Status=Deeded")
                        resp3 = self.session.post(post_url, data=form_data)
                        if resp3:
                            soup3 = BeautifulSoup(resp3.text, "lxml")
                            self._parse_tables(soup3, post_url, county)
                        break

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    # ====================================================================
    # DOUGLAS COUNTY — Unclaimed Funds PDF
    # ====================================================================

    def _harvest_douglas(self, start_year: int, end_year: int):
        """
        Douglas County Public Trustee Unclaimed Funds PDF.

        Direct target: /documents/public-trustee-unclaimed-funds.pdf/
        This is real surplus money sitting in county accounts.
        """
        county = "Douglas"
        pdf_url = ("https://www.douglas.co.us/documents/"
                   "public-trustee-unclaimed-funds.pdf/")

        log.info(f"[HARVESTER:{county}] Downloading unclaimed funds PDF")
        self._parse_pdf_for_surplus(pdf_url, county)

        # Also try the main unclaimed funds page for any other links
        page_url = "https://www.douglas.co.us/treasurer/unclaimed-funds/"
        resp = self.session.get(page_url)
        if resp:
            soup = BeautifulSoup(resp.text, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].lower()
                text = a_tag.get_text(strip=True).lower()
                if href.endswith(".pdf") and "trustee" in (href + " " + text):
                    full_url = urljoin(page_url, a_tag["href"])
                    if full_url != pdf_url:
                        self._parse_pdf_for_surplus(full_url, county)

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    # ====================================================================
    # DENVER — Excess Funds / Overbid Lists
    # ====================================================================

    def _harvest_denver(self, start_year: int, end_year: int):
        """
        Denver excess funds / overbid data.

        Strategy: Crawl the Denver Public Trustee page for any PDFs
        containing surplus/excess/overbid fund lists.
        """
        county = "Denver"
        urls = [
            "https://www.denvergov.org/Government/Agencies-Departments-Offices/"
            "Agencies-Departments-Offices-Directory/Denver-Clerk-and-Recorder/"
            "Recording-Division/Denver-Public-Trustee",
        ]

        for url in urls:
            resp = self.session.get(url)
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Find all PDF links related to surplus/overbid/excess
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].lower()
                text = a_tag.get_text(strip=True).lower()
                combined = href + " " + text

                if not (href.endswith(".pdf") or href.endswith(".xlsx")
                        or href.endswith(".csv")):
                    continue

                # Only pursue surplus-related files
                if any(kw in combined for kw in
                       ("surplus", "overbid", "excess", "unclaimed",
                        "refund", "overage", "available funds")):
                    full_url = urljoin(url, a_tag["href"])
                    log.info(f"[HARVESTER:{county}] Found surplus PDF: "
                             f"{a_tag.get_text(strip=True)} → {full_url}")
                    self._parse_pdf_for_surplus(full_url, county)

            # Also follow links to sub-pages that might have surplus data
            for a_tag in soup.find_all("a", href=True):
                text = a_tag.get_text(strip=True).lower()
                if any(kw in text for kw in
                       ("surplus", "overbid", "excess", "unclaimed")):
                    full_url = urljoin(url, a_tag["href"])
                    if not full_url.endswith(".pdf"):
                        sub_resp = self.session.get(full_url)
                        if sub_resp:
                            sub_soup = BeautifulSoup(sub_resp.text, "lxml")
                            self._parse_tables(sub_soup, full_url, county)

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    # ====================================================================
    # EL PASO COUNTY — Public Trustee Surplus / Foreclosure Reports
    # ====================================================================

    def _harvest_el_paso(self, start_year: int, end_year: int):
        """
        El Paso County surplus/overbid data.

        RealForeclose (elpasoco.realforeclose.com) is a JavaScript SPA — the
        auction data loads via AJAX after page render, invisible to static HTML.
        Strategy: Target the Public Trustee's own website for surplus PDFs.
        """
        county = "El Paso"
        urls = [
            "https://elpasopublictrustee.com/",
            "https://elpasopublictrustee.com/foreclosure-reports/",
            "https://elpasopublictrustee.com/foreclosure-info/bids",
            "https://elpasopublictrustee.com/foreclosure-info/redemption",
            "https://www.elpasoco.com/el-paso-county-public-trustee/",
        ]

        for url in urls:
            resp = self.session.get(url)
            if not resp:
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # Find surplus/overbid/excess PDF and data links
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].lower()
                text = a_tag.get_text(strip=True).lower()
                combined = href + " " + text

                if any(kw in combined for kw in
                       ("surplus", "overbid", "excess", "unclaimed",
                        "overage", "available funds", "bid sheet",
                        "sale results", "completed sale")):
                    full_url = urljoin(url, a_tag["href"])
                    log.info(f"[HARVESTER:{county}] Found link: "
                             f"{a_tag.get_text(strip=True)} -> {full_url}")

                    if href.endswith(".pdf"):
                        self._parse_pdf_for_surplus(full_url, county)
                    elif not href.startswith("mailto:"):
                        self._scrape_page_for_surplus(full_url, county)

            # Parse any tables on the page
            self._parse_tables(soup, url, county)

        log.info(f"[HARVESTER:{county}] Complete: {len(self.results)} records")

    # ====================================================================
    # SHARED PARSING METHODS
    # ====================================================================

    def _parse_pdf_for_surplus(self, pdf_url: str, county: str):
        """Download and parse a PDF for surplus/overbid data."""
        if pdfplumber is None:
            log.warning("[HARVESTER] pdfplumber not installed, skipping PDF parse")
            self.results.append({
                "_type": "pdf_link", "_url": pdf_url,
                "_label": f"Outcome PDF ({county})", "county": county,
            })
            return

        pdf_bytes = self.session.download_pdf(pdf_url)
        if not pdf_bytes:
            log.warning(f"[HARVESTER:{county}] PDF download failed: {pdf_url}")
            return

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Try table extraction first
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        self._parse_pdf_table(table, county, pdf_url)

                    # Fallback: text extraction with regex
                    text = page.extract_text()
                    if text:
                        self._parse_pdf_text(text, county, pdf_url)

        except Exception as e:
            log.error(f"[HARVESTER:{county}] PDF parse error: {e}")
            self.errors.append(f"{county} PDF: {e}")

    def _parse_pdf_table(self, table: list, county: str, source_url: str):
        """Parse a table extracted from a PDF."""
        headers = [str(c).strip().upper() if c else "" for c in table[0]]
        col_map = self._map_pdf_columns(headers)
        if not col_map:
            return

        log.info(f"[HARVESTER:{county}] PDF table: {len(table)-1} rows, "
                 f"columns: {col_map}")

        for row in table[1:]:
            cells = [str(c).strip() if c else "" for c in row]
            record = self._row_to_asset(cells, col_map, county, source_url)
            if record:
                self.results.append(record)

    def _map_pdf_columns(self, headers: List[str]) -> Dict[str, int]:
        """Map PDF table headers to field names."""
        PATTERNS = {
            "case_number": ["CASE", "CASE #", "CASE NO", "FILE #", "FILE NO",
                            "FORECLOSURE #", "FORECLOSURE NO",
                            "FC #", "FC#", "FC NO",
                            "RECEPTION", "RECEPTION #", "RECEPTION NO",
                            "REC #", "REC NO", "RECORDING",
                            "DOCKET", "BOOK", "INSTRUMENT",
                            "TRUSTEE FILE", "PT FILE", "PT#"],
            "owner_of_record": ["OWNER", "GRANTOR", "BORROWER", "CLAIMANT",
                                "NAME", "PAYEE", "DEFENDANT"],
            "property_address": ["PROPERTY", "ADDRESS", "LOCATION", "SITUS", "STREET", "GRANTOR STREET", "PROP STREET"],
            "estimated_surplus": ["SURPLUS", "EXCESS", "OVERBID", "OVERAGE",
                                  "UNCLAIMED", "AVAILABLE FUNDS"],
            "total_indebtedness": ["DEBT", "INDEBTEDNESS", "JUDGMENT",
                                   "TOTAL DUE", "OWED", "BALANCE DUE",
                                   "BALANCE OWED", "AMOUNT DUE"],
            "overbid_amount": ["WINNING BID", "SALE PRICE", "SOLD",
                               "BID AMOUNT", "PURCHASE"],
            "sale_date": ["SALE DATE", "DATE OF SALE", "SOLD DATE", "DATE"],
        }

        col_map = {}
        for i, header in enumerate(headers):
            h = header.strip()
            for field, patterns in PATTERNS.items():
                if field in col_map:
                    continue
                for pattern in patterns:
                    if pattern in h:
                        col_map[field] = i
                        break

        # Need at least some identifying info
        has_identity = any(f in col_map for f in
                          ("case_number", "owner_of_record", "property_address"))
        has_financial = any(f in col_map for f in
                           ("estimated_surplus", "overbid_amount",
                            "total_indebtedness"))

        if has_identity or has_financial:
            return col_map
        return {}

    def _parse_pdf_text(self, text: str, county: str, source_url: str):
        """Extract surplus records from PDF free text using regex."""
        money_pattern = r"\$?([\d,]+\.?\d{0,2})"

        # Look for lines with dollar amounts near surplus keywords
        lines = text.split("\n")
        for line in lines:
            line_lower = line.lower()
            if not any(kw in line_lower for kw in
                       ("surplus", "overbid", "excess", "unclaimed",
                        "overage", "available")):
                continue

            # Extract dollar amount
            amounts = re.findall(money_pattern, line)
            if not amounts:
                continue

            surplus = clean_money(amounts[0])
            if not surplus or surplus <= 0:
                continue

            # Try to extract case number
            case_match = re.search(
                r"(?:case|file|fc|reception)[#: ]*(\S+)", line, re.I
            )
            # Try to extract name
            name_match = re.search(
                r"(?:owner|borrower|claimant|payee)[:\s]*([A-Z][A-Za-z\s,]+)",
                line, re.I
            )

            record = {
                "county": county,
                "state": "CO",
                "asset_type": "FORECLOSURE_SURPLUS",
                "case_number": case_match.group(1) if case_match else None,
                "owner_of_record": clean_owner(
                    name_match.group(1) if name_match else None
                ),
                "estimated_surplus": surplus,
                "sale_date": None,
                "lien_type": "Deed of Trust",
                "source_name": f"{county.lower()}_harvester",
                "source_file": f"harvester:pdf:{source_url[:60]}",
                "_scraped_at": datetime.utcnow().isoformat() + "Z",
                "_harvest_source": "pdf_text",
            }
            self.results.append(record)

    def _parse_tables(self, soup: BeautifulSoup, source_url: str,
                      county: str):
        """Parse HTML tables from a page."""
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers = [th.get_text(strip=True).upper()
                       for th in rows[0].find_all(["th", "td"])]

            # DIAGNOSTIC: Log raw headers so we can verify column indices
            log.info(f"[HARVESTER:{county}] RAW HEADERS ({len(headers)}): {headers}")
            print(f"  [HARVESTER:{county}] HEADERS: {headers}")

            col_map = self._map_pdf_columns(headers)
            if not col_map:
                log.warning(f"[HARVESTER:{county}] No column mapping found "
                            f"for headers: {headers}")
                continue

            log.info(f"[HARVESTER:{county}] HTML table: {len(rows)-1} rows, "
                     f"columns: {col_map}")

            for row in rows[1:]:
                cells = [td.get_text(strip=True)
                         for td in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                record = self._row_to_asset(cells, col_map, county,
                                            source_url)
                if record:
                    self.results.append(record)

    def _row_to_asset(self, cells: List[str], col_map: Dict[str, int],
                      county: str, source_url: str) -> Optional[Dict]:
        """Convert a table row to an asset dict."""
        def cell(field: str) -> Optional[str]:
            idx = col_map.get(field)
            if idx is not None and idx < len(cells):
                val = cells[idx].strip()
                return val if val else None
            return None

        case_num = cell("case_number")
        owner = clean_owner(cell("owner_of_record"))
        prop_addr = cell("property_address")
        surplus = clean_money(cell("estimated_surplus"))
        debt = clean_money(cell("total_indebtedness"))
        bid = clean_money(cell("overbid_amount"))
        sale_date = parse_date(cell("sale_date"))

        # Skip empty rows
        if not case_num and not owner and not prop_addr:
            return None

        # Compute surplus if not directly available
        if surplus is None and bid is not None and debt is not None:
            surplus = round(bid - debt, 2)

        # POTENTIAL_SURPLUS: If surplus is 0/None but debt exists,
        # flag the record instead of killing it. The surplus data
        # may be on a different page or computed from sale price.
        potential_surplus = False
        if (surplus is None or surplus == 0) and debt is not None and debt > 0:
            potential_surplus = True
            # Don't kill — keep with flag

        # Skip only confirmed negative surplus (overbid < debt)
        if surplus is not None and surplus < 0:
            return None

        # SYNTHETIC ID: If case_number is missing, generate one so we don't
        # lose records to PK collision during dedup/ingestion
        if not case_num:
            parts = [county.upper()]
            if sale_date:
                parts.append(str(sale_date))
            if surplus is not None:
                parts.append(f"{surplus:.2f}")
            if owner:
                parts.append(owner[:20])
            elif prop_addr:
                parts.append(prop_addr[:20])
            case_num = "-".join(parts)
            log.info(f"[HARVESTER:{county}] Synthetic ID: {case_num}")

        # Build recorder link
        recorder_templates = {
            "Jefferson": "https://gts.co.jefferson.co.us/recorder/eagleweb/docSearch.jsp?search={owner}",
            "Arapahoe": "https://clerk.arapahoeco.gov/recorder/eagleweb/docSearch.jsp?search={owner}",
            "Adams": "http://recording.adcogov.org/LandmarkWeb/search/index?nameFilter={owner}",
            "Douglas": "https://apps.douglas.co.us/recorder/web/search?name={owner}",
            "Denver": "https://denvergov.org/recorder/search?query={owner}",
            "El Paso": "https://www.elpasoco.com/recorder/search?query={owner}",
        }
        recorder_link = None
        if owner:
            template = recorder_templates.get(county)
            if template:
                recorder_link = template.replace("{owner}", quote_plus(owner))

        return {
            "county": county,
            "state": "CO",
            "asset_type": "FORECLOSURE_SURPLUS",
            "case_number": case_num,
            "property_address": normalize_address(prop_addr) if prop_addr else None,
            "owner_of_record": owner,
            "estimated_surplus": surplus,
            "total_indebtedness": debt,
            "overbid_amount": bid,
            "sale_date": sale_date,
            "lien_type": "Deed of Trust",
            "recorder_link": recorder_link,
            "source_name": f"{county.lower()}_harvester",
            "source_file": f"harvester:{county.lower()}:{source_url[:60]}",
            "_scraped_at": datetime.utcnow().isoformat() + "Z",
            "_harvest_source": "outcome_harvester",
            "_potential_surplus": potential_surplus,
        }

    def _scrape_page_for_surplus(self, url: str, county: str):
        """Fetch a page and parse it for surplus data."""
        resp = self.session.get(url)
        if not resp:
            return
        soup = BeautifulSoup(resp.text, "lxml")
        self._parse_tables(soup, url, county)

        # Also check for PDF links on this sub-page
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            if href.endswith(".pdf"):
                text = a_tag.get_text(strip=True).lower()
                if any(kw in text + href for kw in
                       ("surplus", "overbid", "excess", "unclaimed", "funds")):
                    full_url = urljoin(url, a_tag["href"])
                    self._parse_pdf_for_surplus(full_url, county)
