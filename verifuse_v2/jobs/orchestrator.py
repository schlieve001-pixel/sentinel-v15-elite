"""
VERIFUSE V2 — orchestrator.py

Full pipeline: Download PDFs → Classify → Vertex Extract → Upsert/Quarantine.

Runs as a single-shot job (systemd timer calls it).
Steps:
  1. WAL checkpoint (safety)
  2. Download new PDFs from all enabled counties
  3. Classify PDFs (DENY/ALLOW/UNKNOWN gate)
  4. Run Vertex extraction on ALLOW + UNKNOWN PDFs
  5. Log summary to pipeline_events

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json
    python -m verifuse_v2.jobs.orchestrator
    python -m verifuse_v2.jobs.orchestrator --skip-download
    python -m verifuse_v2.jobs.orchestrator --dry-run
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ── Fail-fast ────────────────────────────────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH not set.")
    sys.exit(1)


def wal_checkpoint() -> None:
    """WAL checkpoint before pipeline run."""
    conn = sqlite3.connect(DB_PATH)
    try:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"  [WAL] checkpoint: busy={result[0]}, log={result[1]}, checkpointed={result[2]}")
    finally:
        conn.close()


def log_event(event_type: str, detail: str) -> None:
    """Log pipeline event."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT INTO pipeline_events
            (asset_id, event_type, old_value, new_value, actor, reason, created_at)
            VALUES ('SYSTEM', ?, '', ?, 'orchestrator', 'pipeline_run', ?)
        """, [event_type, detail, datetime.now(timezone.utc).isoformat()])
        conn.commit()
        conn.close()
    except Exception:
        pass


def run(skip_download: bool = False, dry_run: bool = False,
        limit: int = 50, county: str | None = None) -> dict:
    """Run the full pipeline."""
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "started_at": now,
        "download": None,
        "extraction": None,
        "errors": [],
    }

    print(f"\n{'='*60}")
    print(f"  VERIFUSE ORCHESTRATOR — Full Pipeline Run")
    print(f"  {now}")
    print(f"{'='*60}")

    # Step 1: WAL checkpoint
    print("\n  [STEP 1] WAL checkpoint...")
    try:
        wal_checkpoint()
    except Exception as e:
        print(f"  [WARN] WAL checkpoint failed: {e}")

    # Step 2: Download PDFs
    if not skip_download:
        print("\n  [STEP 2] Downloading PDFs from county sites...")
        try:
            from verifuse_v2.jobs.pdf_downloader import run as download_run
            dl_stats = download_run(county_filter=county)
            summary["download"] = dl_stats
            if dl_stats.get("errors"):
                summary["errors"].extend(dl_stats["errors"])
        except Exception as e:
            print(f"  [ERROR] Download phase failed: {e}")
            summary["errors"].append(f"download: {e}")
    else:
        print("\n  [STEP 2] SKIPPED (--skip-download)")

    # Step 3: Vertex extraction
    print("\n  [STEP 3] Running Vertex AI extraction...")
    if dry_run:
        print("  DRY RUN — skipping Vertex calls")
    try:
        from verifuse_v2.scrapers.vertex_engine_enterprise import process_all
        ext_stats = process_all(limit=limit, dry_run=dry_run)
        summary["extraction"] = ext_stats
        if ext_stats.get("errors"):
            summary["errors"].extend(ext_stats["errors"])
    except Exception as e:
        print(f"  [ERROR] Extraction phase failed: {e}")
        summary["errors"].append(f"extraction: {e}")

    # Step 4: Final WAL checkpoint
    print("\n  [STEP 4] Final WAL checkpoint...")
    try:
        wal_checkpoint()
    except Exception:
        pass

    # Log summary
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    log_event("ORCHESTRATOR_RUN", str(summary))

    # Print summary
    print(f"\n{'='*60}")
    print(f"  ORCHESTRATOR COMPLETE")
    print(f"{'='*60}")
    if summary["download"]:
        dl = summary["download"]
        print(f"  Downloads: {dl.get('pdfs_downloaded', 0)} new PDFs from {dl.get('counties_scanned', 0)} counties")
    if summary["extraction"]:
        ex = summary["extraction"]
        print(f"  Extraction: {ex.get('processed', 0)} processed, "
              f"{ex.get('inserted', 0)} inserted, {ex.get('updated', 0)} updated, "
              f"{ex.get('quarantined', 0)} quarantined, {ex.get('denied', 0)} denied")
    if summary["errors"]:
        print(f"  ERRORS: {len(summary['errors'])}")
        for err in summary["errors"][:5]:
            print(f"    - {err}")
    print(f"{'='*60}\n")

    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VeriFuse Orchestrator — Full Pipeline")
    ap.add_argument("--skip-download", action="store_true", help="Skip PDF download phase")
    ap.add_argument("--dry-run", action="store_true", help="Scan PDFs without calling Vertex")
    ap.add_argument("--limit", type=int, default=50, help="Max PDFs to process per run")
    ap.add_argument("--county", type=str, default=None, help="Filter to single county")
    args = ap.parse_args()

    result = run(
        skip_download=args.skip_download,
        dry_run=args.dry_run,
        limit=args.limit,
        county=args.county,
    )

    if result["errors"]:
        sys.exit(1)
