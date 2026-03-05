"""
calculation_engine.py — Canonical overbid pool + net-to-owner calculation.

Pool source priority:
  VOUCHER    OBCLAIM/OBCKREQ/CKREQ doc present + OCR amount → authoritative
  LEDGER     Explicit overbid ledger document present
  HTML_MATH  winning_bid − total_due from HTML extraction
  UNVERIFIED Insufficient inputs

All monetary values stored as cents (int) in DB. Engine works in float dollars.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Optional


class PoolSource:
    VOUCHER    = "VOUCHER"
    LEDGER     = "LEDGER"
    HTML_MATH  = "HTML_MATH"
    UNVERIFIED = "UNVERIFIED"


@dataclass
class CalcInputs:
    lead_id:             str
    triggered_by:        str                          # user_id or 'system'
    winning_bid:         Optional[float] = None
    total_due:           Optional[float] = None       # total_indebtedness from extraction
    trustee_fees:        Optional[float] = None       # None → display_tier = POTENTIAL
    foreclosure_costs:   Optional[float] = None
    voucher_overbid:     Optional[float] = None       # from OBCLAIM/OBCKREQ OCR
    voucher_doc_id:      Optional[str]   = None
    junior_liens:        list            = field(default_factory=list)
    # [{amount_cents: int, is_open: int, lien_type: str, priority: int}, ...]


@dataclass
class CalcResult:
    pool_source:           str
    candidate_pool:        float            # gross overbid before fees
    verified_net_to_owner: Optional[float]  # None if trustee_fees missing
    confidence_score:      float            # 0.0–1.0
    confidence_reasons:    list
    missing_inputs:        list
    calc_hash:             str              # sha256 of canonical inputs
    display_tier:          str              # POTENTIAL | VERIFIED


def _to_cents(val: Optional[float]) -> Optional[int]:
    if val is None:
        return None
    return int(round(val * 100))


def _rule_confidence(
    inputs: CalcInputs,
    pool_source: str,
) -> tuple:
    """Rule-based confidence scorer. Returns (score, reasons[], missing[])."""
    pts = 0
    reasons = []
    missing = []

    # Pool source (0-35 pts)
    if pool_source == PoolSource.VOUCHER:
        pts += 35
        reasons.append("+35: pool sourced from overbid voucher (authoritative)")
    elif pool_source == PoolSource.LEDGER:
        pts += 25
        reasons.append("+25: pool sourced from confirmed ledger document")
    elif pool_source == PoolSource.HTML_MATH:
        pts += 10
        reasons.append("+10: pool computed from HTML math (unverified source)")
    else:
        missing.append("pool_source")
        reasons.append("+0: pool_source unverified — no voucher or proven inputs")

    # Total indebtedness (0-20 pts)
    if inputs.total_due and inputs.total_due > 0:
        pts += 20
        reasons.append("+20: total_indebtedness confirmed")
    else:
        missing.append("total_due")

    # Trustee fees (0-20 pts)
    if inputs.trustee_fees is not None:
        pts += 20
        reasons.append("+20: trustee_fees provided")
    else:
        missing.append("trustee_fees")
        reasons.append("+0: trustee_fees missing — cannot compute verified net")

    # Foreclosure costs (0-10 pts)
    if inputs.foreclosure_costs is not None:
        pts += 10
        reasons.append("+10: foreclosure_costs provided")
    else:
        missing.append("foreclosure_costs")

    # Caps
    if not inputs.total_due or inputs.total_due <= 0:
        pts = min(pts, 50)
        reasons.append("cap@50%: total_due missing")
    elif pool_source == PoolSource.UNVERIFIED:
        pts = min(pts, 60)
        reasons.append("cap@60%: pool_source unverified")

    return pts / 100.0, reasons, missing


def compute(inputs: CalcInputs) -> CalcResult:
    """
    Compute overbid pool and (if possible) verified net to owner.
    Returns CalcResult with full provenance.
    """
    # 1 — Resolve pool source (strict priority order)
    if inputs.voucher_overbid is not None and inputs.voucher_doc_id:
        pool_source    = PoolSource.VOUCHER
        candidate_pool = max(0.0, inputs.voucher_overbid)
    elif (
        inputs.winning_bid is not None
        and inputs.total_due is not None
        and inputs.winning_bid > 0
        and inputs.total_due > 0
    ):
        pool_source    = PoolSource.HTML_MATH
        candidate_pool = max(0.0, inputs.winning_bid - inputs.total_due)
    else:
        pool_source    = PoolSource.UNVERIFIED
        candidate_pool = 0.0

    # 2 — Verified net to owner (requires trustee_fees + foreclosure_costs)
    calc_missing = []
    if inputs.trustee_fees is None:      calc_missing.append("trustee_fees")
    if inputs.foreclosure_costs is None: calc_missing.append("foreclosure_costs")
    if pool_source == PoolSource.UNVERIFIED: calc_missing.append("pool_source")

    verified_net_to_owner = None
    if not calc_missing:
        junior_sum = sum(
            (lien.get("amount_cents", 0) / 100.0)
            for lien in inputs.junior_liens
            if lien.get("is_open", 0)
        )
        verified_net_to_owner = max(
            0.0,
            candidate_pool
            - (inputs.trustee_fees or 0.0)
            - (inputs.foreclosure_costs or 0.0)
            - junior_sum,
        )

    # 3 — calc_hash over canonical inputs (for audit trail)
    canonical = json.dumps(
        {
            "winning_bid":       inputs.winning_bid,
            "total_due":         inputs.total_due,
            "trustee_fees":      inputs.trustee_fees,
            "foreclosure_costs": inputs.foreclosure_costs,
            "voucher_overbid":   inputs.voucher_overbid,
            "voucher_doc_id":    inputs.voucher_doc_id,
            "junior_liens": sorted(
                inputs.junior_liens,
                key=lambda x: (x.get("priority", 999), x.get("lien_type", "")),
            ),
        },
        sort_keys=True,
    )
    calc_hash = hashlib.sha256(canonical.encode()).hexdigest()

    # 4 — Rule-based confidence
    conf_score, conf_reasons, conf_missing = _rule_confidence(inputs, pool_source)
    all_missing = list(dict.fromkeys(calc_missing + conf_missing))

    display_tier = "VERIFIED" if not calc_missing else "POTENTIAL"

    return CalcResult(
        pool_source=pool_source,
        candidate_pool=candidate_pool,
        verified_net_to_owner=verified_net_to_owner,
        confidence_score=conf_score,
        confidence_reasons=conf_reasons,
        missing_inputs=all_missing,
        calc_hash=calc_hash,
        display_tier=display_tier,
    )


def store(conn, result: CalcResult, inputs: CalcInputs) -> str:
    """
    Append-only insert to calculations table.
    Updates leads.calc_hash, leads.current_calc_id, leads.pool_source, leads.last_verified_ts.
    Returns calc_id.
    """
    calc_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO calculations (
            id, lead_id, calc_hash, pool_source,
            winning_bid_cents, total_due_cents, trustee_fees_cents, foreclosure_costs_cents,
            voucher_overbid_cents, voucher_doc_id, junior_liens_json,
            candidate_pool_cents, verified_net_cents,
            confidence_score, confidence_reasons_json, missing_inputs_json,
            display_tier, triggered_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            calc_id, inputs.lead_id, result.calc_hash, result.pool_source,
            _to_cents(inputs.winning_bid),   _to_cents(inputs.total_due),
            _to_cents(inputs.trustee_fees),  _to_cents(inputs.foreclosure_costs),
            _to_cents(inputs.voucher_overbid), inputs.voucher_doc_id,
            json.dumps(inputs.junior_liens),
            _to_cents(result.candidate_pool),
            _to_cents(result.verified_net_to_owner),
            result.confidence_score,
            json.dumps(result.confidence_reasons),
            json.dumps(result.missing_inputs),
            result.display_tier,
            inputs.triggered_by,
        ],
    )
    conn.execute(
        """UPDATE leads
           SET calc_hash        = ?,
               current_calc_id  = ?,
               pool_source      = ?,
               last_verified_ts = unixepoch()
           WHERE id = ?""",
        [result.calc_hash, calc_id, result.pool_source, inputs.lead_id],
    )
    return calc_id
