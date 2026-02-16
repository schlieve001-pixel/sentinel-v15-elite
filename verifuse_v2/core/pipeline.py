"""
VeriFuse V2 — Pipeline Scoring Engine
=======================================
Ported from V1 verifuse/core/pipeline.py + hunter_engine.py BS detector.

Scoring functions only (no full state machine):
  - Completeness scoring (% of Tier 2 fields populated)
  - Confidence scoring (source trust - age penalty)
  - Data grade computation (GOLD/SILVER/BRONZE/REJECT)
  - BS Detector (WHALE_CAP, DATE_GLITCH, RATIO_TEST)

Usage:
    python -m verifuse_v2.core.pipeline --evaluate-all
    python -m verifuse_v2.core.pipeline --evaluate-all --db /path/to/db
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import datetime, date, timezone
from typing import Optional

# ── Field tier definitions ─────────────────────────────────────────

TIER_2_FIELDS = {
    "owner_name", "property_address", "sale_date",
    "claim_deadline", "case_number", "county",
}

PLACEHOLDER_VALUES = {
    "", "unknown", "n/a", "na", "none", "tbd", "check records",
    "check county site", "not available", "pending", "see file",
}


def _is_real_value(val) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return s.lower() not in PLACEHOLDER_VALUES


def _compute_data_age(timestamp_str: Optional[str]) -> int:
    if not timestamp_str:
        return 30
    try:
        ts = timestamp_str.rstrip("Z")
        updated = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, (now - updated).days)
    except (ValueError, TypeError):
        return 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Scoring Engine ─────────────────────────────────────────────────

def compute_completeness(lead: dict) -> float:
    """% of Tier 2 fields that have real (non-placeholder) values."""
    present = sum(1 for f in TIER_2_FIELDS if _is_real_value(lead.get(f)))
    return round(present / len(TIER_2_FIELDS), 3)


def compute_confidence(lead: dict, data_age_days: int) -> float:
    """Source trust - age penalty. Simple deterministic formula."""
    # Base trust from existing confidence or source quality
    existing = lead.get("confidence_score")
    if existing and float(existing) > 0:
        trust = min(1.0, float(existing))
    else:
        trust = 0.5  # Default: medium trust

    age_penalty = max(0, (data_age_days - 7) / 7) * 0.05
    score = max(0.0, trust - age_penalty)
    return round(score, 3)


def compute_data_grade(completeness: float, confidence: float,
                       surplus: float, days_remaining: Optional[int]) -> str:
    """Deterministic grade assignment.

    GOLD:   completeness == 1.0 AND confidence >= 0.7 AND surplus > 0 AND days_remaining > 30
    SILVER: completeness >= 0.8 AND confidence >= 0.5 AND surplus > 0
    BRONZE: completeness < 0.8 or confidence < 0.5
    REJECT: days_remaining <= 0 OR confidence < 0.2 OR surplus <= 0
    """
    if days_remaining is not None and days_remaining <= 0:
        return "REJECT"
    if confidence < 0.2:
        return "REJECT"
    if surplus <= 0:
        return "REJECT"
    if completeness >= 1.0 and confidence >= 0.7 and (days_remaining is None or days_remaining > 30):
        return "GOLD"
    if completeness >= 0.8 and confidence >= 0.5:
        return "SILVER"
    return "BRONZE"


# ── BS Detector (from hunter_engine.py) ────────────────────────────

WHALE_CAP = 1_000_000
RATIO_THRESHOLD = 0.50
DATE_GLITCH_PATTERN = re.compile(r"^[01]?\d[0-3]\d20[12]\d$")


def bs_detect(lead: dict) -> list:
    """Run BS detection rules. Returns list of flag strings (empty = clean)."""
    flags = []
    surplus = float(lead.get("surplus_amount") or lead.get("estimated_surplus") or 0)
    debt = float(lead.get("total_debt") or 0)

    if surplus <= 0:
        flags.append("NEGATIVE:surplus<=0")
        return flags

    # DATE_GLITCH: surplus looks like a date
    surplus_str = str(int(surplus)) if surplus == int(surplus) else str(surplus)
    surplus_int_str = surplus_str.replace(".", "").replace(",", "")
    if DATE_GLITCH_PATTERN.match(surplus_int_str):
        flags.append(f"DATE_GLITCH:surplus={surplus}")

    if surplus > 100000 and surplus == int(surplus):
        s = str(int(surplus))
        if len(s) in (7, 8) and s[-4:].startswith("20"):
            flags.append(f"DATE_GLITCH:surplus={surplus}")

    # WHALE_CAP
    if surplus > WHALE_CAP:
        flags.append(f"WHALE_CAP:surplus=${surplus:,.2f}>$1M")

    # RATIO_TEST
    if debt and debt > 0 and surplus > (debt * RATIO_THRESHOLD):
        flags.append(f"RATIO_TEST:surplus/debt={surplus/debt:.1%}")

    return flags


# ── Evaluate All Leads ─────────────────────────────────────────────

def evaluate_all(db_path: str) -> dict:
    """Evaluate and re-grade all leads in the database.

    Returns summary report.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = _now_iso()

    results = {"evaluated": 0, "upgraded": 0, "downgraded": 0, "bs_flagged": 0}

    rows = conn.execute("SELECT * FROM leads").fetchall()

    for row in rows:
        lead = dict(row)
        lead_id = lead["id"]
        old_grade = lead.get("data_grade", "BRONZE")

        # Compute scores
        completeness = compute_completeness(lead)
        data_age = _compute_data_age(lead.get("updated_at"))
        confidence = compute_confidence(lead, data_age)
        surplus = float(lead.get("surplus_amount") or lead.get("estimated_surplus") or 0)

        # Days remaining from claim_deadline
        days_remaining = None
        deadline = lead.get("claim_deadline")
        if deadline:
            try:
                days_remaining = (date.fromisoformat(deadline) - date.today()).days
            except (ValueError, TypeError):
                pass

        new_grade = compute_data_grade(completeness, confidence, surplus, days_remaining)

        # BS detection
        flags = bs_detect(lead)
        if flags:
            results["bs_flagged"] += 1

        # Update if grade changed
        if new_grade != old_grade:
            conn.execute("""
                UPDATE leads SET data_grade = ?, confidence_score = ?, updated_at = ?
                WHERE id = ?
            """, [new_grade, confidence, now, lead_id])

            if _grade_rank(new_grade) > _grade_rank(old_grade):
                results["upgraded"] += 1
            else:
                results["downgraded"] += 1

            conn.execute("""
                INSERT INTO pipeline_events
                (asset_id, event_type, old_value, new_value, actor, reason, created_at)
                VALUES (?, 'GRADE_CHANGE', ?, ?, 'pipeline:evaluate_all', ?, ?)
            """, [lead_id, old_grade, new_grade,
                  f"completeness={completeness} confidence={confidence} surplus={surplus}",
                  now])
        else:
            # Still update confidence score
            conn.execute("""
                UPDATE leads SET confidence_score = ? WHERE id = ?
            """, [confidence, lead_id])

        results["evaluated"] += 1

    conn.commit()
    conn.close()
    return results


def _grade_rank(grade: str) -> int:
    return {"REJECT": 0, "IRON": 1, "BRONZE": 2, "SILVER": 3, "GOLD": 4}.get(grade, 1)


# ── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline scoring engine")
    parser.add_argument("--evaluate-all", action="store_true", help="Evaluate all leads")
    parser.add_argument("--db", default=os.environ.get("VERIFUSE_DB_PATH"),
                        help="Path to database")
    args = parser.parse_args()

    if not args.db:
        print("FATAL: --db or VERIFUSE_DB_PATH required")
        sys.exit(1)

    if args.evaluate_all:
        print(f"Evaluating all leads in {args.db}...")
        results = evaluate_all(args.db)
        print(f"\nPipeline evaluation complete:")
        print(f"  Evaluated:  {results['evaluated']}")
        print(f"  Upgraded:   {results['upgraded']}")
        print(f"  Downgraded: {results['downgraded']}")
        print(f"  BS Flagged: {results['bs_flagged']}")
    else:
        parser.print_help()
