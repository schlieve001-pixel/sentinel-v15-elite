"""
VERIFUSE V2 — fix_leads_schema.py (The Auto-Patcher)

Makes the `leads` table Vertex-ready. Handles three scenarios:
  1. `leads` is a VIEW (legacy) → drop view, create real table, migrate data
  2. `leads` is a TABLE but missing columns → ALTER TABLE ADD COLUMN
  3. `leads` is already correct → no-op (idempotent)

Canonical source of truth: VERIFUSE_DB_PATH env var.
Fail-fast: exits immediately if env var is missing.

Usage:
    export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
    python -m verifuse_v2.db.fix_leads_schema
"""

from __future__ import annotations

import os
import sqlite3
import sys

# ── Fail-fast: require VERIFUSE_DB_PATH ─────────────────────────────

DB_PATH = os.environ.get("VERIFUSE_DB_PATH")
if not DB_PATH:
    print("FATAL: VERIFUSE_DB_PATH environment variable is not set.")
    print("  export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db")
    sys.exit(1)

# ── Revenue columns Engine #4 needs ─────────────────────────────────

REQUIRED_COLUMNS = [
    # (column_name, column_type_and_default)
    ("id",                "TEXT PRIMARY KEY"),
    ("case_number",       "TEXT"),
    ("county",            "TEXT"),
    ("owner_name",        "TEXT"),
    ("property_address",  "TEXT"),
    ("estimated_surplus", "REAL DEFAULT 0.0"),
    ("record_hash",       "TEXT"),
    # Revenue columns (Engine #4)
    ("winning_bid",       "REAL DEFAULT 0.0"),
    ("total_debt",        "REAL DEFAULT 0.0"),
    ("surplus_amount",    "REAL DEFAULT 0.0"),
    ("overbid_amount",    "REAL DEFAULT 0.0"),
    ("confidence_score",  "REAL DEFAULT 0.0"),
    ("status",            "TEXT DEFAULT 'STAGED'"),
    ("sale_date",         "TEXT"),
    ("claim_deadline",    "TEXT"),
    ("data_grade",        "TEXT DEFAULT 'BRONZE'"),
    ("source_name",       "TEXT"),
    ("vertex_processed",  "INTEGER DEFAULT 0"),
    ("updated_at",        "TEXT"),
]

# Columns that can be added via ALTER TABLE (everything except PK)
ADDABLE_COLUMNS = [
    (name, typedef)
    for name, typedef in REQUIRED_COLUMNS
    if "PRIMARY KEY" not in typedef
]

CREATE_TABLE_SQL = """
CREATE TABLE leads (
    id                TEXT PRIMARY KEY,
    case_number       TEXT,
    county            TEXT,
    owner_name        TEXT,
    property_address  TEXT,
    estimated_surplus REAL DEFAULT 0.0,
    record_hash       TEXT,
    winning_bid       REAL DEFAULT 0.0,
    total_debt        REAL DEFAULT 0.0,
    surplus_amount    REAL DEFAULT 0.0,
    overbid_amount    REAL DEFAULT 0.0,
    confidence_score  REAL DEFAULT 0.0,
    status            TEXT DEFAULT 'STAGED',
    sale_date         TEXT,
    claim_deadline    TEXT,
    data_grade        TEXT DEFAULT 'BRONZE',
    source_name       TEXT,
    vertex_processed  INTEGER DEFAULT 0,
    updated_at        TEXT
)
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")  # OFF during migration
    return conn


def _get_object_type(conn: sqlite3.Connection, name: str) -> str | None:
    """Return 'table', 'view', or None."""
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", [name]
    ).fetchone()
    return row[0] if row else None


def _get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def patch_leads_schema() -> dict:
    report = {
        "db_path": DB_PATH,
        "action": None,
        "rows_migrated": 0,
        "columns_added": [],
        "columns_skipped": [],
        "backfills": [],
        "errors": [],
    }

    conn = get_connection()
    try:
        obj_type = _get_object_type(conn, "leads")

        # ── Case 1: `leads` is a VIEW → convert to real table ────────
        if obj_type == "view":
            print("\n  [DETECT] 'leads' is a VIEW on 'assets'. Converting to real TABLE...")
            report["action"] = "view_to_table"

            # Snapshot the view data before dropping
            rows = conn.execute("SELECT * FROM leads").fetchall()
            col_names = [desc[0] for desc in conn.execute("SELECT * FROM leads LIMIT 1").description]
            print(f"  [SNAPSHOT] {len(rows)} rows captured from view")

            # Drop the view
            conn.execute("DROP VIEW leads")
            print("  [DROP] VIEW 'leads' dropped")

            # Create the real table
            conn.execute(CREATE_TABLE_SQL)
            print("  [CREATE] TABLE 'leads' created with {0} columns".format(
                len(REQUIRED_COLUMNS)
            ))

            # Re-insert data from snapshot
            # Map view columns → table columns
            insert_cols = [c for c in col_names if c in {n for n, _ in REQUIRED_COLUMNS}]
            placeholders = ", ".join("?" for _ in insert_cols)
            col_list = ", ".join(insert_cols)

            for row in rows:
                row_dict = dict(row)
                values = [row_dict.get(c) for c in insert_cols]
                conn.execute(
                    f"INSERT OR IGNORE INTO leads ({col_list}) VALUES ({placeholders})",
                    values,
                )

            report["rows_migrated"] = len(rows)
            print(f"  [MIGRATE] {len(rows)} rows inserted into 'leads' table")

            # Also pull revenue data from assets if it exists
            assets_type = _get_object_type(conn, "assets")
            if assets_type == "table":
                assets_cols = _get_columns(conn, "assets")
                enrichment_map = {
                    "winning_bid": "winning_bid",
                    "total_debt": "total_debt",
                    "surplus_amount": "surplus_amount",
                    "overbid_amount": "overbid_amount",
                    "confidence_score": "confidence_score",
                    "sale_date": "sale_date",
                    "claim_deadline": "claim_deadline",
                    "data_grade": "data_grade",
                    "source_name": "source_name",
                    "estimated_surplus": "estimated_surplus",
                    "total_indebtedness": "total_debt",  # alias
                }

                for assets_col, leads_col in enrichment_map.items():
                    if assets_col in assets_cols:
                        updated = conn.execute(f"""
                            UPDATE leads
                            SET {leads_col} = (
                                SELECT a.{assets_col} FROM assets a
                                WHERE a.asset_id = leads.id
                            )
                            WHERE EXISTS (
                                SELECT 1 FROM assets a
                                WHERE a.asset_id = leads.id
                                  AND a.{assets_col} IS NOT NULL
                                  AND a.{assets_col} != 0
                                  AND a.{assets_col} != 0.0
                            )
                        """).rowcount
                        if updated > 0:
                            report["backfills"].append(f"{leads_col} ← assets.{assets_col}: {updated}")
                            print(f"  [ENRICH] {leads_col} ← assets.{assets_col}: {updated} rows")

        # ── Case 2: `leads` is a TABLE → add missing columns ────────
        elif obj_type == "table":
            print("\n  [DETECT] 'leads' is already a TABLE. Checking columns...")
            report["action"] = "alter_table"
            existing = _get_columns(conn, "leads")

            for col_name, col_def in ADDABLE_COLUMNS:
                if col_name in existing:
                    report["columns_skipped"].append(col_name)
                else:
                    # Strip DEFAULT from ALTER TABLE (SQLite adds it)
                    try:
                        conn.execute(
                            f"ALTER TABLE leads ADD COLUMN {col_name} {col_def}"
                        )
                        report["columns_added"].append(col_name)
                        print(f"  [ADD]  {col_name:20s} — {col_def}")
                    except Exception as e:
                        report["errors"].append(f"{col_name}: {e}")
                        print(f"  [ERR]  {col_name:20s} — {e}")

        # ── Case 3: `leads` doesn't exist → create from scratch ─────
        elif obj_type is None:
            print("\n  [DETECT] 'leads' does not exist. Creating...")
            report["action"] = "create_table"
            conn.execute(CREATE_TABLE_SQL)
            print(f"  [CREATE] TABLE 'leads' created with {len(REQUIRED_COLUMNS)} columns")

        # ── Backfill surplus_amount from estimated_surplus ────────────
        try:
            backfilled = conn.execute("""
                UPDATE leads
                SET surplus_amount = estimated_surplus
                WHERE (surplus_amount IS NULL OR surplus_amount = 0.0)
                  AND estimated_surplus > 0.0
            """).rowcount
            if backfilled > 0:
                report["backfills"].append(f"surplus_amount ← estimated_surplus: {backfilled}")
                print(f"  [BACKFILL] surplus_amount ← estimated_surplus: {backfilled} rows")
        except Exception:
            pass

        # ── Create indexes ───────────────────────────────────────────
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_leads_county ON leads(county)",
            "CREATE INDEX IF NOT EXISTS idx_leads_surplus ON leads(surplus_amount)",
            "CREATE INDEX IF NOT EXISTS idx_leads_case ON leads(case_number)",
            "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
            "CREATE INDEX IF NOT EXISTS idx_leads_grade ON leads(data_grade)",
        ]
        for ddl in indexes:
            try:
                conn.execute(ddl)
            except Exception:
                pass

        conn.commit()

        # ── Final verification ───────────────────────────────────────
        final_type = _get_object_type(conn, "leads")
        final_cols = _get_columns(conn, "leads")
        row_count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        surplus_count = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE surplus_amount > 0"
        ).fetchone()[0]

        print(f"\n{'='*60}")
        print(f"  Schema Verified: 'leads' table is ready for Engine #4.")
        print(f"  Type: {final_type}  |  Columns: {len(final_cols)}  |  Rows: {row_count}")
        print(f"  With surplus data: {surplus_count}/{row_count}")
        print(f"  Action: {report['action']}")
        if report["columns_added"]:
            print(f"  Added: {report['columns_added']}")
        if report["backfills"]:
            print(f"  Backfills: {report['backfills']}")
        if report["errors"]:
            print(f"  ERRORS: {report['errors']}")
        print(f"{'='*60}\n")

    except Exception as e:
        report["errors"].append(str(e))
        print(f"\n  [FATAL] {e}")
        raise
    finally:
        conn.close()

    return report


if __name__ == "__main__":
    result = patch_leads_schema()
    if result["errors"]:
        sys.exit(1)
