"""
VeriFuse — Colorado State Treasurer Unclaimed Foreclosure Surplus Scraper
==========================================================================
Targets unclaimed overbid funds held by the CO State Treasurer after Public
Trustees turn over unclaimed surplus (6-month claim window expired unclaimed).

Statute chain:
  C.R.S. § 38-38-111  → overbid held by Public Trustee for 6 months
  C.R.S. § 38-13-101  → unclaimed property turned over to State Treasurer
  C.R.S. § 38-13-1304 → HB25-1224: 10% fee cap on recovery (eff. June 4 2025)

Target: https://unclaimedproperty.colorado.gov/app/claim-search
API:    POST https://unclaimedproperty.colorado.gov/SWS/properties
        Requires header: SWS-Turnstile-Token (Cloudflare Turnstile managed mode)
        Requires header: SWS-ThreatMetrix-Session-ID

ANTI-BOT NOTE:
  The CO Treasurer site uses Cloudflare Turnstile (managed mode with checkbox).
  Fully automated headless scraping is blocked.
  Supported modes:
    --session-cookies PATH  Use a saved browser session (JSON cookie export)
    --owner-name NAME       Single owner lookup (cross-ref one lead)
    --dry-run               Print what would be searched without hitting the site
    --build-crossref-list   Build a prioritized lookup list from our DB

Usage:
  bin/vf unclaimed-property-run --county jefferson
  bin/vf unclaimed-property-run --owner-name "SMITH JOHN" --county jefferson
  bin/vf unclaimed-property-run --session-cookies /tmp/co_treasurer_session.json --all-counties
  bin/vf unclaimed-property-run --build-crossref-list

Session cookie export:
  1. Open https://unclaimedproperty.colorado.gov/app/claim-search in Chrome
  2. Complete one search (solve the Turnstile checkbox)
  3. In DevTools Console: copy(JSON.stringify(document.cookie.split(';').map(c => c.trim())))
  4. Or use the EditThisCookie browser extension to export to JSON
  5. Save to: verifuse_v2/data/co_treasurer_session.json
  6. Session typically valid for 30-60 min → run batch searches during this window
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)

SESSION_COOKIE_PATH = os.getenv(
    "CO_TREASURER_SESSION",
    str(Path(__file__).resolve().parent.parent / "data" / "co_treasurer_session.json"),
)

SITE_URL = "https://unclaimedproperty.colorado.gov"
SEARCH_URL = f"{SITE_URL}/app/claim-search"
API_URL = f"{SITE_URL}/SWS/properties"

# Public Trustee holder name patterns (as they appear in the Treasurer DB)
HOLDER_PATTERNS = [
    "PUBLIC TRUSTEE",
    "PUBLIC TREASURER",
    "TRUSTEE",
]

# Counties with their Public Trustee display names
COUNTY_TRUSTEE_NAMES = {
    "adams":       "PUBLIC TRUSTEE ADAMS COUNTY",
    "arapahoe":    "PUBLIC TRUSTEE ARAPAHOE COUNTY",
    "boulder":     "PUBLIC TRUSTEE BOULDER COUNTY",
    "broomfield":  "PUBLIC TRUSTEE BROOMFIELD COUNTY",
    "clear_creek": "PUBLIC TRUSTEE CLEAR CREEK COUNTY",
    "denver":      "PUBLIC TRUSTEE DENVER COUNTY",
    "douglas":     "PUBLIC TRUSTEE DOUGLAS COUNTY",
    "eagle":       "PUBLIC TRUSTEE EAGLE COUNTY",
    "el_paso":     "PUBLIC TRUSTEE EL PASO COUNTY",
    "elbert":      "PUBLIC TRUSTEE ELBERT COUNTY",
    "fremont":     "PUBLIC TRUSTEE FREMONT COUNTY",
    "garfield":    "PUBLIC TRUSTEE GARFIELD COUNTY",
    "gilpin":      "PUBLIC TRUSTEE GILPIN COUNTY",
    "jefferson":   "PUBLIC TRUSTEE JEFFERSON COUNTY",
    "la_plata":    "PUBLIC TRUSTEE LA PLATA COUNTY",
    "larimer":     "PUBLIC TRUSTEE LARIMER COUNTY",
    "mesa":        "PUBLIC TRUSTEE MESA COUNTY",
    "san_miguel":  "PUBLIC TRUSTEE SAN MIGUEL COUNTY",
    "teller":      "PUBLIC TRUSTEE TELLER COUNTY",
    "weld":        "PUBLIC TRUSTEE WELD COUNTY",
}


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _get_crossref_owners(conn: sqlite3.Connection, county: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Get expired-window leads from DB as candidate unclaimed property owners."""
    import time
    cutoff_date = "2025-09-01"  # 6+ months ago → restriction expired
    query = """
        SELECT DISTINCT county, owner_name, case_number, sale_date, surplus_amount
        FROM leads
        WHERE owner_name IS NOT NULL
          AND TRIM(owner_name) != ''
          AND data_grade IN ('GOLD', 'SILVER', 'BRONZE')
          AND surplus_stream IN ('FORECLOSURE_OVERBID', 'FORECLOSURE_SURPLUS')
          AND (sale_date IS NULL OR sale_date <= ?)
    """
    params: list = [cutoff_date]
    if county:
        query += " AND county = ?"
        params.append(county)
    query += " ORDER BY surplus_amount DESC NULLS LAST LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _insert_unclaimed_lead(
    conn: sqlite3.Connection,
    county: str,
    case_number: str,
    owner_name: str,
    amount: float,
    holder_name: str,
    property_type: str,
    report_date: str,
    address: str,
    crossref_case: Optional[str],
) -> Optional[str]:
    """Insert unclaimed property lead. Returns lead_id or None if duplicate."""
    existing = conn.execute(
        "SELECT id FROM leads WHERE case_number = ?", [case_number]
    ).fetchone()
    if existing:
        return None

    lead_id = str(uuid.uuid4())
    grade = "SILVER" if crossref_case else "BRONZE"

    conn.execute(
        """
        INSERT INTO leads (
            id, county, case_number, data_grade, processing_status,
            surplus_stream, surplus_amount, overbid_amount, estimated_surplus,
            owner_name, property_address, ned_source,
            ingestion_source, updated_at
        ) VALUES (
            ?, ?, ?, ?, 'STAGED',
            'UNCLAIMED_PROPERTY', ?, ?, ?,
            ?, ?, ?,
            'co_treasurer_scraper', datetime('now')
        )
        """,
        [
            lead_id, county, case_number, grade,
            amount, amount, amount,
            owner_name, address or None,
            (
                f"CO Treasurer – {holder_name} – {property_type} – reported {report_date}"
                + (f" [CROSSREF: {crossref_case}]" if crossref_case else "")
            ),
        ],
    )
    log.info(
        "[unclaimed] %s  county=%s  owner=%r  amount=$%.0f  grade=%s%s",
        case_number, county, (owner_name or "")[:40], amount, grade,
        f" → crossref {crossref_case}" if crossref_case else "",
    )
    return lead_id


# ── Session-based scraper ──────────────────────────────────────────────────────

def _load_session_cookies(session_path: str) -> list[dict]:
    """Load saved browser session cookies from JSON file."""
    p = Path(session_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if isinstance(data, list):
            return data
        # Handle different export formats
        if isinstance(data, dict) and "cookies" in data:
            return data["cookies"]
        return []
    except Exception as e:
        log.warning("[unclaimed] Failed to load session cookies from %s: %s", session_path, e)
        return []


async def _search_with_session(
    owner_name: str,
    county: str,
    session_cookies: list[dict],
    turnstile_token: str = "",
) -> list[dict]:
    """
    Search CO Treasurer API using saved session cookies.
    Requires a valid session (post-Turnstile-solve) to work.
    """
    try:
        import httpx
    except ImportError:
        log.error("[unclaimed] httpx not installed")
        return []

    # Build cookie header from saved session
    cookie_str = "; ".join(
        f"{c.get('name', c.get('key', ''))}={c.get('value', '')}"
        for c in session_cookies
        if c.get("domain", "").endswith("unclaimedproperty.colorado.gov")
        or c.get("domain", "").endswith("colorado.gov")
        or not c.get("domain", "")
    )

    # Extract last name (Treasurer DB stores LAST FIRST format)
    parts = owner_name.upper().strip().split()
    last_name = parts[0] if parts else owner_name[:20]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Cookie": cookie_str,
        "Origin": SITE_URL,
        "Referer": SEARCH_URL,
    }
    if turnstile_token:
        headers["SWS-Turnstile-Token"] = turnstile_token

    payload = {
        "lastName": last_name,
        "city": "",
        "searchZipCode": "",
        "propertyID": "",
        "state": "CO",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(API_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("properties", data.get("results", []))
            elif resp.status_code in (401, 403):
                log.warning("[unclaimed] Session expired or Turnstile required (HTTP %d)", resp.status_code)
            else:
                log.debug("[unclaimed] API returned %d for %s", resp.status_code, last_name)
    except Exception as e:
        log.debug("[unclaimed] Search error for %s: %s", last_name, e)
    return []


async def _search_single_with_playwright(
    owner_name: str,
    session_cookies: list[dict],
) -> list[dict]:
    """
    Full Playwright search for one owner. Uses saved session cookies to
    skip Turnstile. Falls back to Xvfb-required interactive mode if no cookies.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("[unclaimed] playwright not installed")
        return []

    results: list[dict] = []
    parts = owner_name.upper().strip().split()
    last_name = parts[0] if parts else owner_name[:20]

    import subprocess
    use_xvfb = not os.environ.get("DISPLAY") and os.path.exists("/usr/bin/Xvfb")

    async def _run_search():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=not use_xvfb,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/Denver",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            # Inject saved cookies
            if session_cookies:
                playwright_cookies = []
                for c in session_cookies:
                    playwright_cookies.append({
                        "name": c.get("name", c.get("key", "")),
                        "value": str(c.get("value", "")),
                        "domain": c.get("domain", ".unclaimedproperty.colorado.gov"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", False),
                    })
                await context.add_cookies(playwright_cookies)

            page = await context.new_page()
            api_data: list[dict] = []

            async def on_response(resp):
                if "SWS/properties" in resp.url and "app" not in resp.url and resp.status == 200:
                    try:
                        data = await resp.json()
                        if isinstance(data, list):
                            api_data.extend(data)
                        elif isinstance(data, dict):
                            api_data.extend(data.get("properties", data.get("results", [])))
                    except Exception:
                        pass

            page.on("response", on_response)

            try:
                await page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(2)

                # Fill the name field
                await page.fill("#lastName", last_name)
                await asyncio.sleep(0.5)

                # Click search
                btn = await page.query_selector("#btn-turnstile")
                if btn:
                    await btn.click()
                    await asyncio.sleep(20)  # Wait for Turnstile + results

            except Exception as e:
                log.warning("[unclaimed] Playwright search failed for %s: %s", last_name, e)
            finally:
                await browser.close()

            return api_data

    if use_xvfb:
        # Run via xvfb-run subprocess
        proc = await asyncio.create_subprocess_exec(
            "xvfb-run", "-a", "--server-args=-screen 0 1280x800x24",
            "python3", "-c",
            f"""
import asyncio, json, sys
sys.path.insert(0, '.')
from verifuse_v2.scrapers.unclaimed_property_scraper import _run_playwright_xvfb
result = asyncio.run(_run_playwright_xvfb({repr(last_name)}, {repr(session_cookies)}))
print(json.dumps(result))
""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            results = json.loads(stdout.decode())
        except Exception:
            results = []
    else:
        results = await _run_search()

    return results


async def _run_playwright_xvfb(last_name: str, session_cookies: list[dict]) -> list[dict]:
    """Standalone function for xvfb-run subprocess call."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    api_data: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-gpu"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        if session_cookies:
            playwright_cookies = []
            for c in session_cookies:
                playwright_cookies.append({
                    "name": c.get("name", c.get("key", "")),
                    "value": str(c.get("value", "")),
                    "domain": c.get("domain", ".unclaimedproperty.colorado.gov"),
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", True),
                    "httpOnly": c.get("httpOnly", False),
                })
            await context.add_cookies(playwright_cookies)

        page = await context.new_page()

        async def on_response(resp):
            if "SWS/properties" in resp.url and "app" not in resp.url and resp.status == 200:
                try:
                    data = await resp.json()
                    if isinstance(data, list):
                        api_data.extend(data)
                    elif isinstance(data, dict):
                        api_data.extend(data.get("properties", data.get("results", [])))
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            await page.fill("#lastName", last_name)
            await asyncio.sleep(0.5)
            btn = await page.query_selector("#btn-turnstile")
            if btn:
                await btn.click()
                await asyncio.sleep(20)
        except Exception:
            pass
        finally:
            await browser.close()

    return api_data


# ── Result parser ──────────────────────────────────────────────────────────────

def _parse_property_record(prop: dict) -> Optional[dict]:
    """Normalize a CO Treasurer API property record."""
    if not isinstance(prop, dict):
        return None

    holder = (
        prop.get("holderName") or
        (prop.get("holderFirstName", "") + " " + prop.get("holderLastName", "")).strip() or
        ""
    ).upper()

    # Only keep Public Trustee held funds (foreclosure overbids)
    if not any(pat in holder for pat in HOLDER_PATTERNS):
        return None

    owner = (
        (prop.get("firstName", "") + " " + prop.get("lastName", "")).strip() or
        prop.get("ownerName", "") or
        prop.get("owner_name", "")
    ).strip()

    amount_raw = (
        prop.get("amount") or prop.get("reportedValue") or
        prop.get("reported_value") or 0
    )
    try:
        amount = float(str(amount_raw).replace("$", "").replace(",", "") or 0)
    except (ValueError, TypeError):
        amount = 0.0

    if amount < 100:
        return None

    return {
        "owner": owner,
        "amount": amount,
        "holder": holder,
        "property_type": (
            prop.get("propertyType") or prop.get("property_type") or
            prop.get("propertyTypeName") or "Court Funds"
        ),
        "report_date": str(prop.get("reportDate") or prop.get("report_date") or prop.get("reportYear") or ""),
        "address": prop.get("propertyAddress") or prop.get("street") or prop.get("address1") or "",
        "property_id": str(prop.get("propertyID") or prop.get("property_id") or ""),
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_unclaimed_pipeline(
    county: Optional[str] = None,
    owner_name: Optional[str] = None,
    session_cookies_path: Optional[str] = None,
    limit: int = 100,
    all_counties: bool = False,
    dry_run: bool = False,
    build_crossref_list: bool = False,
) -> dict:
    """
    Search CO State Treasurer for unclaimed foreclosure surplus.
    Requires either:
      a) session_cookies_path: saved browser cookies (post-Turnstile-solve)
      b) Direct owner_name lookup (single check)
    """
    conn = _get_conn()

    if build_crossref_list:
        owners = _get_crossref_owners(conn, county=county, limit=limit)
        conn.close()
        print(f"CROSSREF CANDIDATES ({len(owners)}):")
        for o in owners:
            print(f"  {o['county']}/{o['case_number']}: {o['owner_name']} | sale={o['sale_date']} | surplus=${o['surplus_amount'] or 0:.0f}")
        return {"crossref_candidates": len(owners)}

    session_cookies = _load_session_cookies(session_cookies_path or SESSION_COOKIE_PATH)
    has_session = bool(session_cookies)

    if not has_session and not owner_name and not dry_run:
        log.warning(
            "[unclaimed] No session cookies found at %s\n"
            "  The CO Treasurer site requires Cloudflare Turnstile verification.\n"
            "  To enable automated searches:\n"
            "    1. Open %s in Chrome\n"
            "    2. Solve the Turnstile checkbox\n"
            "    3. Export cookies to: %s\n"
            "    4. Re-run within 30-60 min while session is valid",
            session_cookies_path or SESSION_COOKIE_PATH,
            SEARCH_URL,
            session_cookies_path or SESSION_COOKIE_PATH,
        )
        conn.close()
        return {
            "status": "no_session",
            "message": f"Session file not found: {session_cookies_path or SESSION_COOKIE_PATH}. Solve Turnstile in browser first.",
            "leads_inserted": 0,
        }

    # Determine what to search
    if owner_name:
        search_list = [{"owner_name": owner_name, "county": county or "unknown", "case_number": None}]
    elif all_counties:
        search_list = _get_crossref_owners(conn, county=None, limit=limit)
    else:
        search_list = _get_crossref_owners(conn, county=county, limit=limit)

    if not search_list:
        log.info("[unclaimed] No candidate owners to search")
        conn.close()
        return {"leads_inserted": 0, "searched": 0}

    total_inserted = 0
    total_searched = 0
    total_skipped = 0

    for item in search_list:
        owner = item["owner_name"] if isinstance(item, dict) else item
        item_county = item.get("county", county or "unknown") if isinstance(item, dict) else (county or "unknown")
        crossref_case = item.get("case_number") if isinstance(item, dict) else None

        if dry_run:
            log.info("[unclaimed] DRY RUN: Would search CO Treasurer for owner=%r county=%s", owner, item_county)
            total_searched += 1
            continue

        # Try API call first (fast, requires valid session cookies)
        raw_records = asyncio.run(_search_with_session(owner, item_county, session_cookies))
        total_searched += 1

        for prop in raw_records:
            parsed = _parse_property_record(prop)
            if not parsed:
                continue

            fingerprint = f"{parsed['owner']}|{item_county}|{parsed['amount']:.0f}|{parsed['report_date']}"
            case_number = f"UP-{item_county[:4].upper()}-{abs(hash(fingerprint)) % 10000000:07d}"[:20]

            result_id = _insert_unclaimed_lead(
                conn, item_county, case_number,
                parsed["owner"], parsed["amount"],
                parsed["holder"], parsed["property_type"],
                parsed["report_date"], parsed["address"],
                crossref_case,
            )
            if result_id:
                total_inserted += 1
            else:
                total_skipped += 1

        # Polite delay between searches
        if len(search_list) > 1:
            asyncio.run(asyncio.sleep(1.5))

    conn.close()
    summary = {
        "owners_searched": total_searched,
        "leads_inserted": total_inserted,
        "leads_skipped_dup": total_skipped,
    }
    log.info("[unclaimed_pipeline] Complete: %s", summary)
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(
        description=(
            "VeriFuse CO State Treasurer Unclaimed Foreclosure Surplus Checker\n"
            "C.R.S. § 38-13-101 — Public Trustee turnovers (post-6-month expiry)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--county", help="County slug (e.g. jefferson, adams)")
    parser.add_argument("--owner-name", help="Single owner name to look up")
    parser.add_argument("--all-counties", action="store_true", help="Search all counties' expired leads")
    parser.add_argument("--limit", type=int, default=100, help="Max owner records to search (default: 100)")
    parser.add_argument("--session-cookies", help=f"Path to saved browser session cookies JSON (default: {SESSION_COOKIE_PATH})")
    parser.add_argument("--build-crossref-list", action="store_true", help="Print expired-window leads that are candidates for unclaimed check")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be searched without hitting the site")
    args = parser.parse_args()

    result = run_unclaimed_pipeline(
        county=args.county,
        owner_name=args.owner_name,
        session_cookies_path=args.session_cookies,
        limit=args.limit,
        all_counties=args.all_counties,
        dry_run=args.dry_run,
        build_crossref_list=args.build_crossref_list,
    )
    print(json.dumps(result, indent=2))
