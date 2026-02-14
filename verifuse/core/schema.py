"""
VeriFuse Surplus Engine — Canonical Data Model
===============================================
DECISION: SQLite for local pipeline; Airtable is internal sync target only.
Attorneys never touch SQLite or Airtable. They see a read-only derived view
served via attorney.verifuse.tech.

All tables, enums, and field tiers are defined here. No other schema definitions
are authoritative.
"""

import sqlite3
import enum
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "verifuse.db"


# ============================================================================
# ENUMS (CANONICAL — NO OTHERS PERMITTED)
# ============================================================================

class RecordClass(str, enum.Enum):
    """Exactly four record classes. An asset is in one and only one."""
    PIPELINE = "PIPELINE"       # unverified, non-actionable
    QUALIFIED = "QUALIFIED"     # verified, but not attorney-ready
    ATTORNEY = "ATTORNEY"       # ready for legal action
    CLOSED = "CLOSED"           # resolved / expired / disposed


class DataGrade(str, enum.Enum):
    """Gate for QUALIFIED → ATTORNEY transition."""
    GOLD = "GOLD"       # full Tier 2, cross-verified, < 7 days old
    SILVER = "SILVER"   # full Tier 2, single-source or 7-30 days old
    BRONZE = "BRONZE"   # partial Tier 2 — BLOCKS attorney promotion
    REJECT = "REJECT"   # failed validation — kill state


class LegalConfidence(str, enum.Enum):
    """Source-level trust declaration. Required per scraper."""
    HIGH = "HIGH"       # official county site, structured data
    MED = "MED"         # official site, unstructured (PDF/HTML parse)
    LOW = "LOW"         # third-party aggregator, no official verification


class AssetType(str, enum.Enum):
    FORECLOSURE_SURPLUS = "FORECLOSURE_SURPLUS"
    TAX_OVERPAYMENT = "TAX_OVERPAYMENT"
    TAX_DEED_SURPLUS = "TAX_DEED_SURPLUS"
    PROBATE_EXCESS = "PROBATE_EXCESS"
    HOA_SURPLUS = "HOA_SURPLUS"


class EventType(str, enum.Enum):
    CREATED = "CREATED"
    CLASS_CHANGE = "CLASS_CHANGE"
    FIELD_UPDATE = "FIELD_UPDATE"
    SCORE_UPDATE = "SCORE_UPDATE"
    ATTORNEY_VIEW = "ATTORNEY_VIEW"
    ATTORNEY_INTEREST = "ATTORNEY_INTEREST"
    CASE_PACKET_GENERATED = "CASE_PACKET_GENERATED"
    KILL_SWITCH = "KILL_SWITCH"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# ============================================================================
# SCHEMA DDL
# ============================================================================

SCHEMA_SQL = """
-- ============================================================
-- TABLE: ASSETS (immutable facts — no workflow, no notes)
-- ============================================================
-- Tier 1: Identity (Mandatory)
-- Tier 2: Legal Actionability
-- Tier 3: Financial
-- Tier 4: Intelligence (Non-Blocking, internal only)

CREATE TABLE IF NOT EXISTS assets (
    -- TIER 1: IDENTITY (MANDATORY — gate for existence)
    asset_id            TEXT PRIMARY KEY,           -- immutable, format: {county}_{type}_{hash8}
    county              TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'CO',
    jurisdiction        TEXT NOT NULL,              -- "{county}, {state}"
    case_number         TEXT,                       -- case / parcel / tax ID
    asset_type          TEXT NOT NULL,              -- AssetType enum
    source_name         TEXT NOT NULL,              -- scraper that produced this

    -- TIER 2: LEGAL ACTIONABILITY (gate for ATTORNEY class)
    statute_window      TEXT,                       -- e.g. "5 years from sale date" per jurisdiction
    days_remaining      INTEGER,                    -- computed: statute expiry minus today
    owner_of_record     TEXT,                       -- legal owner name
    property_address    TEXT,
    lien_type           TEXT,                       -- e.g. "Deed of Trust", "Tax Lien"
    sale_date           TEXT,                       -- ISO 8601
    redemption_date     TEXT,                       -- ISO 8601, if applicable
    recorder_link       TEXT,                       -- official county recorder URL only

    -- TIER 3: FINANCIAL
    estimated_surplus   REAL,
    total_indebtedness  REAL,
    overbid_amount      REAL,
    fee_cap             REAL,                       -- jurisdiction-specific max attorney fee

    -- TIER 4: INTELLIGENCE (NEVER shown to attorneys)
    completeness_score  REAL,                       -- % of Tier 2 fields present
    confidence_score    REAL,                       -- source trust + cross-verification + age
    risk_score          REAL,                       -- jurisdiction volatility + redemption ambiguity
    data_grade          TEXT,                       -- DataGrade enum

    -- METADATA
    record_hash         TEXT,                       -- SHA-256 of canonical fields
    source_file_hash    TEXT,                       -- SHA-256 of source file
    source_file         TEXT,                       -- filename that produced this record
    created_at          TEXT NOT NULL,              -- ISO 8601
    updated_at          TEXT NOT NULL               -- ISO 8601
);

-- ============================================================
-- TABLE: PIPELINE_EVENTS (append-only audit log)
-- ============================================================
-- Every state transition, field update, and attorney interaction is logged.
-- This table is the forensic backbone. No deletes. No updates.

CREATE TABLE IF NOT EXISTS pipeline_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id            TEXT NOT NULL REFERENCES assets(asset_id),
    event_type          TEXT NOT NULL,              -- EventType enum
    old_value           TEXT,                       -- previous state/value (NULL for creation)
    new_value           TEXT NOT NULL,              -- new state/value
    actor               TEXT NOT NULL,              -- "system:{scraper_name}" or "human:{user_id}"
    reason              TEXT NOT NULL,              -- why this happened (machine-readable)
    metadata_json       TEXT,                       -- optional structured context
    created_at          TEXT NOT NULL               -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_events_asset ON pipeline_events(asset_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON pipeline_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time ON pipeline_events(created_at);

-- ============================================================
-- TABLE: LEGAL_STATUS (current state — exactly one row per asset)
-- ============================================================

CREATE TABLE IF NOT EXISTS legal_status (
    asset_id            TEXT PRIMARY KEY REFERENCES assets(asset_id),
    record_class        TEXT NOT NULL DEFAULT 'PIPELINE',  -- RecordClass enum
    data_grade          TEXT NOT NULL DEFAULT 'BRONZE',     -- DataGrade enum
    days_remaining      INTEGER,
    statute_window      TEXT,
    work_status         TEXT DEFAULT 'UNREVIEWED',          -- UNREVIEWED / INTERESTED / IN_PROGRESS / ARCHIVED
    attorney_id         TEXT,                               -- NULL until claimed
    last_evaluated_at   TEXT NOT NULL,                      -- ISO 8601
    promoted_at         TEXT,                               -- when it entered ATTORNEY class
    closed_at           TEXT,                               -- when it entered CLOSED class
    close_reason        TEXT                                -- expiration / attorney_action / kill_switch / manual
);

-- ============================================================
-- TABLE: STATUTE_AUTHORITY (jurisdiction-specific legal rules)
-- ============================================================
-- DECISION: This is the single source of truth for statute windows.
-- If a county is not in this table, assets from it CANNOT enter ATTORNEY class.
-- "Cannot verify" is an explicit state, not a silent assumption.

CREATE TABLE IF NOT EXISTS statute_authority (
    jurisdiction        TEXT NOT NULL,              -- "{county}, {state}"
    state               TEXT NOT NULL,
    county              TEXT NOT NULL,
    asset_type          TEXT NOT NULL,              -- AssetType enum
    statute_years       INTEGER NOT NULL,           -- window in years from triggering event
    triggering_event    TEXT NOT NULL,              -- "sale_date" or "recording_date"
    statute_citation    TEXT NOT NULL,              -- e.g. "C.R.S. 38-38-111"
    fee_cap_pct         REAL,                       -- max attorney fee as % of surplus (NULL = no cap)
    fee_cap_flat        REAL,                       -- max flat fee (NULL = no cap)
    requires_court      INTEGER NOT NULL DEFAULT 1, -- 1 = court petition required
    known_issues        TEXT,                       -- e.g. "County publishes incorrect sale dates"
    verified_date       TEXT NOT NULL,              -- when this rule was last verified
    verified_by         TEXT NOT NULL,              -- who verified (attorney name or "statute_text")
    confidence          TEXT NOT NULL DEFAULT 'HIGH', -- LegalConfidence enum
    PRIMARY KEY (jurisdiction, asset_type)
);

-- ============================================================
-- TABLE: SCRAPER_REGISTRY (coverage declarations)
-- ============================================================
-- Every scraper MUST have an entry here or it is disabled.

CREATE TABLE IF NOT EXISTS scraper_registry (
    scraper_name        TEXT PRIMARY KEY,
    jurisdiction        TEXT NOT NULL,
    record_type         TEXT NOT NULL,              -- AssetType enum
    fields_collected    TEXT NOT NULL,              -- JSON array of field names
    known_gaps          TEXT NOT NULL,              -- JSON array of missing fields
    update_frequency_days INTEGER NOT NULL,
    legal_confidence    TEXT NOT NULL,              -- LegalConfidence enum
    last_run_at         TEXT,
    last_run_status     TEXT,                       -- "SUCCESS" / "PARTIAL" / "FAILED"
    records_produced    INTEGER DEFAULT 0,
    enabled             INTEGER NOT NULL DEFAULT 1,
    disabled_reason     TEXT
);

-- ============================================================
-- TABLE: ATTORNEY_VIEW (materialized read-only view)
-- ============================================================
-- This is what attorneys see. Derived from assets + legal_status.
-- Rebuilt on every evaluation cycle. Never written to directly.
-- Contains ZERO internal scores, ZERO jargon.

CREATE VIEW IF NOT EXISTS attorney_view AS
SELECT
    a.county,
    a.jurisdiction,
    a.asset_id,
    a.asset_type,
    a.estimated_surplus,
    ls.days_remaining,
    ls.statute_window,
    a.recorder_link,
    ls.work_status AS status,
    a.owner_of_record,
    a.property_address,
    a.sale_date,
    a.case_number
FROM assets a
JOIN legal_status ls ON a.asset_id = ls.asset_id
WHERE ls.record_class = 'ATTORNEY'
  AND ls.days_remaining > 0
  AND ls.data_grade IN ('GOLD', 'SILVER')
  AND a.estimated_surplus >= 25000
ORDER BY ls.days_remaining ASC;

-- ============================================================
-- TABLE: BLACKLIST (address-level exclusions)
-- ============================================================

CREATE TABLE IF NOT EXISTS blacklist (
    address_hash        TEXT PRIMARY KEY,
    reason              TEXT NOT NULL,
    added_at            TEXT NOT NULL,
    added_by            TEXT NOT NULL
);
"""


def init_db(db_path: str = None) -> sqlite3.Connection:
    """Initialize the canonical database. Idempotent."""
    path = db_path or str(DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def seed_statute_authority(conn: sqlite3.Connection):
    """Seed Colorado statute authority table.

    DECISION: Colorado surplus funds are governed by C.R.S. 38-38-111 (foreclosure)
    and C.R.S. 39-11-151 (tax). Statute window is measured from sale date.

    UNCERTAINTY: Some counties interpret "5 years" as 5 calendar years vs 1826 days.
    DESIGN AROUND WORST CASE: We use 1825 days (5*365) which is the shorter interpretation.

    UNCERTAINTY: Douglas County publishes month-only sale dates.
    DESIGN: Assume 1st of month (worst case = shortest window).
    """
    counties = [
        # (county, asset_type, years, triggering_event, citation, fee_cap_pct, requires_court, known_issues)
        ("Denver", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Jefferson", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Arapahoe", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Adams", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Douglas", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1,
         "County publishes month-only sale dates. System assumes 1st of month (worst case)."),
        ("Mesa", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Eagle", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Teller", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Summit", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("San Miguel", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Pitkin", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Routt", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Denver", "TAX_OVERPAYMENT", 3, "sale_date", "C.R.S. 39-11-151", None, 0, None),
        ("Douglas", "TAX_OVERPAYMENT", 3, "sale_date", "C.R.S. 39-11-151", None, 0,
         "Treasurer format uses Mon-YY dates. System parses to 1st of month."),
        # Phase 3 Expansion: Front Range + Mountain
        ("El Paso", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Larimer", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Boulder", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Weld", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Garfield", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        ("Grand", "FORECLOSURE_SURPLUS", 5, "sale_date", "C.R.S. 38-38-111", None, 1, None),
        # Palm Beach County, FL — separate statute regime
        ("Palm Beach", "FORECLOSURE_SURPLUS", 1, "sale_date",
         "Fla. Stat. 45.032", None, 1,
         "Florida 1-year window from certificate of sale. Significantly shorter than CO."),
    ]

    for row in counties:
        county = row[0]
        state = "FL" if county == "Palm Beach" else "CO"
        jurisdiction = f"{county}, {state}"
        conn.execute("""
            INSERT OR IGNORE INTO statute_authority
            (jurisdiction, state, county, asset_type, statute_years, triggering_event,
             statute_citation, fee_cap_pct, requires_court, known_issues,
             verified_date, verified_by, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, date('now'), 'statute_text', 'HIGH')
        """, (jurisdiction, state, county, row[1], row[2], row[3], row[4], row[5], row[6], row[7]))

    conn.commit()


if __name__ == "__main__":
    conn = init_db()
    seed_statute_authority(conn)
    print(f"Database initialized at {DB_PATH}")
    print("Tables:", [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
    print("Views:", [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()])
    print("Statute authorities:", conn.execute("SELECT COUNT(*) FROM statute_authority").fetchone()[0])
    conn.close()
