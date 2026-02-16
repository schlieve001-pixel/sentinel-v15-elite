#!/usr/bin/env python3
"""
dossier_markdown.py — Markdown Forensic Evidence Packet Generator

Companion to dossier_gen.py (which produces PDFs via fpdf2).
This generates a Markdown-format packet for text-based workflows.

Input:  lead_id (from leads table)
Output: Markdown forensic evidence packet (stdout or file)

Strictly factual. No legal motions. No finder-fee language.
Compliant with Colorado data-access fee model.

STANDALONE: Uses only sqlite3, pathlib, datetime from standard library.
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


COMPLIANCE_HEADER = """\
> **DATA ACCESS PRODUCT — NOT LEGAL ADVICE**
> This packet contains publicly-sourced data compiled for informational
> purposes only. No attorney-client relationship is created by this document.
> Recipients should independently verify all information before taking action."""

FEE_SCHEDULE_NOTE = """\
**Statute Window (Colorado Surplus Recovery)**

| Window | Period | Status | Authority |
|--------|--------|--------|-----------|
| DATA_ACCESS_ONLY | 0-6 months from sale | Compensation agreements void | C.R.S. § 38-38-111(2.5)(c) |
| ESCROW_ENDED | 6 months - 5 years from sale | Holding period expired | C.R.S. § 38-38-111 |
| EXPIRED | 5+ years from sale | Funds may have escheated to state | C.R.S. § 38-13-101 |

*C.R.S. § 38-38-111 makes compensation agreements unenforceable during the
six calendar month holding period. No fee percentages are stated or implied.*"""


def get_lead(db_path: str, lead_id: str) -> dict:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM leads WHERE id = ?", [lead_id]).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM leads WHERE id LIKE ? LIMIT 1",
            [f"{lead_id}%"]
        ).fetchone()
    conn.close()
    if not row:
        return {}
    return dict(row)


def compute_escrow_end(sale_date: str) -> str:
    if not sale_date:
        return "Unknown"
    try:
        dt = datetime.strptime(sale_date[:10], "%Y-%m-%d")
        escrow_end = dt + timedelta(days=182)
        return escrow_end.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "Unknown"


def compute_claim_deadline(sale_date: str) -> str:
    if not sale_date:
        return "Unknown"
    try:
        dt = datetime.strptime(sale_date[:10], "%Y-%m-%d")
        deadline = dt + timedelta(days=1826)
        return deadline.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "Unknown"


def compute_days_remaining(claim_deadline: str) -> str:
    if not claim_deadline or claim_deadline == "Unknown":
        return "Unknown"
    try:
        deadline = datetime.strptime(claim_deadline[:10], "%Y-%m-%d")
        delta = (deadline - datetime.now()).days
        if delta < 0:
            return f"EXPIRED ({abs(delta)} days ago)"
        return f"{delta} days"
    except (ValueError, TypeError):
        return "Unknown"


def compute_fee_window(sale_date: str) -> tuple:
    if not sale_date:
        return "Unknown", "N/A", "N/A"
    try:
        dt = datetime.strptime(sale_date[:10], "%Y-%m-%d")
        days_since = (datetime.now() - dt).days
        if days_since <= 180:
            return "DATA_ACCESS_ONLY", "Compensation agreements void", "C.R.S. § 38-38-111(2.5)(c)"
        elif days_since <= 1826:
            return "ESCROW_ENDED", "Consult statute", "C.R.S. § 38-38-111"
        else:
            return "EXPIRED", "N/A", "C.R.S. § 38-13-101"
    except (ValueError, TypeError):
        return "UNKNOWN", "N/A", "N/A"


def fmt_money(value) -> str:
    if value is None:
        return "Not Available"
    try:
        v = float(value)
        if v == 0:
            return "$0.00"
        return f"${v:,.2f}"
    except (ValueError, TypeError):
        return "Not Available"


def generate_dossier(lead: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lead_id = lead.get("id", "UNKNOWN")

    owner = lead.get("owner_name") or "Not Available"
    case_number = lead.get("case_number") or "Not Available"
    county = lead.get("county") or "Unknown"
    state = lead.get("state") or "CO"
    address = lead.get("property_address") or "Not Available"
    sale_date = lead.get("sale_date") or ""
    data_grade = lead.get("data_grade") or "UNKNOWN"
    confidence = lead.get("confidence_score")
    source = lead.get("source_name") or "Unknown"
    status = lead.get("statute_window_status") or "Unknown"

    surplus = lead.get("surplus_amount") or lead.get("estimated_surplus") or 0
    winning_bid = lead.get("winning_bid")
    total_debt = lead.get("total_debt")
    overbid = lead.get("overbid_amount")

    escrow_end = compute_escrow_end(sale_date)
    claim_deadline = lead.get("claim_deadline") or compute_claim_deadline(sale_date)
    days_remaining = compute_days_remaining(claim_deadline)
    fee_window, fee_cap, fee_authority = compute_fee_window(sale_date)

    conf_pct = "N/A"
    if confidence is not None:
        try:
            conf_pct = f"{float(confidence) * 100:.0f}%"
        except (ValueError, TypeError):
            pass

    verified = "VERIFIED" if data_grade in ("GOLD", "SILVER") and float(surplus or 0) > 0 else "UNVERIFIED"

    doc = f"""\
# FORENSIC EVIDENCE PACKET

**VeriFuse Intelligence Platform**
**Generated:** {now}
**Packet ID:** {lead_id[:12]}
**Classification:** {verified} — {data_grade} Grade

---

{COMPLIANCE_HEADER}

---

## SECTION 1: ASSET IDENTIFICATION

| Field | Value |
|-------|-------|
| **Lead ID** | `{lead_id}` |
| **Case Number** | {case_number} |
| **County** | {county}, {state} |
| **Owner of Record** | {owner} |
| **Property Address** | {address} |
| **Data Grade** | {data_grade} |
| **Confidence Score** | {conf_pct} |
| **Source** | {source} |

---

## SECTION 2: FINANCIAL SUMMARY

| Field | Value |
|-------|-------|
| **Estimated Surplus** | {fmt_money(surplus)} |
| **Winning Bid** | {fmt_money(winning_bid)} |
| **Total Indebtedness** | {fmt_money(total_debt)} |
| **Overbid Amount** | {fmt_money(overbid)} |
"""

    if winning_bid and total_debt:
        try:
            bid_f = float(winning_bid)
            debt_f = float(total_debt)
            if bid_f > 0 and debt_f > 0:
                computed_surplus = bid_f - debt_f
                doc += f"""
**The Arithmetic:**
```
  Winning Bid:        {fmt_money(bid_f)}
- Total Indebtedness: {fmt_money(debt_f)}
----------------------------------------------
= Computed Surplus:   {fmt_money(computed_surplus)}
```

"""
                if abs(computed_surplus - float(surplus or 0)) > 50:
                    doc += f"> **Note:** Computed surplus ({fmt_money(computed_surplus)}) differs from reported surplus ({fmt_money(surplus)}). Independent verification recommended.\n\n"
        except (ValueError, TypeError):
            pass

    doc += f"""\
---

## SECTION 3: TIMELINE & STATUTE

| Field | Value |
|-------|-------|
| **Sale Date** | {sale_date or 'Not Available'} |
| **Escrow End Date** | {escrow_end} (Sale + 6 months) |
| **Claim Deadline** | {claim_deadline} (Sale + 5 years) |
| **Days Remaining** | {days_remaining} |
| **Current Window** | {fee_window} |
| **Statute Status** | {status} |

---

## SECTION 4: FEE STRUCTURE

{FEE_SCHEDULE_NOTE}

**This lead's current position:**

| Parameter | Value |
|-----------|-------|
| **Fee Window** | {fee_window} |
| **Applicable Cap** | {fee_cap} |
| **Authority** | {fee_authority} |

---

## SECTION 5: DATA PROVENANCE

| Field | Value |
|-------|-------|
| **Source System** | {source} |
| **Data Grade** | {data_grade} |
| **Confidence** | {conf_pct} |
| **Last Updated** | {lead.get('updated_at') or 'Unknown'} |
| **Verification** | {verified} |

---

## SECTION 6: COMPLIANCE NOTICE

- **Unregulated period (0-6 months):** Fee is a data-access fee for
  research and compilation services. No recovery agreement is created.
  No contingency arrangement exists.

- **Post-transfer period (6 months - 5 years):** For counsel review only.
  Recovery fee cap of 10% applies per C.R.S. 38-38-111. Any recovery
  agreement must be executed by licensed Colorado counsel.

- **No "finder fee" language** is used or implied in this document.
  This packet is an informational data product.

- All data is sourced from **public records** (county clerk, public trustee,
  state treasury). No private data, skip-tracing, or non-public sources
  were used in compilation.

---

*END OF PACKET — {lead_id[:12]} — {now}*
"""
    return doc


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Markdown Forensic Evidence Packet for a lead"
    )
    parser.add_argument("lead_id", help="Lead ID (full or prefix)")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent.parent / "data" / "verifuse_v2.db"),
        help="Path to verifuse_v2.db"
    )
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        import os
        db_path = os.environ.get("VERIFUSE_DB_PATH", db_path)
    if not Path(db_path).exists():
        print(f"FATAL: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    lead = get_lead(db_path, args.lead_id)
    if not lead:
        print(f"FATAL: No lead found with ID '{args.lead_id}'", file=sys.stderr)
        sys.exit(1)

    dossier = generate_dossier(lead)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(dossier, encoding="utf-8")
        print(f"Dossier saved to: {output_path}")
    else:
        print(dossier)


if __name__ == "__main__":
    main()
