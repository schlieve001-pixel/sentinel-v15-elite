"""
VERIFUSE V2 — System Verification Diagnostic

Green Light diagnostic — validates every layer of the system.

Checks:
  1. Database connection + WAL mode
  2. Schema health: all tables, required columns
  3. Data integrity: asset counts by grade, orphans, duplicates
  4. Google credential validation
  5. Vertex API connectivity
  6. Staging pipeline status
  7. API server health
  8. File system: data dirs, PDFs, logs

Usage:
  python -m verifuse_v2.verify_system
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
RAW_PDF_DIR = DATA_DIR / "raw_pdfs"


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str = "", warn: bool = False):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.warn = warn

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        if self.warn:
            return "WARN"
        return "FAIL"


def check_database() -> list[CheckResult]:
    """Check database connection and WAL mode."""
    results = []
    try:
        from verifuse_v2.db import database as db

        conn = db.get_connection()
        results.append(CheckResult("DB Connection", True, str(db.DB_PATH)))

        # WAL mode
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        results.append(CheckResult("WAL Mode", mode == "wal", f"journal_mode={mode}"))

        conn.close()
    except Exception as e:
        results.append(CheckResult("DB Connection", False, str(e)))

    return results


def check_schema() -> list[CheckResult]:
    """Check all required tables and columns exist."""
    results = []
    required_tables = {
        "assets": ["asset_id", "county", "estimated_surplus", "total_indebtedness",
                    "sale_date", "data_grade", "winning_bid", "vertex_processed"],
        "legal_status": ["asset_id", "record_class", "data_grade", "days_remaining"],
        "statute_authority": ["jurisdiction", "state", "county"],
        "pipeline_events": ["event_id", "asset_id", "event_type"],
        "users": ["user_id", "email", "tier"],
        "unlocks": ["unlock_id", "user_id", "asset_id"],
        "tiers": ["tier_id", "name"],
        "scraper_registry": ["scraper_name"],
        "blacklist": ["address_hash"],
        "assets_staging": ["pdf_path", "status", "processed_at", "engine_version"],
    }

    try:
        from verifuse_v2.db import database as db

        with db.get_db() as conn:
            existing = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            for table, cols in required_tables.items():
                if table not in existing:
                    results.append(CheckResult(f"Table: {table}", False, "MISSING"))
                    continue

                existing_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                missing = [c for c in cols if c not in existing_cols]
                if missing:
                    results.append(CheckResult(
                        f"Table: {table}", False,
                        f"Missing columns: {', '.join(missing)}"
                    ))
                else:
                    results.append(CheckResult(f"Table: {table}", True, f"{len(existing_cols)} columns"))

    except Exception as e:
        results.append(CheckResult("Schema Check", False, str(e)))

    return results


def check_data_integrity() -> list[CheckResult]:
    """Check asset counts, orphans, duplicates."""
    results = []
    try:
        from verifuse_v2.db import database as db

        with db.get_db() as conn:
            # Total assets
            total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            results.append(CheckResult("Total Assets", total > 0, f"{total} records"))

            # By grade
            grades = conn.execute("""
                SELECT data_grade, COUNT(*) FROM assets
                GROUP BY data_grade ORDER BY COUNT(*) DESC
            """).fetchall()
            grade_str = ", ".join(f"{r[0]}:{r[1]}" for r in grades)
            results.append(CheckResult("Grade Distribution", True, grade_str or "No data"))

            # By county
            counties = conn.execute("""
                SELECT county, COUNT(*) FROM assets
                GROUP BY county ORDER BY COUNT(*) DESC
            """).fetchall()
            county_str = ", ".join(f"{r[0]}:{r[1]}" for r in counties)
            results.append(CheckResult("County Distribution", True, county_str or "No data"))

            # Orphan detection: assets without legal_status
            orphans = conn.execute("""
                SELECT COUNT(*) FROM assets a
                LEFT JOIN legal_status ls ON a.asset_id = ls.asset_id
                WHERE ls.asset_id IS NULL
            """).fetchone()[0]
            results.append(CheckResult("Orphan Assets", orphans == 0, f"{orphans} without legal_status", warn=orphans > 0))

            # Duplicate case_numbers
            dupes = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT case_number FROM assets
                    WHERE case_number IS NOT NULL AND case_number != ''
                    GROUP BY case_number HAVING COUNT(*) > 1
                )
            """).fetchone()[0]
            results.append(CheckResult("Duplicate Cases", dupes == 0, f"{dupes} duplicates", warn=dupes > 0))

            # Total pipeline value
            total_surplus = conn.execute(
                "SELECT COALESCE(SUM(estimated_surplus), 0) FROM assets WHERE estimated_surplus >= 1000"
            ).fetchone()[0]
            results.append(CheckResult("Pipeline Value", True, f"${total_surplus:,.2f}"))

    except Exception as e:
        results.append(CheckResult("Data Integrity", False, str(e)))

    return results


def check_credentials() -> list[CheckResult]:
    """Check Google credentials file."""
    results = []
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if not cred_path:
        results.append(CheckResult("GOOGLE_APPLICATION_CREDENTIALS", False, "Not set", warn=True))
        return results

    path = Path(cred_path)
    if not path.exists():
        results.append(CheckResult("Credentials File", False, f"Not found: {cred_path}"))
        return results

    try:
        data = json.loads(path.read_text())
        has_key = "private_key" in data
        has_project = "project_id" in data
        project = data.get("project_id", "unknown")

        if has_key and has_project:
            results.append(CheckResult("Credentials File", True, f"project={project}"))
        else:
            missing = []
            if not has_key:
                missing.append("private_key")
            if not has_project:
                missing.append("project_id")
            results.append(CheckResult("Credentials File", False, f"Missing: {', '.join(missing)}"))

    except json.JSONDecodeError as e:
        results.append(CheckResult("Credentials File", False, f"Invalid JSON: {e}"))

    return results


def check_vertex_connectivity() -> list[CheckResult]:
    """Lightweight check for Vertex AI connectivity."""
    results = []
    try:
        # Just test that we can resolve the API endpoint
        addr = socket.getaddrinfo("us-central1-aiplatform.googleapis.com", 443, socket.AF_INET)
        results.append(CheckResult("Vertex API DNS", True, "Resolved OK"))
    except socket.gaierror as e:
        results.append(CheckResult("Vertex API DNS", False, f"DNS failed: {e}", warn=True))

    return results


def check_staging_pipeline() -> list[CheckResult]:
    """Check staging pipeline status."""
    results = []
    try:
        from verifuse_v2.db import database as db

        with db.get_db() as conn:
            try:
                total = conn.execute("SELECT COUNT(*) FROM assets_staging").fetchone()[0]
                by_status = conn.execute("""
                    SELECT COALESCE(status, 'NULL'), COUNT(*)
                    FROM assets_staging GROUP BY status
                """).fetchall()
                status_str = ", ".join(f"{r[0]}:{r[1]}" for r in by_status)

                with_pdf = conn.execute(
                    "SELECT COUNT(*) FROM assets_staging WHERE pdf_path IS NOT NULL"
                ).fetchone()[0]

                results.append(CheckResult("Staging Total", True, f"{total} records"))
                results.append(CheckResult("Staging Status", True, status_str or "Empty"))
                results.append(CheckResult("PDFs Available", True, f"{with_pdf}/{total} have pdf_path"))

            except Exception as e:
                results.append(CheckResult("Staging Table", False, f"Error: {e}"))

    except Exception as e:
        results.append(CheckResult("Staging Pipeline", False, str(e)))

    return results


def check_api_server() -> list[CheckResult]:
    """Check if API server is running."""
    results = []
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8000/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            results.append(CheckResult("API Server", True, f"port=8000, status={data.get('status', 'ok')}"))
    except Exception:
        results.append(CheckResult("API Server", False, "Not running on port 8000", warn=True))

    return results


def check_filesystem() -> list[CheckResult]:
    """Check data directories and files."""
    results = []

    # Data directory
    results.append(CheckResult("Data Dir", DATA_DIR.exists(), str(DATA_DIR)))

    # DB file
    db_file = DATA_DIR / "verifuse_v2.db"
    if db_file.exists():
        size_mb = db_file.stat().st_size / 1024 / 1024
        results.append(CheckResult("Database File", True, f"{size_mb:.1f}MB"))
    else:
        results.append(CheckResult("Database File", False, "Not found"))

    # Raw PDF directories
    pdf_dirs = list(RAW_PDF_DIR.glob("*")) if RAW_PDF_DIR.exists() else []
    pdf_count = sum(1 for d in pdf_dirs if d.is_dir() for _ in d.glob("*.pdf"))
    results.append(CheckResult("Raw PDFs", True, f"{len(pdf_dirs)} counties, {pdf_count} PDFs"))

    # Logs directory
    if LOG_DIR.exists():
        log_files = list(LOG_DIR.glob("*"))
        results.append(CheckResult("Logs Dir", True, f"{len(log_files)} files"))
    else:
        results.append(CheckResult("Logs Dir", False, "Not found", warn=True))

    # Check logs writable
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        test_file = LOG_DIR / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        results.append(CheckResult("Logs Writable", True, "OK"))
    except Exception as e:
        results.append(CheckResult("Logs Writable", False, str(e)))

    return results


def run_diagnostics() -> dict:
    """Run all diagnostic checks and return structured results."""
    sections = {
        "Database": check_database,
        "Schema": check_schema,
        "Data Integrity": check_data_integrity,
        "Credentials": check_credentials,
        "Vertex AI": check_vertex_connectivity,
        "Staging Pipeline": check_staging_pipeline,
        "API Server": check_api_server,
        "File System": check_filesystem,
    }

    all_results = {}
    for section_name, check_fn in sections.items():
        all_results[section_name] = check_fn()

    return all_results


def print_diagnostics(all_results: dict) -> int:
    """Print formatted diagnostic table. Returns exit code (0=all pass, 1=failures)."""
    print()
    print("=" * 70)
    print("  VERIFUSE V2 — SYSTEM DIAGNOSTIC")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    total_pass = 0
    total_fail = 0
    total_warn = 0

    for section, checks in all_results.items():
        print(f"\n  [{section}]")
        for check in checks:
            icon = "PASS" if check.passed else ("WARN" if check.warn else "FAIL")
            marker = "+" if check.passed else ("~" if check.warn else "!")
            print(f"    [{marker}] {icon:4s} | {check.name:30s} | {check.detail}")

            if check.passed:
                total_pass += 1
            elif check.warn:
                total_warn += 1
            else:
                total_fail += 1

    total = total_pass + total_fail + total_warn
    print()
    print("=" * 70)
    print(f"  RESULTS: {total_pass}/{total} PASS, {total_warn} WARN, {total_fail} FAIL")

    if total_fail == 0:
        print("  STATUS: GREEN LIGHT")
    elif total_fail <= 2:
        print("  STATUS: YELLOW — non-critical failures")
    else:
        print("  STATUS: RED — critical issues detected")

    print("=" * 70)
    print()

    return 1 if total_fail > 0 else 0


if __name__ == "__main__":
    results = run_diagnostics()
    exit_code = print_diagnostics(results)
    sys.exit(exit_code)
