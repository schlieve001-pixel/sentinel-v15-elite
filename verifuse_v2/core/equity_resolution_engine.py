"""
VeriFuse vNEXT Gate 6 — Equity Resolution Engine
==================================================
Classifies each captured foreclosure asset into one of five equity categories
based on surplus amount, junior liens, transfer evidence, and time-on-book.

Classification logic (strict, fail-closed):
  TREASURER_TRANSFERRED   — explicit text evidence only ("Overbid Transferred On/To",
                            remit doc, CERTQH presence). NEVER from time alone.
  LIEN_ABSORBED           — junior liens ≥ gross surplus (net equity = 0)
  OWNER_ELIGIBLE          — net owner equity > 0 after lien deduction
  NEEDS_REVIEW_TREASURER_WINDOW — time > 30 months + no explicit transfer evidence
  RESOLUTION_PENDING      — default; net equity=0 but no lien data or < 30 months

State mutations:
  - Writes to equity_resolution (INSERT OR REPLACE — idempotent)
  - Writes to lien_records only via seed_lien_records() helper (INSERT OR IGNORE)
  - Does NOT mutate asset_registry, leads, or extraction_events

Explicit transfer detection (strict regex):
  TRANSFER_RE = r"overbid\\s+transferred\\s+(on|to)|remit\\s+to"
  CERTQH doc in evidence_documents (doc_family='OB', filename LIKE '%CERTQH%')
  counts as explicit transfer ONLY when it exists for the asset.

Lienor tab parsing:
  Reads LIENOR_TAB html_snapshot, parses lienholders + amounts → lien_records
  (source='govsoft_html'). Amounts stored as integer cents. is_open=1 (open lien).

Usage:
  from verifuse_v2.core.equity_resolution_engine import resolve

  db = sqlite3.connect("verifuse_v2/data/verifuse_v2.db")
  result = resolve("FORECLOSURE:CO:JEFFERSON:J2500358", db)
  # {"classification": "LIEN_ABSORBED", "net_owner_equity_cents": 0, ...}
"""

from __future__ import annotations

import gzip
import logging
import re
import sqlite3
import time
from decimal import Decimal
from uuid import uuid4

log = logging.getLogger(__name__)

# ── Strict transfer evidence regex ────────────────────────────────────────────
#
# Requires an explicit label-anchored phrase — avoids false positives from
# generic mentions of "transferred" in property descriptions or other contexts.
# CERTQH doc presence is checked separately (see _detect_explicit_transfer).
#
TRANSFER_RE = re.compile(
    r"overbid\s+transferred\s+(on|to)|remit\s+to",
    re.IGNORECASE,
)

# Amount label regex for lienor tab parsing
AMOUNT_RE = re.compile(r"\$\s*([\d,]+\.?\d{0,2})")

# Lien type heuristics (case-insensitive filename/label matching)
_LIEN_TYPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\birs\b|\binternal\s+revenue\b|\bfederal\s+tax\b", re.I), "IRS"),
    (re.compile(r"\bhoa\b|\bhomeowner.?s?\s+assoc", re.I), "HOA"),
    (re.compile(r"\bmortgage\b|\bdeed\s+of\s+trust\b|\blender\b", re.I), "MORTGAGE"),
    (re.compile(r"\bjudgment\b|\bjudgement\b", re.I), "JUDGMENT"),
]


def _now_ts() -> int:
    return int(time.time())


def _lien_type_from_text(text: str) -> str:
    """Heuristically classify lien type from lienholder name/label text."""
    for pattern, lien_type in _LIEN_TYPE_MAP:
        if pattern.search(text):
            return lien_type
    return "OTHER"


def _parse_cents(text: str) -> int:
    """Parse '$1,234.56' or '1234.56' to integer cents. Returns 0 on failure."""
    try:
        m = AMOUNT_RE.search(text)
        if not m:
            return 0
        return int(Decimal(m.group(1).replace(",", "")) * 100)
    except Exception:
        return 0


def _get_gross_surplus_cents(asset_id: str, conn: sqlite3.Connection) -> int:
    """Return gross overbid surplus in cents from asset_registry.amount_cents.

    Falls back to leads.overbid_amount (* 100) if asset_registry.amount_cents is NULL.
    Returns 0 if no data available.
    """
    row = conn.execute(
        "SELECT amount_cents FROM asset_registry WHERE asset_id = ?",
        [asset_id],
    ).fetchone()
    if row and row[0] is not None and row[0] > 0:
        return int(row[0])

    # Fallback: leads.overbid_amount
    lead_row = conn.execute(
        """SELECT overbid_amount FROM leads
           WHERE county || ':' || case_number = ?
              OR case_number = ?""",
        [asset_id.split(":")[-1], asset_id.split(":")[-1]],
    ).fetchone()

    if not lead_row:
        # Try joining via asset_registry.source_id
        ar = conn.execute(
            "SELECT county, source_id FROM asset_registry WHERE asset_id = ?",
            [asset_id],
        ).fetchone()
        if ar:
            lead_row = conn.execute(
                "SELECT overbid_amount FROM leads WHERE county = ? AND case_number = ?",
                [ar["county"], ar["source_id"].split(":")[-1] if ar["source_id"] else ""],
            ).fetchone()

    if lead_row and lead_row[0] is not None:
        try:
            return int(Decimal(str(lead_row[0])) * 100)
        except Exception:
            pass

    return 0


def _sum_open_junior_liens_cents(asset_id: str, conn: sqlite3.Connection) -> int:
    """Sum all open lien_records for this asset. Returns 0 if no lien data."""
    row = conn.execute(
        "SELECT SUM(amount_cents) FROM lien_records WHERE asset_id = ? AND is_open = 1",
        [asset_id],
    ).fetchone()
    return int(row[0] or 0) if row and row[0] is not None else 0


def _months_since_sale(asset_id: str, conn: sqlite3.Connection) -> int | None:
    """Return months since sale date (event_ts from asset_registry) as integer.

    Returns None if event_ts is NULL (data missing — never assume time window).
    Uses calendar-month approximation: 1 month = 30.4375 days.
    """
    row = conn.execute(
        "SELECT event_ts FROM asset_registry WHERE asset_id = ?",
        [asset_id],
    ).fetchone()
    if not row or row[0] is None:
        return None
    elapsed_seconds = _now_ts() - int(row[0])
    if elapsed_seconds < 0:
        return 0
    return int(elapsed_seconds / (30.4375 * 86400))


def _detect_explicit_transfer(asset_id: str, conn: sqlite3.Connection) -> bool:
    """Return True ONLY if explicit transfer evidence is found with a non-empty value.

    Strict two-part test for each html_snapshot:
      1. Find a dt/label element whose text matches TRANSFER_RE.
      2. The adjacent dd/value element must be non-empty (has actual text, not blank).

    GovSoft renders financial fields as <dt>Label</dt><dd>Value</dd> pairs.
    An empty <dd></dd> means "not yet recorded" — NOT transfer evidence.
    Matching label text alone (even with empty value) is NOT sufficient.

    NOTE: CERTQH (Certificate of Qualified Holder) presence signals an IRS lien
    claim but does NOT constitute transfer evidence — the IRS has a lien against
    the overbid, which is captured in lien_records. Transfer only occurs when
    explicit text evidence ("Overbid Transferred On: 2025-03-01") exists.

    NEVER returns True based on time alone, label text alone, or doc presence alone.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError:
        log.warning("[equity] beautifulsoup4 not installed — transfer detection unavailable")
        return False

    snaps = conn.execute(
        "SELECT raw_html_gzip, snapshot_type FROM html_snapshots WHERE asset_id = ?",
        [asset_id],
    ).fetchall()

    for snap in snaps:
        try:
            html = gzip.decompress(snap[0]).decode("utf-8", errors="replace")
        except Exception:
            continue

        # Fast pre-check: skip snapshots that don't even contain the transfer keywords
        if not TRANSFER_RE.search(html):
            continue

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            continue

        # Check dt/dd pairs: label matches TRANSFER_RE AND value is non-empty
        for dt in soup.find_all("dt"):
            label_text = dt.get_text(strip=True)
            if not TRANSFER_RE.search(label_text):
                continue
            # Find the immediately following dd sibling
            dd = dt.find_next_sibling("dd")
            if dd:
                value = dd.get_text(strip=True)
                if value:  # Non-empty value = actual transfer record
                    log.debug(
                        "[equity] %s: transfer evidence in %s: %r = %r",
                        asset_id, snap["snapshot_type"], label_text, value,
                    )
                    return True

        # Also check plain text patterns for non-DL HTML structures
        # (e.g., table cells with explicit "Overbid Transferred To: 12/01/2025")
        for tag in soup.find_all(["td", "span", "p"]):
            text = tag.get_text(separator=" ", strip=True)
            m = TRANSFER_RE.search(text)
            if m:
                # The matched text must be followed by non-whitespace content
                after = text[m.end():].strip()
                if after and not after.startswith("<"):
                    log.debug(
                        "[equity] %s: transfer evidence (table/span): %r",
                        asset_id, text[:100],
                    )
                    return True

    return False


def seed_lien_records(
    asset_id: str, conn: sqlite3.Connection, lienor_html: str | None = None
) -> int:
    """Parse LIENOR_TAB html_snapshot and INSERT OR IGNORE lien_records.

    Returns the number of lien_records rows inserted (0 if already seeded).
    If lienor_html is not provided, fetches from html_snapshots automatically.
    Uses source='govsoft_html'; all inserted liens are is_open=1.
    """
    if lienor_html is None:
        snap = conn.execute(
            """SELECT raw_html_gzip FROM html_snapshots
               WHERE asset_id = ? AND snapshot_type = 'LIENOR_TAB'
               LIMIT 1""",
            [asset_id],
        ).fetchone()
        if not snap:
            log.debug("[equity] No LIENOR_TAB snapshot for %s — no liens to seed", asset_id)
            return 0
        try:
            lienor_html = gzip.decompress(snap[0]).decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("[equity] Failed to decompress LIENOR_TAB for %s: %s", asset_id, exc)
            return 0

    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError:
        log.warning("[equity] beautifulsoup4 not installed — cannot parse lienor tab")
        return 0

    soup = BeautifulSoup(lienor_html, "lxml")
    inserted = 0
    now_ts = _now_ts()

    # Find table rows that contain lienholder data (heuristic: rows with $ amounts)
    for row in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        row_text = " ".join(cells)
        if not AMOUNT_RE.search(row_text):
            continue

        # Lienholder name: first non-empty, non-numeric cell
        lienholder_name = None
        for cell in cells:
            if cell and not re.match(r"^[\d$,.\s%]+$", cell):
                lienholder_name = cell[:200]
                break

        amount_cents = _parse_cents(row_text)
        if amount_cents <= 0:
            continue

        lien_type = _lien_type_from_text(lienholder_name or "")
        lien_id = str(uuid4())

        result = conn.execute(
            """INSERT OR IGNORE INTO lien_records
               (id, asset_id, lien_type, lienholder_name, amount_cents,
                is_open, source, retrieved_ts)
               VALUES (?,?,?,?,?,1,'govsoft_html',?)""",
            [lien_id, asset_id, lien_type, lienholder_name, amount_cents, now_ts],
        )
        inserted += result.rowcount

    log.info("[equity] seed_lien_records: %s → %d new lien_records", asset_id, inserted)
    return inserted


def resolve(asset_id: str, conn: sqlite3.Connection) -> dict:
    """Compute and persist equity_resolution for the given asset.

    Classification is deterministic — same inputs always produce same output.
    All DB writes are to equity_resolution only (INSERT OR REPLACE = idempotent).

    Returns dict:
      asset_id, gross_surplus_cents, junior_liens_total_cents,
      net_owner_equity_cents, classification, resolved_ts, notes
    """
    log.info("[equity] Resolving %s", asset_id)

    # ── Step 1: Seed lien_records from LIENOR_TAB if not yet seeded ──────────
    seed_lien_records(asset_id, conn)

    # ── Step 2: Gather financial inputs ───────────────────────────────────────
    gross_cents = _get_gross_surplus_cents(asset_id, conn)
    liens_cents = _sum_open_junior_liens_cents(asset_id, conn)
    net_cents   = max(0, gross_cents - liens_cents)

    notes_parts: list[str] = []

    # ── Step 3: Explicit transfer evidence (check BEFORE math) ────────────────
    transfer_evidence = _detect_explicit_transfer(asset_id, conn)
    if transfer_evidence:
        classification = "TREASURER_TRANSFERRED"
        notes_parts.append("Explicit transfer evidence found (CERTQH doc or TRANSFER_RE match)")

    elif gross_cents == 0:
        # No surplus data → cannot classify
        classification = "RESOLUTION_PENDING"
        notes_parts.append("No gross surplus data available")

    elif net_cents == 0 and liens_cents >= gross_cents and gross_cents > 0:
        # Junior liens absorb entire surplus
        classification = "LIEN_ABSORBED"
        notes_parts.append(
            f"Liens {liens_cents}¢ ≥ gross {gross_cents}¢ — surplus fully absorbed"
        )

    elif net_cents > 0:
        # Owner has equity after lien deduction
        classification = "OWNER_ELIGIBLE"
        notes_parts.append(
            f"Net equity {net_cents}¢ after liens {liens_cents}¢"
        )

    else:
        # net==0, liens < gross or no liens — check time window
        months = _months_since_sale(asset_id, conn)
        if months is not None and months >= 30:
            classification = "NEEDS_REVIEW_TREASURER_WINDOW"
            notes_parts.append(f"{months} months since sale ≥ 30 — treasurer window review")
        else:
            classification = "RESOLUTION_PENDING"
            notes_parts.append(
                f"Months since sale: {months!r} (< 30 or unknown) — pending"
            )

    notes = "; ".join(notes_parts) if notes_parts else None
    resolved_ts = _now_ts()

    # ── Step 4: Persist to equity_resolution ─────────────────────────────────
    eq_id = str(uuid4())
    conn.execute(
        """INSERT OR REPLACE INTO equity_resolution
           (id, asset_id, gross_surplus_cents, junior_liens_total_cents,
            net_owner_equity_cents, classification, resolved_ts, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            eq_id, asset_id,
            gross_cents, liens_cents, net_cents,
            classification, resolved_ts, notes,
        ],
    )

    result = {
        "asset_id":                 asset_id,
        "gross_surplus_cents":      gross_cents,
        "junior_liens_total_cents": liens_cents,
        "net_owner_equity_cents":   net_cents,
        "classification":           classification,
        "resolved_ts":              resolved_ts,
        "notes":                    notes,
    }
    log.info(
        "[equity] %s → %s (gross=%d¢ liens=%d¢ net=%d¢)",
        asset_id, classification, gross_cents, liens_cents, net_cents,
    )
    return result
