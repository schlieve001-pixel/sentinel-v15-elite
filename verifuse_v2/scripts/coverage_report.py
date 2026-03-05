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
    """Generate coverage report data.

    Uses ingestion_runs table (written by ingest_runner) for actual run history.
    pipeline_events only contains CASE_PACKET_GENERATED events, not scraper runs.
    """
    counties = load_counties()
    conn = _get_conn()

    # Query lead counts per county
    county_lead_counts: dict[str, int] = {}
    try:
        lead_rows = conn.execute(
            "SELECT LOWER(county) as county, COUNT(*) as cnt FROM leads GROUP BY LOWER(county)"
        ).fetchall()
        for row in lead_rows:
            county_lead_counts[row["county"]] = row["cnt"]
    except Exception as e:
        log.warning("Could not query lead counts: %s", e)

    # Grade breakdown per county for richer display
    county_grades: dict[str, dict] = {}
    try:
        grade_rows = conn.execute("""
            SELECT LOWER(county) as county, data_grade, COUNT(*) as cnt
            FROM leads GROUP BY LOWER(county), data_grade
        """).fetchall()
        for row in grade_rows:
            c = row["county"]
            if c not in county_grades:
                county_grades[c] = {"GOLD": 0, "SILVER": 0, "BRONZE": 0, "REJECT": 0}
            county_grades[c][row["data_grade"]] = row["cnt"]
    except Exception as e:
        log.warning("Could not query grade breakdown: %s", e)

    # Query ingestion_runs for last run per county + 24h activity
    # ingestion_runs.start_ts is a Unix epoch integer
    epoch_24h_ago = int(datetime.now(timezone.utc).timestamp()) - 86400
    ingestion_by_county: dict[str, dict] = {}
    try:
        run_rows = conn.execute("""
            SELECT county, MAX(start_ts) as last_ts, status, cases_processed, cases_failed, notes
            FROM ingestion_runs
            GROUP BY county
            ORDER BY last_ts DESC
        """).fetchall()
        for row in run_rows:
            ingestion_by_county[row["county"].lower()] = dict(row)
    except Exception as e:
        log.warning("Could not query ingestion_runs: %s", e)

    # Also get 24h run counts per county
    ran_24h_counties: set[str] = set()
    try:
        recent_rows = conn.execute(
            "SELECT DISTINCT county FROM ingestion_runs WHERE start_ts >= ?",
            [epoch_24h_ago],
        ).fetchall()
        for row in recent_rows:
            ran_24h_counties.add(row["county"].lower())
    except Exception as e:
        log.warning("Could not query recent ingestion_runs: %s", e)

    # Build report rows
    report = []
    for county_cfg in counties:
        code = county_cfg.get("code", "").lower()
        name = county_cfg.get("name", "")
        enabled = county_cfg.get("enabled", False)
        platform = county_cfg.get("platform", "unknown")

        run_info = ingestion_by_county.get(code, {})
        ran_24h = code in ran_24h_counties
        last_ts = run_info.get("last_ts")
        last_run = (
            datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
            if last_ts else None
        )
        cases_processed = run_info.get("cases_processed", 0) or 0
        cases_failed = run_info.get("cases_failed", 0) or 0
        last_status = run_info.get("status", "")
        last_error = (
            f"status={last_status}, failed={cases_failed}"
            if last_status in ("FAILED", "PARTIAL", "FAILED_STALE") and cases_failed
            else None
        )
        found_zero_24h = ran_24h and cases_processed == 0
        # Only mark silent if enabled AND has a GovSoft/real scraper built
        # (county_page platform counties are research-only, not yet automated)
        has_active_scraper = platform in ("gts", "realforeclose", "govsoft")
        silent_24h = enabled and has_active_scraper and not ran_24h

        grades = county_grades.get(code, {})
        leads_count = county_lead_counts.get(code, 0)
        report.append({
            "county_code": code,
            "county": name or code,
            "name": name,
            "enabled": enabled,
            "active": enabled,
            "platform": platform,
            "platform_type": platform,
            "last_run": last_run,
            "last_scraped_at": last_run,
            "leads_count": leads_count,
            "gold": grades.get("GOLD", 0),
            "silver": grades.get("SILVER", 0),
            "bronze": grades.get("BRONZE", 0),
            "cases_processed": cases_processed,
            "cases_failed": cases_failed,
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
