"""
VeriFuse vNEXT — GovSoft Playwright Engine
===========================================
Playwright-based scraper for ASP.NET WebForms public trustee platforms
served by GovSoft.us SaaS. Each county is a separate deployment with its
own domain — URLs are read exclusively from county_profiles.base_url (env-
seeded), never hardcoded here.

Platform details:
  - SearchDetails.aspx: date-range search form with __VIEWSTATE pagination
  - Left-nav tabs: Sale Info / Lienor Redemption / View Documents
  - Doc types handled: BID, COP, NED, PTD, OAS, CERTQH, OBCLAIM, OBCKREQ

Selector constants are config-driven with fuzzy fallbacks.
CAPTCHA handling is CLI + sentinel file only (no REST). Timeout = 20 min.
On timeout: mark CAPTCHA_BLOCKED, fail-closed, continue.

Usage (via ingest_runner.py):
    python3 -m verifuse_v2.ingest.ingest_runner --single-case \
        --county jefferson --case-number J2400300
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

# ── Environment / constants ──────────────────────────────────────────────────

HEADLESS = os.getenv("GOVSOFT_HEADLESS", "1") == "1"
HITL_TIMEOUT_SECS = 1200  # 20 minutes

VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "/var/lib/verifuse/vault/govsoft"))

DB_PATH = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "verifuse_v2.db"),
)

# ── Resilient selector constants — override via county_profiles.selectors_json ──

SEL_SEARCH_BTN    = "input[value*='Search'], input[type='submit'][id*='Search']"
SEL_SHOW_ALL_BTN  = "input[id*='btnShowAll'], input[value*='Show All']"
SEL_RESULTS_TABLE = "table[id*='gv'], table[id*='SearchResults'], table[id*='Grid']"
SEL_DOPOSTBACK    = "a[href*='__doPostBack']"
SEL_ACCEPT_TERMS  = "input[id*='chk'][type='checkbox'], input[id*='Accept']"
# GTS Jefferson: nav tabs use NavList_NavButton_* IDs; fallbacks for other counties
SEL_NAV_TABS      = "a[id*='NavButton'], td.tab a, div.tab a, a[id*='tab'], a[id*='Tab']"
# GTS Jefferson: documents served via docviewer?fn=... relative links
SEL_DOC_LINKS     = "a[href*='docviewer'], a[href*='.pdf'], a[href*='Document'], a[href*='ViewDoc']"

# Tab label fragments used to identify which tab to click
TAB_SALE_INFO    = ("sale info", "sale information", "sale")
TAB_LIENOR       = ("lienor", "lienor redemption", "lien")
TAB_DOCS         = ("view documents", "document", "view doc", "docs")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _db_connect():
    """Open a SQLite connection with WAL + busy_timeout hardening.

    isolation_level=None (autocommit) is mandatory here so that
    _store_snapshot() INSERT calls do NOT open an implicit deferred
    transaction that would span Playwright await calls. With autocommit,
    each INSERT is committed immediately; BEGIN IMMEDIATE in
    _store_evidence_doc() then works without conflict.
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _safe_filename(raw_name: str) -> str:
    """Sanitize a filename for safe disk writes.

    Preserves the raw filename in the DB; only the disk write uses this.
    """
    base = os.path.basename(raw_name)
    return re.sub(r"[^\w.\-]", "_", base)[:120]


def _content_type_from_ext(filename: str) -> str:
    """Derive MIME type from file extension."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".tif") or lower.endswith(".tiff"):
        return "image/tiff"
    return "application/octet-stream"


def _doc_family_from_filename(filename: str) -> str:
    """Classify a GovSoft document filename into the doc_family CHECK enum.

    Heuristic order matters — more specific matches first.
    CERTQH (Certificate of Qualified Holder) and CKREQ (check request) are
    overbid-related documents; both map to OB (closest enum value).
    """
    upper = filename.upper()
    if "OBCLAIM" in upper or "OBCKREQ" in upper or "CKREQ" in upper:
        return "OB"
    if "CERTQH" in upper:
        return "OB"  # Certificate of Qualified Holder — overbid related
    if "BID" in upper:
        return "BID"
    if "COP" in upper:
        return "COP"
    if "NED" in upper:
        return "NED"
    if "PTD" in upper:
        return "PTD"
    # Match OB as a standalone token — \b doesn't work with _ so use non-alpha lookaround
    if re.search(r"(?<![A-Z])OB(?![A-Z])", upper):
        return "OB"
    if "NOTICE" in upper:
        return "NOTICE"
    if "INVOICE" in upper:
        return "INVOICE"
    return "OTHER"


def _asset_id(county: str, case_number: str) -> str:
    return f"FORECLOSURE:CO:{county.upper()}:{case_number}"


def _now_ts() -> int:
    return int(time.time())


# ── HITL CAPTCHA sentinel ────────────────────────────────────────────────────


def _hitl_wait(county: str, case_number: str) -> bool:
    """Block until the human solves the CAPTCHA (sentinel deleted) or timeout.

    Returns True if CAPTCHA was solved, False if timed out (fail-closed).
    """
    sentinel = VAULT_ROOT / ".paused" / f"{county}_{case_number}"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    print(
        f"[HITL] CAPTCHA detected at {county}/{case_number}. "
        f"Solve it in the browser, then delete: {sentinel}",
        file=sys.stderr,
    )
    deadline = time.time() + HITL_TIMEOUT_SECS
    while sentinel.exists():
        if time.time() > deadline:
            sentinel.unlink(missing_ok=True)
            log.warning("[HITL] Timeout waiting for CAPTCHA at %s/%s", county, case_number)
            return False
        time.sleep(5)
    return True


def _mark_captcha_blocked(conn, asset_id_val: str, county: str) -> None:
    """Write CAPTCHA_BLOCKED to both asset_registry and extraction_events.

    Uses upsert pattern — rows are created if they don't exist yet (entry-mode
    CAPTCHA fires before any page navigation, so no rows exist). Both writes
    are wrapped in a single BEGIN IMMEDIATE for atomicity. The UI will see
    processing_status='CAPTCHA_BLOCKED' on both tables immediately after.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        # asset_registry — insert or update processing_status
        conn.execute(
            """INSERT INTO asset_registry
                   (asset_id, engine_type, source_table, source_id, county, processing_status)
               VALUES (?, 'FORECLOSURE', 'leads', ?, ?, 'CAPTCHA_BLOCKED')
               ON CONFLICT(asset_id) DO UPDATE SET
                   processing_status = 'CAPTCHA_BLOCKED'
            """,
            [asset_id_val, asset_id_val, county],
        )
        # extraction_events — update existing row, insert new one if none existed
        updated = conn.execute(
            "UPDATE extraction_events SET status='CAPTCHA_BLOCKED', notes='HITL timeout' "
            "WHERE asset_id=?",
            [asset_id_val],
        ).rowcount
        if updated == 0:
            conn.execute(
                """INSERT INTO extraction_events
                   (id, asset_id, run_ts, status, notes)
                   VALUES (?, ?, ?, 'CAPTCHA_BLOCKED', 'HITL timeout')
                """,
                [str(uuid4()), asset_id_val, _now_ts()],
            )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


# ── HTML snapshot storage ────────────────────────────────────────────────────


def _store_snapshot(
    conn, asset_id_val: str, snapshot_type: str, html: str,
    source_url: str | None = None,
) -> None:
    """Gzip-compress and store an HTML snapshot (INSERT OR IGNORE on sha256 UNIQUE).

    source_url — the page.url at capture time (Gate 4 first-class URL capture).
    """
    raw_bytes = html.encode("utf-8", errors="replace")
    gz_bytes = gzip.compress(raw_bytes)
    sha = _sha256_bytes(raw_bytes)
    conn.execute(
        """INSERT OR IGNORE INTO html_snapshots
           (id, asset_id, snapshot_type, raw_html_gzip, html_sha256, retrieved_ts, source_url)
           VALUES (?,?,?,?,?,?,?)
        """,
        [str(uuid4()), asset_id_val, snapshot_type, gz_bytes, sha, _now_ts(), source_url],
    )


# ── Evidence document storage ────────────────────────────────────────────────


def _store_evidence_doc(
    conn,
    asset_id_val: str,
    county: str,
    case_number: str,
    raw_filename: str,
    doc_type: str,
    file_bytes: bytes,
    source_url: str | None = None,
) -> str | None:
    """Write document bytes to vault and insert into evidence_documents.

    Returns the evidence_doc id if inserted, None if already existed.
    Uses BEGIN IMMEDIATE to prevent concurrent double-spend.

    Data Integrity Invariant (Gate 4): HTML masquerading as a document is rejected.
    Legitimate binary formats (PDF, TIFF, DOC, etc.) from any county are allowed.
    Rejection is triggered if the first 512 bytes look like HTML — not by
    requiring a specific magic byte sequence (which would break TIFF/DOC evidence).
    source_url — the download URL (docviewer endpoint) for first-class evidence.
    """
    # Gate 4 HTML rejection guard — reject HTML error pages, allow all binary formats.
    # GovSoft sometimes returns an ASP.NET HTML error page instead of the document
    # when a file is missing or the session has expired. Detecting HTML (not requiring
    # PDF magic bytes) ensures TIFF, DOC, and other valid binary evidence is preserved.
    # lstrip() handles ASP.NET error pages that begin with BOM or leading whitespace
    # before the opening '<' tag — a known GovSoft error response pattern.
    probe = file_bytes[:512].lower().lstrip()
    if probe.startswith(b"<"):
        log.error(
            "REJECTED HTML masquerading as document for %s/%s file=%s "
            "(first 64 bytes=%r) — skipping vault write",
            county, case_number, raw_filename, file_bytes[:64],
        )
        return None

    safe_name = _safe_filename(raw_filename)
    doc_family = _doc_family_from_filename(raw_filename)
    content_type = _content_type_from_ext(raw_filename)
    file_sha = _sha256_bytes(file_bytes)

    # Vault path
    dest_dir = VAULT_ROOT / county / case_number / "original"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name

    # Write to disk only if not already there (sha256-idempotent)
    if not dest_path.exists():
        dest_path.write_bytes(file_bytes)
    elif _sha256_file(dest_path) != file_sha:
        # Same name, different content — use a disambiguated name
        dest_path = dest_dir / f"{file_sha[:8]}_{safe_name}"
        dest_path.write_bytes(file_bytes)

    doc_id = str(uuid4())
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """INSERT OR IGNORE INTO evidence_documents
               (id, asset_id, filename, doc_type, doc_family,
                file_path, file_sha256, bytes, content_type, retrieved_ts, source_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                doc_id, asset_id_val, raw_filename, doc_type, doc_family,
                str(dest_path), file_sha, len(file_bytes), content_type, _now_ts(),
                source_url,
            ],
        ).rowcount
        conn.execute("COMMIT")
        return doc_id if rows > 0 else None
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


# ── Leads upsert (Option A — site source-of-truth) ──────────────────────────


def _upsert_lead(
    conn,
    county: str,
    case_number: str,
    asset_id_val: str,
    overbid_amount: float | None,
    sale_date: str | None,
    data_grade: str,
    processing_status: str,
) -> None:
    """INSERT OR UPDATE leads row so the existing UI serves this case immediately.

    Column names are PRAGMA-verified against live schema before every run
    (done at engine startup in GovSoftEngine.__init__). This function uses
    only columns confirmed to exist: county, case_number, overbid_amount,
    sale_date, data_grade, processing_status, ingestion_source.
    """
    conn.execute(
        """INSERT INTO leads
               (id, county, case_number, overbid_amount, sale_date,
                data_grade, processing_status, ingestion_source)
           VALUES (?,?,?,?,?,?,?,'govsoft')
           ON CONFLICT(county, case_number) DO UPDATE SET
               data_grade      = excluded.data_grade,
               processing_status = excluded.processing_status,
               overbid_amount  = COALESCE(excluded.overbid_amount, leads.overbid_amount),
               sale_date       = COALESCE(excluded.sale_date, leads.sale_date),
               ingestion_source = 'govsoft'
        """,
        [
            str(uuid4()), county, case_number,
            overbid_amount, sale_date, data_grade, processing_status,
        ],
    )


# ── Core GovSoft engine ──────────────────────────────────────────────────────


class GovSoftEngine:
    """Playwright-based scraper for a single GovSoft county instance.

    Instantiate once per county. Each run() call uses an isolated browser
    context so cookies/sessions don't leak between counties.
    """

    def __init__(self, county: str, db_conn=None):
        self.county = county
        self._conn = db_conn or _db_connect()
        self._selectors: dict = {}

        # Load county profile from DB
        row = self._conn.execute(
            "SELECT * FROM county_profiles WHERE county=?", [county]
        ).fetchone()
        if not row:
            raise ValueError(f"No county_profiles row for county={county!r}")

        self.base_url: str = row["base_url"]
        self.search_path: str = row["search_path"]
        self.detail_path: str = row["detail_path"]
        self.captcha_mode: str = row["captcha_mode"]
        self.requires_accept_terms: bool = bool(row["requires_accept_terms"])

        if row["selectors_json"]:
            try:
                self._selectors = json.loads(row["selectors_json"])
            except (json.JSONDecodeError, TypeError):
                log.warning("Could not parse selectors_json for county=%s", county)

        # PRAGMA-verify leads columns used in upsert
        self._leads_cols = {
            r[1] for r in
            self._conn.execute("PRAGMA table_info(leads)").fetchall()
        }
        required = {"county", "case_number", "data_grade", "processing_status"}
        missing = required - self._leads_cols
        if missing:
            raise RuntimeError(f"leads table missing required columns: {missing}")

    def _sel(self, key: str, default: str) -> str:
        """Return per-county selector override or fall back to default."""
        return self._selectors.get(key, default)

    async def _capture_case_detail_on_page(
        self, page, case_number: str, asset_id_val: str
    ) -> None:
        """Capture CASE_DETAIL / tabs / documents given a page already on the detail view.

        Called from both run_single_case() (after case link click) and from
        run_date_window() (after clicking a case row within the existing session).
        Writes html_snapshots, evidence_documents, extraction_events, asset_registry,
        and leads rows. All DB writes are idempotent (INSERT OR IGNORE / upsert).
        """
        # CASE_DETAIL snapshot
        _store_snapshot(
            self._conn, asset_id_val, "CASE_DETAIL", await page.content(),
            source_url=page.url,
        )

        # Tab snapshots
        tab_snapshots = {
            TAB_SALE_INFO: "SALE_INFO",
            TAB_LIENOR:    "LIENOR_TAB",
            TAB_DOCS:      "DOCS_TAB",
        }
        docs_html = ""
        for tab_labels, snap_type in tab_snapshots.items():
            try:
                tabs = page.locator(self._sel("nav_tabs", SEL_NAV_TABS))
                count = await tabs.count()
                for i in range(count):
                    tab = tabs.nth(i)
                    txt = (await tab.inner_text()).strip().lower()
                    if any(lbl in txt for lbl in tab_labels):
                        await tab.click()
                        await asyncio.sleep(2)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        html = await page.content()
                        _store_snapshot(
                            self._conn, asset_id_val, snap_type, html,
                            source_url=page.url,
                        )
                        if snap_type == "DOCS_TAB":
                            docs_html = html
                        break
            except Exception as exc:
                log.warning("Tab %s failed for %s/%s: %s",
                            snap_type, self.county, case_number, exc)

        # Document downloads
        if docs_html:
            doc_locators = await page.locator(
                self._sel("doc_links", SEL_DOC_LINKS)
            ).all()
            seen_hrefs: set = set()
            docs_to_download: list = []
            for link in doc_locators:
                try:
                    href = await link.get_attribute("href")
                    raw_name = (await link.inner_text()).strip()
                    if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                        continue
                    if href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)
                    docs_to_download.append({"href": href, "raw_name": raw_name or os.path.basename(href)})
                except Exception:
                    continue

            for doc_info in docs_to_download:
                href = doc_info["href"]
                raw_name = doc_info["raw_name"]
                page_url_before = page.url
                try:
                    fresh_links = await page.locator(self._sel("doc_links", SEL_DOC_LINKS)).all()
                    target = None
                    for fl in fresh_links:
                        if await fl.get_attribute("href") == href:
                            target = fl
                            break
                    if target is None:
                        log.warning("Doc link not found (re-query) href=%s (%s/%s)",
                                    href, self.county, case_number)
                        continue
                    try:
                        target_handle = await target.element_handle()
                        if target_handle:
                            await page.evaluate("el => el.removeAttribute('target')", target_handle)
                    except Exception:
                        pass
                    async with page.expect_download(timeout=45000) as dl_info:
                        await target.click()
                    download = await dl_info.value
                    actual_filename = download.suggested_filename or raw_name
                    tmp_path = await download.path()
                    if tmp_path is None:
                        log.warning("Download path is None for %s (%s/%s)",
                                    actual_filename, self.county, case_number)
                        continue
                    file_bytes = Path(tmp_path).read_bytes()
                    if file_bytes:
                        _store_evidence_doc(
                            self._conn, asset_id_val, self.county, case_number,
                            actual_filename, raw_name, file_bytes,
                            source_url=download.url,
                        )
                        log.info("Downloaded %s (%d bytes) for %s/%s",
                                 actual_filename, len(file_bytes), self.county, case_number)
                except Exception as exc:
                    log.warning("Doc download failed for %s/%s href=%s: %s",
                                self.county, case_number, href, exc)
                    if page.url != page_url_before:
                        try:
                            await page.go_back(wait_until="domcontentloaded", timeout=10000)
                            await asyncio.sleep(1)
                            tabs_loc = page.locator(self._sel("nav_tabs", SEL_NAV_TABS))
                            for ti in range(await tabs_loc.count()):
                                t = tabs_loc.nth(ti)
                                # Compute text separately — await inside any() generator
                                # creates an async generator that any() cannot iterate.
                                t_txt = (await t.inner_text()).lower()
                                if any(lbl in t_txt for lbl in TAB_DOCS):
                                    await t.click()
                                    await asyncio.sleep(2)
                                    await page.wait_for_load_state("networkidle", timeout=15000)
                                    break
                        except Exception as nav_exc:
                            log.warning("DOCS_TAB recovery failed for %s/%s: %s",
                                        self.county, case_number, nav_exc)

        # Atomic final DB batch: extraction_events + asset_registry + leads
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                """INSERT OR IGNORE INTO extraction_events
                   (id, asset_id, run_ts, status) VALUES (?, ?, ?, 'PENDING')""",
                [str(uuid4()), asset_id_val, _now_ts()],
            )
            self._conn.execute(
                """INSERT INTO asset_registry
                       (asset_id, engine_type, source_table, source_id, county, processing_status)
                   VALUES (?, 'FORECLOSURE', 'leads', ?, ?, 'PENDING')
                   ON CONFLICT(asset_id) DO UPDATE SET processing_status = 'PENDING'""",
                [asset_id_val, asset_id_val, self.county],
            )
            _upsert_lead(
                self._conn, self.county, case_number, asset_id_val,
                overbid_amount=None, sale_date=None,
                data_grade="BRONZE", processing_status="PENDING",
            )
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    async def run_single_case(self, case_number: str) -> dict:
        """Scrape a single case by case number and store all evidence.

        Returns a result dict with keys: asset_id, processing_status, error.
        """
        if self.base_url == "CONFIGURE_ME":
            raise RuntimeError(
                f"county={self.county!r} base_url is not configured. "
                f"Set GOVSOFT_{self.county.upper()}_URL env var and re-run migrations."
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run: pip install 'playwright>=1.45.0' "
                "&& playwright install chromium"
            )

        asset_id_val = _asset_id(self.county, case_number)
        result = {"asset_id": asset_id_val, "processing_status": "PENDING", "error": None}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=HEADLESS)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            try:
                page = await context.new_page()
                search_url = f"{self.base_url.rstrip('/')}{self.search_path}"

                # CAPTCHA on entry
                if self.captcha_mode == "entry":
                    solved = _hitl_wait(self.county, case_number)
                    if not solved:
                        _mark_captcha_blocked(self._conn, asset_id_val, self.county)
                        result["processing_status"] = "CAPTCHA_BLOCKED"
                        return result

                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                # Brief pause to let reCAPTCHA v3 score the session before interaction
                await asyncio.sleep(3)

                # Accept terms — GovSoft Jefferson requires a two-step flow:
                #   Step 1: click the checkbox (makes the Accept Terms button visible)
                #   Step 2: click the "btnAcceptTerms" submit button (loads the search form)
                # Without step 2, the engine stays on the terms redirect page and the
                # search form (ddStatus, case number fields, etc.) is never accessible.
                if self.requires_accept_terms:
                    try:
                        # Step 1: checkbox
                        chk_el = page.locator(
                            self._sel("accept_terms", "input[id*='chk'][type='checkbox']")
                        )
                        if await chk_el.count() > 0:
                            await chk_el.first.click()
                            await asyncio.sleep(1)
                        # Step 2: Accept Terms submit button (appears after checkbox click)
                        accept_btn = page.locator(
                            "#MainContent_CustomContentPlaceHolder_btnAcceptTerms"
                        )
                        if await accept_btn.count() == 0:
                            # Fuzzy fallback for other GovSoft deployments
                            accept_btn = page.locator(
                                "input[id*='btnAccept'][type='submit'], "
                                "input[value*='Accept Terms'][type='submit']"
                            )
                        if await accept_btn.count() > 0:
                            await accept_btn.first.click()
                            await page.wait_for_load_state("networkidle", timeout=20000)
                            await asyncio.sleep(2)
                    except Exception:
                        pass

                # Select ddStatus='Sold' FIRST — the form defaults to Active/Pending
                # which excludes sold foreclosure cases. Must do this before filling the
                # case-number field to prevent the UpdatePanel AJAX from resetting the input.
                dd_status_loc = page.locator(
                    "#MainContent_CustomContentPlaceHolder_ddStatus"
                )
                if await dd_status_loc.count() > 0:
                    await dd_status_loc.select_option("Sold")
                    await asyncio.sleep(1)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    log.info(
                        "[engine] ddStatus='Sold' selected for %s single-case", self.county
                    )
                else:
                    log.warning(
                        "[engine] ddStatus dropdown not found for %s single-case "
                        "— proceeding without status filter",
                        self.county,
                    )

                # Fill case-number search field and submit
                # If reCAPTCHA blocks the specific-case search (returns 0 results),
                # fall back to btnShowAll which bypasses the token check on some deployments.
                search_succeeded = False
                try:
                    ci_sel = self._sel("case_input", "input[id*='Case'], input[name*='case']")
                    ci_el = page.locator(ci_sel)
                    if await ci_el.count() > 0:
                        await ci_el.first.fill(case_number)
                    await page.click(self._sel("search_btn", SEL_SEARCH_BTN))
                    await page.wait_for_load_state("networkidle", timeout=20000)
                    search_succeeded = True
                except Exception as exc:
                    log.warning("Search failed for %s/%s: %s", self.county, case_number, exc)
                    result["error"] = str(exc)
                    return result

                # Check if the specific-case search returned the target case link.
                # Some deployments (e.g. GTS Jefferson) have reCAPTCHA that blocks
                # specific searches; btnShowAll bypasses it and returns all cases.
                # IMPORTANT: clear the case number field before ShowAll so the server
                # does NOT apply the case-number filter (which would re-trigger reCAPTCHA).
                case_link_sel = self._sel("case_link", f"a:has-text('{case_number}')")
                if search_succeeded and await page.locator(case_link_sel).count() == 0:
                    log.info(
                        "Specific search returned no results for %s/%s; trying btnShowAll fallback",
                        self.county, case_number,
                    )
                    show_all_sel = self._sel("show_all_btn", SEL_SHOW_ALL_BTN)
                    show_all_el = page.locator(show_all_sel)
                    if await show_all_el.count() > 0:
                        # Clear all text filters before ShowAll to avoid server-side filtering
                        ci_sel = self._sel("case_input", "input[id*='Case'], input[name*='case']")
                        ci_el = page.locator(ci_sel)
                        if await ci_el.count() > 0:
                            await ci_el.first.fill("")
                        await show_all_el.first.click()
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        await asyncio.sleep(2)  # Let results render fully

                # Save SEARCH_RESULTS snapshot
                _store_snapshot(
                    self._conn, asset_id_val, "SEARCH_RESULTS", await page.content(),
                    source_url=page.url,
                )

                # CAPTCHA on detail
                if self.captcha_mode == "detail":
                    solved = _hitl_wait(self.county, case_number)
                    if not solved:
                        _mark_captcha_blocked(self._conn, asset_id_val, self.county)
                        result["processing_status"] = "CAPTCHA_BLOCKED"
                        return result

                # Click case link — look for exact match first, then any table link
                search_url_before_click = page.url
                try:
                    case_link = page.locator(
                        self._sel("case_link", f"a:has-text('{case_number}')")
                    )
                    if await case_link.count() == 0:
                        log.warning(
                            "Case link %s not found in results for %s; skipping detail capture",
                            case_number, self.county,
                        )
                        result["error"] = f"Case {case_number} not found in search results"
                        return result
                    await case_link.first.click()
                    await asyncio.sleep(2)  # Let JS navigation settle before networkidle
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception as exc:
                    log.warning("Case link click failed for %s/%s: %s",
                                self.county, case_number, exc)
                    result["error"] = str(exc)
                    return result

                # If the URL didn't change after clicking (e.g. Deeded cases on GTS), the
                # platform returned to the search results page — no case detail available.
                if page.url == search_url_before_click:
                    log.info(
                        "Case %s/%s: click did not navigate to detail page (status may be Deeded). "
                        "Saving search results snapshot and continuing with 0 documents.",
                        self.county, case_number,
                    )

                # Capture detail page: tabs, documents, DB batch (shared helper)
                await self._capture_case_detail_on_page(page, case_number, asset_id_val)

                result["processing_status"] = "PENDING"

            except Exception as exc:
                log.exception("Engine error for %s/%s: %s", self.county, case_number, exc)
                result["error"] = str(exc)
            finally:
                await context.close()
                await browser.close()

        return result

    async def run_date_window(self, date_from: str, date_to: str) -> dict:
        """Scrape all cases in a date range.

        date_from / date_to: MM/DD/YYYY strings.
        Returns {cases_processed, cases_failed}.
        """
        if self.base_url == "CONFIGURE_ME":
            raise RuntimeError(
                f"county={self.county!r} base_url is not configured. "
                f"Set GOVSOFT_{self.county.upper()}_URL env var and re-run migrations."
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. Run: pip install 'playwright>=1.45.0' "
                "&& playwright install chromium"
            )

        stats = {"cases_processed": 0, "cases_failed": 0}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
            try:
                page = await context.new_page()
                search_url = f"{self.base_url.rstrip('/')}{self.search_path}"

                if self.captcha_mode == "entry":
                    solved = _hitl_wait(self.county, "date_window")
                    if not solved:
                        log.error("CAPTCHA timeout on date-window entry for %s", self.county)
                        return stats

                await page.goto(search_url, wait_until="networkidle", timeout=30000)

                # Accept terms — same two-step flow as run_single_case().
                # Step 1: checkbox → Step 2: btnAcceptTerms submit button.
                if self.requires_accept_terms:
                    try:
                        chk_el = page.locator(
                            self._sel("accept_terms", "input[id*='chk'][type='checkbox']")
                        )
                        if await chk_el.count() > 0:
                            await chk_el.first.click()
                            await asyncio.sleep(1)
                        accept_btn = page.locator(
                            "#MainContent_CustomContentPlaceHolder_btnAcceptTerms"
                        )
                        if await accept_btn.count() == 0:
                            accept_btn = page.locator(
                                "input[id*='btnAccept'][type='submit'], "
                                "input[value*='Accept Terms'][type='submit']"
                            )
                        if await accept_btn.count() > 0:
                            await accept_btn.first.click()
                            await page.wait_for_load_state("networkidle", timeout=20000)
                            await asyncio.sleep(2)
                    except Exception:
                        pass

                # input[type="date"] requires ISO 8601 (YYYY-MM-DD) for Playwright fill().
                # Callers pass MM/DD/YYYY; convert here so the interface contract is preserved.
                def _to_iso(mmddyyyy: str) -> str:
                    try:
                        from datetime import datetime as _dt
                        return _dt.strptime(mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")
                    except ValueError:
                        return mmddyyyy  # already ISO or unrecognised — pass through unchanged

                try:
                    # Step 1: Select ddStatus='Sold' to explicitly target sold/auctioned
                    # cases. The sold date fields (txtSoldDate1/txtSoldDate2) filter by
                    # AUCTION DATE, so the status selection narrows to confirmed-sold cases
                    # within the date window. Selecting 'Sold' first, then filling date
                    # fields after networkidle, prevents UpdatePanel from clearing the dates.
                    dd_status_loc = page.locator(
                        "#MainContent_CustomContentPlaceHolder_ddStatus"
                    )
                    if await dd_status_loc.count() > 0:
                        await dd_status_loc.select_option("Sold")
                        await asyncio.sleep(1)
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        log.info("[engine] ddStatus='Sold' selected for %s", self.county)
                    else:
                        log.warning(
                            "[engine] ddStatus dropdown not found for %s — "
                            "proceeding without status filter",
                            self.county,
                        )

                    # Step 2: Fill sold-date range fields (YYYY-MM-DD via _to_iso).
                    # txtSoldDate1/txtSoldDate2 confirmed present after terms acceptance
                    # (Playwright diagnostic 2026-02-23). Filled AFTER ddStatus selection
                    # so UpdatePanel AJAX does not clear them.
                    sold_from_sel = self._sel(
                        "sold_date_from",
                        "#MainContent_CustomContentPlaceHolder_txtSoldDate1",
                    )
                    sold_to_sel = self._sel(
                        "sold_date_to",
                        "#MainContent_CustomContentPlaceHolder_txtSoldDate2",
                    )
                    from_loc = page.locator(sold_from_sel)
                    to_loc = page.locator(sold_to_sel)
                    if await from_loc.count() > 0:
                        await from_loc.fill(_to_iso(date_from))
                        log.info("[engine] txtSoldDate1 filled: %s", _to_iso(date_from))
                    else:
                        log.warning("txtSoldDate1 not found for %s", self.county)
                    if await to_loc.count() > 0:
                        await to_loc.fill(_to_iso(date_to))
                        log.info("[engine] txtSoldDate2 filled: %s", _to_iso(date_to))
                    else:
                        log.warning("txtSoldDate2 not found for %s", self.county)

                    # Step 3: Click Search — GovSoft uses ASP.NET UpdatePanel AJAX.
                    # Sleep briefly first so the UpdatePanel JS can fire the XHR,
                    # then wait for networkidle, then wait for the results table
                    # OR the search form (0 results). Avoids mid-AJAX snapshots.
                    await page.click(self._sel("search_btn", SEL_SEARCH_BTN))
                    await asyncio.sleep(2)  # Let UpdatePanel JS fire the XHR
                    await page.wait_for_load_state("networkidle", timeout=20000)
                    # Explicit wait: results table OR the search form (0 results)
                    try:
                        await page.wait_for_selector(
                            "table[id*='gvSearchResults'], "
                            "table[id*='gvSearch'], "
                            "input[id*='btnSearch']",
                            timeout=10000,
                        )
                    except Exception:
                        pass  # Either results loaded or form shown — proceed
                    await asyncio.sleep(1)
                except Exception as exc:
                    log.error("Date-range search failed for %s: %s", self.county, exc)
                    return stats

                # Paginate through results — process each case INLINE within this
                # browser session. Do NOT call run_single_case() here: post-sale
                # cases don't appear in a fresh case-number search (the default form
                # shows Active/Pending only). We click each row directly from the
                # sold-date results, capture the detail, then navigate back.
                while True:
                    _store_snapshot(
                        self._conn,
                        f"FORECLOSURE:CO:{self.county.upper()}:SEARCH",
                        "SEARCH_RESULTS",
                        await page.content(),
                        source_url=page.url,
                    )

                    # Collect (case_number, row_link_href) pairs from this results page.
                    # Collect upfront so row locators don't go stale after navigation.
                    rows = await page.locator(
                        self._sel("results_table", SEL_RESULTS_TABLE) + " tbody tr"
                    ).all()

                    case_entries: list[tuple[str, str]] = []  # (case_number, href)
                    for row in rows:
                        try:
                            cells = await row.locator("td").all_inner_texts()
                            case_number = ""
                            for cell_text in cells[:4]:
                                txt = cell_text.strip()
                                if txt and len(txt) >= 4:
                                    case_number = txt
                                    break
                            if not case_number:
                                continue
                            # Capture the row link href for direct navigation
                            link_el = row.locator("a").first
                            href = ""
                            if await link_el.count() > 0:
                                href = (await link_el.get_attribute("href")) or ""
                            case_entries.append((case_number, href))
                        except Exception:
                            continue

                    results_page_content = await page.content()

                    for case_number, _href in case_entries:
                        asset_id_val = _asset_id(self.county, case_number)
                        try:
                            # Re-locate the case link on the current page (locators are
                            # refreshed after go_back / search re-run to avoid stale refs).
                            case_link = page.locator(
                                f"a:has-text('{case_number}')"
                            ).first
                            if await case_link.count() == 0:
                                log.warning(
                                    "Case link %s not in results (stale?); skipping",
                                    case_number,
                                )
                                stats["cases_failed"] += 1
                                continue

                            url_before = page.url
                            await case_link.click()
                            await asyncio.sleep(2)
                            await page.wait_for_load_state("networkidle", timeout=20000)

                            log.info("Opened case detail: %s/%s url=%s",
                                     self.county, case_number, page.url)

                            # Capture all detail tabs, documents, and write DB rows
                            await self._capture_case_detail_on_page(
                                page, case_number, asset_id_val
                            )
                            stats["cases_processed"] += 1

                        except Exception as exc:
                            log.error("Case %s/%s failed in date-window: %s",
                                      self.county, case_number, exc)
                            stats["cases_failed"] += 1

                        # Navigate back to the results page (within same session).
                        # Use go_back() first; if that loses the results, re-run the search.
                        try:
                            await page.go_back(
                                wait_until="domcontentloaded", timeout=15000
                            )
                            await asyncio.sleep(2)
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            # Verify results table is still present
                            if await page.locator(SEL_RESULTS_TABLE).count() == 0:
                                raise Exception("Results table missing after go_back")
                        except Exception:
                            log.info(
                                "Results page lost for %s — re-running sold-date search",
                                self.county,
                            )
                            # Re-run the sold-date search to restore the results page
                            try:
                                # Re-select ddStatus='Sold' before filling date fields
                                dd_re = page.locator(
                                    "#MainContent_CustomContentPlaceHolder_ddStatus"
                                )
                                if await dd_re.count() > 0:
                                    await dd_re.select_option("Sold")
                                    await asyncio.sleep(1)
                                    await page.wait_for_load_state("networkidle", timeout=10000)
                                f_loc = page.locator(
                                    self._sel("sold_date_from",
                                              "#MainContent_CustomContentPlaceHolder_txtSoldDate1")
                                )
                                t_loc = page.locator(
                                    self._sel("sold_date_to",
                                              "#MainContent_CustomContentPlaceHolder_txtSoldDate2")
                                )
                                if await f_loc.count() > 0:
                                    await f_loc.fill(_to_iso(date_from))
                                if await t_loc.count() > 0:
                                    await t_loc.fill(_to_iso(date_to))
                                await page.click(self._sel("search_btn", SEL_SEARCH_BTN))
                                await asyncio.sleep(2)
                                await page.wait_for_load_state("networkidle", timeout=20000)
                            except Exception as re_exc:
                                log.error("Search re-run failed for %s: %s",
                                          self.county, re_exc)

                        await asyncio.sleep(random.uniform(1.0, 2.5))

                    # Next page via __doPostBack
                    next_link = page.locator(SEL_DOPOSTBACK + ":has-text('Next')")
                    if await next_link.count() == 0:
                        break
                    await next_link.first.click()
                    await asyncio.sleep(2)
                    await page.wait_for_load_state("networkidle", timeout=20000)

            finally:
                await context.close()
                await browser.close()

        return stats
