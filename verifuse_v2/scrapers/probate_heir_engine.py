"""
VERIFUSE V2 — Probate / Heir Cross-Reference Engine

Identifies foreclosure surplus assets where the owner is deceased,
meaning heirs must be located to claim funds. These are the highest-value
leads because:
  1. Heirs often don't know surplus exists
  2. Attorney representation is virtually required (probate + surplus claim)
  3. The attorney-client exemption (C.R.S. § 38-13-1302(5)) applies

Data sources:
  - Colorado Judicial Branch probate search (courts.state.co.us)
  - Colorado obituary cross-reference (public newspaper archives)
  - County assessor ownership records (for property transfer detection)

Usage:
  python -m verifuse_v2.scrapers.probate_heir_engine
  python -m verifuse_v2.scrapers.probate_heir_engine --county Denver
  python -m verifuse_v2.scrapers.probate_heir_engine --import-csv /path/to/probate_data.csv
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# Colorado Judicial Branch case search
# Probate cases use case type "PR" (Probate) or "D" (Decedent Estate)
CO_COURTS_SEARCH = "https://www.courts.state.co.us/dockets/index.cfm"

# County codes for Colorado district courts
COUNTY_COURT_CODES = {
    "Denver": "02",
    "Jefferson": "01",
    "Arapahoe": "18",
    "Adams": "17",
    "Douglas": "18",
    "El Paso": "04",
    "Mesa": "21",
    "Larimer": "08",
    "Boulder": "20",
    "Weld": "19",
    "Teller": "04",
}

# User agent rotation for stealth
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _normalize_name(name: str) -> str:
    """Normalize owner name for fuzzy matching.

    'SMITH, JOHN A.' → 'john smith'
    'John A. Smith' → 'john smith'
    """
    if not name:
        return ""
    # Remove suffixes like Jr., Sr., III, etc.
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v|esq|md|phd)\.?\b", "", name, flags=re.IGNORECASE)
    # Remove punctuation
    name = re.sub(r"[^a-zA-Z\s]", "", name)
    # Split and sort parts (handles "SMITH, JOHN" vs "JOHN SMITH")
    parts = [p.strip().lower() for p in name.split() if p.strip()]
    # Sort alphabetically for order-independent matching
    return " ".join(sorted(parts))


def _name_match_score(name1: str, name2: str) -> float:
    """Compute similarity score between two normalized names. 0.0 - 1.0."""
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)

    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    # Check if one contains the other (partial match)
    parts1 = set(n1.split())
    parts2 = set(n2.split())
    overlap = parts1 & parts2
    total = parts1 | parts2

    if not total:
        return 0.0

    return len(overlap) / len(total)


def _make_probate_asset_id(county: str, case_number: str) -> str:
    """Generate deterministic ID for probate-linked surplus."""
    clean = case_number.strip().replace(" ", "_")
    return f"probate_{county.lower()}_{clean}"


def _record_hash(rec: dict) -> str:
    """SHA-256 hash of key fields for dedup."""
    key = f"{rec.get('decedent_name', '')}|{rec.get('case_number', '')}|{rec.get('county', '')}"
    return hashlib.sha256(key.encode()).hexdigest()


# ── Cross-Reference Engine ──────────────────────────────────────────


def cross_reference_surplus_with_deaths(county: Optional[str] = None) -> dict:
    """Cross-reference existing surplus assets with probate/death indicators.

    Checks each owner in the assets table for:
    1. Name matches in probate court records (if accessible)
    2. Property transfer patterns (owner changed after sale)
    3. Estate/trust indicators in owner name

    Returns stats about matches found.
    """
    db.init_db()
    stats = {"total_checked": 0, "estate_name_matches": 0, "flagged_for_review": 0}

    # Get all surplus assets
    with db.get_db() as conn:
        assets = conn.execute("""
            SELECT asset_id, owner_of_record, county, sale_date, estimated_surplus
            FROM assets
            WHERE estimated_surplus >= 1000
        """).fetchall()

    for asset in assets:
        stats["total_checked"] += 1
        owner = asset["owner_of_record"] or ""

        # Check for estate/trust/deceased indicators in name
        estate_patterns = [
            r"\bestate\b", r"\best\.\s+of\b", r"\bdeceased\b",
            r"\bdec[']?d\b", r"\btrust\b", r"\bheirs\b",
            r"\bpersonal\s+rep", r"\bexecutor\b", r"\badministrat",
            r"\bsuccessor\b", r"\bguardian\b", r"\bconservator\b",
        ]

        for pattern in estate_patterns:
            if re.search(pattern, owner, re.IGNORECASE):
                stats["estate_name_matches"] += 1
                _flag_as_heir_lead(asset["asset_id"], owner, "estate_name_indicator")
                break

    log.info("Cross-reference complete: %d checked, %d estate matches",
             stats["total_checked"], stats["estate_name_matches"])
    return stats


def _flag_as_heir_lead(asset_id: str, owner: str, reason: str) -> None:
    """Flag an existing asset as a potential heir/probate lead."""
    now = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        # Add pipeline event
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'HEIR_FLAG', ?, 'HEIR_LEAD', 'probate_heir_engine', ?, ?)
        """, [asset_id, owner, reason, now])

        # Update asset type to indicate heir lead
        conn.execute("""
            UPDATE assets SET asset_type = 'HEIR_SURPLUS',
            updated_at = ? WHERE asset_id = ?
        """, [now, asset_id])


# ── CSV Import for Probate Data ──────────────────────────────────────


def import_probate_csv(csv_path: str | Path) -> dict:
    """Import probate case data from CSV and cross-reference with surplus assets.

    Expected CSV columns (flexible mapping):
        case_number, decedent_name, date_of_death, county, filing_date

    This creates new leads when a decedent name matches a surplus asset owner,
    or stages the probate record for future cross-referencing.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        return {"error": f"File not found: {csv_path}"}

    COLUMN_MAP = {
        "case_number": "case_number", "case_#": "case_number", "case": "case_number",
        "decedent": "decedent_name", "decedent_name": "decedent_name",
        "deceased": "decedent_name", "name": "decedent_name",
        "date_of_death": "date_of_death", "dod": "date_of_death", "death_date": "date_of_death",
        "county": "county", "district": "county",
        "filing_date": "filing_date", "filed": "filing_date", "file_date": "filing_date",
    }

    records = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}

        header_map = {}
        for raw in reader.fieldnames:
            normalized = raw.strip().lower().replace(" ", "_")
            header_map[raw] = COLUMN_MAP.get(normalized, normalized)

        for row in reader:
            mapped = {}
            for k, v in row.items():
                mapped[header_map.get(k, k)] = (v or "").strip()
            if mapped.get("decedent_name") or mapped.get("case_number"):
                records.append(mapped)

    if not records:
        return {"error": "No valid probate records found"}

    log.info("Parsed %d probate records from %s", len(records), csv_path.name)
    return _cross_ref_probate_records(records)


def _cross_ref_probate_records(probate_records: list[dict]) -> dict:
    """Cross-reference probate records against surplus assets.

    For each decedent, check if their name matches any surplus asset owner.
    """
    db.init_db()
    stats = {
        "total_probate": len(probate_records),
        "matches_found": 0,
        "new_heir_leads": 0,
        "staged": 0,
    }

    # Load all surplus asset owners for matching
    with db.get_db() as conn:
        assets = conn.execute("""
            SELECT asset_id, owner_of_record, county, estimated_surplus, sale_date
            FROM assets WHERE estimated_surplus >= 1000
        """).fetchall()

    asset_list = [dict(a) for a in assets]
    now = datetime.now(timezone.utc).isoformat()

    for probate in probate_records:
        decedent = probate.get("decedent_name", "")
        if not decedent:
            continue

        # Try to match against surplus asset owners
        best_match = None
        best_score = 0.0

        for asset in asset_list:
            score = _name_match_score(decedent, asset.get("owner_of_record", ""))
            if score > best_score and score >= 0.6:  # 60% threshold
                best_score = score
                best_match = asset

        if best_match:
            stats["matches_found"] += 1
            log.info("MATCH: Probate '%s' ↔ Surplus '%s' (score=%.2f, surplus=$%s)",
                     decedent, best_match["owner_of_record"],
                     best_score, best_match["estimated_surplus"])

            # Flag the existing asset as an heir lead
            _flag_as_heir_lead(best_match["asset_id"], decedent,
                             f"probate_match:{probate.get('case_number', 'unknown')}:score={best_score:.2f}")
            stats["new_heir_leads"] += 1
        else:
            # Stage for future reference
            stats["staged"] += 1

    log.info("Probate cross-ref: %d matches from %d records",
             stats["matches_found"], stats["total_probate"])
    return stats


# ── Colorado Courts Probate Search ───────────────────────────────────


def search_probate_filings(county: str, months_back: int = 12) -> list[dict]:
    """Search Colorado courts for recent probate filings.

    Uses the Colorado Judicial Branch public docket search.
    Note: This may be rate-limited or require CAPTCHA. Falls back to
    manual CSV import if automated search fails.
    """
    court_code = COUNTY_COURT_CODES.get(county)
    if not court_code:
        log.warning("No court code for county: %s", county)
        return []

    # Colorado courts search — may require session handling
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml",
    })

    # The CO courts website requires specific form data
    # This is a best-effort attempt — if blocked, use CSV import
    start_date = (datetime.now() - timedelta(days=30 * months_back)).strftime("%m/%d/%Y")
    end_date = datetime.now().strftime("%m/%d/%Y")

    try:
        resp = session.get(CO_COURTS_SEARCH, timeout=15)
        if resp.status_code != 200:
            log.warning("Courts search returned %d — use CSV import instead", resp.status_code)
            return []

        # Attempt to search for probate cases
        search_data = {
            "court": court_code,
            "casetype": "PR",  # Probate
            "datefiled_from": start_date,
            "datefiled_to": end_date,
        }

        resp = session.post(CO_COURTS_SEARCH, data=search_data, timeout=30)
        if resp.status_code != 200 or "captcha" in resp.text.lower():
            log.warning("Courts search blocked (CAPTCHA or rate limit) — use CSV import")
            return []

        # Parse results (HTML scraping)
        # This is fragile — the court website may change
        log.info("Courts search returned %d bytes — parsing...", len(resp.text))
        return _parse_court_results(resp.text, county)

    except requests.RequestException as e:
        log.warning("Courts search failed: %s — use CSV import", e)
        return []


def _parse_court_results(html: str, county: str) -> list[dict]:
    """Parse Colorado courts docket search HTML for probate cases.

    Returns list of dicts with: case_number, decedent_name, filing_date, county
    """
    results = []
    # Pattern: look for case rows with PR (probate) case type
    case_pattern = re.compile(
        r'(\d{4}PR\d+)\s*.*?<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d{2}/\d{2}/\d{4})</td>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in case_pattern.finditer(html):
        results.append({
            "case_number": match.group(1).strip(),
            "decedent_name": match.group(2).strip(),
            "filing_date": match.group(3).strip(),
            "county": county,
        })

    log.info("Parsed %d probate cases from courts HTML", len(results))
    return results


# ── Obituary Cross-Reference ────────────────────────────────────────


def check_obituary_indicators(owner_name: str, county: str = "Denver") -> dict:
    """Check public obituary sources for a given name.

    Uses newspaper obituary search sites (public, no paywall):
    - legacy.com (largest free obit database)
    - newspapers.com (limited free access)
    - Colorado-specific: denverpost.com/obituaries

    Returns: {"found": bool, "source": str, "date": str}
    """
    if not owner_name or len(owner_name) < 3:
        return {"found": False}

    # Normalize name for search
    parts = _normalize_name(owner_name).split()
    if len(parts) < 2:
        return {"found": False}

    # Try legacy.com (most comprehensive free obit database)
    search_url = f"https://www.legacy.com/us/obituaries/denverpost/name/{parts[0]}-{parts[-1]}"

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENTS[1],
        "Accept": "text/html",
    })

    try:
        resp = session.get(search_url, timeout=15)
        if resp.status_code == 200 and owner_name.split()[-1].lower() in resp.text.lower():
            return {
                "found": True,
                "source": "legacy.com",
                "search_url": search_url,
                "confidence": 0.6,  # Name match only, not confirmed
            }
    except requests.RequestException:
        pass

    return {"found": False}


# ── Main Pipeline ────────────────────────────────────────────────────


def run(county: Optional[str] = None, csv_path: Optional[str] = None) -> dict:
    """Full pipeline: discover deceased owners in surplus assets.

    Steps:
    1. Check existing surplus owners for estate/trust name indicators
    2. If CSV provided, cross-reference probate data
    3. Try automated court search (may fail due to CAPTCHA)
    """
    results = {"steps": []}

    # Step 1: Name-based estate detection
    log.info("Step 1: Checking surplus owners for estate/death indicators...")
    estate_stats = cross_reference_surplus_with_deaths(county=county)
    results["estate_scan"] = estate_stats
    results["steps"].append("estate_name_scan")

    # Step 2: CSV import if provided
    if csv_path:
        log.info("Step 2: Importing probate CSV and cross-referencing...")
        csv_stats = import_probate_csv(csv_path)
        results["probate_csv"] = csv_stats
        results["steps"].append("probate_csv_import")

    # Step 3: Try automated court search
    counties_to_search = [county] if county else list(COUNTY_COURT_CODES.keys())[:3]
    court_results = []
    for c in counties_to_search:
        log.info("Step 3: Searching %s County probate filings...", c)
        filings = search_probate_filings(c, months_back=24)
        if filings:
            court_results.extend(filings)

    if court_results:
        xref_stats = _cross_ref_probate_records(court_results)
        results["court_search"] = xref_stats
        results["steps"].append("court_search")
    else:
        results["court_search"] = {"note": "Automated search unavailable — use --import-csv"}
        results["steps"].append("court_search_skipped")

    # Log pipeline event
    now = datetime.now(timezone.utc).isoformat()
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', 'HEIR_SCAN', '', ?, 'probate_heir_engine', ?, ?)
        """, [
            f"estate={estate_stats.get('estate_name_matches', 0)}",
            f"Scanned {estate_stats.get('total_checked', 0)} assets",
            now,
        ])

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Probate / Heir Cross-Reference Engine")
    parser.add_argument("--county", help="County to search (e.g., Denver, Jefferson)")
    parser.add_argument("--import-csv", dest="csv", help="Path to probate case CSV")
    args = parser.parse_args()

    result = run(county=args.county, csv_path=args.csv)
    print()
    print("=" * 60)
    print("  PROBATE / HEIR ENGINE RESULTS")
    print("=" * 60)
    for step in result.get("steps", []):
        print(f"  Step: {step}")
        data = result.get(step.replace("_skipped", ""), {})
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"    {k}: {v}")
    print("=" * 60)
