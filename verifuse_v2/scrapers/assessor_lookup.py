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
    "el_paso": {
        "search_url": "https://assessor.elpasoco.com/Search/Address",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], input[id*='Address'], input[placeholder*='ddress']",
        "search_btn_selector":    "button[type='submit'], input[type='submit'], button:has-text('Search')",
        "result_row_selector":    "table tr:not(:first-child), .result-row, .search-result",
        "owner_selector":         "td:nth-child(2), .owner-name, [class*='owner']",
        "mailing_selector":       "td:nth-child(5), td:nth-child(4), .mailing-address",
    },
    "boulder": {
        "search_url": "https://assessor.bouldercounty.org/residential/search",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], input[id*='address'], input[placeholder*='Address']",
        "search_btn_selector":    "button[type='submit'], input[type='submit']",
        "result_row_selector":    "table tr:not(:first-child), .property-row, .search-result-item",
        "owner_selector":         "td:nth-child(2), .owner-name",
        "mailing_selector":       "td:nth-child(4), td:nth-child(5), .mailing-address",
    },
    "douglas": {
        "search_url": "https://assessor.douglas.co.us/assessor/search",
        "search_by": "address",
        "address_input_selector": "input[name*='address'], input[id*='address'], input[placeholder*='ddress']",
        "search_btn_selector":    "button[type='submit'], input[type='submit']",
        "result_row_selector":    "table tr:not(:first-child), .search-result-row",
        "owner_selector":         "td:nth-child(2), .owner, [class*='owner']",
        "mailing_selector":       "td:nth-child(5), td:nth-child(4), .mailing",
    },
    "weld": {
        "search_url": "https://www.weldgov.com/departments/assessor/search",
        "search_by": "parcel",
        "address_input_selector": "input[name*='parcel'], input[id*='parcel'], input[name*='address'], input[placeholder*='arcel']",
        "search_btn_selector":    "button[type='submit'], input[type='submit']",
        "result_row_selector":    "table tr:not(:first-child), .result-row",
        "owner_selector":         "td:nth-child(2), .owner-name",
        "mailing_selector":       "td:nth-child(4), td:nth-child(5), .mailing-address",
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


# ── County adapter registry ────────────────────────────────────────────────────

def _get_adapter(county: str):
    """Return the county-specific adapter module, or None if not supported."""
    try:
        if county == "jefferson":
            from verifuse_v2.scrapers.assessor_adapters import jefferson as m
        elif county == "arapahoe":
            from verifuse_v2.scrapers.assessor_adapters import arapahoe as m
        elif county == "adams":
            from verifuse_v2.scrapers.assessor_adapters import adams as m
        elif county == "denver":
            from verifuse_v2.scrapers.assessor_adapters import denver as m
        elif county == "el_paso":
            from verifuse_v2.scrapers.assessor_adapters import el_paso as m
        elif county == "boulder":
            from verifuse_v2.scrapers.assessor_adapters import boulder as m
        elif county == "douglas":
            from verifuse_v2.scrapers.assessor_adapters import douglas as m
        elif county == "weld":
            from verifuse_v2.scrapers.assessor_adapters import weld as m
        else:
            return None
        # Skip adapters that are marked as permanently blocked
        if getattr(m, "BLOCKED", False):
            log.debug("[assessor] %s: adapter marked BLOCKED, skipping", county)
            return None
        return m
    except ImportError:
        return None


# ── Playwright lookup ──────────────────────────────────────────────────────────

async def _lookup_owner_playwright(
    county: str,
    property_address: str,
    timeout_ms: int = 20000,
) -> Optional[dict]:
    """Dispatch to county-specific adapter for owner + mailing address lookup.

    Returns dict with owner_name and mailing_address keys, or None if not found.
    Each county adapter handles its own portal navigation logic.
    """
    county_key = county.lower()
    adapter = _get_adapter(county_key)
    if not adapter:
        log.debug("[assessor] No adapter for county: %s", county)
        return None

    try:
        from playwright.async_api import async_playwright  # type: ignore
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        try:
            result = await adapter.lookup(page, address_clean, timeout_ms)
            if result:
                log.info(
                    "[assessor] %s: found owner=%r mailing=%r",
                    county, result.get("owner_name", "")[:40], result.get("mailing_address", "")[:60],
                )
            return result

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
    parser.add_argument("--county", help="County slug (jefferson, arapahoe, adams, denver, el_paso, boulder, douglas, weld)")
    parser.add_argument("--all-counties", action="store_true", help="Run all supported counties")
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
    elif getattr(args, "all_counties", False):
        # Run all supported counties sequentially
        totals = {"total_candidates": 0, "addresses_found": 0, "not_found": 0, "skipped_unsupported": 0}
        for county in sorted(ASSESSOR_CONFIGS.keys()):
            print(f"[assessor] Running county={county} limit={args.limit} ...")
            result = asyncio.run(run_assessor_queue(county=county, limit=args.limit))
            for k in totals:
                totals[k] += result.get(k, 0)
            print(json.dumps(result, indent=2))
        print(f"\n[assessor] All-counties totals: {json.dumps(totals)}")
    else:
        result = asyncio.run(
            run_assessor_queue(county=args.county, limit=args.limit)
        )
        print(json.dumps(result, indent=2))
