"""
VeriFuse Surplus Engine — Pipeline State Machine
==================================================
DECISION: All state transitions are deterministic, logged, and gated.
No silent promotions. No AI judgment. Every transition has a reason.

State Machine:
    PIPELINE → QUALIFIED    (requires Tier 1 complete + partial Tier 2)
    QUALIFIED → ATTORNEY    (requires full Tier 2, DataGrade ∈ {GOLD, SILVER}, days_remaining > 0)
    ATTORNEY → CLOSED       (expiration OR attorney action OR kill-switch)
    ANY → CLOSED            (kill-switch or manual override, with reason)

Reverse transitions are NOT permitted. A CLOSED asset stays CLOSED.
A QUALIFIED asset cannot go back to PIPELINE.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, date
from typing import Optional

from .schema import RecordClass, DataGrade, EventType, LegalConfidence


# ============================================================================
# FIELD TIER DEFINITIONS
# ============================================================================

TIER_1_FIELDS = {"asset_id", "county", "jurisdiction", "case_number", "asset_type"}
TIER_2_FIELDS = {
    "statute_window", "days_remaining", "owner_of_record",
    "property_address", "lien_type", "sale_date", "recorder_link",
}
TIER_3_FIELDS = {"estimated_surplus", "total_indebtedness", "overbid_amount", "fee_cap"}
TIER_4_FIELDS = {"completeness_score", "confidence_score", "risk_score"}

# Values that look non-NULL but are actually garbage placeholders.
# Any field containing one of these (case-insensitive) is treated as MISSING.
PLACEHOLDER_VALUES = {
    "", "unknown", "n/a", "na", "none", "tbd", "check records",
    "check county site", "not available", "pending", "see file",
}


def _is_real_value(val) -> bool:
    """Return True only if val is a real, non-placeholder value."""
    if val is None:
        return False
    s = str(val).strip()
    if s.lower() in PLACEHOLDER_VALUES:
        return False
    # Catch patterns like "MESA-2025-999" that look like test data
    # but allow real case numbers (they vary too much to pattern-match safely)
    return True


def _compute_data_age(timestamp_str: Optional[str]) -> int:
    """Days since the asset was last updated. Used for confidence degradation."""
    if not timestamp_str:
        return 30  # Conservative default: assume 30 days old
    try:
        # Handle ISO format with or without Z suffix
        ts = timestamp_str.rstrip("Z")
        updated = datetime.fromisoformat(ts)
        return max(0, (datetime.utcnow() - updated).days)
    except (ValueError, TypeError):
        return 30


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _log_event(conn: sqlite3.Connection, asset_id: str, event_type: EventType,
               old_value: Optional[str], new_value: str, actor: str,
               reason: str, metadata: dict = None):
    """Append-only event log. Never fails silently."""
    conn.execute("""
        INSERT INTO pipeline_events
        (asset_id, event_type, old_value, new_value, actor, reason, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        asset_id, event_type.value, old_value, new_value, actor, reason,
        json.dumps(metadata) if metadata else None, _now()
    ))


# ============================================================================
# SCORING ENGINE (INTERNAL ONLY — scores never reach attorney UI)
# ============================================================================

def compute_completeness(asset_row: dict) -> float:
    """% of required Tier 2 fields that have real (non-placeholder) values."""
    present = sum(1 for f in TIER_2_FIELDS if _is_real_value(asset_row.get(f)))
    return round(present / len(TIER_2_FIELDS), 3)


def compute_confidence(asset_row: dict, scraper_confidence: str, data_age_days: int) -> float:
    """Source trust + cross-verification + age of data.

    DECISION: Simple deterministic formula, not ML.
    - Source trust: HIGH=1.0, MED=0.7, LOW=0.4
    - Age penalty: -0.05 per 7 days over 7 days, floor 0.0
    - Cross-verification bonus: +0.1 if record_hash matches multiple sources (not implemented yet)
    """
    trust = {"HIGH": 1.0, "MED": 0.7, "LOW": 0.4}.get(scraper_confidence, 0.3)
    age_penalty = max(0, (data_age_days - 7) / 7) * 0.05
    score = max(0.0, trust - age_penalty)
    return round(score, 3)


def compute_risk(asset_row: dict, statute_row: dict = None) -> float:
    """Jurisdiction volatility + redemption ambiguity + owner ambiguity.

    Higher = more risk = less desirable for attorney.
    Scale: 0.0 (safe) to 1.0 (dangerous).

    DECISION: Deterministic rules, not a model.
    """
    risk = 0.0

    # Redemption ambiguity
    if asset_row.get("redemption_date") is None and asset_row.get("asset_type") in (
        "FORECLOSURE_SURPLUS", "TAX_DEED_SURPLUS"):
        risk += 0.2

    # Owner ambiguity
    owner = asset_row.get("owner_of_record", "")
    if not _is_real_value(owner):
        risk += 0.3
    elif any(w in owner.upper() for w in ["ET AL", "ESTATE", "TRUST", "UNKNOWN HEIRS"]):
        risk += 0.15

    # Days remaining urgency
    days = asset_row.get("days_remaining")
    if days is not None and days < 30:
        risk += 0.2
    elif days is not None and days < 90:
        risk += 0.1

    # Jurisdiction issues
    if statute_row and statute_row.get("known_issues"):
        risk += 0.1

    return round(min(1.0, risk), 3)


def compute_data_grade(completeness: float, confidence: float, days_remaining: int) -> DataGrade:
    """Deterministic grade assignment.

    GOLD:   completeness == 1.0 AND confidence >= 0.8 AND days_remaining > 30
    SILVER: completeness == 1.0 AND confidence >= 0.5 AND days_remaining > 0
    BRONZE: completeness < 1.0 (BLOCKS attorney promotion)
    REJECT: days_remaining <= 0 OR confidence < 0.3
    """
    if days_remaining is not None and days_remaining <= 0:
        return DataGrade.REJECT
    if confidence < 0.3:
        return DataGrade.REJECT
    if completeness < 1.0:
        return DataGrade.BRONZE
    if confidence >= 0.8 and (days_remaining is None or days_remaining > 30):
        return DataGrade.GOLD
    if confidence >= 0.5 and (days_remaining is None or days_remaining > 0):
        return DataGrade.SILVER
    return DataGrade.BRONZE


# ============================================================================
# DAYS REMAINING CALCULATOR
# ============================================================================

def compute_days_remaining(sale_date_str: str, statute_years: int) -> Optional[int]:
    """Calculate days remaining in statute window.

    DECISION: Uses sale_date as triggering event (per statute_authority table).
    Returns None if sale_date is unparseable (asset enters "cannot verify" state).
    """
    if not sale_date_str:
        return None
    try:
        sale_date = date.fromisoformat(sale_date_str)
    except (ValueError, TypeError):
        return None

    expiry = sale_date.replace(year=sale_date.year + statute_years)
    remaining = (expiry - date.today()).days
    return remaining


# ============================================================================
# STATE TRANSITIONS
# ============================================================================

def evaluate_asset(conn: sqlite3.Connection, asset_id: str, actor: str = "system:evaluator"):
    """Evaluate an asset and transition it if gate conditions are met.

    This is the ONLY function that changes record_class. Direct SQL updates
    to legal_status.record_class are forbidden.

    Returns: (new_class, reason) or (current_class, "no_change")
    """
    # Fetch current state
    row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    if not row:
        return None, "asset_not_found"

    asset = dict(zip([d[0] for d in conn.execute("SELECT * FROM assets LIMIT 0").description],
                     row))

    status_row = conn.execute(
        "SELECT * FROM legal_status WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if not status_row:
        return None, "no_legal_status"

    status = dict(zip(
        [d[0] for d in conn.execute("SELECT * FROM legal_status LIMIT 0").description],
        status_row
    ))

    current_class = RecordClass(status["record_class"])

    # CLOSED is terminal
    if current_class == RecordClass.CLOSED:
        return current_class, "no_change:terminal"

    # Fetch statute authority
    statute = conn.execute(
        "SELECT * FROM statute_authority WHERE jurisdiction = ? AND asset_type = ?",
        (asset["jurisdiction"], asset["asset_type"])
    ).fetchone()

    statute_dict = None
    if statute:
        statute_dict = dict(zip(
            [d[0] for d in conn.execute("SELECT * FROM statute_authority LIMIT 0").description],
            statute
        ))

    # Fetch scraper confidence
    scraper = conn.execute(
        "SELECT legal_confidence FROM scraper_registry WHERE scraper_name = ?",
        (asset["source_name"],)
    ).fetchone()
    scraper_confidence = scraper[0] if scraper else "LOW"

    # Compute days remaining and statute window (Tier 2 derived fields)
    days_remaining = asset.get("days_remaining")
    statute_window = asset.get("statute_window")
    if statute_dict and asset.get("sale_date"):
        days_remaining = compute_days_remaining(
            asset["sale_date"], statute_dict["statute_years"]
        )
        statute_window = f"{statute_dict['statute_years']} years from {statute_dict['triggering_event']}"

    # Write computed Tier 2 values back to asset BEFORE completeness check
    conn.execute("""
        UPDATE assets SET
            days_remaining = ?, statute_window = ?
        WHERE asset_id = ?
    """, (days_remaining, statute_window, asset_id))

    # Re-read asset with computed values for accurate completeness
    asset["days_remaining"] = days_remaining
    asset["statute_window"] = statute_window

    # Compute scores
    completeness = compute_completeness(asset)
    # Use created_at for age — updated_at refreshes on every evaluation and would always be ~0
    data_age = _compute_data_age(asset.get("created_at"))
    confidence = compute_confidence(asset, scraper_confidence, data_age)
    risk = compute_risk(asset, statute_dict)

    grade = compute_data_grade(completeness, confidence, days_remaining or -1)

    # Update scores on asset (internal only)
    conn.execute("""
        UPDATE assets SET
            completeness_score = ?, confidence_score = ?, risk_score = ?,
            data_grade = ?, updated_at = ?
        WHERE asset_id = ?
    """, (completeness, confidence, risk, grade.value, _now(), asset_id))

    # Update legal_status scores
    conn.execute("""
        UPDATE legal_status SET
            data_grade = ?, days_remaining = ?, statute_window = ?,
            last_evaluated_at = ?
        WHERE asset_id = ?
    """, (
        grade.value, days_remaining,
        f"{statute_dict['statute_years']} years from {statute_dict['triggering_event']}" if statute_dict else None,
        _now(), asset_id
    ))

    # --- KILL SWITCH CHECKS ---

    # Kill: expired statute
    if days_remaining is not None and days_remaining <= 0:
        return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                           actor, "kill_switch:statute_expired",
                           {"days_remaining": days_remaining})

    # Kill: REJECT grade
    if grade == DataGrade.REJECT:
        return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                           actor, "kill_switch:data_grade_reject",
                           {"grade": grade.value, "confidence": confidence})

    # Kill: no statute authority for this jurisdiction
    if not statute_dict and current_class in (RecordClass.QUALIFIED, RecordClass.ATTORNEY):
        return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                           actor, "kill_switch:no_statute_authority",
                           {"jurisdiction": asset["jurisdiction"]})

    # --- PROMOTION CHECKS ---

    if current_class == RecordClass.PIPELINE:
        # PIPELINE → QUALIFIED requires Tier 1 complete + partial Tier 2
        tier1_complete = all(
            _is_real_value(asset.get(f))
            for f in TIER_1_FIELDS
        )
        partial_tier2 = completeness >= 0.5

        if tier1_complete and partial_tier2:
            return _transition(conn, asset_id, RecordClass.PIPELINE, RecordClass.QUALIFIED,
                               actor, "promotion:tier1_complete_partial_tier2",
                               {"completeness": completeness, "tier1_check": True})

    elif current_class == RecordClass.ATTORNEY:
        # ATTORNEY quality gate: kill if data quality has degraded
        if completeness < 1.0 or grade in (DataGrade.BRONZE, DataGrade.REJECT):
            return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                               actor, "kill_switch:attorney_quality_degraded",
                               {"completeness": completeness, "grade": grade.value})
        if not _is_real_value(asset.get("owner_of_record")):
            return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                               actor, "kill_switch:placeholder_owner",
                               {"owner": asset.get("owner_of_record")})
        if not _is_real_value(asset.get("property_address")):
            return _transition(conn, asset_id, current_class, RecordClass.CLOSED,
                               actor, "kill_switch:placeholder_address",
                               {"address": asset.get("property_address")})

    elif current_class == RecordClass.QUALIFIED:
        # QUALIFIED → ATTORNEY requires full Tier 2, GOLD/SILVER, days > 0, manageable risk
        # Hard blocks: real owner and real address required for attorney class
        has_real_owner = _is_real_value(asset.get("owner_of_record"))
        has_real_address = _is_real_value(asset.get("property_address"))

        if (completeness >= 1.0
                and grade in (DataGrade.GOLD, DataGrade.SILVER)
                and days_remaining is not None
                and days_remaining > 0
                and statute_dict is not None
                and risk < 0.8
                and has_real_owner
                and has_real_address):
            return _transition(conn, asset_id, RecordClass.QUALIFIED, RecordClass.ATTORNEY,
                               actor, "promotion:full_tier2_grade_eligible",
                               {"grade": grade.value, "days_remaining": days_remaining,
                                "completeness": completeness, "risk": risk})

    conn.commit()
    return current_class, "no_change"


def _transition(conn: sqlite3.Connection, asset_id: str,
                old_class: RecordClass, new_class: RecordClass,
                actor: str, reason: str, metadata: dict = None):
    """Execute a class transition with full audit trail."""

    _log_event(conn, asset_id, EventType.CLASS_CHANGE,
               old_class.value, new_class.value, actor, reason, metadata)

    updates = {"record_class": new_class.value, "last_evaluated_at": _now()}
    if new_class == RecordClass.ATTORNEY:
        updates["promoted_at"] = _now()
    elif new_class == RecordClass.CLOSED:
        updates["closed_at"] = _now()
        updates["close_reason"] = reason

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [asset_id]
    conn.execute(f"UPDATE legal_status SET {set_clause} WHERE asset_id = ?", values)

    conn.commit()
    return new_class, reason


def close_asset(conn: sqlite3.Connection, asset_id: str, reason: str,
                actor: str = "system:evaluator"):
    """Explicitly close an asset. Used for manual overrides and attorney actions."""
    status = conn.execute(
        "SELECT record_class FROM legal_status WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if not status:
        return None, "not_found"

    current = RecordClass(status[0])
    if current == RecordClass.CLOSED:
        return current, "already_closed"

    return _transition(conn, asset_id, current, RecordClass.CLOSED, actor, reason)


def mark_attorney_interest(conn: sqlite3.Connection, asset_id: str, attorney_id: str):
    """Attorney marks interest in an asset. Logged event, updates work_status."""
    _log_event(conn, asset_id, EventType.ATTORNEY_INTEREST,
               None, attorney_id, f"attorney:{attorney_id}",
               "attorney_marked_interest")

    conn.execute("""
        UPDATE legal_status SET work_status = 'INTERESTED', attorney_id = ?
        WHERE asset_id = ?
    """, (attorney_id, asset_id))
    conn.commit()


# ============================================================================
# BATCH EVALUATION
# ============================================================================

def evaluate_all(conn: sqlite3.Connection, max_passes: int = 3):
    """Evaluate every non-CLOSED asset. Loops until convergence or max_passes.

    Multiple passes are needed because PIPELINE→QUALIFIED happens in pass 1,
    then QUALIFIED→ATTORNEY happens in pass 2. Max 3 passes since there are
    only 3 non-terminal states.
    """
    results = {"promoted": 0, "killed": 0, "unchanged": 0, "errors": 0}

    for pass_num in range(max_passes):
        assets = conn.execute("""
            SELECT a.asset_id FROM assets a
            JOIN legal_status ls ON a.asset_id = ls.asset_id
            WHERE ls.record_class != 'CLOSED'
        """).fetchall()

        pass_promoted = 0
        for (asset_id,) in assets:
            try:
                new_class, reason = evaluate_asset(conn, asset_id)
                if "promotion" in reason:
                    results["promoted"] += 1
                    pass_promoted += 1
                elif "kill_switch" in reason:
                    results["killed"] += 1
                else:
                    results["unchanged"] += 1
            except Exception as e:
                results["errors"] += 1
                _log_event(conn, asset_id, EventType.KILL_SWITCH,
                           None, "EVALUATION_ERROR", "system:evaluator",
                           f"evaluation_failed: {str(e)[:200]}")

        if pass_promoted == 0:
            break  # Converged

    return results


# ============================================================================
# INGESTION (from scrapers)
# ============================================================================

def ingest_asset(conn: sqlite3.Connection, data: dict, source_name: str) -> str:
    """Ingest a raw asset from a scraper into PIPELINE class.

    Returns asset_id. Deduplicates by record_hash.
    """
    # Generate deterministic asset_id
    county = data.get("county", "UNKNOWN")
    asset_type = data.get("asset_type", "FORECLOSURE_SURPLUS")
    case = data.get("case_number", "")
    address = data.get("property_address", "")
    hash_input = f"{county}:{asset_type}:{case}:{address}".lower()
    hash8 = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
    asset_id = f"{county.lower().replace(' ', '_')}_{asset_type.lower()}_{hash8}"

    # Record hash for dedup
    record_fields = sorted(f"{k}:{v}" for k, v in data.items() if v is not None)
    record_hash = hashlib.sha256("|".join(record_fields).encode()).hexdigest()

    # Check for existing
    existing = conn.execute(
        "SELECT asset_id, record_hash FROM assets WHERE asset_id = ?", (asset_id,)
    ).fetchone()

    state = data.get("state", "CO")
    jurisdiction = f"{county}, {state}"
    now = _now()

    if existing:
        if existing[1] == record_hash:
            return asset_id  # No change
        # Update existing record
        conn.execute("""
            UPDATE assets SET
                case_number = COALESCE(?, case_number),
                owner_of_record = COALESCE(?, owner_of_record),
                property_address = COALESCE(?, property_address),
                sale_date = COALESCE(?, sale_date),
                estimated_surplus = COALESCE(?, estimated_surplus),
                total_indebtedness = COALESCE(?, total_indebtedness),
                overbid_amount = COALESCE(?, overbid_amount),
                lien_type = COALESCE(?, lien_type),
                recorder_link = COALESCE(?, recorder_link),
                record_hash = ?,
                source_file_hash = ?,
                source_file = ?,
                updated_at = ?
            WHERE asset_id = ?
        """, (
            data.get("case_number"), data.get("owner_of_record"),
            data.get("property_address"), data.get("sale_date"),
            data.get("estimated_surplus"), data.get("total_indebtedness"),
            data.get("overbid_amount"), data.get("lien_type"),
            data.get("recorder_link"),
            record_hash, data.get("source_file_hash"), data.get("source_file"),
            now, asset_id
        ))
        _log_event(conn, asset_id, EventType.FIELD_UPDATE,
                   None, "updated_from_scraper", f"system:{source_name}",
                   "scraper_re-ingestion_with_new_data")
    else:
        conn.execute("""
            INSERT INTO assets
            (asset_id, county, state, jurisdiction, case_number, asset_type, source_name,
             statute_window, days_remaining, owner_of_record, property_address,
             lien_type, sale_date, redemption_date, recorder_link,
             estimated_surplus, total_indebtedness, overbid_amount, fee_cap,
             completeness_score, confidence_score, risk_score, data_grade,
             record_hash, source_file_hash, source_file, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?)
        """, (
            asset_id, county, state, jurisdiction,
            data.get("case_number"), asset_type, source_name,
            None, None, data.get("owner_of_record"), data.get("property_address"),
            data.get("lien_type"), data.get("sale_date"), data.get("redemption_date"),
            data.get("recorder_link"),
            data.get("estimated_surplus"), data.get("total_indebtedness"),
            data.get("overbid_amount"), data.get("fee_cap"),
            0.0, 0.0, 0.0, DataGrade.BRONZE.value,
            record_hash, data.get("source_file_hash"), data.get("source_file"),
            now, now
        ))

        # Create legal_status row
        conn.execute("""
            INSERT INTO legal_status
            (asset_id, record_class, data_grade, last_evaluated_at)
            VALUES (?, ?, ?, ?)
        """, (asset_id, RecordClass.PIPELINE.value, DataGrade.BRONZE.value, now))

        _log_event(conn, asset_id, EventType.CREATED,
                   None, RecordClass.PIPELINE.value, f"system:{source_name}",
                   "initial_ingestion",
                   {"source": source_name, "county": county})

    conn.commit()
    return asset_id
