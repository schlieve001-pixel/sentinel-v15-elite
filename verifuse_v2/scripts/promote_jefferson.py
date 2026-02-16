"""
VeriFuse V2 — Promote Jefferson Big Fish
==========================================
Manual enrichment for the 3 Jefferson BRONZE leads ($1.8M combined).
Fills missing Tier 2 fields and promotes to GOLD.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.scripts.promote_jefferson
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH not set")
    sys.exit(1)

# Jefferson big fish — enrichment data from public records
ENRICHMENTS = [
    {
        "id": "jefferson_foreclosure_surplus_1e525f4f",
        "owner_name": "THE WAVE INVESTMENT TEAM, INC.",
        "surplus_amount": 1057500.57,
        "claim_deadline": "2031-01-22",
        "data_grade": "GOLD",
        "confidence_score": 0.85,
        "attorney_packet_ready": 1,
        "processing_status": "ENRICHED",
        "statute_window_status": "ACTIVE_ESCROW",
    },
    {
        "id": "jefferson_foreclosure_surplus_7a5fba3e",
        "owner_name": "LOUISE THOMAS AND RYAN L. THOMAS",
        "surplus_amount": 427062.69,
        "claim_deadline": "2031-01-22",
        "data_grade": "GOLD",
        "confidence_score": 0.85,
        "attorney_packet_ready": 1,
        "processing_status": "ENRICHED",
        "statute_window_status": "ACTIVE_ESCROW",
    },
    {
        "id": "jefferson_foreclosure_surplus_941feefc",
        "owner_name": "RALPH F. MALITO & CHERYL A. MALITO",
        "surplus_amount": 342111.76,
        "claim_deadline": "2031-01-22",
        "data_grade": "GOLD",
        "confidence_score": 0.85,
        "attorney_packet_ready": 1,
        "processing_status": "ENRICHED",
        "statute_window_status": "ACTIVE_ESCROW",
    },
]


def promote():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    promoted = 0
    for enrichment in ENRICHMENTS:
        lead_id = enrichment["id"]
        row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
        if not row:
            print(f"  [SKIP] {lead_id} not found")
            continue

        old_grade = row["data_grade"]
        conn.execute("""
            UPDATE leads SET
                data_grade = ?,
                confidence_score = ?,
                claim_deadline = ?,
                attorney_packet_ready = ?,
                processing_status = ?,
                statute_window_status = ?,
                updated_at = ?
            WHERE id = ?
        """, [
            enrichment["data_grade"],
            enrichment["confidence_score"],
            enrichment["claim_deadline"],
            enrichment["attorney_packet_ready"],
            enrichment["processing_status"],
            enrichment["statute_window_status"],
            now,
            lead_id,
        ])

        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES (?, 'GRADE_CHANGE', ?, ?, 'promote_jefferson.py',
                    'Manual enrichment: Jefferson big fish', ?)
        """, [lead_id, old_grade, enrichment["data_grade"], now])

        surplus = enrichment["surplus_amount"]
        print(f"  [OK] {enrichment['owner_name'][:40]:40s} ${surplus:>12,.2f} → GOLD")
        promoted += 1

    conn.commit()
    conn.close()

    print(f"\nPromoted {promoted}/{len(ENRICHMENTS)} Jefferson leads to GOLD")

    # Verify
    conn = sqlite3.connect(DB_PATH)
    gold_count = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE data_grade = 'GOLD'"
    ).fetchone()[0]
    gold_surplus = conn.execute(
        "SELECT SUM(COALESCE(surplus_amount, estimated_surplus, 0)) FROM leads WHERE data_grade = 'GOLD'"
    ).fetchone()[0]
    conn.close()
    print(f"Total GOLD leads: {gold_count} (${gold_surplus:,.2f})")


if __name__ == "__main__":
    print("Jefferson Big Fish Promotion")
    print("=" * 60)
    promote()
