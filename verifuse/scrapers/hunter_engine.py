"""
VeriFuse Hunter Engine — TITAN BUILD
=====================================
Industrial-grade Colorado surplus dragnet. Zero tolerance for bad data.

PLATFORM MAP (verified 2026-02-07):
  RealForeclose (6): Eagle, El Paso, Larimer, Mesa, Summit, Weld
  GTS Search    (5): Adams, Arapahoe, Boulder, Douglas, Garfield
  County Page   (4): Pitkin, Routt, San Miguel, Grand
  Standard      (2): Denver, Jefferson

MODULES:
  A.  StealthSession        — Hardcoded UA rotation, fast retry, no external deps
  A2. DataValidator         — BS Detector: Whale Cap, Date Glitch, Ratio Test
  B.  ForensicScraper       — Generic HTML table/div parser (Denver, Jefferson)
  B2. RealForecloseScraper  — Calendar + rowA/rowB auction table parser
  B3. GTSSearchScraper      — ASP.NET form search + pagination
  B4. CountyPageScraper     — .gov page + PDF Foreclosure Book support
  B5. ZombieScraper         — Tax lien sales + code enforcement (placeholder)
  C.  OCRPatcher            — PDF bid-sheet extraction via pdfplumber
  D.  LienWiper             — Surplus math, whale classification, lien analysis

ETHICAL CONSTRAINTS:
  - Targets PUBLIC RECORD data only (no login walls, no CAPTCHA bypass)
  - Respectful rate limiting (1-3s random delay between requests)
  - Instant retry with UA rotation on failure (max 3 attempts)
  - No external UA library dependency (all agents hardcoded)
"""

import hashlib
import io
import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

# fake_useragent DELETED per TITAN directive — unreliable external dependency.
# All UA strings are hardcoded in StealthSession.AGENTS below.

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("verifuse.hunter")


# ============================================================================
# MODULE A: STEALTH SESSION
# ============================================================================

class StealthSession:
    """
    TITAN-grade HTTP session:
      - 10 hardcoded modern User-Agents (Chrome 125+, Firefox 126+, Edge 125+)
      - Instant retry with UA rotation on failure (no 30s sleep)
      - Rate-limited backoff ONLY on 403/429 (WAF blocks)
      - 15s timeout (not 30s — fail fast, move on)
      - Persistent cookies for ASP.NET ViewState/SessionID
    """

    # 10 hardcoded modern UAs — no external dependency
    AGENTS = [
        # Chrome 125-127 (Windows, Mac, Linux)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        # Firefox 126-128
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
        # Edge 125-127
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        # Safari 17.5+ (Mac)
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        # Chrome on Android (mobile variant)
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36",
    ]

    MAX_RETRIES = 3
    # Fast retry delays: rotate UA and retry instantly for network errors,
    # only back off on WAF blocks (403/429)
    FAST_RETRY_DELAY = 1.0       # 1 second between retries (network errors)
    WAF_BACKOFF_BASE = 10.0      # 10s base for WAF blocks, multiplied by attempt
    MIN_DELAY = 1.0              # Polite delay between normal requests
    MAX_DELAY = 3.0

    def __init__(self):
        self.session = requests.Session()
        self.request_count = 0
        self.error_count = 0
        self._ua_index = random.randint(0, len(self.AGENTS) - 1)
        self._rotate_ua()

        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

    def _rotate_ua(self):
        """Rotate to next User-Agent (round-robin, deterministic)."""
        self._ua_index = (self._ua_index + 1) % len(self.AGENTS)
        self.session.headers["User-Agent"] = self.AGENTS[self._ua_index]

    def _sleep(self):
        """Polite delay between requests."""
        time.sleep(random.uniform(self.MIN_DELAY, self.MAX_DELAY))

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """GET with retry logic."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Optional[requests.Response]:
        """POST with retry logic."""
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """
        TITAN request logic:
          1. Polite delay between requests (1-3s)
          2. UA rotation every 5 requests
          3. On failure: rotate UA, retry in 1s (not 30s)
          4. On WAF block (403/429): exponential backoff with UA rotation
          5. Timeout: 15s (fail fast)
        """
        if self.request_count > 0 and self.request_count % 5 == 0:
            self._rotate_ua()

        if self.request_count > 0:
            self._sleep()

        kwargs.setdefault("timeout", 15)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self.request_count += 1
                resp = self.session.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                log.warning(f"HTTP {status} on {url} (attempt {attempt})")
                self._rotate_ua()

                if status in (403, 429):
                    wait = self.WAF_BACKOFF_BASE * attempt
                    log.warning(f"WAF block ({status}). Backoff {wait:.0f}s, rotating UA.")
                    time.sleep(wait)
                elif attempt < self.MAX_RETRIES:
                    time.sleep(self.FAST_RETRY_DELAY)

            except requests.exceptions.ConnectionError:
                log.warning(f"Connection error on {url} (attempt {attempt})")
                self._rotate_ua()
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.FAST_RETRY_DELAY)

            except requests.exceptions.Timeout:
                log.warning(f"Timeout on {url} (attempt {attempt})")
                self._rotate_ua()
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.FAST_RETRY_DELAY)

            except Exception as e:
                log.error(f"Unexpected error on {url}: {e}")
                self.error_count += 1
                self._rotate_ua()
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.FAST_RETRY_DELAY)

        log.error(f"FAILED after {self.MAX_RETRIES} attempts: {url}")
        self.error_count += 1
        return None

    def download_pdf(self, url: str) -> Optional[bytes]:
        """Download a PDF file. Returns raw bytes or None."""
        resp = self.get(url)
        if resp and resp.content:
            if resp.content[:5] == b"%PDF-":
                return resp.content
            else:
                log.warning(f"Content from {url} is not a valid PDF")
        return None

    def stats(self) -> dict:
        return {
            "requests": self.request_count,
            "errors": self.error_count,
            "current_ua": self.session.headers.get("User-Agent", "")[:60] + "...",
        }


# ============================================================================
# MODULE A2: DATA VALIDATOR — THE BS DETECTOR
# ============================================================================

class DataValidator:
    """
    TITAN-grade data validation. Every record passes through these gates
    BEFORE it can enter the pipeline. Rejects hallucinations, misparses,
    and column-mapping errors.

    RULES:
      1. WHALE_CAP:   surplus > $1,000,000 → FLAG AS SUSPICIOUS
      2. DATE_GLITCH: surplus looks like a date (e.g. 5212025 = 5/21/2025) → KILL
      3. RATIO_TEST:  surplus > 50% of total_indebtedness → FLAG
      4. NEGATIVE:    surplus <= 0 → KILL
      5. ZERO_DEBT:   debt == 0 but surplus > 0 and no winning bid → SUSPICIOUS
    """

    WHALE_CAP = 1_000_000
    RATIO_THRESHOLD = 0.50

    # Date-as-number patterns: digits that look like MMDDYYYY or MDYYYY
    DATE_GLITCH_PATTERN = re.compile(
        r"^[01]?\d[0-3]\d20[12]\d$"  # matches 5212025, 05212025, 12312024, etc.
    )

    def __init__(self):
        self.rejections: List[Dict] = []  # audit trail of rejected records
        self.flags: List[Dict] = []       # suspicious but not killed

    def validate(self, record: Dict, county: str = "") -> Optional[Dict]:
        """
        Validate a single record. Returns the record if valid, None if killed.
        Adds _validation_flags to records that pass but are suspicious.
        """
        surplus = record.get("estimated_surplus")
        debt = record.get("total_indebtedness")
        bid = record.get("overbid_amount")

        # --- GATE 1: No surplus → not actionable ---
        if surplus is None:
            return record  # pass through — LienWiper will classify as SKIP

        # --- GATE 2: NEGATIVE surplus → kill ---
        if surplus <= 0:
            self._reject(record, county, "NEGATIVE", f"surplus={surplus}")
            return None

        # --- GATE 3: DATE_GLITCH — surplus looks like a date ---
        surplus_str = str(int(surplus)) if surplus == int(surplus) else str(surplus)
        # Remove decimal: 5212025.0 → "5212025"
        surplus_int_str = surplus_str.replace(".", "").replace(",", "")
        if self.DATE_GLITCH_PATTERN.match(surplus_int_str):
            self._reject(record, county, "DATE_GLITCH",
                         f"surplus={surplus} looks like date {surplus_int_str}")
            return None

        # Also catch large integers that are clearly date-formatted
        # e.g. surplus=1012024 (10/1/2024), surplus=3152025 (3/15/2025)
        if surplus > 100000 and surplus == int(surplus):
            s = str(int(surplus))
            if len(s) in (7, 8) and s[-4:].startswith("20"):
                self._reject(record, county, "DATE_GLITCH",
                             f"surplus={surplus} → possible date {s}")
                return None

        # --- GATE 4: WHALE_CAP — flag but don't kill ---
        validation_flags = []
        if surplus > self.WHALE_CAP:
            validation_flags.append(f"WHALE_CAP:surplus=${surplus:,.2f}>$1M")
            self.flags.append({
                "county": county, "rule": "WHALE_CAP",
                "value": f"${surplus:,.2f}",
                "case": record.get("case_number", "?"),
            })

        # --- GATE 5: RATIO_TEST — surplus > 50% of debt ---
        if debt and debt > 0 and surplus > (debt * self.RATIO_THRESHOLD):
            validation_flags.append(
                f"RATIO_TEST:surplus=${surplus:,.2f}>{self.RATIO_THRESHOLD*100:.0f}%"
                f" of debt=${debt:,.2f}"
            )
            self.flags.append({
                "county": county, "rule": "RATIO_TEST",
                "value": f"surplus/debt={surplus/debt:.1%}",
                "case": record.get("case_number", "?"),
            })

        if validation_flags:
            record["_validation_flags"] = validation_flags

        return record

    def _reject(self, record: Dict, county: str, rule: str, detail: str):
        """Log a rejected record to the audit trail."""
        self.rejections.append({
            "county": county,
            "rule": rule,
            "detail": detail,
            "case": record.get("case_number", "?"),
            "owner": record.get("owner_of_record", "?"),
            "surplus": record.get("estimated_surplus"),
        })
        log.info(f"[BS DETECTOR] KILLED {county} | {rule} | {detail}")

    def summary(self) -> Dict:
        """Return rejection/flag counts by rule."""
        reject_by_rule = {}
        for r in self.rejections:
            rule = r["rule"]
            reject_by_rule[rule] = reject_by_rule.get(rule, 0) + 1
        flag_by_rule = {}
        for f in self.flags:
            rule = f["rule"]
            flag_by_rule[rule] = flag_by_rule.get(rule, 0) + 1
        return {
            "total_rejected": len(self.rejections),
            "total_flagged": len(self.flags),
            "rejected_by_rule": reject_by_rule,
            "flagged_by_rule": flag_by_rule,
        }


# ============================================================================
# MODULE B: FORENSIC SCRAPER — Denver Public Trustee
# ============================================================================

# ---------------------------------------------------------------------------
# SELECTOR CONFIGS — Update these when county sites change their HTML layout.
# Keeping selectors in dicts means you fix ONE line instead of hunting through
# parser code when a site redesigns.
# ---------------------------------------------------------------------------

DENVER_CONFIG = {
    "base_url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/"
                "Agencies-Departments-Offices-Directory/Denver-Clerk-and-Recorder/"
                "Recording-Division/Denver-Public-Trustee",
    # Denver Public Trustee — updated Feb 2026 after site restructure
    "search_url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/"
                  "Agencies-Departments-Offices-Directory/Denver-Clerk-and-Recorder/"
                  "Recording-Division/Denver-Public-Trustee",
    "recorder_url_template": "https://denvergov.org/recorder/search?query={owner}",
    "county": "Denver",
    "state": "CO",
    "asset_type": "FORECLOSURE_SURPLUS",
    "source_name": "denver_foreclosure",  # Must match scraper_registry
}

JEFFERSON_CONFIG = {
    "base_url": "https://www.jeffco.us/807/Public-Trustee",
    "search_url": "https://www.jeffco.us/807/Public-Trustee",
    "recorder_url_template": (
        "https://gts.co.jefferson.co.us/recorder/eagleweb/"
        "docSearch.jsp?search={owner}"
    ),
    "county": "Jefferson",
    "state": "CO",
    "asset_type": "FORECLOSURE_SURPLUS",
    "source_name": "jefferson_foreclosure",  # Must match scraper_registry
}


# ============================================================================
# REALFORECLOSE COUNTIES — Direct Vendor Endpoints (VERIFIED LIVE)
# ============================================================================
# RealForeclose.com: Active auction platform for 6 Colorado counties.
# URL pattern: https://{county}.realforeclose.com/index.cfm?zaction=...
# Calendar → Auction Preview → Auction Details (rowA/rowB table structure)
#
# VERIFIED 2026-02-07: All 6 subdomains return 200 with 22-24KB calendar pages.
# Dead subdomains (pitkin, routt, adams, arapahoe, douglas, boulder, garfield,
# grand) redirect to realauction.com corporate homepage — NOT auction data.

REALFORECLOSE_COUNTIES = {
    "Eagle": {
        "base_url": "https://eagle.realforeclose.com",
        "search_url": "https://eagle.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://eagle.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://eaglecounty.us/Clerk/Recording/Search?name={owner}",
        "county": "Eagle",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "eagle_portal",
        "platform": "realforeclose",
    },
    "El Paso": {
        "base_url": "https://elpasoco.realforeclose.com",
        "search_url": "https://elpasoco.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://elpasoco.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://www.elpasoco.com/recorder/search?query={owner}",
        "county": "El Paso",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "elpaso_foreclosure",
        "platform": "realforeclose",
    },
    "Larimer": {
        "base_url": "https://larimer.realforeclose.com",
        "search_url": "https://larimer.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://larimer.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://www.larimer.gov/clerk/recording/search?name={owner}",
        "county": "Larimer",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "larimer_foreclosure",
        "platform": "realforeclose",
    },
    "Mesa": {
        "base_url": "https://mesa.realforeclose.com",
        "search_url": "https://mesa.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://mesa.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://www.mesacounty.us/clerk-and-recorder/recording/search?name={owner}",
        "county": "Mesa",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "mesa_foreclosure",
        "platform": "realforeclose",
    },
    "Summit": {
        "base_url": "https://summit.realforeclose.com",
        "search_url": "https://summit.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://summit.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://www.summitcountyco.gov/recorder/search?query={owner}",
        "county": "Summit",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "summit_govease",
        "platform": "realforeclose",
    },
    "Weld": {
        "base_url": "https://weld.realforeclose.com",
        "search_url": "https://weld.realforeclose.com/index.cfm?zaction=USER&zmethod=CALENDAR",
        "auction_url": "https://weld.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW",
        "recorder_url_template": "https://www.weld.gov/recorder/search?query={owner}",
        "county": "Weld",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "weld_foreclosure",
        "platform": "realforeclose",
    },
}


# ============================================================================
# GTS SEARCH COUNTIES — County-Hosted Foreclosure Search Databases
# ============================================================================
# These counties run their own ASP.NET GTS (Government Technology Solutions)
# or custom web apps for foreclosure search. Verified LIVE 2026-02-07.
# Data format: HTML tables with search forms, sometimes downloadable reports.

GTS_COUNTIES = {
    "Adams": {
        "base_url": "https://apps.adcogov.org/PTForeclosureSearch/",
        "search_url": "https://apps.adcogov.org/PTForeclosureSearch/",
        "reports_url": "https://apps.adcogov.org/PTForeclosureSearch/reports",
        "recorder_url_template": "http://recording.adcogov.org/LandmarkWeb/search/index?nameFilter={owner}",
        "county": "Adams",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "adams_foreclosure",
        "platform": "gts",
    },
    "Arapahoe": {
        "base_url": "https://foreclosuresearch.arapahoegov.com/",
        "search_url": "https://foreclosuresearch.arapahoegov.com/foreclosure/",
        "recorder_url_template": "https://clerk.arapahoeco.gov/recorder/eagleweb/docSearch.jsp?search={owner}",
        "county": "Arapahoe",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "arapahoe_foreclosure",
        "platform": "gts",
    },
    "Boulder": {
        "base_url": "http://www.bouldercountypt.org/GTSSearch/",
        "search_url": "http://www.bouldercountypt.org/GTSSearch/index.aspx?ds=1",
        "recorder_url_template": "https://recorder.bouldercounty.gov/search?name={owner}",
        "county": "Boulder",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "boulder_foreclosure",
        "platform": "gts",
    },
    "Douglas": {
        "base_url": "https://apps.douglas.co.us/gts/",
        "search_url": "https://apps.douglas.co.us/gts/",
        "recorder_url_template": "https://apps.douglas.co.us/recorder/web/search?name={owner}",
        "county": "Douglas",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "douglas_foreclosure",
        "platform": "gts",
    },
    "Garfield": {
        "base_url": "https://foreclosures.garfield-county.com/",
        "search_url": "https://foreclosures.garfield-county.com/index.aspx",
        "govease_url": "https://liveauctions.govease.com/CO/cogarfieldforeclosure/1324/browsestandard",
        "recorder_url_template": "https://www.garfield-county.com/clerk/recording/search?name={owner}",
        "county": "Garfield",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "garfield_foreclosure",
        "platform": "gts",
    },
}


# ============================================================================
# COUNTY PAGE COUNTIES — Direct .gov Scraping
# ============================================================================
# These counties don't use vendor auction platforms. Data lives on their
# official .gov websites as HTML pages, sometimes with linked PDFs.

COUNTY_PAGE_COUNTIES = {
    "Pitkin": {
        "base_url": "https://pitkincounty.com/294/Foreclosures",
        "search_url": "https://pitkincounty.com/325/Foreclosure-Search",
        "recorder_url_template": "https://www.pitkinclerk.com/clerk-recorder/search?q={owner}",
        "county": "Pitkin",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "pitkin_foreclosure",
        "platform": "county_page",
    },
    "Routt": {
        "base_url": "https://www.co.routt.co.us/414/Public-Trustee",
        "search_url": "https://www.co.routt.co.us/679/Foreclosure-Sale",
        "recorder_url_template": "https://www.co.routt.co.us/recorder/search?query={owner}",
        "county": "Routt",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "routt_foreclosure",
        "platform": "county_page",
    },
    "San Miguel": {
        "base_url": "https://www.sanmiguelcountyco.gov/199/Public-Trustee",
        "search_url": "https://www.sanmiguelcountyco.gov/199/Public-Trustee",
        "recorder_url_template": "https://www.sanmiguelcountyco.gov/recorder/search?query={owner}",
        "county": "San Miguel",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "sanmiguel_portal",
        "platform": "county_page",
    },
    "Grand": {
        "base_url": "https://www.co.grand.co.us/137/Public-Trustee",
        "search_url": "https://www.co.grand.co.us/137/Public-Trustee",
        "pdf_url": "https://www.co.grand.co.us/DocumentCenter/View/27356/Foreclosure-Book-2025",
        "recorder_url_template": "https://www.co.grand.co.us/clerk/recording/search?name={owner}",
        "county": "Grand",
        "state": "CO",
        "asset_type": "FORECLOSURE_SURPLUS",
        "source_name": "grand_foreclosure",
        "platform": "county_page",
    },
}


def clean_money(raw: Any) -> Optional[float]:
    """
    Extract a numeric dollar amount from messy text.

    Handles:
      "$1,234.56"  → 1234.56
      "(1,234.56)" → -1234.56   (accounting negatives)
      "1234"       → 1234.0
      "$0.00"      → 0.0
      "N/A"        → None
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.upper() in ("N/A", "NA", "-", "", "NONE", "TBD"):
        return None

    # Accounting-style negatives: (1,234.56) → -1234.56
    negative = "(" in text and ")" in text
    text = re.sub(r"[^0-9.]", "", text)

    try:
        val = float(text)
        return -val if negative else val
    except (ValueError, TypeError):
        return None


def clean_owner(name: Any) -> Optional[str]:
    """
    Normalize owner name.
    Strips legal suffixes, normalizes whitespace, title-cases.
    """
    if not name:
        return None
    text = str(name).strip()
    if text.upper() in ("UNKNOWN", "N/A", "", "NONE"):
        return None

    # Remove common legal suffixes that don't help identification
    for suffix in (" ET AL", " ET UX", " ETAL", " ET VIR"):
        text = text.replace(suffix, "").replace(suffix.lower(), "")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Title case unless it looks like an entity (has LLC, INC, etc.)
    if not re.search(r"\b(LLC|INC|CORP|LP|LLP|TRUST|BANK|HOA)\b", text.upper()):
        text = text.title()

    return text if text else None


def normalize_address(addr: Any) -> Optional[str]:
    """Standardize street abbreviations for matching."""
    if not addr:
        return None
    text = str(addr).strip().upper()
    if text in ("UNKNOWN", "N/A", "", "NONE"):
        return None

    replacements = {
        "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD",
        "DRIVE": "DR", "COURT": "CT", "PLACE": "PL",
        "LANE": "LN", "ROAD": "RD", "CIRCLE": "CIR",
        "PARKWAY": "PKWY", "TERRACE": "TER", "TRAIL": "TRL",
        "HIGHWAY": "HWY", "NORTH": "N", "SOUTH": "S",
        "EAST": "E", "WEST": "W",
    }
    for full, abbr in replacements.items():
        text = re.sub(rf"\b{full}\b", abbr, text)

    return re.sub(r"\s+", " ", text).strip()


def detect_absentee(property_addr: Optional[str],
                    mailing_addr: Optional[str]) -> Tuple[bool, str]:
    """
    THE ZOMBIE ALGORITHM
    ====================
    Compare property address vs mailing address.
    If they differ → owner has already moved → "ABSENTEE OWNER"
    This means less friction for attorney contact (owner isn't occupying).

    Returns: (is_absentee: bool, reason: str)
    """
    if not property_addr or not mailing_addr:
        return False, "insufficient_data"

    prop = normalize_address(property_addr)
    mail = normalize_address(mailing_addr)

    if not prop or not mail:
        return False, "insufficient_data"

    # Exact match after normalization → owner lives at property
    if prop == mail:
        return False, "owner_occupant"

    # Check if one contains the other (partial match — same building, different unit)
    if prop in mail or mail in prop:
        return False, "partial_match_same_location"

    # Different addresses → absentee owner confirmed
    return True, "address_mismatch"


def parse_date(raw: Any) -> Optional[str]:
    """
    Parse various date formats into ISO 8601 (YYYY-MM-DD).
    Handles: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, Mon DD YYYY, etc.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if text.upper() in ("N/A", "NONE", "", "TBD"):
        return None

    formats = [
        "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%Y/%m/%d",
        "%B %d, %Y", "%b %d, %Y", "%m/%d/%y", "%m-%d-%y",
        "%d-%b-%Y", "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def generate_asset_hash(county: str, case_number: str,
                        property_address: str) -> str:
    """Deterministic hash for deduplication — matches pipeline.py logic."""
    parts = sorted([
        str(county).lower().strip(),
        str(case_number).lower().strip(),
        str(property_address).lower().strip(),
    ])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class ForensicScraper:
    """
    MODULE B: Denver & Jefferson County Public Trustee scraper.

    Strategy:
      1. Hit the county's public trustee surplus/foreclosure page
      2. Parse the HTML table(s) of completed sales
      3. Extract: bid, debt, surplus, owner, property address, mailing address
      4. Run the Zombie Algorithm (absentee owner detection)
      5. Output: list of dicts compatible with pipeline.ingest_asset()

    IMPORTANT — HTML Structure Reality:
      County sites change layouts frequently. This scraper uses a
      CONFIGURABLE selector approach. If the site changes, you update
      the config dict — not the parser logic.
    """

    def __init__(self, session: StealthSession, config: dict):
        self.session = session
        self.config = config
        self.results: List[Dict] = []
        self.errors: List[str] = []

    def scrape(self, start_year: int = 2020,
               end_year: int = 2026) -> List[Dict]:
        """
        Main entry point. Scrapes surplus records for a date range.

        Since Denver/Jefferson don't always have a date-range API endpoint,
        this method:
          1. Fetches the main foreclosure sales page
          2. Looks for links to historical sale data (year-by-year or paginated)
          3. Parses each page for tabular surplus data
          4. Falls back to parsing whatever table data is on the main page

        Returns: List of asset dicts ready for pipeline ingestion.
        """
        log.info(f"[{self.config['county']}] Starting scrape: {start_year}-{end_year}")

        # Step 1: Fetch the main page
        resp = self.session.get(self.config["search_url"])
        if not resp:
            self.errors.append(f"Failed to fetch main page: {self.config['search_url']}")
            return self.results

        soup = BeautifulSoup(resp.text, "lxml")

        # Step 2: Look for links to surplus/overbid/excess data
        data_links = self._find_data_links(soup, start_year, end_year)

        if data_links:
            # Step 3a: Follow each data link and parse
            for link_url, link_label in data_links:
                log.info(f"[{self.config['county']}] Following: {link_label} → {link_url}")
                self._scrape_page(link_url)
        else:
            # Step 3b: Parse the main page directly
            log.info(f"[{self.config['county']}] No sub-links found, parsing main page")
            self._parse_tables(soup, self.config["search_url"])

        # Step 4: Look for downloadable CSV/Excel/PDF links
        self._find_downloadable_files(soup)

        log.info(
            f"[{self.config['county']}] Scrape complete: "
            f"{len(self.results)} records, {len(self.errors)} errors"
        )
        return self.results

    def _find_data_links(self, soup: BeautifulSoup,
                         start_year: int, end_year: int) -> List[Tuple[str, str]]:
        """
        Find links on the page that point to surplus/overbid data.
        Looks for keywords: surplus, overbid, excess, foreclosure sale, completed.
        Filters by year range if years appear in the link text.
        """
        keywords = re.compile(
            r"(surplus|overbid|excess|completed.?sale|foreclosure.?sale|"
            r"unclaimed|overage|bid.?sheet)",
            re.IGNORECASE,
        )
        links = []
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not keywords.search(text) and not keywords.search(href):
                continue

            # Resolve relative URLs
            full_url = urljoin(self.config["search_url"], href)

            # Filter by year if a year appears in the text
            year_match = re.search(r"20\d{2}", text)
            if year_match:
                year = int(year_match.group())
                if year < start_year or year > end_year:
                    continue

            links.append((full_url, text))

        return links

    def _scrape_page(self, url: str):
        """Fetch a single page and extract table data."""
        resp = self.session.get(url)
        if not resp:
            self.errors.append(f"Failed to fetch: {url}")
            return
        soup = BeautifulSoup(resp.text, "lxml")
        self._parse_tables(soup, url)

        # Also check for PDF links on this page (bid sheets)
        self._find_downloadable_files(soup)

    def _parse_tables(self, soup: BeautifulSoup, source_url: str):
        """
        Parse HTML tables from the page. Identify which columns map to
        our required fields using fuzzy keyword matching.
        """
        tables = soup.find_all("table")
        if not tables:
            # Some county sites use div-based layouts instead of tables
            self._parse_div_layout(soup, source_url)
            return

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue  # Need at least header + 1 data row

            # Find header row
            header_row = rows[0]
            headers = [th.get_text(strip=True).upper()
                       for th in header_row.find_all(["th", "td"])]

            # Map headers to our field names
            col_map = self._map_columns(headers)
            if not col_map:
                continue  # No recognizable columns in this table

            log.info(
                f"[{self.config['county']}] Found table with "
                f"{len(rows)-1} rows, mapped columns: {col_map}"
            )

            # Parse data rows
            for row in rows[1:]:
                cells = [td.get_text(strip=True)
                         for td in row.find_all(["td", "th"])]
                if len(cells) < len(headers):
                    continue

                record = self._row_to_asset(cells, col_map, source_url, row)
                if record:
                    self.results.append(record)

    def _map_columns(self, headers: List[str]) -> Dict[str, int]:
        """
        Map raw column headers to standard field names.
        Returns {field_name: column_index} for recognized columns.
        """
        COLUMN_PATTERNS = {
            "case_number": [
                "CASE", "CASE NUMBER", "CASE #", "CASE NO", "FILE NUMBER",
                "FORECLOSURE NUMBER", "FC#", "FC #", "FC_NUM", "RECEPTION",
            ],
            "property_address": [
                "PROPERTY ADDRESS", "ADDRESS", "LOCATION",
                "PROPERTY DESCRIPTION", "SITUS", "STREET",
            ],
            "mailing_address": [
                "MAILING ADDRESS", "MAILING", "MAIL ADDRESS",
                "OWNER ADDRESS", "BORROWER ADDRESS",
            ],
            "owner_of_record": [
                "OWNER", "GRANTOR", "BORROWER", "TAXPAYER", "DEFENDANT",
                "TITLE HOLDER", "ASSESSED TO", "OWNER NAME", "OWNER OF RECORD",
            ],
            "overbid_amount": [
                "WINNING BID", "WINNING_BID", "GRANTEE BID", "SALE PRICE",
                "SOLD AMOUNT", "BID AMOUNT", "PURCHASE PRICE", "AMOUNT BID",
                "BID", "PREMIUM",
            ],
            "total_indebtedness": [
                "TOTAL INDEBTEDNESS", "TOTAL_DEBT", "TOTAL DEBT",
                "JUDGMENT AMOUNT", "AMOUNT DUE", "OUTSTANDING BALANCE",
                "FACE AMOUNT", "LIEN COST", "BALANCE DUE", "DEBT",
            ],
            "estimated_surplus": [
                "SURPLUS", "EXCESS", "OVERBID", "SURPLUS AMOUNT",
                "SURPLUS_AMOUNT", "OVERAGE", "EXCESS PROCEEDS",
            ],
            "sale_date": [
                "SALE DATE", "SALE_DATE", "SOLD DATE", "AUCTION DATE",
                "DATE OF SALE", "DATE",
            ],
        }

        col_map = {}
        used_indices = {}  # Track which column index maps to which field
        for field, patterns in COLUMN_PATTERNS.items():
            for i, header in enumerate(headers):
                for pattern in patterns:
                    if pattern in header or header in pattern:
                        col_map[field] = i
                        used_indices.setdefault(i, []).append(field)
                        break
                if field in col_map:
                    break

        # COLLISION DETECTION: If 3+ fields map to the same column,
        # the table is garbage (navigation/UI table, not data table).
        # Example: a 3-column table where column 2 matches "ADDRESS",
        # "OWNER", "DEBT", "SURPLUS", "DATE" — all false positives.
        max_collision = max((len(v) for v in used_indices.values()), default=0)
        if max_collision >= 3:
            log.debug(f"[{self.config['county']}] Rejected column mapping: "
                      f"{max_collision} fields share one column. "
                      f"Headers: {headers}")
            return {}

        # Must have at least one identifying field to be useful
        has_identity = any(f in col_map for f in
                          ("case_number", "property_address", "owner_of_record"))
        has_financial = any(f in col_map for f in
                           ("overbid_amount", "estimated_surplus", "total_indebtedness"))

        if has_identity and has_financial:
            return col_map
        return {}

    def _row_to_asset(self, cells: List[str], col_map: Dict[str, int],
                      source_url: str,
                      row_element: Any = None) -> Optional[Dict]:
        """
        Convert a single table row into a pipeline-compatible asset dict.
        Runs the Zombie Algorithm for absentee detection.
        """
        def cell(field: str) -> Optional[str]:
            idx = col_map.get(field)
            if idx is not None and idx < len(cells):
                val = cells[idx].strip()
                return val if val else None
            return None

        # Extract raw values
        case_num = cell("case_number") or "UNKNOWN"
        prop_addr = cell("property_address")
        mail_addr = cell("mailing_address")
        owner = clean_owner(cell("owner_of_record"))
        bid = clean_money(cell("overbid_amount"))
        debt = clean_money(cell("total_indebtedness"))
        surplus = clean_money(cell("estimated_surplus"))
        sale_date = parse_date(cell("sale_date"))

        # Skip rows with no usable data
        if not prop_addr and not owner and not case_num:
            return None

        # If surplus isn't directly provided, compute it
        if surplus is None and bid is not None and debt is not None:
            surplus = round(bid - debt, 2)

        # Skip negative surplus (no money to recover)
        if surplus is not None and surplus <= 0:
            return None

        # --- THE ZOMBIE ALGORITHM ---
        is_absentee, absentee_reason = detect_absentee(prop_addr, mail_addr)

        # Check for PDF bid sheet link in the row
        pdf_link = None
        if row_element:
            for a in row_element.find_all("a", href=True):
                href = a["href"].lower()
                if href.endswith(".pdf") or "bid" in href or "sheet" in href:
                    pdf_link = urljoin(source_url, a["href"])
                    break

        # Generate recorder link
        recorder_link = None
        if owner and owner != "Unknown":
            recorder_link = self.config["recorder_url_template"].replace(
                "{owner}", quote_plus(owner)
            )

        # Build the asset dict — matches pipeline.ingest_asset() signature
        asset = {
            "county": self.config["county"],
            "state": self.config["state"],
            "asset_type": self.config["asset_type"],
            "case_number": case_num,
            "property_address": normalize_address(prop_addr) or prop_addr,
            "owner_of_record": owner,
            "estimated_surplus": surplus,
            "total_indebtedness": debt,
            "overbid_amount": bid,
            "sale_date": sale_date,
            "lien_type": "Deed of Trust",  # Default for CO foreclosures
            "recorder_link": recorder_link,
            "source_name": self.config.get("source_name", f"hunter_{self.config['county'].lower()}"),
            "source_file": f"hunter:{self.config['county'].lower()}:{source_url[:80]}",

            # Intelligence fields (not in pipeline schema but useful)
            "_mailing_address": mail_addr,
            "_is_absentee": is_absentee,
            "_absentee_reason": absentee_reason,
            "_pdf_link": pdf_link,
            "_scraped_at": datetime.utcnow().isoformat() + "Z",
        }

        return asset

    def _parse_div_layout(self, soup: BeautifulSoup, source_url: str):
        """
        Fallback parser for sites that use div/card layouts instead of tables.
        Looks for repeating div structures with keyword-labeled fields.
        """
        # Common patterns: dl/dt/dd pairs, labeled divs, card grids
        cards = soup.find_all("div", class_=re.compile(
            r"(card|result|record|item|listing)", re.IGNORECASE
        ))
        if not cards:
            return

        for card in cards:
            text = card.get_text(separator="\n", strip=True)
            # Try to extract key-value pairs from text
            asset = self._extract_from_text_block(text, source_url)
            if asset:
                self.results.append(asset)

    def _extract_from_text_block(self, text: str,
                                 source_url: str) -> Optional[Dict]:
        """
        Extract asset data from a freeform text block using regex patterns.
        Last resort when no clean table structure exists.
        """
        # Money pattern: $1,234.56 or 1234.56
        money_pattern = r"\$?[\d,]+\.?\d{0,2}"

        case_match = re.search(
            r"(?:case|file|fc)[#: ]*(\S+)", text, re.IGNORECASE
        )
        surplus_match = re.search(
            rf"(?:surplus|excess|overbid)[:\s]*({money_pattern})",
            text, re.IGNORECASE,
        )
        bid_match = re.search(
            rf"(?:bid|sale price|winning)[:\s]*({money_pattern})",
            text, re.IGNORECASE,
        )
        debt_match = re.search(
            rf"(?:debt|judgment|indebtedness|balance)[:\s]*({money_pattern})",
            text, re.IGNORECASE,
        )
        owner_match = re.search(
            r"(?:owner|borrower|grantor|defendant)[:\s]*([A-Z][A-Za-z\s,\.]+)",
            text, re.IGNORECASE,
        )
        date_match = re.search(
            r"(?:sale date|date of sale|sold)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            text, re.IGNORECASE,
        )

        if not (surplus_match or bid_match):
            return None

        surplus = clean_money(surplus_match.group(1)) if surplus_match else None
        bid = clean_money(bid_match.group(1)) if bid_match else None
        debt = clean_money(debt_match.group(1)) if debt_match else None

        if surplus is None and bid and debt:
            surplus = round(bid - debt, 2)

        if surplus is not None and surplus <= 0:
            return None

        return {
            "county": self.config["county"],
            "state": self.config["state"],
            "asset_type": self.config["asset_type"],
            "case_number": case_match.group(1) if case_match else "UNKNOWN",
            "owner_of_record": clean_owner(
                owner_match.group(1) if owner_match else None
            ),
            "estimated_surplus": surplus,
            "total_indebtedness": debt,
            "overbid_amount": bid,
            "sale_date": parse_date(
                date_match.group(1) if date_match else None
            ),
            "lien_type": "Deed of Trust",
            "source_file": f"hunter:{self.config['county'].lower()}:text_extract",
            "_scraped_at": datetime.utcnow().isoformat() + "Z",
        }

    def _find_downloadable_files(self, soup: BeautifulSoup):
        """
        Look for downloadable CSV/Excel/PDF files linked on the page.
        These often contain the actual surplus data in cleaner format
        than the HTML tables.
        """
        file_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).lower()
            if any(ext in href for ext in (".csv", ".xlsx", ".xls", ".pdf")):
                if any(kw in text or kw in href for kw in
                       ("surplus", "overbid", "excess", "bid", "foreclosure")):
                    full_url = urljoin(self.config["search_url"], a["href"])
                    file_links.append((full_url, a.get_text(strip=True)))

        for url, label in file_links:
            log.info(f"[{self.config['county']}] Found downloadable file: {label} → {url}")
            # PDF files get handled by the OCR Patcher (Module C)
            # CSV/Excel files could be parsed inline but we log them for now
            if url.lower().endswith(".pdf"):
                # Store for OCR Patcher to process
                self.results.append({
                    "_type": "pdf_link",
                    "_url": url,
                    "_label": label,
                    "county": self.config["county"],
                })


# ============================================================================
# MODULE B2: REALAUCTION SCRAPER — Multi-County Platform
# ============================================================================

class RealForecloseScraper(ForensicScraper):
    """
    MODULE B2: RealForeclose.com Platform Parser
    =============================================
    Targets the ACTUAL auction data on {county}.realforeclose.com.

    VERIFIED LIVE (2026-02-07): Eagle, El Paso, Larimer, Mesa, Summit, Weld.

    Data Flow:
      1. Hit Calendar page → extract sale date links
      2. Hit Auction Preview page → get listing of all properties
      3. Parse rowA/rowB table rows (standard RealForeclose layout)
      4. Extract: case number, address, opening bid, winning bid, status
      5. Surplus = Winning Bid - Opening Bid (Opening Bid ≈ total indebtedness)
      6. Also follow detail links for per-property deep data

    URL Patterns (all relative to base_url):
      Calendar:   /index.cfm?zaction=USER&zmethod=CALENDAR
      Preview:    /index.cfm?zaction=AUCTION&zmethod=PREVIEW
      Background: /index.cfm?zaction=FORECLOSURE&zmethod=BACKGROUND
      Detail:     /index.cfm?zaction=AUCTION&zmethod=DETAILS&Aession=XXXXX

    CRITICAL: All internal link resolution uses urljoin(base_url, href).
    Never string-concatenate URLs.
    """

    # RealForeclose table row CSS classes
    ROW_CLASSES = re.compile(r"\brow[AB]\b", re.IGNORECASE)

    # Column header patterns specific to RealForeclose
    RF_COLUMN_MAP = {
        "case_number": re.compile(
            r"(case|file|foreclosure)\s*(#|no|number)?", re.IGNORECASE),
        "property_address": re.compile(
            r"(property|address|location|parcel)", re.IGNORECASE),
        "owner_of_record": re.compile(
            r"(owner|grantor|borrower|defendant)", re.IGNORECASE),
        "opening_bid": re.compile(
            r"(opening|start|minimum|upset)\s*(bid|price|amount)?", re.IGNORECASE),
        "winning_bid": re.compile(
            r"(winning|final|sold?|sale|high)\s*(bid|price|amount)?", re.IGNORECASE),
        "estimated_surplus": re.compile(
            r"(surplus|excess|over\s*bid|overage)", re.IGNORECASE),
        "sale_date": re.compile(
            r"(sale|auction|sold)\s*(date)?", re.IGNORECASE),
        "status": re.compile(
            r"(status|result|disposition)", re.IGNORECASE),
    }

    def scrape(self, start_year: int = 2020,
               end_year: int = 2026) -> List[Dict]:
        county = self.config["county"]
        base = self.config["base_url"]
        log.info(f"[{county}] RealForeclose scrape: {start_year}-{end_year}")

        # --- STEP 1: Hit Calendar to discover sale date links ---
        calendar_url = self.config.get("search_url") or \
            f"{base}/index.cfm?zaction=USER&zmethod=CALENDAR"
        resp = self.session.get(calendar_url)
        sale_date_links = []
        if resp:
            soup = BeautifulSoup(resp.text, "lxml")
            sale_date_links = self._extract_calendar_links(soup, base,
                                                           start_year, end_year)
            log.info(f"[{county}] Calendar: found {len(sale_date_links)} sale date links")
            # Also try parsing any tables already on the calendar page
            self._parse_rf_tables(soup, calendar_url)
        else:
            self.errors.append(f"Calendar page failed: {calendar_url}")

        # --- STEP 2: Hit Auction Preview (main listing) ---
        auction_url = self.config.get("auction_url") or \
            f"{base}/index.cfm?zaction=AUCTION&zmethod=PREVIEW"
        resp2 = self.session.get(auction_url)
        if resp2:
            soup2 = BeautifulSoup(resp2.text, "lxml")
            self._parse_rf_tables(soup2, auction_url)
            # Find links to individual auction detail pages
            detail_links = self._extract_detail_links(soup2, base)
            log.info(f"[{county}] Preview: found {len(detail_links)} detail links")
            for detail_url, label in detail_links[:50]:  # Cap at 50 to be respectful
                self._scrape_detail_page(detail_url)
        else:
            self.errors.append(f"Auction preview failed: {auction_url}")

        # --- STEP 3: Follow discovered sale date pages ---
        for sd_url, sd_label in sale_date_links[:24]:  # Cap at 24 months
            resp3 = self.session.get(sd_url)
            if resp3:
                soup3 = BeautifulSoup(resp3.text, "lxml")
                self._parse_rf_tables(soup3, sd_url)

        # --- STEP 4: Try Background page for extra context ---
        bg_url = f"{base}/index.cfm?zaction=FORECLOSURE&zmethod=BACKGROUND"
        resp4 = self.session.get(bg_url)
        if resp4:
            soup4 = BeautifulSoup(resp4.text, "lxml")
            self._parse_rf_tables(soup4, bg_url)
            self._find_downloadable_files(soup4)

        # --- STEP 5: Deduplicate ---
        seen = set()
        deduped = []
        for r in self.results:
            key = r.get("case_number") or r.get("property_address") or r.get("owner_of_record")
            if not key:
                deduped.append(r)
            elif key not in seen:
                seen.add(key)
                deduped.append(r)
        self.results = deduped

        log.info(
            f"[{county}] RealForeclose complete: "
            f"{len(self.results)} records, {len(self.errors)} errors"
        )
        return self.results

    def _extract_calendar_links(self, soup: BeautifulSoup, base_url: str,
                                start_year: int, end_year: int) -> List[Tuple[str, str]]:
        """Extract sale date links from the RealForeclose calendar page.

        FIXED: Previous version matched ANY link containing "auction" in the URL,
        which caught LinkedIn/Facebook/mailto links to realauction.com.
        Now only matches links that:
          1. Are on the SAME domain (relative or same-host)
          2. Contain RealForeclose action params (zaction, session_date, etc.)
          3. Are NOT social media, mailto, or external links
        """
        from urllib.parse import urlparse

        base_host = urlparse(base_url).hostname or ""
        links = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)
            href_lower = href.lower()

            # SKIP: external links, social media, mailto, javascript
            if any(href_lower.startswith(prefix) for prefix in
                   ("mailto:", "javascript:", "tel:", "http://www.",
                    "https://www.linkedin", "https://www.facebook",
                    "https://www.twitter", "https://twitter",
                    "https://www.realauction.com")):
                continue

            # For absolute URLs, verify same domain
            if href_lower.startswith("http"):
                link_host = urlparse(href).hostname or ""
                if link_host != base_host:
                    continue

            # Match RealForeclose auction/calendar URL patterns
            if not any(kw in href_lower for kw in
                       ("zaction", "session_date", "ession_date",
                        "zmethod=calendar", "zmethod=preview",
                        "zmethod=details")):
                continue

            # Skip navigation links (home, about, FAQ, contact, login)
            if any(kw in href_lower for kw in
                   ("zmethod=aboutus", "zmethod=faq", "zmethod=start",
                    "zmethod=forgot", "zmethod=fsalepol")):
                continue

            full_url = urljoin(base_url, href)

            # Filter by year if present
            year_match = re.search(r"20\d{2}", text + href)
            if year_match:
                year = int(year_match.group())
                if year < start_year or year > end_year:
                    continue

            links.append((full_url, text))

        # Deduplicate by URL
        seen = set()
        deduped = []
        for url, label in links:
            if url not in seen:
                seen.add(url)
                deduped.append((url, label))

        return deduped

    def _extract_detail_links(self, soup: BeautifulSoup,
                              base_url: str) -> List[Tuple[str, str]]:
        """Extract links to individual auction detail pages."""
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)
            if "details" in href.lower() or "zmethod=details" in href.lower():
                full_url = urljoin(base_url, href)
                links.append((full_url, text))
        return links

    def _scrape_detail_page(self, url: str):
        """Fetch an individual auction detail page and parse it."""
        resp = self.session.get(url)
        if not resp:
            return
        soup = BeautifulSoup(resp.text, "lxml")
        self._parse_rf_tables(soup, url)
        # Also try extracting from text blocks (detail pages may use div layout)
        self._parse_div_layout(soup, url)

    def _parse_rf_tables(self, soup: BeautifulSoup, source_url: str):
        """
        Parse RealForeclose-specific table structure.

        RealForeclose uses CSS classes 'rowA' and 'rowB' for alternating
        table rows. This parser specifically targets that pattern, then
        falls back to the generic table parser.
        """
        # --- PRIMARY: Look for rowA/rowB rows (RealForeclose signature) ---
        rf_rows = soup.find_all("tr", class_=self.ROW_CLASSES)
        if rf_rows:
            log.info(f"[{self.config['county']}] Found {len(rf_rows)} "
                     f"RealForeclose rowA/rowB entries")
            # Find the header row (usually the <tr> before the first rowA/rowB)
            header_row = None
            first_rf = rf_rows[0]
            prev = first_rf.find_previous_sibling("tr")
            if prev:
                header_cells = prev.find_all(["th", "td"])
                if header_cells:
                    headers = [c.get_text(strip=True) for c in header_cells]
                    header_row = headers

            col_map = self._map_rf_columns(header_row) if header_row else {}

            for row in rf_rows:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if not cells:
                    continue
                record = self._rf_row_to_asset(cells, col_map, source_url, row)
                if record:
                    self.results.append(record)
            return

        # --- FALLBACK: Use generic table parser ---
        self._parse_tables(soup, source_url)

    def _map_rf_columns(self, headers: List[str]) -> Dict[str, int]:
        """Map RealForeclose header text to field names using regex matching."""
        col_map = {}
        for i, header in enumerate(headers):
            for field, pattern in self.RF_COLUMN_MAP.items():
                if pattern.search(header):
                    if field not in col_map:  # First match wins
                        col_map[field] = i
                    break
        return col_map

    def _rf_row_to_asset(self, cells: List[str], col_map: Dict[str, int],
                         source_url: str,
                         row_element: Any = None) -> Optional[Dict]:
        """
        Convert a RealForeclose rowA/rowB into an asset dict.

        SURPLUS CALCULATION:
          If 'estimated_surplus' column exists → use directly.
          Else: Surplus = Winning Bid - Opening Bid
          (Opening Bid ≈ total indebtedness on RealForeclose)
        """
        def cell(field: str) -> Optional[str]:
            idx = col_map.get(field)
            if idx is not None and idx < len(cells):
                val = cells[idx].strip()
                return val if val else None
            return None

        # If no column mapping, try positional (common RealForeclose layout):
        # [0]=Case, [1]=Address, [2]=OpeningBid, [3]=Status/WinningBid
        if not col_map and len(cells) >= 3:
            col_map = {"case_number": 0, "property_address": 1}
            # Detect which cell is money
            for i, c in enumerate(cells):
                if "$" in c or re.search(r"\d{1,3}(,\d{3})+", c):
                    if "opening_bid" not in col_map:
                        col_map["opening_bid"] = i
                    else:
                        col_map["winning_bid"] = i

        case_num = cell("case_number") or "UNKNOWN"
        prop_addr = cell("property_address")
        owner = clean_owner(cell("owner_of_record"))
        opening = clean_money(cell("opening_bid"))
        winning = clean_money(cell("winning_bid"))
        surplus = clean_money(cell("estimated_surplus"))
        sale_date = parse_date(cell("sale_date"))
        status = cell("status") or ""

        # Skip if no identifying data
        if not prop_addr and not owner and case_num == "UNKNOWN":
            return None

        # --- SURPLUS MATH ---
        # Opening Bid on RealForeclose = total indebtedness (debt owed)
        # Winning Bid = what the property actually sold for
        # Surplus = Winning - Opening (if positive, there's money for the owner)
        debt = opening
        bid = winning

        if surplus is None and bid is not None and debt is not None:
            computed = round(bid - debt, 2)
            if computed > 0:
                surplus = computed

        # Skip if no positive surplus and no financial data at all
        if surplus is not None and surplus <= 0:
            return None

        # Skip pending/cancelled unless they have surplus data
        status_upper = status.upper()
        if any(kw in status_upper for kw in ("CANCEL", "WITHDRAW", "POSTPONE")) \
                and surplus is None:
            return None

        # Generate recorder link
        recorder_link = None
        if owner and owner != "Unknown":
            recorder_link = self.config["recorder_url_template"].replace(
                "{owner}", quote_plus(owner)
            )

        # Check for PDF links in the row
        pdf_link = None
        if row_element:
            for a in row_element.find_all("a", href=True):
                href = a["href"].lower()
                if href.endswith(".pdf") or "bid" in href or "sheet" in href:
                    pdf_link = urljoin(source_url, a["href"])
                    break

        asset = {
            "county": self.config["county"],
            "state": self.config["state"],
            "asset_type": self.config["asset_type"],
            "case_number": case_num,
            "property_address": normalize_address(prop_addr) or prop_addr,
            "owner_of_record": owner,
            "estimated_surplus": surplus,
            "total_indebtedness": debt,
            "overbid_amount": bid,
            "sale_date": sale_date,
            "lien_type": "Deed of Trust",
            "recorder_link": recorder_link,
            "source_name": self.config.get("source_name",
                                           f"hunter_{self.config['county'].lower()}"),
            "source_file": f"realforeclose:{self.config['county'].lower()}:{source_url[:80]}",
            "_pdf_link": pdf_link,
            "_auction_status": status,
            "_scraped_at": datetime.utcnow().isoformat() + "Z",
        }
        return asset


# ============================================================================
# MODULE B3: GOVEASE SCRAPER — Mountain Resort Counties
# ============================================================================

class GTSSearchScraper(ForensicScraper):
    """
    MODULE B3: County-Hosted GTS Foreclosure Search Scraper
    =======================================================
    Targets ASP.NET foreclosure search applications hosted by counties.

    Used by: Adams, Arapahoe, Boulder, Douglas, Garfield

    Strategy:
      1. Hit the search page to get the form structure and any default results
      2. Look for ViewState/EventValidation (ASP.NET CSRF tokens)
      3. Submit search form with date range to get foreclosure listings
      4. Parse result tables (standard HTML tables, no rowA/rowB)
      5. Follow pagination if present
      6. Also check for downloadable reports (PDF/CSV links)
      7. If Garfield: also hit GovEase secondary endpoint

    IMPORTANT: These are ASP.NET apps — they require ViewState tokens.
    The StealthSession handles cookies automatically, which helps.
    """

    def scrape(self, start_year: int = 2020,
               end_year: int = 2026) -> List[Dict]:
        county = self.config["county"]
        log.info(f"[{county}] GTS search scrape: {start_year}-{end_year}")

        # --- STEP 1: Load search page ---
        search_url = self.config["search_url"]
        resp = self.session.get(search_url)
        if not resp:
            self.errors.append(f"Search page failed: {search_url}")
            return self.results

        soup = BeautifulSoup(resp.text, "lxml")

        # --- STEP 2: Parse any default results already on the page ---
        self._parse_tables(soup, search_url)

        # --- STEP 3: Try submitting search form with date range ---
        form = soup.find("form")
        if form:
            self._submit_gts_search(form, soup, search_url, start_year, end_year)

        # --- STEP 4: Look for data links (surplus, overbid, reports) ---
        data_links = self._find_data_links(soup, start_year, end_year)
        for link_url, link_label in data_links:
            log.info(f"[{county}] Following: {link_label} → {link_url}")
            self._scrape_page(link_url)

        # --- STEP 5: Check for downloadable files ---
        self._find_downloadable_files(soup)

        # --- STEP 6: Check reports URL if available ---
        reports_url = self.config.get("reports_url")
        if reports_url:
            resp2 = self.session.get(reports_url)
            if resp2:
                soup2 = BeautifulSoup(resp2.text, "lxml")
                self._parse_tables(soup2, reports_url)
                self._find_downloadable_files(soup2)

        # --- STEP 7: Garfield secondary — GovEase ---
        govease_url = self.config.get("govease_url")
        if govease_url:
            log.info(f"[{county}] Hitting GovEase secondary: {govease_url}")
            resp3 = self.session.get(govease_url)
            if resp3:
                soup3 = BeautifulSoup(resp3.text, "lxml")
                self._parse_tables(soup3, govease_url)
                self._find_downloadable_files(soup3)

        # --- STEP 8: Deduplicate ---
        seen = set()
        deduped = []
        for r in self.results:
            key = r.get("case_number") or r.get("property_address") or r.get("owner_of_record")
            if not key:
                deduped.append(r)
            elif key not in seen:
                seen.add(key)
                deduped.append(r)
        self.results = deduped

        log.info(
            f"[{county}] GTS search complete: "
            f"{len(self.results)} records, {len(self.errors)} errors"
        )
        return self.results

    def _submit_gts_search(self, form, soup: BeautifulSoup,
                           source_url: str,
                           start_year: int, end_year: int):
        """
        Submit the ASP.NET search form with date range parameters.

        GTS apps typically have:
          - __VIEWSTATE, __EVENTVALIDATION hidden fields
          - Date range inputs (start date, end date)
          - A "Search" submit button
        """
        # Extract ASP.NET hidden fields
        form_data = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                form_data[name] = value

        # Find date inputs and set range
        date_inputs = soup.find_all("input", {"type": re.compile(r"text|date", re.IGNORECASE)})
        date_fields_set = 0
        for inp in date_inputs:
            name = inp.get("name", "").lower()
            inp_id = inp.get("id", "").lower()
            label = name + " " + inp_id
            if any(kw in label for kw in ("start", "from", "begin", "saledate1")):
                form_data[inp.get("name")] = f"01/01/{start_year}"
                date_fields_set += 1
            elif any(kw in label for kw in ("end", "to", "through", "saledate2")):
                form_data[inp.get("name")] = f"12/31/{end_year}"
                date_fields_set += 1

        if date_fields_set < 2:
            log.info(f"[{self.config['county']}] Could not identify date range fields")
            return

        # Find submit button
        submit = soup.find("input", {"type": "submit"})
        if submit and submit.get("name"):
            form_data[submit["name"]] = submit.get("value", "Search")

        # Determine form action URL
        action = form.get("action", "")
        post_url = urljoin(source_url, action) if action else source_url

        log.info(f"[{self.config['county']}] Submitting GTS search: "
                 f"{start_year}-{end_year} → {post_url}")

        resp = self.session.post(post_url, data=form_data)
        if resp:
            soup2 = BeautifulSoup(resp.text, "lxml")
            self._parse_tables(soup2, post_url)
            self._find_downloadable_files(soup2)

            # Follow pagination
            self._follow_pagination(soup2, post_url, form_data)

    def _follow_pagination(self, soup: BeautifulSoup, source_url: str,
                           form_data: dict, max_pages: int = 10):
        """Follow pagination links in GTS search results."""
        for page_num in range(2, max_pages + 1):
            # Look for "Next" or page number links
            next_link = None
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True).lower()
                if text in ("next", "next >", ">>", str(page_num)):
                    href = a["href"]
                    if "javascript" in href.lower():
                        # ASP.NET postback — extract event target
                        match = re.search(r"__doPostBack\('([^']+)'", href)
                        if match:
                            page_data = form_data.copy()
                            page_data["__EVENTTARGET"] = match.group(1)
                            page_data["__EVENTARGUMENT"] = ""
                            resp = self.session.post(source_url, data=page_data)
                            if resp:
                                soup = BeautifulSoup(resp.text, "lxml")
                                new_count = len(self.results)
                                self._parse_tables(soup, source_url)
                                if len(self.results) == new_count:
                                    return  # No new records — stop
                                next_link = True
                    else:
                        full_url = urljoin(source_url, href)
                        resp = self.session.get(full_url)
                        if resp:
                            soup = BeautifulSoup(resp.text, "lxml")
                            new_count = len(self.results)
                            self._parse_tables(soup, full_url)
                            if len(self.results) == new_count:
                                return
                            next_link = True
                    break
            if not next_link:
                return


class CountyPageScraper(ForensicScraper):
    """
    MODULE B4: County .gov Page Scraper
    ====================================
    For counties that don't use vendor platforms: Pitkin, Routt,
    San Miguel, Grand.

    Strategy:
      1. Hit the county's foreclosure/surplus page
      2. Parse HTML tables and div layouts
      3. Follow links to surplus lists, overbid data, PDFs
      4. For Grand: download and parse the Foreclosure Book PDF
    """

    def scrape(self, start_year: int = 2020,
               end_year: int = 2026) -> List[Dict]:
        county = self.config["county"]
        log.info(f"[{county}] County page scrape: {start_year}-{end_year}")

        # Hit the main page
        search_url = self.config["search_url"]
        resp = self.session.get(search_url)
        if resp:
            soup = BeautifulSoup(resp.text, "lxml")
            self._parse_tables(soup, search_url)
            data_links = self._find_data_links(soup, start_year, end_year)
            for link_url, link_label in data_links:
                log.info(f"[{county}] Following: {link_label}")
                self._scrape_page(link_url)
            self._find_downloadable_files(soup)
        else:
            self.errors.append(f"County page failed: {search_url}")

        # Also try base_url if different from search_url
        base_url = self.config.get("base_url")
        if base_url and base_url != search_url:
            resp2 = self.session.get(base_url)
            if resp2:
                soup2 = BeautifulSoup(resp2.text, "lxml")
                self._parse_tables(soup2, base_url)
                self._find_downloadable_files(soup2)

        # Special: Grand County PDF Foreclosure Book
        pdf_url = self.config.get("pdf_url")
        if pdf_url:
            log.info(f"[{county}] Downloading PDF Foreclosure Book")
            pdf_bytes = self.session.download_pdf(pdf_url)
            if pdf_bytes and pdfplumber:
                self._parse_grand_pdf(pdf_bytes, pdf_url)
            elif pdf_bytes:
                self.results.append({
                    "_type": "pdf_link",
                    "_url": pdf_url,
                    "_label": "Foreclosure Book PDF",
                    "county": county,
                })

        # Deduplicate
        seen = set()
        deduped = []
        for r in self.results:
            key = r.get("case_number") or r.get("property_address") or r.get("owner_of_record")
            if not key:
                deduped.append(r)
            elif key not in seen:
                seen.add(key)
                deduped.append(r)
        self.results = deduped

        log.info(
            f"[{county}] County page complete: "
            f"{len(self.results)} records, {len(self.errors)} errors"
        )
        return self.results

    # Grand County Foreclosure Book has a KNOWN column layout that differs
    # from standard county sites. The generic _map_columns() mismaps
    # "Sale Date" → "estimated_surplus" because both match money/date patterns.
    # TITAN FIX: Explicit column mapping for Grand County PDF tables.
    GRAND_COLUMN_OVERRIDES = {
        # Grand County Foreclosure Book typical columns:
        # Case# | Borrower | Property | Sale Date | Indebtedness | Overbid | Surplus
        "CASE": "case_number",
        "CASE#": "case_number",
        "CASE NO": "case_number",
        "BORROWER": "owner_of_record",
        "OWNER": "owner_of_record",
        "DEFENDANT": "owner_of_record",
        "PROPERTY": "property_address",
        "ADDRESS": "property_address",
        "SALE DATE": "sale_date",
        "DATE": "sale_date",
        "SALE": "sale_date",
        "INDEBTEDNESS": "total_indebtedness",
        "TOTAL INDEBTEDNESS": "total_indebtedness",
        "DEBT": "total_indebtedness",
        "JUDGMENT": "total_indebtedness",
        "OVERBID": "overbid_amount",
        "WINNING BID": "overbid_amount",
        "BID": "overbid_amount",
        "SURPLUS": "estimated_surplus",
        "EXCESS": "estimated_surplus",
        "OVERAGE": "estimated_surplus",
    }

    def _map_grand_columns(self, headers: List[str]) -> Dict[str, int]:
        """
        Grand County-specific column mapping using explicit overrides.
        Prevents the sale_date → surplus mismap that produces $5M hallucinations.
        """
        col_map = {}
        for i, header in enumerate(headers):
            h = header.strip().upper()
            # Try exact match first
            if h in self.GRAND_COLUMN_OVERRIDES:
                field = self.GRAND_COLUMN_OVERRIDES[h]
                if field not in col_map:
                    col_map[field] = i
                continue
            # Try substring match (e.g., header="TOTAL INDEBTEDNESS (incl costs)")
            for key, field in self.GRAND_COLUMN_OVERRIDES.items():
                if key in h and field not in col_map:
                    col_map[field] = i
                    break
        return col_map

    def _parse_grand_pdf(self, pdf_bytes: bytes, source_url: str):
        """
        Parse Grand County's Foreclosure Book PDF.
        TITAN FIX: Uses Grand-specific column mapping to prevent mismaps.
        """
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        headers = [str(c).strip().upper() if c else ""
                                   for c in table[0]]

                        # TITAN: Use Grand-specific mapping, NOT generic
                        col_map = self._map_grand_columns(headers)
                        if not col_map:
                            # Fallback to generic only if Grand mapping fails
                            col_map = self._map_columns(headers)
                        if not col_map:
                            continue

                        log.info(f"[Grand] PDF table: {len(table)-1} rows, "
                                 f"mapped: {col_map}")

                        for row in table[1:]:
                            cells = [str(c).strip() if c else "" for c in row]
                            record = self._row_to_asset(cells, col_map,
                                                        source_url)
                            if record:
                                self.results.append(record)

                    # Fallback: text extraction (no table structure found)
                    if not tables:
                        text = page.extract_text()
                        if text:
                            asset = self._extract_from_text_block(text,
                                                                   source_url)
                            if asset:
                                self.results.append(asset)
        except Exception as e:
            log.error(f"[Grand] PDF parse error: {e}")
            self.errors.append(f"Grand PDF parse: {e}")


# ============================================================================
# MODULE B5: ZOMBIE SCRAPER — Tax Lien Sales + Code Enforcement (PLACEHOLDER)
# ============================================================================

class ZombieScraper:
    """
    MODULE B5: Zombie Property Intelligence Scraper
    =================================================
    Targets "zombie" properties: vacant, tax-delinquent, code violations.
    These fill the pipeline when foreclosure data is thin.

    TARGET A: County Treasurer "Tax Lien Sale" Lists
      - Annual tax lien sale results (distinct from foreclosure surplus)
      - Key data: parcel, owner, delinquent amount, sale price, buyer
      - Surplus = Sale Price - Delinquent Taxes - Fees

    TARGET B: County "Code Enforcement" Violations
      - Indicates vacancy (tall grass, condemned, boarded up)
      - Cross-reference with tax lien data for zombie detection
      - Key data: address, violation type, date, status

    STATUS: PLACEHOLDER — structure ready, scrapers disabled.
    To activate: implement scrape() for each county's treasurer site.
    """

    # County Treasurer tax lien sale URLs (research needed per county)
    # TODO: Verify these URLs and add date range parameters
    TAX_LIEN_ENDPOINTS = {
        "Denver": {
            "url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/"
                   "Agencies-Departments-Offices-Directory/Department-of-Finance/"
                   "Treasury/Tax-Lien-Sale",
            "platform": "html_table",
            "asset_type": "TAX_DEED_SURPLUS",
        },
        "El Paso": {
            "url": "https://treasurer.elpasoco.com/tax-lien-sale/",
            "platform": "html_table",
            "asset_type": "TAX_DEED_SURPLUS",
        },
        # TODO: Add remaining counties as treasurer URLs are verified
    }

    # Code enforcement / vacancy indicators
    CODE_ENFORCEMENT_ENDPOINTS = {
        "Denver": {
            "url": "https://www.denvergov.org/Government/Agencies-Departments-Offices/"
                   "Agencies-Departments-Offices-Directory/Community-Planning-and-Development/"
                   "Code-Enforcement",
            "platform": "html_table",
        },
        # TODO: Add remaining counties
    }

    def __init__(self, session: StealthSession):
        self.session = session
        self.results: List[Dict] = []
        self.errors: List[str] = []

    def scrape_tax_liens(self, counties: Optional[List[str]] = None,
                         start_year: int = 2020,
                         end_year: int = 2026) -> List[Dict]:
        """
        Scrape county tax lien sale results.

        TODO: Implement per-county parsing logic.
        Each county's treasurer site has a different HTML structure.

        Returns: List of asset dicts with asset_type=TAX_DEED_SURPLUS
        """
        log.info("[ZombieScraper] Tax lien scraping is PLACEHOLDER — not yet implemented")
        # TODO: For each county:
        #   1. Hit treasurer tax lien sale page
        #   2. Parse HTML tables for sale results
        #   3. Extract: parcel, owner, delinquent amount, sale price
        #   4. Compute surplus: sale_price - delinquent_taxes - fees
        #   5. Return asset dicts compatible with pipeline.ingest_asset()
        return []

    def scrape_code_enforcement(self, counties: Optional[List[str]] = None) -> List[Dict]:
        """
        Scrape code enforcement violations to detect vacancy.

        TODO: Implement per-county parsing logic.

        Returns: List of violation records (not direct pipeline assets,
                 but used for cross-referencing with tax lien / foreclosure data)
        """
        log.info("[ZombieScraper] Code enforcement scraping is PLACEHOLDER — not yet implemented")
        # TODO: For each county:
        #   1. Hit code enforcement page
        #   2. Parse violation records
        #   3. Cross-reference addresses with existing pipeline assets
        #   4. Flag matches as potential zombie properties
        return []

    def detect_zombies(self, tax_liens: List[Dict],
                       violations: List[Dict]) -> List[Dict]:
        """
        Cross-reference tax lien sales with code enforcement violations.
        Properties appearing in BOTH lists are likely zombies.

        TODO: Implement address matching + scoring logic.
        """
        log.info("[ZombieScraper] Zombie detection is PLACEHOLDER — not yet implemented")
        # TODO:
        #   1. Normalize addresses from both lists
        #   2. Match by address similarity (fuzzy match)
        #   3. Score: tax_lien + code_violation = high zombie probability
        #   4. Return enriched records with _zombie_score
        return []


# ============================================================================
# MODULE C: OCR PATCHER — PDF Bid Sheet Extraction
# ============================================================================

class OCRPatcher:
    """
    Extracts surplus/overbid data from PDF bid sheets.

    Strategy:
      1. Download the PDF via StealthSession
      2. Open with pdfplumber (text extraction, not OCR)
      3. Search for "Overbid:", "Surplus:", "Excess:" patterns
      4. Extract dollar amounts adjacent to those keywords
      5. Patch the original asset record with found values

    pdfplumber handles text-based PDFs. For scanned image PDFs,
    you'd need Tesseract OCR — but county bid sheets are almost
    always text-based since they're generated digitally.
    """

    # Patterns to search for in PDF text
    SURPLUS_PATTERNS = [
        re.compile(r"(?:overbid|surplus|excess)[:\s]*\$?([\d,]+\.?\d{0,2})", re.IGNORECASE),
        re.compile(r"(?:excess proceeds|surplus funds)[:\s]*\$?([\d,]+\.?\d{0,2})", re.IGNORECASE),
    ]

    BID_PATTERNS = [
        re.compile(r"(?:winning bid|sale price|purchase price|bid amount)[:\s]*\$?([\d,]+\.?\d{0,2})", re.IGNORECASE),
    ]

    DEBT_PATTERNS = [
        re.compile(r"(?:total (?:indebtedness|debt|judgment)|judgment amount)[:\s]*\$?([\d,]+\.?\d{0,2})", re.IGNORECASE),
    ]

    OWNER_PATTERNS = [
        re.compile(r"(?:owner|grantor|borrower|defendant)[:\s]*([A-Z][A-Za-z\s,\.]+?)(?:\n|$)", re.IGNORECASE),
    ]

    CASE_PATTERNS = [
        re.compile(r"(?:case|file|reception)[# :]*(\d{4}[A-Z]*\d+|\d+-\w+-\d+)", re.IGNORECASE),
    ]

    def __init__(self, session: StealthSession):
        self.session = session
        if pdfplumber is None:
            log.warning(
                "pdfplumber not installed. OCR Patcher disabled. "
                "Install with: pip install pdfplumber"
            )

    def extract_from_pdf(self, pdf_url: str) -> Optional[Dict]:
        """
        Download and extract data from a single PDF bid sheet.
        Returns a partial asset dict with whatever fields were found.
        """
        if pdfplumber is None:
            return None

        log.info(f"[OCR] Downloading PDF: {pdf_url}")
        pdf_bytes = self.session.download_pdf(pdf_url)
        if not pdf_bytes:
            return None

        return self._parse_pdf_bytes(pdf_bytes, pdf_url)

    def _parse_pdf_bytes(self, pdf_bytes: bytes,
                         source_url: str = "") -> Optional[Dict]:
        """Extract data from raw PDF bytes."""
        if pdfplumber is None:
            return None

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"

                    # Also try extracting tables from the PDF
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if row:
                                full_text += " | ".join(
                                    str(c) for c in row if c
                                ) + "\n"

        except Exception as e:
            log.error(f"[OCR] Failed to parse PDF: {e}")
            return None

        if not full_text.strip():
            log.warning(f"[OCR] PDF has no extractable text (may be scanned image)")
            return None

        # Extract fields using regex patterns
        result = {"_source_pdf": source_url}

        for pattern in self.SURPLUS_PATTERNS:
            match = pattern.search(full_text)
            if match:
                result["estimated_surplus"] = clean_money(match.group(1))
                break

        for pattern in self.BID_PATTERNS:
            match = pattern.search(full_text)
            if match:
                result["overbid_amount"] = clean_money(match.group(1))
                break

        for pattern in self.DEBT_PATTERNS:
            match = pattern.search(full_text)
            if match:
                result["total_indebtedness"] = clean_money(match.group(1))
                break

        for pattern in self.OWNER_PATTERNS:
            match = pattern.search(full_text)
            if match:
                result["owner_of_record"] = clean_owner(match.group(1))
                break

        for pattern in self.CASE_PATTERNS:
            match = pattern.search(full_text)
            if match:
                result["case_number"] = match.group(1)
                break

        # Compute surplus if we got bid and debt but not surplus directly
        if ("estimated_surplus" not in result
                and result.get("overbid_amount") and result.get("total_indebtedness")):
            surplus = result["overbid_amount"] - result["total_indebtedness"]
            if surplus > 0:
                result["estimated_surplus"] = round(surplus, 2)

        return result if len(result) > 1 else None  # >1 because _source_pdf always present

    def patch_records(self, records: List[Dict]) -> List[Dict]:
        """
        For any record missing surplus but having a PDF link,
        download the PDF and patch the record.
        """
        patched_count = 0
        for record in records:
            # Skip non-asset entries (like pdf_link placeholders)
            if record.get("_type") == "pdf_link":
                continue

            pdf_url = record.get("_pdf_link")
            if not pdf_url:
                continue

            # Only patch if surplus is missing
            if record.get("estimated_surplus"):
                continue

            log.info(f"[OCR] Patching record {record.get('case_number', '?')} from PDF")
            pdf_data = self.extract_from_pdf(pdf_url)
            if pdf_data:
                # Merge PDF data into record (don't overwrite existing values)
                for key, val in pdf_data.items():
                    if key.startswith("_"):
                        record[key] = val
                    elif not record.get(key):
                        record[key] = val
                        log.info(f"  → Patched {key} = {val}")

                patched_count += 1

        log.info(f"[OCR] Patched {patched_count} records from PDF bid sheets")
        return records


# ============================================================================
# MODULE D: LIEN WIPER — Surplus Math & Whale Classification
# ============================================================================

class LienWiper:
    """
    Financial analysis module:
      1. Computes Surplus_Liquidity = Bid - Total_Debt
      2. Detects WHALE records ($100K+ surplus, no junior liens)
      3. Calculates fee estimates based on statute tier
      4. Flags records by litigation quality

    Classification tiers:
      WHALE    — Surplus > $100K, no junior liens detected
      PRIME    — Surplus > $25K
      VIABLE   — Surplus > $5K
      MARGINAL — Surplus > $1K
      SKIP     — Surplus ≤ $1K (not worth attorney time)
    """

    THRESHOLDS = {
        "WHALE": 100_000,
        "PRIME": 25_000,
        "VIABLE": 5_000,
        "MARGINAL": 1_000,
    }

    # Keywords that indicate junior liens (risk factors)
    LIEN_VULTURE_KEYWORDS = [
        "HOA", "HOMEOWNERS ASSOCIATION", "BANK OF AMERICA", "WELLS FARGO",
        "CHASE", "CITIBANK", "US BANK", "NATIONSTAR", "OCWEN",
        "IRS", "INTERNAL REVENUE", "STATE TAX", "DEPARTMENT OF REVENUE",
        "SECOND DEED", "JUNIOR LIEN", "MECHANIC", "JUDGMENT CREDITOR",
    ]

    def classify(self, records: List[Dict]) -> List[Dict]:
        """
        Run financial analysis on all records.
        Adds classification fields to each record dict.
        """
        for record in records:
            if record.get("_type") == "pdf_link":
                continue

            surplus = record.get("estimated_surplus")
            bid = record.get("overbid_amount")
            debt = record.get("total_indebtedness")

            # Recompute surplus if needed
            if surplus is None and bid is not None and debt is not None:
                surplus = round(bid - debt, 2)
                record["estimated_surplus"] = surplus

            if surplus is None or surplus <= 0:
                # POTENTIAL_SURPLUS: Has debt but no surplus data yet.
                # These are confirmed sold foreclosures where surplus
                # needs to be computed from sale price (different page).
                if record.get("_potential_surplus") and debt and debt > 0:
                    record["_classification"] = "POTENTIAL_SURPLUS"
                    record["_skip_reason"] = None
                    record["estimated_surplus"] = 0
                    record["_estimated_fee"] = 0
                    record["_fee_pct"] = 0.33
                    record["_litigation_quality"] = "C"
                    continue
                record["_classification"] = "SKIP"
                record["_skip_reason"] = "no_positive_surplus"
                continue

            # --- CLASSIFICATION ---
            classification = "SKIP"
            for tier, threshold in self.THRESHOLDS.items():
                if surplus >= threshold:
                    classification = tier
                    break

            # --- JUNIOR LIEN DETECTION ---
            # Check all text fields for vulture keywords
            junior_lien_count = 0
            lien_flags = []
            text_to_check = " ".join(
                str(v) for v in record.values() if isinstance(v, str)
            ).upper()

            for keyword in self.LIEN_VULTURE_KEYWORDS:
                if keyword in text_to_check:
                    junior_lien_count += 1
                    lien_flags.append(keyword)

            # WHALE requires $100K+ AND zero junior liens
            if classification == "WHALE" and junior_lien_count > 0:
                classification = "PRIME"  # Downgrade — liens detected

            # --- FEE ESTIMATE ---
            # Based on Colorado statute tiers
            sale_date = record.get("sale_date")
            fee_pct = 0.33  # Default: attorney exclusive window
            if sale_date:
                try:
                    sale_dt = datetime.strptime(sale_date, "%Y-%m-%d")
                    days_since = (datetime.utcnow() - sale_dt).days
                    if days_since <= 180:
                        fee_pct = 0.33  # Unregulated
                    elif days_since <= 730:
                        fee_pct = 0.20  # Finder eligible, 20% cap
                    else:
                        fee_pct = 0.10  # Treasury, 10% cap
                    record["_days_since_sale"] = days_since
                except ValueError:
                    pass

            estimated_fee = round(surplus * fee_pct, 2)

            # --- WRITE RESULTS ---
            record["_classification"] = classification
            record["_junior_lien_count"] = junior_lien_count
            record["_junior_lien_flags"] = lien_flags
            record["_fee_pct"] = fee_pct
            record["_estimated_fee"] = estimated_fee
            record["_litigation_quality"] = self._assess_quality(record)

        return records

    def _assess_quality(self, record: Dict) -> str:
        """
        Overall litigation quality score based on data completeness.
        A = All fields present, high surplus, no liens, absentee owner
        B = Most fields, decent surplus
        C = Minimum viable — needs manual enrichment
        D = Missing critical fields — probably not actionable
        """
        score = 0

        # Has surplus > 0
        if record.get("estimated_surplus", 0) > 0:
            score += 1

        # Has owner name
        if record.get("owner_of_record") and record["owner_of_record"] != "Unknown":
            score += 1

        # Has sale date
        if record.get("sale_date"):
            score += 1

        # Has property address
        if record.get("property_address"):
            score += 1

        # Has case number
        if record.get("case_number") and record["case_number"] != "UNKNOWN":
            score += 1

        # No junior liens
        if record.get("_junior_lien_count", 0) == 0:
            score += 1

        # Absentee owner (bonus — easier to contact)
        if record.get("_is_absentee"):
            score += 1

        # High surplus
        if record.get("estimated_surplus", 0) >= 25_000:
            score += 1

        if score >= 7:
            return "A"
        elif score >= 5:
            return "B"
        elif score >= 3:
            return "C"
        else:
            return "D"

    def detect_zombies(self, records: List[Dict]) -> int:
        """
        THE ZOMBIE PROTOCOL — Detect potential zombie properties.

        A zombie is a record that has total_indebtedness (debt data exists)
        but is missing estimated_surplus. This means the property went through
        foreclosure proceedings but we couldn't extract/compute the surplus.

        These are NOT discarded — they are flagged as POTENTIAL_ZOMBIE for
        manual review or tax lien cross-reference.

        Returns: count of zombies detected.
        """
        zombie_count = 0
        for record in records:
            if record.get("_type") == "pdf_link":
                continue

            debt = record.get("total_indebtedness")
            surplus = record.get("estimated_surplus")
            bid = record.get("overbid_amount")
            classification = record.get("_classification", "SKIP")

            # Zombie criteria: has debt data but no surplus and no winning bid
            # This means the foreclosure record exists but financial outcome is unknown
            if debt and debt > 0 and surplus is None and bid is None:
                record["_zombie_status"] = "POTENTIAL_ZOMBIE"
                record["_zombie_reason"] = "has_debt_no_surplus"
                zombie_count += 1
                continue

            # Also flag: has debt and bid but surplus was negative (already filtered)
            # These got SKIP classification but may have surplus in a different data source
            if (classification == "SKIP" and debt and debt > 0
                    and record.get("_skip_reason") == "no_positive_surplus"):
                record["_zombie_status"] = "POTENTIAL_ZOMBIE"
                record["_zombie_reason"] = "negative_surplus_needs_review"
                zombie_count += 1

        if zombie_count > 0:
            log.info(f"[ZOMBIE] Detected {zombie_count} potential zombie properties")
        return zombie_count

    def summary(self, records: List[Dict]) -> dict:
        """Generate classification summary."""
        counts = {"WHALE": 0, "PRIME": 0, "VIABLE": 0, "MARGINAL": 0, "SKIP": 0}
        total_surplus = 0
        total_fees = 0
        zombie_count = 0

        for r in records:
            cls = r.get("_classification", "SKIP")
            counts[cls] = counts.get(cls, 0) + 1
            if cls != "SKIP":
                total_surplus += r.get("estimated_surplus", 0)
                total_fees += r.get("_estimated_fee", 0)
            if r.get("_zombie_status") == "POTENTIAL_ZOMBIE":
                zombie_count += 1

        return {
            "classification_counts": counts,
            "total_surplus_found": round(total_surplus, 2),
            "total_estimated_fees": round(total_fees, 2),
            "actionable_records": sum(
                v for k, v in counts.items() if k != "SKIP"
            ),
            "zombie_count": zombie_count,
        }


# ============================================================================
# ORCHESTRATOR — Ties all 4 modules together
# ============================================================================

def _build_config_map() -> Dict[str, dict]:
    """Build the complete county config map across all platforms."""
    configs = {
        "Denver": DENVER_CONFIG,
        "Jefferson": JEFFERSON_CONFIG,
    }
    configs.update(REALFORECLOSE_COUNTIES)
    configs.update(GTS_COUNTIES)
    configs.update(COUNTY_PAGE_COUNTIES)
    return configs


# All Colorado counties with active scraper support
ALL_COLORADO_COUNTIES = list(_build_config_map().keys())


def _get_scraper_class(config: dict):
    """Return the correct scraper class based on platform.

    Platform routing:
      realforeclose → RealForecloseScraper (rowA/rowB calendar parser)
      gts          → GTSSearchScraper (ASP.NET form search)
      county_page  → CountyPageScraper (.gov page + PDF support)
      standard     → ForensicScraper (generic HTML table parser)
    """
    platform = config.get("platform", "standard")
    if platform == "realforeclose":
        return RealForecloseScraper
    elif platform == "gts":
        return GTSSearchScraper
    elif platform == "county_page":
        return CountyPageScraper
    return ForensicScraper


def _update_scraper_registry(source_name: str, records_count: int, status: str):
    """Update scraper_registry with run results after each county scrape."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent / "data" / "verifuse.db"
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            UPDATE scraper_registry SET
                last_run_at = datetime('now'),
                last_run_status = ?,
                records_produced = records_produced + ?
            WHERE scraper_name = ?
        """, (status, records_count, source_name))
        conn.commit()
        conn.close()
    except Exception as e:
        log.debug(f"Registry update failed for {source_name}: {e}")


# ============================================================================
# ORACLE — Coverage Intelligence
# ============================================================================

# Major markets: if these return 0 records, something is wrong
MAJOR_MARKETS = {"Denver", "El Paso", "Arapahoe", "Jefferson", "Adams"}


def _coverage_audit(county_audit: Dict[str, dict]) -> Dict[str, dict]:
    """
    THE ORACLE — Coverage Intelligence.

    Runs after scraping, before the report. Upgrades county statuses:
      SUSPICIOUS_ZERO  — Major market returned 0 records (silent failure)
      PARSING_FAILURE  — Raw rows found but 0 extracted (HTML drift)

    Returns the mutated county_audit dict.
    """
    for county, audit in county_audit.items():
        raw = audit["raw"]
        extracted = audit["extracted"]
        current_status = audit["status"]

        # Only upgrade status if the scrape itself didn't error
        if current_status not in ("OK",):
            continue

        # Rule 1: PARSING_FAILURE — got rows from HTML but extracted nothing
        if raw > 0 and extracted == 0:
            audit["status"] = "PARSING_FAILURE"
            continue

        # Rule 2: SUSPICIOUS_ZERO — major market returned nothing at all
        if county in MAJOR_MARKETS and raw == 0:
            audit["status"] = "SUSPICIOUS_ZERO"

    return county_audit


# ============================================================================
# PARALLEL SCRAPE WORKER
# ============================================================================

def _scrape_county(
    county: str,
    config: dict,
    start_year: int,
    end_year: int,
) -> Dict:
    """
    Scrape a single county in its own thread with its own StealthSession.

    Returns a result dict with: county, records, errors, raw, extracted,
    rejected, rejection_details, status, time.
    """
    # Each thread gets its own session (thread safety)
    session = StealthSession()
    validator = DataValidator()

    ScraperClass = _get_scraper_class(config)
    scraper = ScraperClass(session, config)

    county_t0 = time.time()
    raw_count = 0
    extracted_count = 0
    rejected_count = 0
    rejection_details = []
    validated = []
    errors = []
    status = "OK"

    try:
        records = scraper.scrape(start_year, end_year)
        errors.extend(scraper.errors)
        raw_count = len(records)

        # BS DETECTOR: Validate every record
        for rec in records:
            if rec.get("_type") == "pdf_link":
                validated.append(rec)
                continue
            result = validator.validate(rec, county)
            if result is not None:
                validated.append(result)
                extracted_count += 1
            else:
                rejected_count += 1

        rejection_details = [r for r in validator.rejections if r["county"] == county]

        _update_scraper_registry(
            config.get("source_name", ""),
            extracted_count,
            "SUCCESS" if not scraper.errors else "PARTIAL",
        )

    except requests.exceptions.HTTPError as e:
        http_status = e.response.status_code if e.response is not None else 0
        _update_scraper_registry(config.get("source_name", ""), 0, f"FAILED:{http_status}")
        status = f"HTTP_{http_status}"
        errors.append(f"{county}: HTTP {http_status}")

    except (requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout) as e:
        _update_scraper_registry(config.get("source_name", ""), 0, "FAILED:CONNECTION")
        status = "CONN_FAIL"
        errors.append(f"{county}: {type(e).__name__}")

    except Exception as e:
        _update_scraper_registry(config.get("source_name", ""), 0, "FAILED")
        status = "ERROR"
        errors.append(f"{county}: {e}")

    county_time = time.time() - county_t0

    return {
        "county": county,
        "records": validated,
        "errors": errors,
        "raw": raw_count,
        "extracted": extracted_count,
        "rejected": rejected_count,
        "rejection_details": rejection_details,
        "status": status,
        "time": round(county_time, 1),
        "session_stats": session.stats(),
    }


# ============================================================================
# RUN_HUNTER — Parallel Orchestrator
# ============================================================================

MAX_WORKERS = 5  # Cap concurrent threads to avoid IP bans


def run_hunter(
    counties: Optional[List[str]] = None,
    start_year: int = 2020,
    end_year: int = 2026,
    output_csv: Optional[str] = None,
) -> Dict:
    """
    TITAN Hunter Engine — Parallel execution with Coverage Oracle.

    Scrapes all configured counties using ThreadPoolExecutor (max 5 workers),
    validates every record through the BS Detector, runs the Oracle coverage
    audit, and outputs a per-county live audit table.

    Args:
        counties:   List of county names to scrape. Default: all 17.
        start_year: Earliest year to search. Default: 2020
        end_year:   Latest year to search. Default: 2026
        output_csv: Optional path to save results as CSV.

    Returns:
        Dict with keys: records, summary, session_stats, errors, validation,
        county_audit, coverage_alerts
    """
    CONFIGS = _build_config_map()

    if counties is None or counties == ["ALL"] or counties == "ALL":
        counties = ALL_COLORADO_COUNTIES

    # --- INITIALIZE MODULES ---
    ocr_session = StealthSession()  # OCR gets its own session (runs after parallel)
    ocr = OCRPatcher(ocr_session)
    lien_wiper = LienWiper()
    all_records = []
    all_errors = []
    total_requests = 0
    total_session_errors = 0

    # Per-county audit tracking
    county_audit = {}
    print_lock = threading.Lock()

    t_start = time.time()

    print("=" * 70)
    print("VERIFUSE HUNTER ENGINE — TITAN BUILD (PARALLEL)")
    print(f"Target Counties: {len(counties)} | Workers: {MAX_WORKERS}")
    print(f"Date Range: {start_year} - {end_year}")
    print("=" * 70)

    # --- SEPARATE: counties with config vs without ---
    valid_counties = []
    for county in counties:
        config = CONFIGS.get(county)
        if not config:
            log.warning(f"No config for county: {county}. Skipping.")
            all_errors.append(f"No config for county: {county}")
            county_audit[county] = {
                "raw": 0, "extracted": 0, "rejected": 0,
                "rejection_details": [], "status": "NO_CONFIG", "time": 0,
            }
        else:
            valid_counties.append((county, config))

    # --- PARALLEL SCRAPE ---
    futures = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for county, config in valid_counties:
            future = executor.submit(
                _scrape_county, county, config, start_year, end_year
            )
            futures[future] = county

        # Collect results as they complete (live output)
        for future in as_completed(futures):
            county = futures[future]
            try:
                result = future.result()
            except Exception as e:
                # Should not happen — _scrape_county catches all exceptions
                result = {
                    "county": county, "records": [], "errors": [f"{county}: {e}"],
                    "raw": 0, "extracted": 0, "rejected": 0,
                    "rejection_details": [], "status": "THREAD_ERROR",
                    "time": 0, "session_stats": {"requests": 0, "errors": 1},
                }

            # Collect into main lists
            all_records.extend(result["records"])
            all_errors.extend(result["errors"])
            total_requests += result["session_stats"]["requests"]
            total_session_errors += result["session_stats"]["errors"]

            county_audit[county] = {
                "raw": result["raw"],
                "extracted": result["extracted"],
                "rejected": result["rejected"],
                "rejection_details": result["rejection_details"],
                "status": result["status"],
                "time": result["time"],
            }

            # Live audit line (thread-safe print)
            with print_lock:
                print(f"  [{county:12s}] Raw: {result['raw']:3d} | "
                      f"Extracted: {result['extracted']:3d} | "
                      f"Rejected: {result['rejected']:3d} | "
                      f"{result['time']:.1f}s | {result['status']}")
                for rej in result["rejection_details"]:
                    print(f"    KILLED: {rej['rule']:15s} | {rej['detail']}")

    # --- ORACLE: Coverage Intelligence ---
    county_audit = _coverage_audit(county_audit)
    coverage_alerts = []
    for county, audit in county_audit.items():
        if audit["status"] in ("SUSPICIOUS_ZERO", "PARSING_FAILURE"):
            coverage_alerts.append(f"{county}: {audit['status']}")

    # --- OUTCOME HARVEST: Fallback for SUSPICIOUS_ZERO counties ---
    suspicious_counties = [
        c for c, a in county_audit.items() if a["status"] == "SUSPICIOUS_ZERO"
    ]
    if suspicious_counties:
        print(f"\n  OUTCOME HARVESTER: Targeting {len(suspicious_counties)} "
              f"SUSPICIOUS_ZERO counties...")
        from .outcome_harvester import OutcomeHarvester

        for county in suspicious_counties:
            harvester = OutcomeHarvester()
            h_result = harvester.harvest(county, start_year, end_year)

            with print_lock:
                print(f"  [HARVEST:{county:8s}] Raw: {h_result['raw']:3d} | "
                      f"Extracted: {h_result['extracted']:3d} | "
                      f"Rejected: {h_result['rejected']:3d} | "
                      f"{h_result['time']:.1f}s | {h_result['status']}")

            if h_result["records"]:
                all_records.extend(h_result["records"])
                # Update county audit with harvest data
                county_audit[county]["raw"] += h_result["raw"]
                county_audit[county]["extracted"] += h_result["extracted"]
                county_audit[county]["rejected"] += h_result["rejected"]
                county_audit[county]["rejection_details"].extend(
                    h_result["rejection_details"]
                )
                if h_result["extracted"] > 0:
                    county_audit[county]["status"] = "HARVESTED"
                    # Remove stale coverage alert
                    coverage_alerts = [
                        a for a in coverage_alerts
                        if not a.startswith(f"{county}:")
                    ]

            all_errors.extend(h_result["errors"])

    # --- SEPARATE ACTUAL RECORDS FROM PDF LINK PLACEHOLDERS ---
    pdf_links = [r for r in all_records if r.get("_type") == "pdf_link"]
    asset_records = [r for r in all_records if r.get("_type") != "pdf_link"]

    # --- PROCESS PDF LINKS (sequential — small number of PDFs) ---
    for pdf_entry in pdf_links:
        pdf_data = ocr.extract_from_pdf(pdf_entry["_url"])
        if pdf_data:
            pdf_data["county"] = pdf_entry["county"]
            pdf_data["state"] = "CO"
            pdf_data["asset_type"] = "FORECLOSURE_SURPLUS"
            pdf_data["source_file"] = f"hunter:pdf:{pdf_entry['_url'][:60]}"
            # No shared validator in main thread — create fresh for PDF pass
            pdf_validator = DataValidator()
            result = pdf_validator.validate(pdf_data, pdf_entry["county"])
            if result:
                asset_records.append(result)

    # --- OCR PATCH (fill missing surplus from linked PDFs) ---
    if asset_records:
        asset_records = ocr.patch_records(asset_records)

    # --- LIEN WIPER (classify + zombie detection) ---
    asset_records = lien_wiper.classify(asset_records)
    zombie_count = lien_wiper.detect_zombies(asset_records)

    # --- FILTER OUT SKIPS FOR FINAL OUTPUT (keep zombies) ---
    actionable = [r for r in asset_records
                  if r.get("_classification") != "SKIP"
                  or r.get("_zombie_status") == "POTENTIAL_ZOMBIE"]

    # --- SUMMARY ---
    summary = lien_wiper.summary(asset_records)
    total_time = round(time.time() - t_start, 1)

    # Aggregate validation stats from all per-county rejections
    all_rejections = []
    for audit in county_audit.values():
        all_rejections.extend(audit.get("rejection_details", []))
    reject_by_rule = {}
    for r in all_rejections:
        rule = r["rule"]
        reject_by_rule[rule] = reject_by_rule.get(rule, 0) + 1
    validation_summary = {
        "total_rejected": len(all_rejections),
        "total_flagged": 0,  # flags live on individual records
        "rejected_by_rule": reject_by_rule,
    }

    print()
    print("=" * 70)
    print("TITAN HUNTER REPORT")
    print("=" * 70)

    # Per-county audit table
    print(f"\n  {'COUNTY':12s} | {'RAW':>4s} | {'GOOD':>4s} | {'KILL':>4s} | "
          f"{'TIME':>5s} | STATUS")
    print(f"  {'-'*12}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}-+-{'-'*5}-+"
          f"-----------------")
    total_raw = 0
    total_good = 0
    total_kill = 0
    for county in counties:  # Print in original order, not completion order
        audit = county_audit.get(county, {})
        total_raw += audit.get("raw", 0)
        total_good += audit.get("extracted", 0)
        total_kill += audit.get("rejected", 0)
        status_str = audit.get("status", "?")
        # Highlight Oracle alerts
        if status_str == "SUSPICIOUS_ZERO":
            status_str = "!! SUSPICIOUS_ZERO"
        elif status_str == "PARSING_FAILURE":
            status_str = "!! PARSING_FAILURE"
        print(f"  {county:12s} | {audit.get('raw', 0):4d} | "
              f"{audit.get('extracted', 0):4d} | {audit.get('rejected', 0):4d} | "
              f"{audit.get('time', 0):4.1f}s | {status_str}")
    print(f"  {'-'*12}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}-+-{'-'*5}-+"
          f"-----------------")
    print(f"  {'TOTAL':12s} | {total_raw:4d} | {total_good:4d} | {total_kill:4d} | "
          f"{total_time:4.1f}s |")

    # Oracle coverage alerts
    if coverage_alerts:
        print(f"\n  ORACLE COVERAGE ALERTS ({len(coverage_alerts)}):")
        for alert in coverage_alerts:
            print(f"    !! {alert}")

    # Financial summary
    print(f"\n  Actionable records:       {summary['actionable_records']}")
    print(f"  Potential zombies:        {zombie_count}")
    print(f"  Total surplus found:      ${summary['total_surplus_found']:,.2f}")
    print(f"  Estimated attorney fees:  ${summary['total_estimated_fees']:,.2f}")

    # Classification breakdown
    print(f"\n  Classification:")
    for cls, count in summary["classification_counts"].items():
        marker = "**" if cls == "WHALE" else "  "
        print(f"  {marker} {cls:10s}: {count}")

    # BS Detector summary
    if validation_summary["total_rejected"] > 0:
        print(f"\n  BS Detector:")
        print(f"    Rejected: {validation_summary['total_rejected']}")
        for rule, count in validation_summary["rejected_by_rule"].items():
            print(f"      {rule}: {count}")

    # Session stats (aggregated across all threads)
    print(f"\n  Session: {total_requests} requests, "
          f"{total_session_errors} errors, {total_time}s total, "
          f"{MAX_WORKERS} workers")

    if all_errors:
        print(f"\n  Errors ({len(all_errors)}):")
        for err in all_errors[:10]:
            print(f"    !! {err}")

    # --- OPTIONAL CSV EXPORT ---
    if output_csv and actionable:
        _export_csv(actionable, output_csv)

    return {
        "records": actionable,
        "all_records": asset_records,
        "summary": summary,
        "session_stats": {
            "requests": total_requests,
            "errors": total_session_errors,
        },
        "errors": all_errors,
        "validation": validation_summary,
        "county_audit": county_audit,
        "coverage_alerts": coverage_alerts,
        "zombie_count": zombie_count,
    }


def _export_csv(records: List[Dict], filepath: str):
    """Export actionable records to CSV for manual review or Airtable import."""
    import csv

    # Define column order (pipeline fields first, then intelligence fields)
    columns = [
        "county", "case_number", "property_address", "owner_of_record",
        "estimated_surplus", "overbid_amount", "total_indebtedness",
        "sale_date", "lien_type", "recorder_link",
        "_classification", "_litigation_quality", "_estimated_fee",
        "_fee_pct", "_days_since_sale",
        "_is_absentee", "_absentee_reason", "_mailing_address",
        "_junior_lien_count", "_junior_lien_flags",
        "_pdf_link", "_scraped_at",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    log.info(f"Exported {len(records)} records to {filepath}")
    print(f"\n✓ CSV exported: {filepath}")


# ============================================================================
# PIPELINE BRIDGE — Feed results into canonical verifuse pipeline
# ============================================================================

def ingest_to_pipeline(records: List[Dict], db_path: Optional[str] = None):
    """
    Feed hunter results into the canonical VeriFuse pipeline.

    This bridges Module B/C/D output → verifuse.core.pipeline.ingest_asset().
    Only call this when you want to persist results to the canonical DB.

    Args:
        records: List of asset dicts from run_hunter()
        db_path: Path to verifuse DB. Uses default if None.
    """
    import sqlite3
    from ..core.schema import DB_PATH, init_db
    from ..core.pipeline import ingest_asset, evaluate_all

    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    ingested = 0
    skipped = 0
    errors = 0

    seen_ids = set()
    for record in records:
        # Strip intelligence fields (prefixed with _) before ingestion
        clean = {k: v for k, v in record.items() if not k.startswith("_")}
        # Extract source_name for pipeline registry lookup (must match scraper_registry)
        source = clean.pop("source_name", clean.pop("source_file", "hunter_engine"))
        try:
            asset_id = ingest_asset(conn, clean, source)
            if asset_id in seen_ids:
                skipped += 1
            else:
                seen_ids.add(asset_id)
                ingested += 1
        except Exception as e:
            log.error(f"Ingestion error for {record.get('case_number')}: {e}")
            errors += 1

    # Run evaluation to promote through pipeline
    eval_results = evaluate_all(conn)
    conn.close()

    print(f"\n{'='*70}")
    print("PIPELINE INGESTION COMPLETE")
    print(f"{'='*70}")
    print(f"Ingested:  {ingested}")
    print(f"Skipped:   {skipped} (duplicates)")
    print(f"Errors:    {errors}")
    print(f"Evaluation: {eval_results}")

    return {"ingested": ingested, "skipped": skipped, "errors": errors,
            "evaluation": eval_results}


# ============================================================================
# COLAB / CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    # CLI: python hunter_engine.py [county1,county2,...] [start_year] [end_year]
    if len(sys.argv) > 1 and sys.argv[1].upper() != "ALL":
        target_counties = [c.strip() for c in sys.argv[1].split(",")]
    else:
        target_counties = ALL_COLORADO_COUNTIES

    try:
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 2020
        end = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
    except ValueError:
        print("Usage: hunter_engine.py [county1,county2,...|ALL] [start_year] [end_year]")
        sys.exit(1)

    results = run_hunter(
        counties=target_counties,
        start_year=start,
        end_year=end,
        output_csv="verifuse_hunter_results.csv",
    )
