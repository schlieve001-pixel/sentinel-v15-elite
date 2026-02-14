#!/usr/bin/env python3
"""
VeriFuse Master Controller — Single-Button Operations
======================================================
CEO-level interface. One menu. Six commands. Total Colorado Domination.

USAGE:
  python run_verifuse.py          # Interactive menu
  python run_verifuse.py 1        # Direct: Run Colorado Dragnet
  python run_verifuse.py 2        # Direct: Generate Dossiers
  python run_verifuse.py 3        # Direct: Run Mail Room
  python run_verifuse.py 4        # Direct: System Status
  python run_verifuse.py 5        # Direct: Health Check (URL + Data)
  python run_verifuse.py 6        # Direct: Full Watchdog (Self-Heal)
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

# Ensure verifuse package is importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
os.chdir(str(ROOT))

DB_PATH = ROOT / "data" / "verifuse.db"


# ============================================================================
# DISPLAY
# ============================================================================

def banner():
    print()
    print("=" * 70)
    print("  VERIFUSE LEGAL INTELLIGENCE — MASTER CONTROLLER")
    print("  Total Colorado Domination Engine")
    print("=" * 70)
    print()
    print("  [1]  RUN COLORADO DRAGNET (All Markets)")
    print("  [2]  GENERATE LEGAL DOSSIERS (Motions)")
    print("  [3]  RUN MAIL ROOM (Marketing Letters)")
    print("  [4]  SYSTEM STATUS & RECON")
    print("  [5]  HEALTH CHECK (URL + Data Audit)")
    print("  [6]  FULL WATCHDOG (Self-Heal + Report)")
    print("  [Q]  QUIT")
    print()


# ============================================================================
# [1] COLORADO DRAGNET
# ============================================================================

def run_dragnet():
    print("\n" + "=" * 70)
    print("  COLORADO DRAGNET — All Markets")
    print("=" * 70)

    from verifuse.scrapers.hunter_engine import run_hunter, ALL_COLORADO_COUNTIES, ingest_to_pipeline

    print(f"\nTarget: {len(ALL_COLORADO_COUNTIES)} counties")
    print(f"Counties: {', '.join(ALL_COLORADO_COUNTIES)}")
    print()

    results = run_hunter(
        counties=ALL_COLORADO_COUNTIES,
        start_year=2020,
        end_year=2026,
        output_csv=str(ROOT / "data" / "dragnet_results.csv"),
    )

    records = results.get("records", [])
    if records:
        print(f"\nIngesting {len(records)} actionable records into pipeline...")
        ingest_to_pipeline(records, str(DB_PATH))
    else:
        print("\nNo new actionable records found in this sweep.")

    return results


# ============================================================================
# [2] GENERATE DOSSIERS
# ============================================================================

def run_dossiers():
    print("\n" + "=" * 70)
    print("  LEGAL DOSSIER GENERATOR — Pre-Litigation Evidence Packets")
    print("=" * 70)

    from verifuse.attorney.dossier_generator import generate_dossier, generate_batch

    if not DB_PATH.exists():
        print(f"\nDatabase not found: {DB_PATH}")
        print("Run the Colorado Dragnet first [Option 1].")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT a.*, ls.record_class, ls.data_grade, ls.days_remaining
        FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE ls.record_class = 'ATTORNEY'
          AND ls.data_grade IN ('GOLD', 'SILVER')
          AND a.estimated_surplus > 0
        ORDER BY a.estimated_surplus DESC
    """).fetchall()

    records = [dict(row) for row in rows]
    conn.close()

    if not records:
        print("\nNo ATTORNEY-class assets found for dossier generation.")
        return

    print(f"\nFound {len(records)} attorney-ready assets.")
    total_surplus = sum(r.get("estimated_surplus", 0) for r in records)
    print(f"Total surplus in portfolio: ${total_surplus:,.2f}")

    output_dir = str(ROOT / "output" / "dossiers")
    paths = generate_batch(records, output_dir)

    print(f"\nDossiers saved to: {output_dir}/")
    return paths


# ============================================================================
# [3] MAIL ROOM
# ============================================================================

def run_mail():
    print("\n" + "=" * 70)
    print("  MAIL ROOM — Attorney Solicitation Letters")
    print("=" * 70)

    from verifuse.legal.mail_room import run_mail_room

    output_dir = str(ROOT / "output" / "letters")
    paths = run_mail_room(
        output_dir=output_dir,
        db_path=str(DB_PATH),
    )

    if paths:
        print(f"\nLetters saved to: {output_dir}/")
    return paths


# ============================================================================
# [4] SYSTEM STATUS
# ============================================================================

def run_status():
    print("\n" + "=" * 70)
    print("  SYSTEM STATUS & RECON")
    print("=" * 70)

    # Database check
    print(f"\n  Database: {DB_PATH}")
    if not DB_PATH.exists():
        print("  STATUS: NOT INITIALIZED")
        print("  Run the Colorado Dragnet first [Option 1].")
        return

    conn = sqlite3.connect(str(DB_PATH))
    db_size = os.path.getsize(str(DB_PATH))
    print(f"  Size: {db_size / 1024:.0f} KB")

    # Asset counts
    total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    print(f"\n  Total Assets: {total}")

    classes = conn.execute("""
        SELECT record_class, COUNT(*) FROM legal_status GROUP BY record_class
    """).fetchall()
    for cls, count in classes:
        print(f"    {cls:12s}: {count}")

    # Grade breakdown for ATTORNEY
    grades = conn.execute("""
        SELECT data_grade, COUNT(*) FROM legal_status
        WHERE record_class = 'ATTORNEY' GROUP BY data_grade
    """).fetchall()
    if grades:
        print(f"\n  ATTORNEY Grade Breakdown:")
        for grade, count in grades:
            print(f"    {grade:8s}: {count}")

    # County breakdown
    counties = conn.execute("""
        SELECT a.county, ls.record_class, COUNT(*)
        FROM assets a JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE ls.record_class = 'ATTORNEY'
        GROUP BY a.county
        ORDER BY COUNT(*) DESC
    """).fetchall()
    if counties:
        print(f"\n  ATTORNEY Assets by County:")
        for county, cls, count in counties:
            print(f"    {county:15s}: {count}")

    # Financial summary
    fin = conn.execute("""
        SELECT
            SUM(a.estimated_surplus),
            AVG(a.estimated_surplus),
            MAX(a.estimated_surplus),
            COUNT(*)
        FROM assets a
        JOIN legal_status ls ON a.asset_id = ls.asset_id
        WHERE ls.record_class = 'ATTORNEY'
          AND a.estimated_surplus > 0
    """).fetchone()
    if fin and fin[0]:
        print(f"\n  Financial Intelligence (ATTORNEY class):")
        print(f"    Total Surplus:   ${fin[0]:>14,.2f}")
        print(f"    Avg Surplus:     ${fin[1]:>14,.2f}")
        print(f"    Max Surplus:     ${fin[2]:>14,.2f}")
        print(f"    Asset Count:     {fin[3]:>14d}")

    # Scraper registry
    scrapers = conn.execute("""
        SELECT scraper_name, jurisdiction, enabled, last_run_at
        FROM scraper_registry ORDER BY jurisdiction
    """).fetchall()
    print(f"\n  Scraper Registry ({len(scrapers)} registered):")
    for name, juris, enabled, last_run in scrapers:
        status = "ON " if enabled else "OFF"
        run_info = f"last: {last_run[:10]}" if last_run else "never run"
        print(f"    [{status}] {name:25s} {juris:20s} ({run_info})")

    # Statute authority
    statutes = conn.execute("SELECT COUNT(*) FROM statute_authority").fetchone()[0]
    print(f"\n  Statute Authorities: {statutes} jurisdictions")

    # Pipeline events
    events = conn.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0]
    print(f"  Pipeline Events: {events} (audit trail)")

    conn.close()

    # Dependencies
    print(f"\n  Dependencies:")
    deps = ["requests", "pandas", "fake_useragent", "bs4", "docx", "pdfplumber"]
    for dep in deps:
        try:
            __import__(dep)
            print(f"    {dep:20s}: OK")
        except ImportError:
            print(f"    {dep:20s}: MISSING")

    print(f"\n  Timestamp: {datetime.now().isoformat()}")


# ============================================================================
# [5] HEALTH CHECK
# ============================================================================

def run_health():
    print("\n" + "=" * 70)
    print("  HEALTH CHECK — URL Audit + Data Integrity")
    print("=" * 70)

    from verifuse.core.watchdog import check_url_health, print_system_status

    print("\n  Testing all 17 county endpoints...")
    health = check_url_health(timeout=15)
    s = health.get("summary", {})
    print(f"\n  Results: {s.get('green', 0)} GREEN | "
          f"{s.get('yellow', 0)} YELLOW | "
          f"{s.get('red', 0)} RED | "
          f"{s.get('dead', 0)} DEAD")

    for county, detail in health.get("details", {}).items():
        status = detail.get("status", "?")
        icon = {"GREEN": "  ", "YELLOW": "? ", "RED": "!!", "DEAD": "XX"}
        code = detail.get("http_code", "---")
        size = detail.get("size_bytes", 0)
        reason = detail.get("reason", "")
        print(f"  {icon.get(status, '??')} {county:12s} | {status:6s} | "
              f"HTTP {code} | {size:>6d}B"
              + (f" | {reason}" if reason else ""))

    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        print_system_status(conn, health)
        conn.close()

    return health


# ============================================================================
# [6] FULL WATCHDOG
# ============================================================================

def run_watchdog():
    print("\n" + "=" * 70)
    print("  FULL WATCHDOG — Self-Healing System Check")
    print("=" * 70)

    import json
    from verifuse.core.watchdog import (
        run_daily_checks, check_url_health,
        auto_disable_broken_scrapers, print_system_status
    )

    if not DB_PATH.exists():
        print("\n  Database not initialized. Run Dragnet first [Option 1].")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Step 1: URL health
    print("\n  [1/4] Checking URL health...")
    health = check_url_health(timeout=15)
    s = health.get("summary", {})
    print(f"        {s.get('green', 0)} GREEN | {s.get('red', 0)} RED | {s.get('dead', 0)} DEAD")

    # Step 2: Auto-disable broken scrapers
    print("  [2/4] Auto-disabling broken scrapers...")
    disabled = auto_disable_broken_scrapers(conn, health)
    if disabled:
        print(f"        Disabled {len(disabled)}: {', '.join(disabled)}")
    else:
        print("        All scrapers healthy.")

    # Step 3: Run daily checks (includes re-evaluation)
    print("  [3/4] Running daily checks (evaluation + expiry sweep)...")
    report = run_daily_checks(conn)

    eval_results = report["checks"].get("evaluation", {})
    print(f"        Promoted: {eval_results.get('promoted', 0)} | "
          f"Killed: {eval_results.get('killed', 0)} | "
          f"Unchanged: {eval_results.get('unchanged', 0)}")

    # Step 4: Print alerts
    print("  [4/4] Checking for alerts...")
    alerts = report.get("alerts", [])
    if alerts:
        print(f"\n  ALERTS ({len(alerts)}):")
        for alert in alerts:
            print(f"    !! {alert}")
    else:
        print("        No alerts. System healthy.")

    # Actions taken
    actions = report.get("actions_taken", [])
    if actions:
        print(f"\n  ACTIONS TAKEN ({len(actions)}):")
        for action in actions:
            print(f"    -> {action}")

    # Full status dashboard
    print_system_status(conn, health)
    conn.close()

    return report


# ============================================================================
# MAIN
# ============================================================================

def main():
    # Direct command mode: python run_verifuse.py 1
    if len(sys.argv) > 1:
        choice = sys.argv[1].strip().upper()
        if choice == "1":
            run_dragnet()
        elif choice == "2":
            run_dossiers()
        elif choice == "3":
            run_mail()
        elif choice == "4":
            run_status()
        elif choice == "5":
            run_health()
        elif choice == "6":
            run_watchdog()
        else:
            print(f"Unknown option: {choice}")
        return

    # Interactive menu mode
    while True:
        banner()
        choice = input("  Select [1-6, Q]: ").strip().upper()

        if choice == "1":
            run_dragnet()
        elif choice == "2":
            run_dossiers()
        elif choice == "3":
            run_mail()
        elif choice == "4":
            run_status()
        elif choice == "5":
            run_health()
        elif choice == "6":
            run_watchdog()
        elif choice in ("Q", "QUIT", "EXIT"):
            print("\n  Shutting down. Stay sovereign.\n")
            break
        else:
            print(f"\n  Unknown option: {choice}")

        input("\n  Press ENTER to continue...")


if __name__ == "__main__":
    main()
