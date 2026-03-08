"""
VeriFuse vNEXT — Ingestion Runner
==================================
CLI entry point for the GovSoft Playwright capture engine.

Usage:
    # Single case
    python3 -m verifuse_v2.ingest.ingest_runner \
        --single-case --county jefferson --case-number J2400300

    # Date window (explicit)
    python3 -m verifuse_v2.ingest.ingest_runner \
        --date-window --county jefferson --start 01/01/2024 --end 01/31/2024

    # Date window (rolling N days back from today)
    python3 -m verifuse_v2.ingest.ingest_runner \
        --date-window --county jefferson --days 3

Idempotency: ingestion_runs rows are keyed by run_id (UUID). Stale RUNNING
rows older than 2h are marked FAILED_STALE on startup to prevent zombies.
flock is applied by the caller (bin/vf or systemd) to prevent overlap.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ingest_runner")

DB_PATH = os.getenv(
    "VERIFUSE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
)


def _db_connect():
    import sqlite3
    # isolation_level=None (autocommit) matches govsoft_engine._db_connect()
    # so that BEGIN IMMEDIATE in the engine never conflicts with an implicit
    # transaction opened by the runner's own INSERT statements.
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _cleanup_stale_runs(conn) -> int:
    """Mark any RUNNING ingestion_runs older than 2h as FAILED_STALE.

    Called on every startup before any new run is created.
    Returns the number of rows updated.
    """
    stale_cutoff = int(time.time()) - 7200  # 2 hours
    rowcount = conn.execute(
        """UPDATE ingestion_runs
           SET status = 'FAILED_STALE',
               end_ts = ?,
               notes  = 'Stale RUNNING row cleaned up on startup'
           WHERE status = 'RUNNING' AND start_ts < ?
        """,
        [int(time.time()), stale_cutoff],
    ).rowcount
    if rowcount:
        log.warning("Cleaned up %d stale RUNNING ingestion_run(s)", rowcount)
    conn.commit()
    return rowcount


async def _run_single_case(conn, county: str, case_number: str) -> dict:
    """Execute a single-case capture run with full ingestion_runs tracking."""
    from verifuse_v2.scrapers.adapters.govsoft_engine import GovSoftEngine

    run_id = str(uuid4())
    _run_start_ts = int(time.time())
    conn.execute(
        """INSERT INTO ingestion_runs
           (run_id, county, start_ts, status, cases_processed, cases_failed)
           VALUES (?,?,?,'RUNNING',0,0)
        """,
        [run_id, county, _run_start_ts],
    )
    conn.commit()
    log.info("ingestion_run started: run_id=%s county=%s case=%s", run_id, county, case_number)

    cases_processed = 0
    cases_failed = 0
    final_status = "FAILED"

    try:
        engine = GovSoftEngine(county, db_conn=conn)
        result = await engine.run_single_case(case_number)

        if result.get("error"):
            log.error("Case %s/%s error: %s", county, case_number, result["error"])
            cases_failed = 1
        else:
            log.info("Case %s/%s → %s", county, case_number, result.get("processing_status"))
            cases_processed = 1

        final_status = "SUCCESS" if cases_failed == 0 else "PARTIAL"

    except Exception as exc:
        final_status = "FAILED"
        log.exception("Ingestion run failed: %s", exc)
    finally:
        _end_ts = int(time.time())
        _browser = 1  # single-case always visits exactly 1 case
        _db = cases_processed
        conn.execute(
            """UPDATE ingestion_runs
               SET end_ts=?, status=?, cases_processed=?, cases_failed=?,
                   run_duration_s=?, browser_count=?, db_count=?, delta=?, mode=?
               WHERE run_id=?
            """,
            [_end_ts, final_status, cases_processed, cases_failed,
             _end_ts - _run_start_ts, _browser, _db, _browser - _db, "single_case", run_id],
        )
        conn.commit()

    log.info(
        "ingestion_run complete: run_id=%s status=%s processed=%d failed=%d duration=%ds",
        run_id, final_status, cases_processed, cases_failed, int(time.time()) - _run_start_ts,
    )
    return {
        "run_id": run_id,
        "status": final_status,
        "cases_processed": cases_processed,
        "cases_failed": cases_failed,
    }


async def _run_date_window(conn, county: str, date_from: str, date_to: str) -> dict:
    """Execute a date-window capture run with full ingestion_runs tracking."""
    from verifuse_v2.scrapers.adapters.govsoft_engine import GovSoftEngine

    run_id = str(uuid4())
    _run_start_ts = int(time.time())
    conn.execute(
        """INSERT INTO ingestion_runs
           (run_id, county, start_ts, status, cases_processed, cases_failed,
            notes)
           VALUES (?,?,?,'RUNNING',0,0,?)
        """,
        [run_id, county, _run_start_ts, f"{date_from} to {date_to}"],
    )
    conn.commit()
    log.info(
        "ingestion_run started: run_id=%s county=%s window=%s→%s",
        run_id, county, date_from, date_to,
    )

    cases_processed = 0
    cases_failed = 0
    stats: dict = {}
    final_status = "FAILED"

    try:
        engine = GovSoftEngine(county, db_conn=conn)
        stats = await engine.run_date_window(date_from, date_to)
        cases_processed = stats.get("cases_processed", 0)
        cases_failed = stats.get("cases_failed", 0)
        final_status = "SUCCESS" if cases_failed == 0 else "PARTIAL"

    except Exception as exc:
        final_status = "FAILED"
        log.exception("Ingestion run failed: %s", exc)
    finally:
        _end_ts = int(time.time())
        _browser = stats.get("browser_count", cases_processed + cases_failed)
        _db = stats.get("db_count", cases_processed)
        conn.execute(
            """UPDATE ingestion_runs
               SET end_ts=?, status=?, cases_processed=?, cases_failed=?,
                   run_duration_s=?, browser_count=?, db_count=?, delta=?, mode=?
               WHERE run_id=?
            """,
            [_end_ts, final_status, cases_processed, cases_failed,
             _end_ts - _run_start_ts, _browser, _db, _browser - _db, "date_window", run_id],
        )
        conn.commit()

    log.info(
        "ingestion_run complete: run_id=%s status=%s processed=%d failed=%d duration=%ds",
        run_id, final_status, cases_processed, cases_failed, int(time.time()) - _run_start_ts,
    )
    return {
        "run_id": run_id,
        "status": final_status,
        "cases_processed": cases_processed,
        "cases_failed": cases_failed,
    }


async def _run_sequential_enum(
    conn, county: str, prefix: str, start_num: int, end_num: int
) -> dict:
    """Execute a sequential case enumeration run with ingestion_runs tracking."""
    from verifuse_v2.scrapers.adapters.govsoft_engine import GovSoftEngine

    run_id = str(uuid4())
    _run_start_ts = int(time.time())
    conn.execute(
        """INSERT INTO ingestion_runs
           (run_id, county, start_ts, status, cases_processed, cases_failed, notes)
           VALUES (?,?,?,'RUNNING',0,0,?)
        """,
        [run_id, county, _run_start_ts, f"sequential_enum:{prefix}{start_num}..{prefix}{end_num}"],
    )
    log.info(
        "ingestion_run started: run_id=%s county=%s mode=sequential_enum prefix=%s num=%d..%d",
        run_id, county, prefix, start_num, end_num,
    )

    cases_processed = 0
    cases_failed = 0
    enum_stats: dict = {}
    final_status = "FAILED"

    try:
        engine = GovSoftEngine(county, db_conn=conn)
        enum_stats = await engine.run_sequential_enum(prefix, start_num, end_num)
        cases_processed = enum_stats.get("cases_processed", 0)
        cases_failed = enum_stats.get("cases_failed", 0)
        final_status = "SUCCESS" if cases_failed == 0 else "PARTIAL"
    except Exception as exc:
        final_status = "FAILED"
        log.exception("Sequential enum run failed: %s", exc)
    finally:
        _end_ts = int(time.time())
        _browser = enum_stats.get("browser_count", cases_processed + cases_failed)
        _db = enum_stats.get("db_count", cases_processed)
        conn.execute(
            """UPDATE ingestion_runs
               SET end_ts=?, status=?, cases_processed=?, cases_failed=?,
                   run_duration_s=?, browser_count=?, db_count=?, delta=?, mode=?
               WHERE run_id=?
            """,
            [_end_ts, final_status, cases_processed, cases_failed,
             _end_ts - _run_start_ts, _browser, _db, _browser - _db, "sequential_enum", run_id],
        )

    log.info(
        "ingestion_run complete: run_id=%s status=%s processed=%d failed=%d duration=%ds",
        run_id, final_status, cases_processed, cases_failed, int(time.time()) - _run_start_ts,
    )
    return {
        "run_id": run_id,
        "status": final_status,
        "cases_processed": cases_processed,
        "cases_failed": cases_failed,
    }


async def _run_pending_sales(conn, county: str) -> dict:
    """Scrape Active/Pending cases (pre-sale pipeline) for a county."""
    from verifuse_v2.scrapers.adapters.govsoft_engine import GovSoftEngine

    run_id = str(uuid4())
    _run_start_ts = int(time.time())
    conn.execute(
        """INSERT INTO ingestion_runs
           (run_id, county, start_ts, status, cases_processed, cases_failed, notes)
           VALUES (?,?,?,'RUNNING',0,0,'pending_sales')
        """,
        [run_id, county, _run_start_ts],
    )
    log.info("ingestion_run started: run_id=%s county=%s mode=pending_sales", run_id, county)

    cases_processed = 0
    cases_failed = 0
    stats: dict = {}
    final_status = "FAILED"

    try:
        engine = GovSoftEngine(county, db_conn=conn)
        stats = await engine.run_pending_sales()
        cases_processed = stats.get("cases_processed", 0)
        cases_failed = stats.get("cases_failed", 0)
        final_status = "SUCCESS" if cases_failed == 0 else "PARTIAL"
        log.info(
            "[pending_sales] %s — inserted=%d upgraded=%d",
            county,
            stats.get("leads_inserted", 0),
            stats.get("leads_upgraded", 0),
        )
    except Exception as exc:
        final_status = "FAILED"
        log.exception("Pending-sales run failed for %s: %s", county, exc)
    finally:
        _end_ts = int(time.time())
        # browser_count = cases the scraper visited; db_count = new/upgraded rows written
        _browser = stats.get("browser_count", cases_processed + cases_failed)
        _db = stats.get("leads_inserted", 0) + stats.get("leads_upgraded", 0) or cases_processed
        conn.execute(
            """UPDATE ingestion_runs
               SET end_ts=?, status=?, cases_processed=?, cases_failed=?,
                   run_duration_s=?, browser_count=?, db_count=?, delta=?, mode=?
               WHERE run_id=?
            """,
            [_end_ts, final_status, cases_processed, cases_failed,
             _end_ts - _run_start_ts, _browser, _db, _browser - _db, "pending_sales", run_id],
        )

    return {"run_id": run_id, "status": final_status,
            "cases_processed": cases_processed, "cases_failed": cases_failed}


async def _run_sale_info_backfill(conn, county: str, limit: int = 50) -> dict:
    """Re-scrape BRONZE leads missing SALE_INFO to attempt GOLD/SILVER promotion."""
    from verifuse_v2.scrapers.adapters.govsoft_engine import GovSoftEngine

    run_id = str(uuid4())
    _run_start_ts = int(time.time())
    conn.execute(
        """INSERT INTO ingestion_runs
           (run_id, county, start_ts, status, cases_processed, cases_failed, notes)
           VALUES (?,?,?,'RUNNING',0,0,?)
        """,
        [run_id, county, _run_start_ts, f"sale_info_backfill:limit={limit}"],
    )
    log.info(
        "ingestion_run started: run_id=%s county=%s mode=sale_info_backfill limit=%d",
        run_id, county, limit,
    )

    cases_processed = 0
    cases_failed = 0
    stats: dict = {}
    final_status = "FAILED"

    try:
        engine = GovSoftEngine(county, db_conn=conn)
        stats = await engine.run_sale_info_backfill(limit=limit)
        cases_processed = stats.get("cases_captured", 0)
        cases_failed = stats.get("cases_failed", 0)
        final_status = "SUCCESS" if cases_failed == 0 else "PARTIAL"
        log.info(
            "[backfill] %s — attempted=%d captured=%d GOLD=%d SILVER=%d failed=%d",
            county,
            stats.get("cases_attempted", 0),
            stats.get("cases_captured", 0),
            stats.get("cases_promoted_gold", 0),
            stats.get("cases_promoted_silver", 0),
            stats.get("cases_failed", 0),
        )
    except Exception as exc:
        final_status = "FAILED"
        log.exception("Sale-info backfill failed for %s: %s", county, exc)
    finally:
        _end_ts = int(time.time())
        # browser_count = cases attempted; db_count = cases captured/promoted
        _browser = stats.get("cases_attempted", cases_processed + cases_failed)
        _db = stats.get("cases_captured", cases_processed)
        conn.execute(
            """UPDATE ingestion_runs
               SET end_ts=?, status=?, cases_processed=?, cases_failed=?,
                   run_duration_s=?, browser_count=?, db_count=?, delta=?, mode=?
               WHERE run_id=?
            """,
            [_end_ts, final_status, cases_processed, cases_failed,
             _end_ts - _run_start_ts, _browser, _db, _browser - _db, "sale_info_backfill", run_id],
        )

    return {"run_id": run_id, "status": final_status,
            "cases_processed": cases_processed, "cases_failed": cases_failed}


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VeriFuse vNEXT GovSoft Ingestion Runner"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--single-case", action="store_true",
                      help="Scrape a single case by case number")
    mode.add_argument("--date-window", action="store_true",
                      help="Scrape all cases in a date range")
    mode.add_argument("--sequential-enum", action="store_true",
                      help="Enumerate case numbers sequentially (bypass search form)")
    mode.add_argument("--pending-sales", action="store_true",
                      help="Scrape Active/Pending cases (pre-sale pipeline)")
    mode.add_argument("--sale-info-backfill", action="store_true",
                      help="Re-scrape BRONZE leads missing SALE_INFO (promotes to GOLD/SILVER)")

    parser.add_argument("--county", required=True,
                        help="County slug (e.g. jefferson, arapahoe)")
    parser.add_argument("--case-number",
                        help="Case number for --single-case mode")
    parser.add_argument("--start",
                        help="Start date MM/DD/YYYY for --date-window")
    parser.add_argument("--end",
                        help="End date MM/DD/YYYY for --date-window")
    parser.add_argument("--days", type=int,
                        help="Rolling window: scrape last N days (--date-window)")
    parser.add_argument("--prefix",
                        help="Case number prefix for --sequential-enum (e.g. J24)")
    parser.add_argument("--start-num", type=int,
                        help="Start number for --sequential-enum (inclusive)")
    parser.add_argument("--end-num", type=int,
                        help="End number for --sequential-enum (inclusive)")
    parser.add_argument("--db", default=DB_PATH,
                        help="Path to SQLite database")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max cases for --sale-info-backfill (default: 50)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    # Override DB path if provided
    global DB_PATH
    if args.db != DB_PATH:
        DB_PATH = args.db
        import verifuse_v2.scrapers.adapters.govsoft_engine as _eng
        _eng.DB_PATH = args.db

    conn = _db_connect()

    # Always clean stale RUNNING rows first
    _cleanup_stale_runs(conn)

    if args.single_case:
        if not args.case_number:
            log.error("--case-number is required for --single-case mode")
            return 1
        result = asyncio.run(
            _run_single_case(conn, args.county, args.case_number)
        )

    elif args.sequential_enum:
        if not args.prefix or args.start_num is None or args.end_num is None:
            log.error("--sequential-enum requires --prefix, --start-num, --end-num")
            return 1
        result = asyncio.run(
            _run_sequential_enum(
                conn, args.county, args.prefix, args.start_num, args.end_num
            )
        )

    elif args.pending_sales:
        result = asyncio.run(_run_pending_sales(conn, args.county))

    elif args.sale_info_backfill:
        result = asyncio.run(_run_sale_info_backfill(conn, args.county, limit=args.limit))

    else:  # date-window
        if args.days:
            today = datetime.now(timezone.utc)
            end_dt = today
            start_dt = today - timedelta(days=args.days)
            date_from = start_dt.strftime("%m/%d/%Y")
            date_to = end_dt.strftime("%m/%d/%Y")
        elif args.start and args.end:
            date_from = args.start
            date_to = args.end
        else:
            log.error("--date-window requires --start/--end or --days")
            return 1

        result = asyncio.run(
            _run_date_window(conn, args.county, date_from, date_to)
        )

    conn.close()

    # Exit non-zero if run failed completely
    return 0 if result.get("status") in ("SUCCESS", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())
