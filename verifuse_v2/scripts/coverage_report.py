"""
VERIFUSE V2 — Coverage Report
================================
Scraper coverage diagnostics. Shows which counties ran, what they found,
and which are silent or empty.

Usage:
    python -m verifuse_v2.scripts.coverage_report
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "counties.yaml"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_counties() -> list[dict]:
    """Load county configurations from YAML."""
    if not CONFIG_PATH.exists():
        log.error("counties.yaml not found at %s", CONFIG_PATH)
        return []
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("counties", data) if isinstance(data, dict) else data


def _detect_time_col(conn: sqlite3.Connection) -> str:
    """Detect time column name in pipeline_events."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pipeline_events)").fetchall()}
    if "created_at" in cols:
        return "created_at"
    if "timestamp" in cols:
        return "timestamp"
    return "created_at"  # fallback


def generate_report() -> list[dict]:
    """Generate coverage report data."""
    counties = load_counties()
    conn = _get_conn()
    time_col = _detect_time_col(conn)

    # Query all scrape events from last 24h
    events_query = f"""
        SELECT asset_id, event_type, reason, metadata_json, {time_col} as event_time
        FROM pipeline_events
        WHERE event_type IN ('COUNTY_SCRAPE_RESULT', 'COUNTY_SCRAPE_ERROR',
                             'SCRAPER_SUCCESS', 'SCRAPER_ERROR')
          AND {time_col} >= datetime('now', '-24 hours')
        ORDER BY {time_col} DESC
    """
    try:
        events = conn.execute(events_query).fetchall()
    except Exception as e:
        log.warning("Could not query pipeline_events: %s", e)
        events = []

    # Index events by county code
    events_by_county: dict[str, list[dict]] = {}
    for ev in events:
        asset_id = ev["asset_id"] or ""
        # Extract county code from asset_id like "SCRAPER:denver"
        code = asset_id.replace("SCRAPER:", "").lower() if "SCRAPER:" in asset_id else asset_id.lower()
        if code not in events_by_county:
            events_by_county[code] = []
        events_by_county[code].append(dict(ev))

    # Build report rows
    report = []
    for county_cfg in counties:
        code = county_cfg.get("code", "").lower()
        name = county_cfg.get("name", "")
        enabled = county_cfg.get("enabled", False)
        platform = county_cfg.get("platform", "unknown")

        county_events = events_by_county.get(code, [])
        ran_24h = len(county_events) > 0
        last_run = None
        duration_sec = None
        pdfs_found = 0
        pdfs_downloaded = 0
        parsed = 0
        inserted = 0
        rejects = 0
        last_error = None
        found_zero_24h = False

        if county_events:
            # Most recent event
            latest = county_events[0]
            last_run = latest.get("event_time")

            # Parse metadata_json if available
            meta_str = latest.get("metadata_json")
            if meta_str:
                try:
                    meta = json.loads(meta_str)
                    duration_sec = meta.get("duration_sec")
                    pdfs_found = meta.get("pdfs_found", 0)
                    pdfs_downloaded = meta.get("pdfs_downloaded", 0)
                    parsed = meta.get("parsed_records", 0)
                    inserted = meta.get("leads_inserted", 0)
                    rejects = meta.get("rejects", 0)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Check for errors
            for ev in county_events:
                if ev.get("event_type") in ("COUNTY_SCRAPE_ERROR", "SCRAPER_ERROR"):
                    last_error = ev.get("reason", "Unknown error")
                    break

            # found_zero: ran but pdfs_found=0
            found_zero_24h = ran_24h and pdfs_found == 0

        silent_24h = enabled and not ran_24h

        report.append({
            "county_code": code,
            "name": name,
            "enabled": enabled,
            "platform": platform,
            "last_run": last_run,
            "duration_sec": duration_sec,
            "pdfs_found": pdfs_found,
            "pdfs_downloaded": pdfs_downloaded,
            "parsed": parsed,
            "inserted": inserted,
            "rejects": rejects,
            "last_error": last_error,
            "ran_24h": ran_24h,
            "found_zero_24h": found_zero_24h,
            "silent_24h": silent_24h,
        })

    conn.close()
    return report


def print_report(report: list[dict]) -> None:
    """Print formatted coverage report."""
    print("=" * 120)
    print("  VERIFUSE — SCRAPER COVERAGE REPORT")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 120)

    # Header
    print(f"  {'County':<15s} {'Enabled':<8s} {'Platform':<15s} {'Last Run':<22s} "
          f"{'Dur(s)':<8s} {'PDFs':<6s} {'DL':<6s} {'Parsed':<8s} {'Insert':<8s} "
          f"{'Reject':<8s} {'Error'}")
    print("-" * 120)

    enabled_count = 0
    ran_count = 0
    silent_counties = []
    empty_counties = []

    for r in report:
        if r["enabled"]:
            enabled_count += 1
        if r["ran_24h"]:
            ran_count += 1
        if r["silent_24h"]:
            silent_counties.append(r)
        if r["found_zero_24h"]:
            empty_counties.append(r)

        enabled_str = "YES" if r["enabled"] else "no"
        last_run_str = (r["last_run"] or "—")[:20]
        dur_str = str(r["duration_sec"]) if r["duration_sec"] is not None else "—"
        error_str = (r["last_error"] or "—")[:30]

        print(f"  {r['county_code']:<15s} {enabled_str:<8s} {r['platform']:<15s} "
              f"{last_run_str:<22s} {dur_str:<8s} {r['pdfs_found']:<6d} "
              f"{r['pdfs_downloaded']:<6d} {r['parsed']:<8d} {r['inserted']:<8d} "
              f"{r['rejects']:<8d} {error_str}")

    print("-" * 120)
    print(f"  Total: {len(report)} counties, {enabled_count} enabled, {ran_count} ran in last 24h")

    # Silent Counties
    if silent_counties:
        print("\n  SILENT COUNTIES (enabled but no events in 24h):")
        for r in silent_counties:
            print(f"    - {r['county_code']} ({r['platform']})")

    # Empty Counties
    if empty_counties:
        print("\n  EMPTY COUNTIES (ran but found 0 PDFs):")
        for r in empty_counties:
            print(f"    - {r['county_code']} ({r['platform']})")

    print("=" * 120)


def main():
    report = generate_report()
    print_report(report)


if __name__ == "__main__":
    main()
