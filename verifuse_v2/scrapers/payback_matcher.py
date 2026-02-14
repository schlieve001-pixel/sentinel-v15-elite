"""
VERIFUSE V2 — Great Colorado Payback Matcher

Cross-references surplus asset owner names against the Colorado State
Treasurer's unclaimed property database ("Great Colorado Payback").

The state holds $2B+ in unclaimed property. When foreclosure surplus goes
unclaimed for 6 months (C.R.S. § 38-38-111), it transfers to the State
Treasurer as unclaimed property. This engine:

1. Searches the Great Colorado Payback database for surplus asset owners
2. Identifies owners who may have MULTIPLE unclaimed property claims
3. Creates high-value "bundled" leads (surplus + unclaimed property)

This makes leads MORE valuable because attorneys can:
  - Recover foreclosure surplus AND unclaimed property in one engagement
  - The unclaimed property claim is often simpler (no court filing needed)
  - Combined value justifies the attorney's time on smaller surplus claims

Data source:
  https://colorado.findyourunclaimedproperty.com/

Usage:
  python -m verifuse_v2.scrapers.payback_matcher
  python -m verifuse_v2.scrapers.payback_matcher --name "John Smith"
  python -m verifuse_v2.scrapers.payback_matcher --import-csv /path/to/unclaimed.csv
"""

from __future__ import annotations

import csv
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from verifuse_v2.db import database as db

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# Great Colorado Payback search endpoint
GCP_SEARCH_URL = "https://colorado.findyourunclaimedproperty.com/app/submit-claim"
GCP_API_URL = "https://colorado.findyourunclaimedproperty.com/api"

# Output directory for match results
MATCH_DIR = Path(__file__).resolve().parent.parent / "data" / "payback_matches"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _normalize_name(name: str) -> dict:
    """Parse owner name into first/last components for search.

    Returns: {"first": "JOHN", "last": "SMITH"}
    """
    if not name:
        return {"first": "", "last": ""}

    # Remove estate/trust suffixes
    name = re.sub(r"\b(estate|est\.|trust|llc|inc|corp)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^a-zA-Z\s]", "", name).strip()

    parts = name.split()
    if not parts:
        return {"first": "", "last": ""}

    # Handle "LAST, FIRST" format
    if "," in (name or ""):
        comma_parts = name.split(",", 1)
        return {
            "last": comma_parts[0].strip().upper(),
            "first": comma_parts[1].strip().split()[0].upper() if len(comma_parts) > 1 else "",
        }

    # Handle "FIRST LAST" format
    if len(parts) == 1:
        return {"first": "", "last": parts[0].upper()}

    return {
        "first": parts[0].upper(),
        "last": parts[-1].upper(),
    }


def search_unclaimed_property(last_name: str, first_name: str = "") -> list[dict]:
    """Search the Great Colorado Payback database for unclaimed property.

    Uses the public search interface. Rate-limited to 1 request per 3 seconds.

    Returns list of matches: [{name, amount, property_type, reported_by, id}, ...]
    """
    if not last_name or len(last_name) < 2:
        return []

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENTS[0],
        "Accept": "application/json, text/html",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://colorado.findyourunclaimedproperty.com/",
    })

    # The Great Colorado Payback site uses a specific API format
    # Try the search endpoint
    search_params = {
        "lastName": last_name.upper(),
        "firstName": first_name.upper() if first_name else "",
        "state": "CO",
    }

    try:
        # First get the search page to establish session
        session.get("https://colorado.findyourunclaimedproperty.com/", timeout=15)
        time.sleep(1)

        # Attempt API search
        resp = session.get(
            f"{GCP_API_URL}/search",
            params=search_params,
            timeout=15,
        )

        if resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "results" in data:
                    return data["results"]
            except (json.JSONDecodeError, ValueError):
                pass

        # If API doesn't work, try the form-based search
        resp = session.post(
            "https://colorado.findyourunclaimedproperty.com/app/search",
            data={
                "lastName": last_name.upper(),
                "firstName": first_name.upper() if first_name else "",
            },
            timeout=15,
            allow_redirects=True,
        )

        if resp.status_code == 200 and last_name.upper() in resp.text.upper():
            # Parse HTML results
            return _parse_payback_html(resp.text, last_name)

    except requests.RequestException as e:
        log.debug("Search failed for %s %s: %s", first_name, last_name, e)

    return []


def _parse_payback_html(html: str, last_name: str) -> list[dict]:
    """Parse Great Colorado Payback HTML search results.

    This is fragile — the site may change. Falls back to CSV import.
    """
    results = []

    # Look for result rows with property data
    # Pattern varies by site version — try common patterns
    row_pattern = re.compile(
        r'<tr[^>]*>.*?'
        r'<td[^>]*>([^<]*' + re.escape(last_name) + r'[^<]*)</td>'
        r'.*?<td[^>]*>\$?([\d,]+\.?\d*)</td>'
        r'.*?<td[^>]*>([^<]+)</td>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in row_pattern.finditer(html):
        name = match.group(1).strip()
        amount_str = match.group(2).strip()
        prop_type = match.group(3).strip()

        try:
            amount = float(amount_str.replace(",", ""))
        except ValueError:
            amount = 0.0

        results.append({
            "name": name,
            "amount": amount,
            "property_type": prop_type,
            "source": "great_colorado_payback",
        })

    return results


# ── CSV Import for Unclaimed Property ────────────────────────────────


def import_unclaimed_csv(csv_path: str | Path) -> dict:
    """Import unclaimed property data from CSV and cross-reference with surplus.

    The State Treasurer publishes unclaimed property data periodically.
    You can also export search results from the website.

    Expected columns:
        name (or first_name + last_name), amount, property_type, reported_by
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return {"error": f"File not found: {csv_path}"}

    COLUMN_MAP = {
        "name": "name", "owner": "name", "owner_name": "name",
        "first_name": "first_name", "first": "first_name",
        "last_name": "last_name", "last": "last_name", "surname": "last_name",
        "amount": "amount", "value": "amount", "property_value": "amount",
        "property_type": "property_type", "type": "property_type",
        "reported_by": "reported_by", "holder": "reported_by", "company": "reported_by",
        "id": "claim_id", "property_id": "claim_id",
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

            # Build full name if first/last provided separately
            if mapped.get("first_name") and mapped.get("last_name"):
                mapped["name"] = f"{mapped['first_name']} {mapped['last_name']}"

            if mapped.get("name"):
                records.append(mapped)

    if not records:
        return {"error": "No valid records found"}

    log.info("Parsed %d unclaimed property records from %s", len(records), csv_path.name)
    return _cross_ref_unclaimed(records)


def _cross_ref_unclaimed(unclaimed_records: list[dict]) -> dict:
    """Cross-reference unclaimed property records with surplus assets."""
    db.init_db()
    stats = {
        "total_unclaimed": len(unclaimed_records),
        "matches_found": 0,
        "total_additional_value": 0.0,
        "bundled_leads": 0,
    }

    # Load surplus asset owners
    with db.get_db() as conn:
        assets = conn.execute("""
            SELECT asset_id, owner_of_record, county, estimated_surplus
            FROM assets WHERE estimated_surplus >= 1000
        """).fetchall()

    asset_owners = {}
    for a in assets:
        owner = (a["owner_of_record"] or "").upper().strip()
        # Store by last name for fast lookup
        parts = owner.replace(",", " ").split()
        for part in parts:
            if len(part) >= 3:
                if part not in asset_owners:
                    asset_owners[part] = []
                asset_owners[part].append(dict(a))

    now = datetime.now(timezone.utc).isoformat()

    for rec in unclaimed_records:
        name = rec.get("name", "").upper()
        amount = 0.0
        try:
            amount = float(re.sub(r"[^\d.]", "", str(rec.get("amount", 0))))
        except ValueError:
            pass

        # Check if any surplus asset owner matches
        name_parts = name.replace(",", " ").split()
        matched_assets = set()

        for part in name_parts:
            if part in asset_owners:
                for asset in asset_owners[part]:
                    # Verify full name overlap (not just one word)
                    owner_parts = set(asset["owner_of_record"].upper().replace(",", " ").split())
                    name_set = set(name_parts)
                    overlap = owner_parts & name_set
                    if len(overlap) >= 2:  # At least 2 name parts match
                        matched_assets.add(asset["asset_id"])

        if matched_assets:
            stats["matches_found"] += 1
            stats["total_additional_value"] += amount
            stats["bundled_leads"] += len(matched_assets)

            log.info("MATCH: '%s' has $%.2f unclaimed property + surplus in %d assets",
                     name, amount, len(matched_assets))

            # Flag matched assets as bundled leads
            with db.get_db() as conn:
                for aid in matched_assets:
                    conn.execute("""
                        INSERT INTO pipeline_events
                        (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                        VALUES (?, 'PAYBACK_MATCH', '', ?, 'payback_matcher', ?, ?)
                    """, [
                        aid,
                        f"unclaimed=${amount:.2f}",
                        f"Owner '{name}' has unclaimed property on Great Colorado Payback",
                        now,
                    ])

    log.info("Payback matching: %d matches, $%.2f additional value found",
             stats["matches_found"], stats["total_additional_value"])
    return stats


# ── Bulk Scan ────────────────────────────────────────────────────────


def scan_all_surplus_owners() -> dict:
    """Search the Great Colorado Payback for ALL surplus asset owners.

    WARNING: This makes many HTTP requests. Rate-limited to 1 per 3 seconds.
    For 55 assets, this takes ~3 minutes.
    """
    db.init_db()
    MATCH_DIR.mkdir(parents=True, exist_ok=True)

    with db.get_db() as conn:
        assets = conn.execute("""
            SELECT asset_id, owner_of_record, county, estimated_surplus
            FROM assets WHERE estimated_surplus >= 1000
        """).fetchall()

    stats = {
        "total_searched": 0,
        "matches_found": 0,
        "total_unclaimed_value": 0.0,
        "results": [],
    }

    for asset in assets:
        owner = asset["owner_of_record"] or ""
        if not owner or len(owner) < 3:
            continue

        parsed = _normalize_name(owner)
        if not parsed["last"]:
            continue

        stats["total_searched"] += 1
        log.info("Searching: %s %s (asset=%s, surplus=$%s)...",
                 parsed["first"], parsed["last"],
                 asset["asset_id"], asset["estimated_surplus"])

        matches = search_unclaimed_property(parsed["last"], parsed["first"])

        if matches:
            total_unclaimed = sum(m.get("amount", 0) for m in matches)
            stats["matches_found"] += 1
            stats["total_unclaimed_value"] += total_unclaimed

            result = {
                "asset_id": asset["asset_id"],
                "owner": owner,
                "surplus": asset["estimated_surplus"],
                "unclaimed_matches": len(matches),
                "unclaimed_total": total_unclaimed,
                "matches": matches,
            }
            stats["results"].append(result)

            log.info("  FOUND: %d unclaimed properties worth $%.2f",
                     len(matches), total_unclaimed)

            # Flag in database
            now = datetime.now(timezone.utc).isoformat()
            with db.get_db() as conn:
                conn.execute("""
                    INSERT INTO pipeline_events
                    (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                    VALUES (?, 'PAYBACK_MATCH', '', ?, 'payback_matcher', ?, ?)
                """, [
                    asset["asset_id"],
                    f"{len(matches)} claims, ${total_unclaimed:.2f}",
                    f"Owner has unclaimed property on Great Colorado Payback",
                    now,
                ])

        # Rate limit: 3 seconds between searches
        time.sleep(3)

    # Save results
    if stats["results"]:
        out_path = MATCH_DIR / f"payback_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        out_path.write_text(json.dumps(stats, indent=2, default=str))
        log.info("Results saved: %s", out_path)
        stats["output_file"] = str(out_path)

    log.info("Scan complete: %d/%d owners have unclaimed property ($%.2f total)",
             stats["matches_found"], stats["total_searched"],
             stats["total_unclaimed_value"])
    return stats


# ── Main Pipeline ────────────────────────────────────────────────────


def run(
    name: Optional[str] = None,
    csv_path: Optional[str] = None,
    scan_all: bool = False,
) -> dict:
    """Run the Great Colorado Payback matcher."""
    if name:
        parsed = _normalize_name(name)
        log.info("Searching for: %s %s", parsed["first"], parsed["last"])
        matches = search_unclaimed_property(parsed["last"], parsed["first"])
        return {
            "name": name,
            "matches": matches,
            "total_unclaimed": sum(m.get("amount", 0) for m in matches),
        }

    if csv_path:
        return import_unclaimed_csv(csv_path)

    if scan_all:
        return scan_all_surplus_owners()

    # Default: scan all surplus owners
    log.info("No specific search — scanning all surplus asset owners...")
    return scan_all_surplus_owners()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Great Colorado Payback Matcher")
    parser.add_argument("--name", help="Search for a specific name")
    parser.add_argument("--import-csv", dest="csv", help="Import unclaimed property CSV")
    parser.add_argument("--scan-all", action="store_true", help="Scan all surplus owners")
    args = parser.parse_args()

    result = run(name=args.name, csv_path=args.csv, scan_all=args.scan_all)
    print("\n" + "=" * 60)
    print("  GREAT COLORADO PAYBACK MATCHER RESULTS")
    print("=" * 60)
    for k, v in result.items():
        if k == "results":
            print(f"  {k}: [{len(v)} entries]")
        elif k == "matches" and isinstance(v, list):
            print(f"  {k}: {len(v)} found")
            for m in v[:5]:
                print(f"    - {m}")
        else:
            print(f"  {k}: {v}")
    print("=" * 60)
