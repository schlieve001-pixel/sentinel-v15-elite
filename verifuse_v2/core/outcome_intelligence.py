"""
verifuse_v2.core.outcome_intelligence — Filing Outcome Intelligence Engine

Aggregates attorney filing outcomes from the case_outcomes table.
This is the "Bloomberg Moat" — outcome data no competitor can replicate.

Data source: case_outcomes table (Migration 019)
Usage:
    engine = OutcomeIntelligence(db_path)
    metrics = engine.county_metrics("jefferson")
    statewide = engine.statewide_summary()
"""
from __future__ import annotations

import sqlite3
from typing import Optional


class OutcomeIntelligence:
    """Compute county and statewide filing outcome metrics."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_outcomes'"
        ).fetchone() is not None

    def county_metrics(self, county: str) -> dict:
        """Return outcome metrics for a specific county.

        Returns:
            {
                "county": str,
                "total_filed": int,
                "win_rate": float,
                "avg_recovery_days": int | None,
                "avg_amount_recovered": int | None,  # dollars
                "top_outcome_factors": list[str],
            }
        """
        conn = self._get_conn()
        try:
            if not self._table_exists(conn):
                return self._empty_metrics(county)
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN result IN ('won','settled') THEN 1 ELSE 0 END) as wins, "
                "AVG(time_to_recovery_days) as avg_days, "
                "AVG(amount_recovered_cents) as avg_amount "
                "FROM case_outcomes WHERE county = ?",
                [county]
            ).fetchone()
            if not row or not row["total"]:
                return self._empty_metrics(county)
            total = row["total"] or 0
            wins = row["wins"] or 0
            return {
                "county": county,
                "total_filed": total,
                "win_rate": round(wins / total, 2) if total > 0 else 0.0,
                "avg_recovery_days": round(row["avg_days"]) if row["avg_days"] else None,
                "avg_amount_recovered": round(row["avg_amount"] / 100) if row["avg_amount"] else None,
                "top_outcome_factors": ["lien_density", "surplus_size", "claim_window"],
            }
        finally:
            conn.close()

    def statewide_summary(self) -> dict:
        """Return statewide filing outcome summary."""
        conn = self._get_conn()
        try:
            if not self._table_exists(conn):
                return {"total_filed": 0, "win_rate": 0.0, "counties_with_data": 0}
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN result IN ('won','settled') THEN 1 ELSE 0 END) as wins, "
                "COUNT(DISTINCT county) as counties "
                "FROM case_outcomes"
            ).fetchone()
            total = row["total"] or 0
            wins = row["wins"] or 0
            return {
                "total_filed": total,
                "win_rate": round(wins / total, 2) if total > 0 else 0.0,
                "counties_with_data": row["counties"] or 0,
            }
        finally:
            conn.close()

    def record_outcome(
        self,
        case_id: str,
        attorney_id: str,
        result: str,
        amount_recovered_dollars: Optional[float] = None,
        time_to_recovery_days: Optional[int] = None,
        county: Optional[str] = None,
        filing_date: Optional[str] = None,
        hearing_date: Optional[str] = None,
        judge_name: Optional[str] = None,
        notes: Optional[str] = None,
        recorded_by: Optional[str] = None,
    ) -> str:
        """Record a case outcome. Returns the new outcome ID."""
        VALID_RESULTS = ("won", "settled", "dismissed", "pending", "withdrawn")
        if result not in VALID_RESULTS:
            raise ValueError(f"result must be one of {VALID_RESULTS}, got: {result!r}")
        conn = self._get_conn()
        try:
            amount_cents = int(amount_recovered_dollars * 100) if amount_recovered_dollars else None
            conn.execute(
                "INSERT INTO case_outcomes "
                "(case_id, attorney_id, filing_date, hearing_date, result, "
                "amount_recovered_cents, time_to_recovery_days, judge_name, county, notes, recorded_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [case_id, attorney_id, filing_date, hearing_date, result,
                 amount_cents, time_to_recovery_days, judge_name, county, notes, recorded_by]
            )
            row = conn.execute("SELECT last_insert_rowid()").fetchone()
            conn.commit()
            return str(row[0]) if row else "unknown"
        finally:
            conn.close()

    @staticmethod
    def _empty_metrics(county: str) -> dict:
        return {
            "county": county,
            "total_filed": 0,
            "win_rate": 0.0,
            "avg_recovery_days": None,
            "avg_amount_recovered": None,
            "top_outcome_factors": [],
        }
