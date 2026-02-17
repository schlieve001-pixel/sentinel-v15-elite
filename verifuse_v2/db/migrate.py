"""
VERIFUSE V2 — Migration Script

Migrates V1 SQLite (verifuse_vault.db) → V2 database.
Applies scoring fixes during migration:
  1. Gate GOLD on surplus > $1,000
  2. Demote Jefferson $0-surplus from GOLD → BRONZE
  3. Re-evaluate all grades and classes
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

V1_DB = Path(__file__).resolve().parent.parent.parent / "verifuse" / "data" / "verifuse_vault.db"
V2_DB = Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"

SURPLUS_FLOOR = 1000.0  # Minimum surplus for GOLD grade


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def regrade(row: dict) -> tuple[str, str]:
    """Apply corrected scoring to produce (data_grade, record_class).

    Fixes:
    - GOLD requires surplus > $1,000
    - GOLD requires days_remaining > 30
    - GOLD requires completeness == 1.0 AND confidence >= 0.8
    - Assets with NULL days_remaining cannot be ATTORNEY
    """
    surplus = row.get("estimated_surplus") or 0.0
    completeness = row.get("completeness_score") or 0.0
    confidence = row.get("confidence_score") or 0.0
    days = row.get("days_remaining")
    risk = row.get("risk_score") or 0.0

    # Data grade
    if days is not None and days <= 0:
        grade = "REJECT"
    elif confidence < 0.3:
        grade = "REJECT"
    elif (completeness >= 1.0 and confidence >= 0.8
          and days is not None and days > 30
          and surplus >= SURPLUS_FLOOR):
        grade = "GOLD"
    elif (completeness >= 1.0 and confidence >= 0.5
          and days is not None and days > 0
          and surplus > 0):
        grade = "SILVER"
    elif completeness < 1.0:
        grade = "BRONZE"
    else:
        grade = "BRONZE"

    # Record class
    if grade == "REJECT":
        record_class = "CLOSED"
    elif grade in ("GOLD", "SILVER") and days is not None and days > 0:
        record_class = "ATTORNEY"
    elif completeness >= 1.0:
        record_class = "QUALIFIED"
    else:
        record_class = "PIPELINE"

    return grade, record_class


def migrate() -> dict:
    """Run the full migration. Returns summary stats."""
    if not V1_DB.exists():
        log.error("V1 database not found at %s", V1_DB)
        return {"error": f"V1 database not found at {V1_DB}"}

    log.info("Source: %s", V1_DB)
    log.info("Target: %s", V2_DB)

    # Connect to both databases
    v1 = sqlite3.connect(str(V1_DB))
    v1.row_factory = sqlite3.Row

    V2_DB.parent.mkdir(parents=True, exist_ok=True)
    v2 = sqlite3.connect(str(V2_DB))
    v2.row_factory = sqlite3.Row
    v2.executescript(SCHEMA.read_text())

    stats = {
        "assets_migrated": 0,
        "grade_changes": 0,
        "class_changes": 0,
        "gold_before": 0,
        "gold_after": 0,
        "attorney_before": 0,
        "attorney_after": 0,
        "surplus_floor_applied": 0,
        "events_migrated": 0,
        "statutes_migrated": 0,
        "scrapers_migrated": 0,
    }

    # ── Migrate statute_authority ─────────────────────────────────
    log.info("Migrating statute_authority...")
    rows = v1.execute("SELECT * FROM statute_authority").fetchall()
    for r in rows:
        d = dict(r)
        try:
            v2.execute("""
                INSERT OR REPLACE INTO statute_authority
                (jurisdiction, state, county, asset_type, statute_years,
                 triggering_event, statute_citation, fee_cap_pct, fee_cap_flat,
                 requires_court, known_issues, verified_date, verified_by, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [d["jurisdiction"], d["state"], d["county"], d["asset_type"],
                  d["statute_years"], d.get("triggering_event"), d.get("statute_citation"),
                  None, None,  # fee_cap_pct/flat DEPRECATED (Sprint 11)
                  d.get("requires_court", 0),
                  d.get("known_issues"), d.get("verified_date"), d.get("verified_by"),
                  d.get("confidence", 1.0)])
            stats["statutes_migrated"] += 1
        except sqlite3.IntegrityError:
            pass
    log.info("  %d statute rules migrated", stats["statutes_migrated"])

    # ── Migrate scraper_registry ─────────────────────────────────
    log.info("Migrating scraper_registry...")
    rows = v1.execute("SELECT * FROM scraper_registry").fetchall()
    for r in rows:
        d = dict(r)
        try:
            v2.execute("""
                INSERT OR REPLACE INTO scraper_registry
                (scraper_name, jurisdiction, record_type, fields_collected, known_gaps,
                 update_frequency_days, legal_confidence, last_run_at, last_run_status,
                 records_produced, enabled, disabled_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, [d["scraper_name"], d.get("jurisdiction"), d.get("record_type"),
                  d.get("fields_collected"), d.get("known_gaps"),
                  d.get("update_frequency_days", 7), d.get("legal_confidence", 0.7),
                  d.get("last_run_at"), d.get("last_run_status"),
                  d.get("records_produced", 0), d.get("enabled", 1),
                  d.get("disabled_reason")])
            stats["scrapers_migrated"] += 1
        except sqlite3.IntegrityError:
            pass
    log.info("  %d scrapers migrated", stats["scrapers_migrated"])

    # ── Migrate assets + legal_status (with re-grading) ──────────
    log.info("Migrating assets with scoring fixes...")
    asset_rows = v1.execute("SELECT * FROM assets").fetchall()
    legal_rows = v1.execute("SELECT * FROM legal_status").fetchall()
    legal_map = {dict(r)["asset_id"]: dict(r) for r in legal_rows}

    for r in asset_rows:
        d = dict(r)
        old_legal = legal_map.get(d["asset_id"], {})
        old_grade = old_legal.get("data_grade", "BRONZE")
        old_class = old_legal.get("record_class", "PIPELINE")

        if old_grade == "GOLD":
            stats["gold_before"] += 1
        if old_class == "ATTORNEY":
            stats["attorney_before"] += 1

        # Apply corrected grading
        new_grade, new_class = regrade(d)

        if old_grade != new_grade:
            stats["grade_changes"] += 1
        if old_class != new_class:
            stats["class_changes"] += 1
        if old_grade == "GOLD" and new_grade != "GOLD":
            stats["surplus_floor_applied"] += 1

        if new_grade == "GOLD":
            stats["gold_after"] += 1
        if new_class == "ATTORNEY":
            stats["attorney_after"] += 1

        # Update the data_grade in asset record
        d["data_grade"] = new_grade

        # Insert asset
        cols = [
            "asset_id", "county", "state", "jurisdiction", "case_number",
            "asset_type", "source_name", "statute_window", "days_remaining",
            "owner_of_record", "property_address", "lien_type", "sale_date",
            "redemption_date", "recorder_link", "estimated_surplus",
            "total_indebtedness", "overbid_amount", "fee_cap",
            "completeness_score", "confidence_score", "risk_score", "data_grade",
            "record_hash", "source_file_hash", "source_file",
            "created_at", "updated_at",
        ]
        vals = [d.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        v2.execute(f"INSERT OR REPLACE INTO assets ({col_names}) VALUES ({placeholders})", vals)

        # Insert legal_status
        close_reason = None
        closed_at = None
        if new_class == "CLOSED":
            if new_grade == "REJECT":
                close_reason = "kill_switch:data_grade_reject"
            elif d.get("days_remaining") is not None and d["days_remaining"] <= 0:
                close_reason = "kill_switch:statute_expired"
            else:
                close_reason = old_legal.get("close_reason", "kill_switch:data_grade_reject")
            closed_at = old_legal.get("closed_at") or _now()

        promoted_at = None
        if new_class == "ATTORNEY":
            promoted_at = old_legal.get("promoted_at") or _now()

        v2.execute("""
            INSERT OR REPLACE INTO legal_status
            (asset_id, record_class, data_grade, days_remaining, statute_window,
             work_status, attorney_id, last_evaluated_at, promoted_at, closed_at, close_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [d["asset_id"], new_class, new_grade, d.get("days_remaining"),
              d.get("statute_window"), old_legal.get("work_status"),
              old_legal.get("attorney_id"), _now(), promoted_at, closed_at, close_reason])

        stats["assets_migrated"] += 1

    # ── Migrate pipeline_events ──────────────────────────────────
    log.info("Migrating pipeline events...")
    events = v1.execute("SELECT * FROM pipeline_events").fetchall()
    for r in events:
        d = dict(r)
        v2.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, metadata_json, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, [d["asset_id"], d["event_type"], d.get("old_value"), d.get("new_value"),
              d.get("actor", "system"), d.get("reason"), d.get("metadata_json"),
              d["created_at"]])
        stats["events_migrated"] += 1
    log.info("  %d events migrated", stats["events_migrated"])

    # Log the migration itself as an event
    v2.execute("""
        INSERT INTO pipeline_events (asset_id, event_type, old_value, new_value, actor, reason, created_at)
        VALUES ('SYSTEM', 'MIGRATION', 'v1_sqlite', 'v2_sqlite', 'migrate.py', ?, ?)
    """, [f"Migrated {stats['assets_migrated']} assets, {stats['grade_changes']} grade changes", _now()])

    v2.commit()
    v1.close()
    v2.close()

    # ── Report ───────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("  MIGRATION COMPLETE")
    log.info("=" * 60)
    log.info("  Assets migrated:       %d", stats["assets_migrated"])
    log.info("  Grade changes:         %d", stats["grade_changes"])
    log.info("  Class changes:         %d", stats["class_changes"])
    log.info("  GOLD before:           %d", stats["gold_before"])
    log.info("  GOLD after:            %d  (surplus floor $%.0f applied)",
             stats["gold_after"], SURPLUS_FLOOR)
    log.info("  Demoted from GOLD:     %d", stats["surplus_floor_applied"])
    log.info("  ATTORNEY before:       %d", stats["attorney_before"])
    log.info("  ATTORNEY after:        %d", stats["attorney_after"])
    log.info("  Events migrated:       %d", stats["events_migrated"])
    log.info("  Statutes migrated:     %d", stats["statutes_migrated"])
    log.info("  Scrapers migrated:     %d", stats["scrapers_migrated"])
    log.info("  Database:              %s", V2_DB)
    log.info("=" * 60)

    return stats


if __name__ == "__main__":
    migrate()
