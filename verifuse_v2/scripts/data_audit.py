"""
VERIFUSE V2 — Data Audit
===========================
Pipeline reconciliation and data quality report.
ALL queries use COALESCE(estimated_surplus, surplus_amount, 0) as canonical surplus.

Usage:
    python -m verifuse_v2.scripts.data_audit
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)

SURPLUS = "COALESCE(estimated_surplus, surplus_amount, 0)"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def run_audit() -> dict:
    """Run full data audit and return results dict."""
    conn = _get_conn()
    results = {}

    # ── 1. Grade Breakdown ────────────────────────────────────────
    rows = conn.execute(f"""
        SELECT data_grade, COUNT(*) as cnt,
               SUM({SURPLUS}) as total_surplus,
               AVG({SURPLUS}) as avg_surplus,
               MAX({SURPLUS}) as max_surplus
        FROM leads
        GROUP BY data_grade
        ORDER BY total_surplus DESC
    """).fetchall()
    results["grade_breakdown"] = [dict(r) for r in rows]

    # ── 2. Zombie Report ──────────────────────────────────────────
    zombie_count = conn.execute(f"""
        SELECT COUNT(*) FROM leads WHERE {SURPLUS} <= 100
    """).fetchone()[0]
    total_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    results["zombies"] = {
        "count": zombie_count,
        "total_leads": total_count,
        "pct": round(zombie_count / total_count * 100, 1) if total_count else 0,
    }

    # ── 3. Reconciliation ─────────────────────────────────────────
    verified = conn.execute(f"""
        SELECT COUNT(*) as cnt, SUM({SURPLUS}) as total
        FROM leads
        WHERE data_grade IN ('GOLD', 'SILVER', 'BRONZE')
          AND {SURPLUS} > 100
    """).fetchone()
    raw = conn.execute(f"""
        SELECT COUNT(*) as cnt, SUM({SURPLUS}) as total
        FROM leads
    """).fetchone()
    results["reconciliation"] = {
        "verified_pipeline": {"count": verified["cnt"], "total_surplus": round(verified["total"] or 0, 2)},
        "total_raw_volume": {"count": raw["cnt"], "total_surplus": round(raw["total"] or 0, 2)},
        "delta_count": raw["cnt"] - verified["cnt"],
        "delta_surplus": round((raw["total"] or 0) - (verified["total"] or 0), 2),
    }

    # ── 4. Top 10 ─────────────────────────────────────────────────
    top10 = conn.execute(f"""
        SELECT id, county, case_number, data_grade, confidence_score,
               {SURPLUS} as surplus
        FROM leads
        ORDER BY {SURPLUS} DESC
        LIMIT 10
    """).fetchall()
    results["top_10"] = [dict(r) for r in top10]

    # ── 5. Reject Rescue Candidates ───────────────────────────────
    rescue = conn.execute(f"""
        SELECT id, county, case_number, confidence_score,
               {SURPLUS} as surplus
        FROM leads
        WHERE data_grade = 'REJECT'
          AND {SURPLUS} >= 5000
          AND confidence_score >= 0.65
        ORDER BY {SURPLUS} DESC
        LIMIT 25
    """).fetchall()
    results["reject_rescue"] = [dict(r) for r in rescue]

    # ── 6. Attorney-Ready Reconciliation ──────────────────────────
    attorney_ready = conn.execute(f"""
        SELECT COUNT(*) as cnt, SUM({SURPLUS}) as total
        FROM leads
        WHERE county IS NOT NULL
          AND case_number IS NOT NULL
          AND owner_name IS NOT NULL
          AND sale_date IS NOT NULL
          AND {SURPLUS} > 0
    """).fetchone()
    results["attorney_ready"] = {
        "count": attorney_ready["cnt"],
        "total_surplus": round(attorney_ready["total"] or 0, 2),
    }

    conn.close()
    return results


def print_audit(results: dict) -> None:
    """Print formatted data audit report."""
    print("=" * 80)
    print("  VERIFUSE — DATA AUDIT REPORT")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Canonical surplus: COALESCE(estimated_surplus, surplus_amount, 0)")
    print("=" * 80)

    # Grade Breakdown
    print("\n  1. GRADE BREAKDOWN")
    print(f"  {'Grade':<12s} {'Count':<10s} {'Total Surplus':<18s} {'Avg Surplus':<15s} {'Max Surplus'}")
    print("  " + "-" * 70)
    for r in results["grade_breakdown"]:
        grade = r["data_grade"] or "UNGRADED"
        print(f"  {grade:<12s} {r['cnt']:<10d} ${r['total_surplus']:>14,.2f} "
              f"${r['avg_surplus']:>11,.2f} ${r['max_surplus']:>11,.2f}")

    # Zombie Report
    z = results["zombies"]
    print(f"\n  2. ZOMBIE REPORT (surplus <= $100)")
    print(f"     Zombies: {z['count']} / {z['total_leads']} ({z['pct']}%)")

    # Reconciliation
    r = results["reconciliation"]
    vp = r["verified_pipeline"]
    rv = r["total_raw_volume"]
    print(f"\n  3. PIPELINE RECONCILIATION")
    print(f"     Verified Pipeline (GOLD/SILVER/BRONZE, surplus>$100): "
          f"{vp['count']} leads, ${vp['total_surplus']:,.2f}")
    print(f"     Total Raw Volume (all leads): "
          f"{rv['count']} leads, ${rv['total_surplus']:,.2f}")
    print(f"     Delta: {r['delta_count']} leads, ${r['delta_surplus']:,.2f}")
    print(f"     (Delta = zombies + REJECTs + low-surplus leads)")

    # Top 10
    print(f"\n  4. TOP 10 LEADS BY SURPLUS")
    print(f"  {'ID':<20s} {'County':<12s} {'Grade':<8s} {'Conf':<8s} {'Surplus'}")
    print("  " + "-" * 60)
    for r in results["top_10"]:
        print(f"  {str(r['id'])[:18]:<20s} {(r['county'] or '?'):<12s} "
              f"{(r['data_grade'] or '?'):<8s} {(r['confidence_score'] or 0):<8.2f} "
              f"${r['surplus']:>12,.2f}")

    # Reject Rescue
    rescue = results["reject_rescue"]
    print(f"\n  5. REJECT RESCUE CANDIDATES ({len(rescue)} found)")
    print(f"     (REJECT grade, surplus >= $5,000, confidence >= 0.65)")
    if rescue:
        for r in rescue:
            print(f"     {str(r['id'])[:18]} | {r['county'] or '?'} | "
                  f"conf={r['confidence_score']:.2f} | ${r['surplus']:,.2f}")
    else:
        print("     None found.")

    # Attorney-Ready
    ar = results["attorney_ready"]
    print(f"\n  6. ATTORNEY-READY RECONCILIATION")
    print(f"     Predicate: county + case_number + owner_name + sale_date + surplus > 0")
    print(f"     Count: {ar['count']} leads, ${ar['total_surplus']:,.2f}")
    print(f"     Note: This may differ from grade totals because grading uses")
    print(f"     confidence thresholds, while attorney-readiness checks field completeness.")

    print("\n" + "=" * 80)


def main():
    results = run_audit()
    print_audit(results)


if __name__ == "__main__":
    main()
