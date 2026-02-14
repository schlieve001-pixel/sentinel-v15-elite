#!/usr/bin/env python3
"""
verifuse_v2/scrapers/vertex_engine.py
ENGINE #4 — Vertex AI Forensic Reader (Production)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from google import genai
from google.genai import types

MONEY_RE = re.compile(r"[-]?\$?\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.(\d{1,2}))?")
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")

def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def parse_money(raw: Optional[str]) -> Optional[float]:
    if raw is None: return None
    s = str(raw).strip()
    m = MONEY_RE.search(s)
    if not m: return None
    whole = m.group(1).replace(",", "")
    frac = m.group(2) or "0"
    try: return float(f"{whole}.{frac}")
    except ValueError: return None

def parse_iso_date(raw: Optional[str]) -> Optional[str]:
    if raw is None: return None
    m = ISO_DATE_RE.search(str(raw).strip())
    return m.group(0) if m else None

FORCE_SCHEMA = {
    "type": "object",
    "required": ["winning_bid_raw", "total_debt_raw", "sale_date_raw", "evidence", "is_illegible"],
    "properties": {
        "winning_bid_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "total_debt_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "sale_date_raw": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "is_illegible": {"type": "boolean"},
        "evidence": {
            "type": "object",
            "properties": {
                "winning_bid": {"type": "object", "properties": {"snippet": {"type": "string"}}},
                "total_debt": {"type": "object", "properties": {"snippet": {"type": "string"}}},
                "sale_date": {"type": "object", "properties": {"snippet": {"type": "string"}}}
            }
        }
    }
}

@dataclass
class ExtractionResult:
    ok: bool
    winning_bid: Optional[float]
    total_debt: Optional[float]
    sale_date: Optional[str]
    surplus: Optional[float]
    error: Optional[str]

def extract_from_pdf_bytes(client: genai.Client, model: str, pdf_bytes: bytes) -> ExtractionResult:
    try:
        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        resp = client.models.generate_content(
            model=model,
            contents=["Extract Winning Bid, Total Debt, Sale Date.", pdf_part],
            config={"response_mime_type": "application/json", "response_json_schema": FORCE_SCHEMA}
        )
        parsed = resp.parsed
        if not parsed: return ExtractionResult(False, None, None, None, None, "empty_response")
        
        if parsed.get("is_illegible"): return ExtractionResult(False, None, None, None, None, "illegible")
        
        bid = parse_money(parsed.get("winning_bid_raw"))
        debt = parse_money(parsed.get("total_debt_raw"))
        sale_date = parse_iso_date(parsed.get("sale_date_raw"))
        surplus = max(0.0, bid - debt) if (bid is not None and debt is not None) else None
        
        ok = (bid is not None and debt is not None and sale_date is not None)
        return ExtractionResult(ok, bid, debt, sale_date, surplus, None if ok else "missing_fields")
    except Exception as e:
        return ExtractionResult(False, None, None, None, None, str(e))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="verifuse_v2/data/verifuse_v2.db")
    ap.add_argument("--status", default="STAGED")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--project", required=True)
    ap.add_argument("--model", default="gemini-2.0-flash")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    
    # Verify DB has correct columns
    cur = conn.execute("PRAGMA table_info(leads)")
    cols = [r[1] for r in cur.fetchall()]
    if "surplus_amount" not in cols:
        print("[!] DB Error: 'leads' table missing columns. Is this the V2 database?")
        sys.exit(1)

    leads = conn.execute("SELECT id, pdf_path, case_number FROM leads WHERE status=? AND pdf_path IS NOT NULL LIMIT ?", (args.status, args.limit)).fetchall()
    print(f"[*] Engine #4 Online. Processing {len(leads)} leads using {args.model}...")

    client = genai.Client(vertexai=True, project=args.project, location="us-central1")
    
    for r in leads:
        # Resolve path safely
        p = Path(r["pdf_path"])
        if not p.is_absolute(): p = Path("verifuse_v2") / p
        
        if not p.exists():
            print(f"  [!] Missing file: {p}")
            continue
            
        print(f"  --> Case {r['case_number']}...", end=" ", flush=True)
        res = extract_from_pdf_bytes(client, args.model, p.read_bytes())
        
        if res.ok:
            print(f"SUCCESS: ${res.surplus:,.2f} | {res.sale_date}")
            conn.execute("UPDATE leads SET winning_bid=?, total_debt=?, surplus_amount=?, sale_date=?, status='VERIFIED', last_updated=? WHERE id=?",
                         (res.winning_bid, res.total_debt, res.surplus, res.sale_date, utc_now_iso(), r["id"]))
            conn.commit()
        else:
            print(f"FAILED: {res.error}")
            conn.execute("UPDATE leads SET status='MANUAL_REVIEW', last_updated=? WHERE id=?", (utc_now_iso(), r["id"]))
            conn.commit()
        
        time.sleep(args.sleep)

if __name__ == "__main__":
    main()
