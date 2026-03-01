"""
VeriFuse — County Assessor Owner Lookup
=======================================
Pulls owner name and mailing address from public county assessor records.
Zero legal risk — all data is from public government portals.

Supported counties:
  - Jefferson  — assessor.jeffco.us
  - Arapahoe   — assessor.arapahoegov.com
  - Adams      — adcogov.org/assessor
  - Denver     — denvergov.org/property

Architecture:
  - Playwright async Chromium for JS-heavy portals
  - Searches by property address or parcel/APN
  - Stores in asset_registry.owner_mailing_address (new column from 010 migration)
  - Idempotent: only updates rows where owner_mailing_address IS NULL

Usage:
  python -m verifuse_v2.scrapers.assessor_lookup --asset-id FORECLOSURE:CO:JEFFERSON:J2400300
  python -m verifuse_v2.scrapers.assessor_lookup --county jefferson --limit 10
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)

# ── Assessor portal configs ────────────────────────────────────────────────────

ASSESSOR_CONFIGS: dict[str, dict] = {
    "jefferson": {
        "search_url": "https://assessor.jeffco.us/assessor/",
        "search_by": "address",
        "address_input_selector": "input[name='address'], input[id*='address'], input[placeholder*='ddress']",
        "search_btn_selector":    "input[type='submit'], button[type='submit']",
        "result_row_selector":    "table.result tr:not(:first-child), .search-result-row",
        "owner_selector":         "td:nth-child(2), .owner-name",
        "mailing_selector":       "td:nth-child(5), .mailing-address",
    },
    "arapahoe": {
        "search_url": "https://assessor.arapahoegov.com/",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], input[id*='Address']",
        "search_btn_selector":    "input[type='submit'], button[type='submit']",
        "result_row_selector":    "table tr:not(:first-child)",
        "owner_selector":         "td:nth-child(1)",
        "mailing_selector":       "td:nth-child(4)",
    },
    "adams": {
        "search_url": "https://www.adcogov.org/assessor",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], #searchInput",
        "search_btn_selector":    "input[type='submit'], #btnSearch",
        "result_row_selector":    ".result-row, table tr:not(:first-child)",
        "owner_selector":         ".owner, td:nth-child(2)",
        "mailing_selector":       ".mailing, td:nth-child(5)",
    },
    "denver": {
        "search_url": "https://www.denvergov.org/property/",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], input[placeholder*='ddress'], #address-search",
        "search_btn_selector":    "button[type='submit'], input[type='submit']",
        "result_row_selector":    ".property-result, table tr:not(:first-child)",
        "owner_selector":         ".owner-name, td:nth-child(2)",
        "mailing_selector":       ".mailing-address, td:nth-child(4)",
    },
}

# ── Address normalizer ─────────────────────────────────────────────────────────

def _normalize_address(address: str) -> str:
    """Strip unit/suite info and normalize for assessor search."""
    # Remove unit/apt/suite info
    address = re.sub(r"\s+(unit|apt|suite|ste|#)\s*\S+", "", address, flags=re.I)
    # Normalize whitespace
    address = " ".join(address.split())
    return address.strip()


def _clean_text(text: str) -> str:
    """Remove extra whitespace and normalize text extracted from page."""
    return " ".join(text.split()).strip()


# ── Playwright lookup ──────────────────────────────────────────────────────────

async def _lookup_owner_playwright(
    county: str,
    property_address: str,
    timeout_ms: int = 20000,
) -> Optional[dict]:
    """Search county assessor portal for owner name + mailing address.

    Returns dict with owner_name and mailing_address keys, or None if not found.
    Uses Playwright Chromium headless to handle JS-heavy portals.
    """
    config = ASSESSOR_CONFIGS.get(county.lower())
    if not config:
        log.debug("[assessor] No config for county: %s", county)
        return None

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout  # type: ignore
    except ImportError:
        log.warning("[assessor] Playwright not installed — cannot do assessor lookup")
        return None

    address_clean = _normalize_address(property_address)
    if not address_clean:
        log.debug("[assessor] Empty address for county=%s", county)
        return None

    log.info("[assessor] Looking up %s / %s", county, address_clean)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
        )
        page = await ctx.new_page()

        try:
            await page.goto(config["search_url"], timeout=timeout_ms, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)

            # Find and fill address input
            addr_input = await page.query_selector(config["address_input_selector"])
            if not addr_input:
                log.debug("[assessor] %s: address input not found", county)
                return None

            await addr_input.fill(address_clean)
            await page.wait_for_timeout(500)

            # Click search button
            btn = await page.query_selector(config["search_btn_selector"])
            if btn:
                await btn.click()
            else:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(3000)

            # Extract first result row
            rows = await page.query_selector_all(config["result_row_selector"])
            if not rows:
                log.debug("[assessor] %s: no result rows found for %s", county, address_clean)
                return None

            row = rows[0]

            owner_el = await row.query_selector(config["owner_selector"])
            mailing_el = await row.query_selector(config["mailing_selector"])

            owner_name = _clean_text(await owner_el.inner_text()) if owner_el else ""
            mailing_addr = _clean_text(await mailing_el.inner_text()) if mailing_el else ""

            if not owner_name and not mailing_addr:
                return None

            log.info(
                "[assessor] %s: found owner=%r mailing=%r",
                county, owner_name[:40], mailing_addr[:60],
            )
            return {
                "owner_name":       owner_name,
                "mailing_address":  mailing_addr,
            }

        except PWTimeout:
            log.warning("[assessor] %s: timeout for %s", county, address_clean)
            return None
        except Exception as exc:
            log.warning("[assessor] %s: error for %s: %s", county, address_clean, exc)
            return None
        finally:
            await browser.close()


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _get_pending_assets(
    conn: sqlite3.Connection,
    county: Optional[str] = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Fetch GOLD/SILVER leads with property_address but no owner_mailing_address."""
    filters = [
        "l.data_grade IN ('GOLD', 'SILVER')",
        "l.property_address IS NOT NULL",
        "l.property_address != ''",
        "(ar.owner_mailing_address IS NULL OR ar.owner_mailing_address = '')",
    ]
    params: list = []
    if county:
        filters.append("lower(l.county) = lower(?)")
        params.append(county)
    params.append(limit)
    where = " AND ".join(filters)
    return conn.execute(
        f"""SELECT l.id, l.county, l.case_number, l.property_address,
                   l.owner_name, ar.asset_id as ar_asset_id
            FROM leads l
            LEFT JOIN asset_registry ar ON ar.asset_id = l.id
            WHERE {where}
            ORDER BY l.estimated_surplus DESC NULLS LAST
            LIMIT ?""",
        params,
    ).fetchall()


def _store_mailing_address(
    conn: sqlite3.Connection,
    lead_id: str,
    mailing_address: str,
    owner_name: str = "",
) -> None:
    """Write owner_mailing_address to asset_registry (and optionally owner_name to leads)."""
    conn.execute(
        "UPDATE asset_registry SET owner_mailing_address = ? WHERE asset_id = ?",
        [mailing_address, lead_id],
    )
    # Only update owner_name if lead has none
    if owner_name:
        conn.execute(
            "UPDATE leads SET owner_name = ? WHERE id = ? AND (owner_name IS NULL OR owner_name = '')",
            [owner_name, lead_id],
        )


# ── Queue runner ───────────────────────────────────────────────────────────────

async def run_assessor_queue(
    county: Optional[str] = None,
    limit: int = 20,
    db_path: str = DB_PATH,
) -> dict:
    """Process pending GOLD/SILVER leads to pull owner mailing address from assessor.

    Only runs lookups for supported counties (Jefferson, Arapahoe, Adams, Denver).
    Returns summary dict with counts.
    """
    supported = set(ASSESSOR_CONFIGS.keys())

    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    rows = _get_pending_assets(conn, county=county, limit=limit)

    total = len(rows)
    found = 0
    skipped = 0
    not_found = 0

    for row in rows:
        county_lower = (row["county"] or "").lower()
        if county_lower not in supported:
            log.debug("[assessor] Skipping unsupported county: %s", row["county"])
            skipped += 1
            continue

        result = await _lookup_owner_playwright(
            county=county_lower,
            property_address=row["property_address"],
        )

        if result and result.get("mailing_address"):
            _store_mailing_address(
                conn,
                lead_id=row["id"],
                mailing_address=result["mailing_address"],
                owner_name=result.get("owner_name", ""),
            )
            found += 1
        else:
            not_found += 1

        # Brief pause between requests
        await asyncio.sleep(2)

    conn.close()

    summary = {
        "total_candidates": total,
        "addresses_found":  found,
        "not_found":        not_found,
        "skipped_unsupported": skipped,
    }
    log.info("[assessor_queue] Complete: %s", summary)
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="VeriFuse Assessor Owner Lookup")
    parser.add_argument("--county", help="County slug (jefferson, arapahoe, adams, denver)")
    parser.add_argument("--limit", type=int, default=10, help="Max assets to process")
    parser.add_argument("--asset-id", help="Process a single asset ID")
    args = parser.parse_args()

    if args.asset_id:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id, county, property_address, owner_name FROM leads WHERE id = ?",
            [args.asset_id],
        ).fetchone()
        conn.close()
        if not row:
            print(json.dumps({"error": f"Asset not found: {args.asset_id}"}))
        else:
            result = asyncio.run(
                _lookup_owner_playwright(
                    county=(row["county"] or "").lower(),
                    property_address=row["property_address"] or "",
                )
            )
            print(json.dumps(result or {"not_found": True}, indent=2))
    else:
        result = asyncio.run(
            run_assessor_queue(county=args.county, limit=args.limit)
        )
        print(json.dumps(result, indent=2))
