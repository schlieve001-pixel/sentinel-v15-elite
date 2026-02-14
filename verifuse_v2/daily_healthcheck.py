"""
VERIFUSE V2 — Daily Self-Healing Health Check

Runs every morning via cron. Performs:
  1. Database integrity verification
  2. Re-grades all assets (deadlines shift daily)
  3. Auto-scrapes Denver excess funds PDFs
  4. Flags expired deadlines → CLOSED
  5. Promotes high-quality leads → ATTORNEY
  6. Generates summary report

Usage:
  python -m verifuse_v2.daily_healthcheck
  # Or via cron: 0 6 * * * cd /path/to/continuity_lab && python -m verifuse_v2.daily_healthcheck >> /var/log/verifuse_healthcheck.log 2>&1

Schedule: Daily at 6:00 AM MT (recommended)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verifuse_v2.db import database as db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).resolve().parent / "data" / "reports"
MIN_SURPLUS = 1000.0


def check_db_integrity() -> dict:
    """Verify database is accessible and tables exist."""
    result = {"status": "OK", "issues": []}
    try:
        db.init_db()
        with db.get_db() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            required = ["assets", "legal_status", "users", "unlocks", "pipeline_events"]
            for t in required:
                if t not in tables:
                    result["issues"].append(f"Missing table: {t}")
                    result["status"] = "DEGRADED"

            asset_count = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            if asset_count == 0:
                result["issues"].append("No assets in database")
                result["status"] = "CRITICAL"
            result["asset_count"] = asset_count
    except Exception as e:
        result["status"] = "CRITICAL"
        result["issues"].append(f"Database error: {e}")
    return result


def compute_confidence(surplus: float, indebtedness: float, sale_date: str | None,
                       owner: str, address: str) -> float:
    """Compute confidence score with proper penalties for missing data.

    Rules:
    - Missing total_indebtedness (= 0 when surplus > 0): max 0.5
    - Missing sale_date: max 0.6
    - Both missing: max 0.4
    - Base confidence from data completeness
    """
    base = 0.95  # Government PDF data starts high

    has_indebtedness = indebtedness > 0
    has_sale_date = bool(sale_date)
    has_owner = bool(owner)
    has_address = bool(address)

    # Penalize missing indebtedness — this is the key forensic field
    if not has_indebtedness and surplus > 0:
        base = min(base, 0.5)

    # Penalize missing sale_date
    if not has_sale_date:
        base = min(base, 0.6)

    # Completeness penalties
    if not has_owner:
        base *= 0.8
    if not has_address:
        base *= 0.9

    return round(base, 2)


def compute_grade(surplus: float, indebtedness: float, sale_date: str | None,
                  days_remaining: int | None, confidence: float,
                  completeness: float) -> tuple[str, str]:
    """Compute (data_grade, record_class) with proper gating.

    GOLD requires ALL of:
    - surplus > $1,000
    - total_indebtedness present (> 0)
    - sale_date present
    - confidence >= 0.7
    - completeness >= 1.0
    - days_remaining > 30
    """
    has_indebtedness = indebtedness > 0

    # Expired deadlines → REJECT
    if days_remaining is not None and days_remaining <= 0:
        return "REJECT", "CLOSED"

    # No meaningful surplus → REJECT
    if surplus < MIN_SURPLUS:
        return "REJECT", "CLOSED"

    # GOLD: fully verified, actionable
    if (surplus >= MIN_SURPLUS
            and has_indebtedness
            and sale_date
            and confidence >= 0.7
            and completeness >= 1.0
            and days_remaining is not None
            and days_remaining > 30):
        return "GOLD", "ATTORNEY"

    # SILVER: good data but missing something for GOLD
    if (surplus >= MIN_SURPLUS
            and days_remaining is not None
            and days_remaining > 0
            and confidence >= 0.5):
        record_class = "ATTORNEY" if completeness >= 1.0 else "QUALIFIED"
        return "SILVER", record_class

    # BRONZE: has surplus but incomplete
    if surplus >= MIN_SURPLUS:
        return "BRONZE", "PIPELINE"

    return "REJECT", "CLOSED"


def regrade_all_assets() -> dict:
    """Re-evaluate all assets: update days_remaining, grades, and classes."""
    stats = {"total": 0, "promoted": 0, "closed": 0, "unchanged": 0}
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT a.asset_id, a.sale_date, a.estimated_surplus, a.owner_of_record,
                   a.property_address, a.completeness_score, ls.record_class, ls.data_grade,
                   a.total_indebtedness
            FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
        """).fetchall()

        for row in rows:
            stats["total"] += 1
            asset_id = row[0]
            sale_date = row[1]
            surplus = row[2] or 0
            owner = row[3] or ""
            address = row[4] or ""
            completeness = row[5] or 0
            old_class = row[6]
            old_grade = row[7]
            indebtedness = row[8] or 0

            # Compute days remaining
            days_remaining = None
            if sale_date:
                try:
                    dt = datetime.fromisoformat(sale_date)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    deadline = dt + timedelta(days=180)
                    days_remaining = (deadline - now).days
                except (ValueError, TypeError):
                    pass

            # Compute completeness
            completeness = 1.0 if all([owner, address, sale_date]) else 0.5

            # Compute confidence with penalties for missing data
            confidence = compute_confidence(surplus, indebtedness, sale_date, owner, address)

            # Grade logic with proper gating
            new_grade, new_class = compute_grade(
                surplus, indebtedness, sale_date, days_remaining, confidence, completeness
            )

            if new_grade == old_grade and new_class == old_class:
                stats["unchanged"] += 1
                continue

            # Update
            promoted_at = now_iso if new_class == "ATTORNEY" and old_class != "ATTORNEY" else None
            closed_at = now_iso if new_class == "CLOSED" and old_class != "CLOSED" else None
            close_reason = "healthcheck:deadline_expired" if new_class == "CLOSED" else None

            conn.execute("""
                UPDATE assets SET days_remaining = ?, completeness_score = ?,
                    confidence_score = ?, data_grade = ?, updated_at = ?
                WHERE asset_id = ?
            """, [days_remaining, completeness, confidence, new_grade, now_iso, asset_id])

            conn.execute("""
                UPDATE legal_status SET record_class = ?, data_grade = ?,
                    days_remaining = ?, last_evaluated_at = ?,
                    promoted_at = COALESCE(?, promoted_at),
                    closed_at = COALESCE(?, closed_at),
                    close_reason = COALESCE(?, close_reason)
                WHERE asset_id = ?
            """, [new_class, new_grade, days_remaining, now_iso,
                  promoted_at, closed_at, close_reason, asset_id])

            if new_class == "ATTORNEY" and old_class != "ATTORNEY":
                stats["promoted"] += 1
                log.info("PROMOTED %s: %s → ATTORNEY (surplus: $%.2f)", asset_id, old_class, surplus)
            elif new_class == "CLOSED" and old_class != "CLOSED":
                stats["closed"] += 1
                log.info("CLOSED %s: deadline expired", asset_id)

            # Log event
            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES (?, 'REGRADE', ?, ?, 'daily_healthcheck', ?, ?)
            """, [asset_id, f"{old_grade}/{old_class}", f"{new_grade}/{new_class}",
                  f"Days remaining: {days_remaining}", now_iso])

    return stats


def scrape_denver() -> dict:
    """Attempt to download and parse the latest Denver excess funds PDF."""
    try:
        from verifuse_v2.scrapers.denver_pdf_parser import run
        result = run()
        if "error" in result:
            log.warning("Denver scrape issue: %s", result["error"])
        else:
            log.info("Denver scrape: %d inserted, %d updated",
                     result.get("inserted", 0), result.get("updated", 0))
        return result
    except Exception as e:
        log.error("Denver scrape failed: %s", e)
        return {"error": str(e)}


def _run_heir_scan() -> dict:
    """Run the probate/heir cross-reference engine."""
    try:
        from verifuse_v2.scrapers.probate_heir_engine import cross_reference_surplus_with_deaths
        result = cross_reference_surplus_with_deaths()
        log.info("  Heir scan: %d checked, %d estate matches",
                 result.get("total_checked", 0), result.get("estate_name_matches", 0))
        return result
    except Exception as e:
        log.error("Heir scan failed: %s", e)
        return {"error": str(e)}


def generate_report(db_check: dict, regrade: dict, denver: dict, heir_scan: dict | None = None) -> Path:
    """Generate a daily summary report."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    filename = f"healthcheck_{now.strftime('%Y-%m-%d_%H%M')}.json"
    path = REPORT_DIR / filename

    with db.get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE estimated_surplus >= ?",
            [MIN_SURPLUS],
        ).fetchone()[0]
        total_surplus = conn.execute(
            "SELECT COALESCE(SUM(estimated_surplus), 0) FROM assets WHERE estimated_surplus >= ?",
            [MIN_SURPLUS],
        ).fetchone()[0]
        gold = conn.execute(
            "SELECT COUNT(*) FROM legal_status WHERE data_grade = 'GOLD'"
        ).fetchone()[0]
        attorney = conn.execute(
            "SELECT COUNT(*) FROM legal_status WHERE record_class = 'ATTORNEY'"
        ).fetchone()[0]
        closed = conn.execute(
            "SELECT COUNT(*) FROM legal_status WHERE record_class = 'CLOSED'"
        ).fetchone()[0]
        staged = 0
        try:
            staged = conn.execute("SELECT COUNT(*) FROM assets_staging").fetchone()[0]
        except Exception:
            pass

    report = {
        "timestamp": now.isoformat(),
        "database": db_check,
        "regrading": regrade,
        "denver_scrape": denver,
        "heir_scan": heir_scan or {},
        "current_state": {
            "quality_assets": total,
            "total_surplus": round(total_surplus, 2),
            "gold_grade": gold,
            "attorney_ready": attorney,
            "closed": closed,
            "staged_for_enrichment": staged,
        },
    }

    path.write_text(json.dumps(report, indent=2))
    log.info("Report saved: %s", path)
    return path


def run():
    """Full daily health check pipeline."""
    log.info("=" * 60)
    log.info("  VERIFUSE V2 — DAILY HEALTH CHECK")
    log.info("=" * 60)

    # Step 1: Database integrity
    log.info("[1/4] Checking database integrity...")
    db_check = check_db_integrity()
    log.info("  DB status: %s | Assets: %d | Issues: %d",
             db_check["status"], db_check.get("asset_count", 0), len(db_check["issues"]))

    if db_check["status"] == "CRITICAL":
        log.critical("DATABASE CRITICAL — aborting health check")
        return

    # Step 1b: Deduplicate assets
    log.info("[1b/6] Deduplicating assets...")
    dedup = db.deduplicate_assets()
    log.info("  Duplicates: %d found, %d removed",
             dedup.get("duplicates_found", 0), dedup.get("records_removed", 0))

    # Step 2: Re-grade all assets
    log.info("[2/6] Re-grading all assets...")
    regrade = regrade_all_assets()
    log.info("  Total: %d | Promoted: %d | Closed: %d | Unchanged: %d",
             regrade["total"], regrade["promoted"], regrade["closed"], regrade["unchanged"])

    # Step 3: Scrape Denver
    log.info("[3/6] Scraping Denver excess funds...")
    denver = scrape_denver()

    # Step 4: Heir/probate cross-reference
    log.info("[4/6] Scanning for deceased owner indicators...")
    heir_scan = _run_heir_scan()

    # Step 5: Great Colorado Payback cross-reference (skip HTTP — just log)
    log.info("[5/6] Payback matcher ready (run manually: python -m verifuse_v2.scrapers.payback_matcher)")
    payback = {"status": "manual", "note": "Run --scan-all to search unclaimed property database"}

    # Step 6: Generate report
    log.info("[6/6] Generating report...")
    report_path = generate_report(db_check, regrade, denver, heir_scan=heir_scan)

    log.info("=" * 60)
    log.info("  HEALTH CHECK COMPLETE")
    log.info("  Report: %s", report_path)
    log.info("=" * 60)


if __name__ == "__main__":
    run()
