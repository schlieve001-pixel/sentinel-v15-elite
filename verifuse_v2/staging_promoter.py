"""
VERIFUSE V2 — Staging Promoter

Promotes assets_staging records into the main assets table.
Two modes:
  1. PDF-linked records → sent to Engine #4 (Vertex AI) for extraction
  2. Portal records (no PDF) → promoted directly with existing data

Also links available PDFs to staging records by matching county/source.

Usage:
  python -m verifuse_v2.staging_promoter                # Promote all portal records
  python -m verifuse_v2.staging_promoter --link-pdfs    # Link PDFs first, then promote
  python -m verifuse_v2.staging_promoter --dry-run      # Show what would be promoted
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from verifuse_v2.db import database as db
from verifuse_v2.daily_healthcheck import compute_confidence, compute_grade

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

RAW_PDF_DIR = Path(__file__).resolve().parent / "data" / "raw_pdfs"

# Map source_name → PDF subdirectory
PDF_SOURCE_MAP = {
    "adams_harvester": "adams",
    "denver_public_trustee_excess_funds": "",  # root level PDFs
    "eagle_portal": "eagle",
    "jefferson_foreclosure": "jefferson",
    "sanmiguel_portal": "sanmiguel",
    "summit_govease": "summit",
    "teller_govease": "teller",
}


def link_pdfs() -> dict:
    """Link available PDFs to staging records by matching county/source."""
    stats = {"linked": 0, "no_pdf": 0}

    with db.get_db() as conn:
        # Get all staged records without pdf_path
        rows = conn.execute("""
            SELECT asset_id, county, source_name, case_number
            FROM assets_staging
            WHERE status = 'STAGED' AND pdf_path IS NULL
        """).fetchall()

    for row in rows:
        asset_id, county, source_name, case_number = row
        subdir = PDF_SOURCE_MAP.get(source_name, county.lower() if county else "")
        pdf_dir = RAW_PDF_DIR / subdir if subdir else RAW_PDF_DIR

        if not pdf_dir.exists():
            stats["no_pdf"] += 1
            continue

        pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not pdfs:
            stats["no_pdf"] += 1
            continue

        # Link to most recent PDF for this county
        pdf_path = str(pdfs[0])
        with db.get_db() as conn:
            conn.execute(
                "UPDATE assets_staging SET pdf_path = ? WHERE asset_id = ?",
                [pdf_path, asset_id],
            )
        stats["linked"] += 1

    log.info("PDF linking: %d linked, %d no PDF available", stats["linked"], stats["no_pdf"])
    return stats


def promote_portal_records(dry_run: bool = False) -> dict:
    """Promote portal records (no PDF needed) directly to assets table."""
    stats = {"total": 0, "promoted": 0, "skipped": 0, "already_exists": 0}
    now = datetime.now(timezone.utc).isoformat()

    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT asset_id, county, state, case_number, owner_of_record,
                   property_address, sale_date, estimated_surplus, source_name
            FROM assets_staging
            WHERE status = 'STAGED'
        """).fetchall()

    stats["total"] = len(rows)
    log.info("Found %d STAGED records to evaluate", len(rows))

    for row in rows:
        (asset_id, county, state, case_number, owner, address,
         sale_date, surplus, source_name) = row

        # Check if already in assets
        existing = db.get_lead_by_id(asset_id)
        if existing:
            stats["already_exists"] += 1
            # Mark staging as processed
            if not dry_run:
                with db.get_db() as conn:
                    conn.execute(
                        "UPDATE assets_staging SET status = 'ALREADY_IN_ASSETS', processed_at = ? WHERE asset_id = ?",
                        [now, asset_id],
                    )
            continue

        # Compute quality metrics
        surplus = surplus or 0.0
        indebtedness = 0.0  # Portal records typically lack this
        days_remaining = None

        if sale_date:
            try:
                dt = datetime.fromisoformat(sale_date)
                deadline = dt + timedelta(days=180)
                days_remaining = (deadline - datetime.now(timezone.utc).replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        completeness = 0.5
        if owner and address and sale_date:
            completeness = 0.8
        if surplus > 0:
            completeness = min(1.0, completeness + 0.2)

        confidence = compute_confidence(surplus, indebtedness, sale_date, owner, address)
        grade = "BRONZE"
        record_class = "PIPELINE"

        if surplus >= 1000 and sale_date and owner:
            grade = "SILVER"
            record_class = "REVIEW"

        if dry_run:
            log.info("  [DRY] %s | %s | $%.2f | %s", asset_id[:30], county, surplus, grade)
            stats["promoted"] += 1
            continue

        with db.get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO assets
                (asset_id, county, state, jurisdiction, case_number, asset_type,
                 source_name, statute_window, days_remaining, owner_of_record,
                 property_address, sale_date, estimated_surplus, overbid_amount,
                 total_indebtedness, completeness_score, confidence_score,
                 data_grade, source_file, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                asset_id, county, state or "CO", f"{(county or 'unknown').lower()}_co",
                case_number, "FORECLOSURE_SURPLUS",
                source_name or "staging_promoter",
                "180 days from sale_date (C.R.S. § 38-38-111)",
                days_remaining, owner, address, sale_date,
                surplus, 0.0, indebtedness,
                completeness, confidence, grade,
                f"staging:{source_name}", now, now,
            ])

            conn.execute("""
                INSERT OR REPLACE INTO legal_status
                (asset_id, record_class, data_grade, days_remaining,
                 statute_window, last_evaluated_at)
                VALUES (?,?,?,?,?,?)
            """, [asset_id, record_class, grade, days_remaining,
                  "180 days from sale_date (C.R.S. § 38-38-111)", now])

            conn.execute(
                "UPDATE assets_staging SET status = 'PROMOTED', processed_at = ?, engine_version = 'staging_promoter' WHERE asset_id = ?",
                [now, asset_id],
            )

        stats["promoted"] += 1

    if not dry_run:
        db.log_pipeline_event(
            "SYSTEM", "STAGING_PROMOTION",
            f"Evaluated {stats['total']} staged records",
            f"Promoted {stats['promoted']}, Already existed {stats['already_exists']}, Skipped {stats['skipped']}",
            actor="staging_promoter",
        )

    log.info("Promotion: %d promoted, %d already in assets, %d skipped (of %d total)",
             stats["promoted"], stats["already_exists"], stats["skipped"], stats["total"])
    return stats


def main():
    ap = argparse.ArgumentParser(description="VeriFuse V2 — Staging Promoter")
    ap.add_argument("--link-pdfs", action="store_true", help="Link PDFs to staging records first")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be promoted without modifying DB")
    args = ap.parse_args()

    db.init_db()

    if args.link_pdfs:
        print("\n=== LINKING PDFs ===")
        link_stats = link_pdfs()
        for k, v in link_stats.items():
            print(f"  {k}: {v}")

    print("\n=== PROMOTING PORTAL RECORDS ===")
    promo_stats = promote_portal_records(dry_run=args.dry_run)

    print("\n" + "=" * 50)
    print("  STAGING PROMOTER RESULTS")
    print("=" * 50)
    for k, v in promo_stats.items():
        print(f"  {k}: {v}")
    print("=" * 50)


if __name__ == "__main__":
    main()
