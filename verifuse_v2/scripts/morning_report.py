"""
VERIFUSE V2 — Morning Report CLI
==================================
Quick system health + value check for daily operations.

SQLite direct queries + API health ping.

Usage:
    python -m verifuse_v2.scripts.morning_report
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = os.environ.get(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)


def _fmt_money(val) -> str:
    if val is None:
        return "$0.00"
    try:
        return f"${float(val):,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def run_report():
    if not Path(DB_PATH).exists():
        print(f"FATAL: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(hours=24)).isoformat()

    print("=" * 60)
    print("  VERIFUSE — MORNING REPORT")
    print(f"  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # ── Value: New leads in last 24h ────────────────────────────────
    print("\n--- NEW LEADS (Last 24h) ---")
    try:
        new_leads = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE updated_at >= ?", [yesterday]
        ).fetchone()[0]
        new_surplus = conn.execute(
            "SELECT COALESCE(SUM(estimated_surplus), 0) FROM leads WHERE updated_at >= ?",
            [yesterday],
        ).fetchone()[0]
        print(f"  New leads:     {new_leads}")
        print(f"  Total surplus: {_fmt_money(new_surplus)}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Health: Recent scraper failures ──────────────────────────────
    print("\n--- SCRAPER HEALTH ---")
    try:
        failures = conn.execute("""
            SELECT event_type, reason, created_at
            FROM pipeline_events
            WHERE event_type LIKE '%ERROR%' OR event_type LIKE '%FAIL%'
            ORDER BY created_at DESC
            LIMIT 5
        """).fetchall()
        if failures:
            for f in failures:
                print(f"  [{f['created_at'][:16]}] {f['event_type']}: {f['reason'] or 'no reason'}")
        else:
            print("  No recent failures")
    except Exception as e:
        print(f"  Error reading pipeline_events: {e}")

    # ── Budget: Vertex AI usage ──────────────────────────────────────
    print("\n--- VERTEX AI BUDGET ---")
    try:
        today_str = now.strftime("%Y-%m-%d")
        usage = conn.execute(
            "SELECT COUNT(*) FROM vertex_usage WHERE date = ?", [today_str]
        ).fetchone()[0]
        cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM vertex_usage WHERE date = ?",
            [today_str],
        ).fetchone()[0]
        print(f"  PDFs today:    {usage}/50")
        print(f"  Est. cost:     {_fmt_money(cost)}")

        queued = conn.execute(
            "SELECT COUNT(*) FROM vertex_queue WHERE status = 'PENDING'"
        ).fetchone()[0]
        if queued > 0:
            print(f"  Queued:        {queued} PDFs waiting")
    except Exception:
        print("  Vertex tables not yet created (run migration first)")

    # ── Top Leads: Top 5 new GOLD leads ─────────────────────────────
    print("\n--- TOP NEW GOLD LEADS ---")
    try:
        top = conn.execute("""
            SELECT id, county, case_number, estimated_surplus, owner_name
            FROM leads
            WHERE data_grade = 'GOLD'
            ORDER BY estimated_surplus DESC
            LIMIT 5
        """).fetchall()
        if top:
            for i, r in enumerate(top, 1):
                owner = (r["owner_name"] or "Unknown")[:30]
                print(f"  {i}. {r['county'] or '?':12s} | {_fmt_money(r['estimated_surplus']):>12s} | {owner}")
        else:
            print("  No GOLD leads found")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Overall Scoreboard ──────────────────────────────────────────
    print("\n--- SCOREBOARD ---")
    try:
        rows = conn.execute("""
            SELECT data_grade, COUNT(*) as cnt,
                   COALESCE(SUM(estimated_surplus), 0) as total
            FROM leads
            GROUP BY data_grade
            ORDER BY total DESC
        """).fetchall()
        for r in rows:
            print(f"  {r['data_grade'] or 'UNGRADED':10s} {r['cnt']:5d} leads  {_fmt_money(r['total']):>14s}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── API Health Ping ──────────────────────────────────────────────
    print("\n--- API HEALTH ---")
    try:
        import requests
        for url in ["http://localhost:8000/health", "http://localhost:8000/api/health"]:
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    print(f"  {url}: OK")
                    break
            except Exception:
                continue
        else:
            print("  API not responding on localhost:8000")
    except ImportError:
        print("  (requests not available — skipping health ping)")

    print("\n" + "=" * 60)
    conn.close()


if __name__ == "__main__":
    run_report()
