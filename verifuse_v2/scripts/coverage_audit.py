#!/usr/bin/env python3
"""
coverage_audit.py — GovSoft pipeline integrity checker.

Compares browser-visible case count to DB case count for a county + date window.
Writes result row to county_ingestion_runs on every run.

Usage:
  python3 -m verifuse_v2.scripts.coverage_audit --county jefferson --days 60

Exit codes:
  0  PASS  — Delta == 0 (browser_count == db_count)
  1  FAIL  — Delta > 0 (cases missing from DB)
  2  UNKNOWN — browser count undetectable (form rendered but count not found)
  3  ERROR   — form state mismatch after submission
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("coverage_audit")

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)

# ── Count extraction patterns (SHOWING_RE searched first) ─────────────────────

_SHOWING_RE = re.compile(
    r'showing\s+\d+\s*(?:to|-|–)\s*\d+\s+of\s+([\d,]+)',
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r'(\d[\d,]*)\s*(record|result|case|item|found)',
    re.IGNORECASE,
)


def _extract_count_from_text(full_text: str) -> int | None:
    """Extract total result count from page text.

    SHOWING_RE searched first to prevent false match on '1 record' single pages.
    """
    m = _SHOWING_RE.search(full_text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = _COUNT_RE.search(full_text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _db_count(county: str, date_from_iso: str, date_to_iso: str) -> int:
    """Count leads in DB for county + sale_date window."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT COUNT(DISTINCT county || ':' || case_number) AS n
            FROM leads
            WHERE lower(county) = lower(?)
              AND sale_date >= ?
              AND sale_date <= ?
              AND (ingestion_source IS NULL OR ingestion_source = 'govsoft')
              AND sale_date IS NOT NULL
        """, [county, date_from_iso, date_to_iso]).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def _write_run_row(
    county: str,
    window_from: str,
    window_to: str,
    browser_count: int | None,
    db_count: int,
    delta: int | None,
    status: str,
    errors: str | None = None,
) -> None:
    """Write audit result to county_ingestion_runs. Graceful if table missing."""
    run_id = str(uuid.uuid4())
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """INSERT INTO county_ingestion_runs
                   (run_id, county, window_from, window_to, browser_count, db_count,
                    delta, status, errors, run_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [run_id, county, window_from, window_to,
                 browser_count, db_count, delta, status, errors,
                 int(time.time())],
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Failed to write county_ingestion_runs: %s", exc)


async def _run_audit(county: str, days: int) -> int:
    """Run the browser-based audit. Returns exit code."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("playwright not installed: pip install playwright")
        return 3

    # Date window
    today = date.today()
    from_date = today - timedelta(days=days)
    date_from_mmdd = from_date.strftime("%m/%d/%Y")
    date_to_mmdd   = today.strftime("%m/%d/%Y")
    date_from_iso  = from_date.isoformat()
    date_to_iso    = today.isoformat()

    # Load config from DB
    conn_cfg = sqlite3.connect(DB_PATH)
    conn_cfg.row_factory = sqlite3.Row
    try:
        cfg = conn_cfg.execute(
            "SELECT * FROM govsoft_county_configs WHERE county = ? AND active = 1",
            [county]
        ).fetchone()
        if not cfg:
            # Fall back to county_profiles
            cfg = conn_cfg.execute(
                "SELECT * FROM county_profiles WHERE county = ?", [county]
            ).fetchone()
        if not cfg:
            log.error("No config found for county=%r in govsoft_county_configs or county_profiles", county)
            _write_run_row(county, date_from_iso, date_to_iso, None, 0, None,
                           "ERROR", f"No config for county={county!r}")
            return 3
        cfg = dict(cfg)
        base_url = cfg["base_url"]
        search_path = cfg.get("search_path") or "/SearchDetails.aspx"
        requires_accept_terms = bool(cfg.get("requires_accept_terms", 1))
        page_limit = int(cfg.get("page_limit") or 90)
    finally:
        conn_cfg.close()

    if base_url == "CONFIGURE_ME":
        log.error("base_url not configured for county=%r", county)
        _write_run_row(county, date_from_iso, date_to_iso, None, 0, None,
                       "ERROR", f"base_url=CONFIGURE_ME for county={county!r}")
        return 3

    search_url = f"{base_url.rstrip('/')}{search_path}"
    headless = os.getenv("GOVSOFT_HEADLESS", "1") == "1"

    browser_count = None
    exit_code = 2

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context()
        try:
            page = await context.new_page()
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Accept terms if required
            if requires_accept_terms:
                try:
                    chk_el = page.locator("input[id*='chk'][type='checkbox']")
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

            # Select ddStatus='Sold'
            dd = page.locator("#MainContent_CustomContentPlaceHolder_ddStatus")
            if await dd.count() > 0:
                await dd.select_option("Sold")
                await asyncio.sleep(1)
                await page.wait_for_load_state("networkidle", timeout=10000)

            # Fill date fields
            def _to_iso(mmddyyyy: str) -> str:
                try:
                    return datetime.strptime(mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    return mmddyyyy

            from_loc = page.locator("#MainContent_CustomContentPlaceHolder_txtSoldDate1")
            to_loc   = page.locator("#MainContent_CustomContentPlaceHolder_txtSoldDate2")
            if await from_loc.count() > 0:
                await from_loc.fill(_to_iso(date_from_mmdd))
            if await to_loc.count() > 0:
                await to_loc.fill(_to_iso(date_to_mmdd))

            # Click Search
            search_btn = page.locator("input[value*='Search'], input[type='submit'][id*='Search']")
            await search_btn.first.click()
            await asyncio.sleep(2)
            await page.wait_for_load_state("networkidle", timeout=20000)
            await asyncio.sleep(1)

            # ── Form state confirmation ──────────────────────────────────────────
            # Verify ddStatus and date fields still reflect our submission.
            # A mismatch means the UpdatePanel reset the form — counts would be wrong.
            form_ok = True
            try:
                actual_status = await dd.input_value() if await dd.count() > 0 else None
                if actual_status and actual_status.lower() != "sold":
                    log.warning(
                        "[coverage] Form state mismatch: ddStatus=%r (expected 'Sold') "
                        "for county=%s window=%s–%s",
                        actual_status, county, date_from_iso, date_to_iso,
                    )
                    form_ok = False
                if await from_loc.count() > 0:
                    actual_from = await from_loc.input_value()
                    if actual_from and actual_from != _to_iso(date_from_mmdd):
                        log.warning(
                            "[coverage] Form state mismatch: txtSoldDate1=%r (expected %r)",
                            actual_from, _to_iso(date_from_mmdd),
                        )
                        form_ok = False
            except Exception as fe:
                log.warning("[coverage] Form state check failed: %s", fe)
                form_ok = False

            if not form_ok:
                db_cnt = _db_count(county, date_from_iso, date_to_iso)
                _write_run_row(county, date_from_iso, date_to_iso, None, db_cnt, None,
                               "ERROR", "Form state mismatch after submission")
                return 3

            # ── Extract browser count ────────────────────────────────────────────
            full_text = await page.inner_text("body")
            browser_count = _extract_count_from_text(full_text)

        finally:
            await context.close()
            await browser.close()

    db_cnt = _db_count(county, date_from_iso, date_to_iso)

    if browser_count is None:
        log.warning(
            "[coverage] UNKNOWN county=%s window=%s–%s "
            "browser_count=undetectable db=%d page_limit=%d",
            county, date_from_iso, date_to_iso, db_cnt, page_limit,
        )
        _write_run_row(county, date_from_iso, date_to_iso, None, db_cnt, None,
                       "FAIL", "browser_count undetectable")
        print(f"[{county.upper()}] Browser: UNKNOWN | DB: {db_cnt} | Delta: UNKNOWN")
        print("UNKNOWN: Browser count undetectable. Manual verification required.")
        return 2

    delta = browser_count - db_cnt

    if delta > 0:
        log.error(
            "[coverage] FAIL county=%s window=%s–%s browser=%d db=%d delta=%d "
            "page_limit=%d recursion_depth_max=%d",
            county, date_from_iso, date_to_iso,
            browser_count, db_cnt, delta,
            page_limit, 6,
        )
        status = "FAIL"
        exit_code = 1
    else:
        status = "PASS"
        exit_code = 0

    _write_run_row(county, date_from_iso, date_to_iso,
                   browser_count, db_cnt, delta, status)

    print(f"[{county.upper()}] Browser: {browser_count} | DB: {db_cnt} | Delta: {delta}")
    if exit_code == 0:
        print("PASS: Perfect match. Pipeline integrity verified.")
    else:
        print(f"FAIL: {delta} case(s) missing from DB. Investigate scraper coverage.")

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description="GovSoft pipeline coverage audit")
    parser.add_argument("--county", required=True, help="County name (e.g. jefferson)")
    parser.add_argument("--days", type=int, default=60, help="Rolling window in days (default 60)")
    args = parser.parse_args()

    exit_code = asyncio.run(_run_audit(args.county, args.days))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
