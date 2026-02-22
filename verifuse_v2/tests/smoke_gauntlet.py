#!/usr/bin/env python3
"""
VeriFuse vNEXT — The Gauntlet (Smoke Test Suite)

DB tests (30 + 9 vNEXT Phase 0 + 9 vNEXT Phase 10 = 48 target):
  1–12. Required tables (wallet, transactions, stripe_events, etc.)
  13.   Wallet CHECK constraints
  14.   Wallet backfill complete
  15.   No negative wallet balances
  16.   No 'recon' tier
  17.   lead_unlocks dedupe index UNIQUE
  18.   leads county+case UNIQUE index
  19.   Users column: subscription_status
  20.   Users column: current_period_end
  21.   Users column: founders_pricing
  22.   unlock_ledger_entries table + CHECK constraints   [vNEXT Ph0]
  23.   asset_registry table                              [vNEXT Ph0]
  24.   asset_unlocks table + UNIQUE(user_id,asset_id)   [vNEXT Ph0]
  25.   unlock_spend_journal table                        [vNEXT Ph0]
  26.   tax_assets table + row_hash UNIQUE               [vNEXT Ph0]
  27.   users.role column                                 [vNEXT Ph0]
  28.   Ledger backfill complete                          [vNEXT Ph0]
  29.   No expired entries with remaining credits         [vNEXT Ph0]
  30.   asset_registry backfill complete                  [vNEXT Ph0]
  31.   county_profiles (selectors_json + last_verified_ts) [Gate 2]
  32.   html_snapshots UNIQUE(asset_id,snapshot_type,html_sha256) [Gate 2]
  33.   evidence_documents UNIQUE(asset_id,doc_family,file_sha256) [Gate 2]
  34.   evidence_documents has content_type column        [Gate 2]
  35.   extraction_events CHECK includes CAPTCHA_BLOCKED  [Gate 2]
  36.   field_evidence table exists                       [Gate 2]
  37.   ingestion_runs CHECK (RUNNING/SUCCESS/FAILED/PARTIAL/FAILED_STALE) [Gate 2]
  38.   asset_registry has processing_status column       [Gate 2]
  39.   asset_registry has treasurer_transfer_flag column [Gate 2]

HTTP tests (9, target 48 DB + 9 HTTP = 57 target):
  31.  Health endpoint
  32.  Public config
  33.  Preview leads (no PII)
  34.  Inventory health
  35.  Sample dossier (or skip)
  36.  Dossier Cache-Control
  37.  Dossier bad key → 404
  38.  Vary header
  39.  Case number masked (unauthenticated)

Usage:
    python3 verifuse_v2/tests/smoke_gauntlet.py [--dry-run]
    --dry-run: DB-only checks, no HTTP calls (for CI)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.request

API = os.environ.get("VERIFUSE_API", "http://localhost:8000")
DB = os.environ.get("VERIFUSE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "verifuse_v2.db"))

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def http_get(path: str) -> tuple[int, dict]:
    try:
        req = urllib.request.Request(f"{API}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def http_get_raw(path: str) -> tuple[int, bytes, dict]:
    """Returns (status, body_bytes, headers_dict)."""
    try:
        req = urllib.request.Request(f"{API}{path}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp.read(), headers
    except urllib.error.HTTPError as e:
        return e.code, b"", {}
    except Exception:
        return 0, b"", {}


def run_http_tests():
    print("\n=== HTTP Tests ===\n")

    # 1. Health
    code, body = http_get("/health")
    check("Health endpoint", code == 200 and body.get("status") == "ok")

    # 2. Public config
    code, body = http_get("/api/public-config")
    check("Public config", code == 200 and "stripe_mode" in body and "build_id" in body,
          f"mode={body.get('stripe_mode')}")

    # 3. Preview leads — no PII
    code, body = http_get("/api/preview/leads?limit=3")
    leads = body.get("leads", [])
    has_pii = any(
        l.get("owner_name") or l.get("property_address") or l.get("id")
        for l in leads
    )
    check("Preview leads (no PII)", code == 200 and len(leads) > 0 and not has_pii,
          f"{len(leads)} leads, PII={'LEAKED' if has_pii else 'clean'}")

    # 4. Inventory health
    code, body = http_get("/api/inventory_health")
    check("Inventory health", code == 200 and "active_leads" in body,
          f"active={body.get('active_leads')}")

    # 5. Sample dossier (if preview key available)
    preview_key = leads[0].get("preview_key") if leads else None
    if preview_key:
        code, pdf_bytes, headers = http_get_raw(f"/api/dossier/sample/{preview_key}")
        is_pdf = pdf_bytes[:4] == b"%PDF"
        check("Sample dossier PDF", code == 200 and is_pdf,
              f"size={len(pdf_bytes)}, pdf_header={'yes' if is_pdf else 'no'}")
        _cc = headers.get("cache-control", "")
        check("Sample dossier Cache-Control",
              all(d in _cc for d in ("no-store", "no-cache", "must-revalidate", "proxy-revalidate")),
              f"cache-control: {_cc}")
        # Bad key → 404
        code2, _, _ = http_get_raw("/api/dossier/sample/bad_key_12345678")
        check("Sample dossier bad key → 404", code2 == 404)
    else:
        check("Sample dossier (skipped — no preview key)", True, "no preview leads")

    # 6. Vary header
    code, _, headers = http_get_raw("/api/preview/leads?limit=1")
    vary = headers.get("vary", "")
    check("Vary header", "authorization" in vary.lower(),
          f"Vary: {vary}")

    # 7. Unauthenticated lead masking
    code, body = http_get("/api/leads?limit=1")
    if code == 200 and body.get("leads"):
        lead = body["leads"][0]
        check("Case number masked (unauthenticated)", lead.get("case_number") is None)
    else:
        check("Lead masking (skipped — no leads or auth required)", True)


def run_db_tests():
    print("\n=== Database Tests ===\n")

    if not os.path.exists(DB):
        check("DB file exists", False, DB)
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Required tables
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]

    required = [
        "wallet", "transactions", "stripe_events", "founders_redemptions",
        "rate_limits", "audit_log", "user_daily_lead_views", "email_verifications",
        "subscriptions", "lead_unlocks", "leads", "users",
    ]
    for t in required:
        check(f"Table: {t}", t in tables)

    # Wallet schema — CHECK constraints
    wallet_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='wallet'"
    ).fetchone()
    if wallet_sql:
        sql = wallet_sql[0] or ""
        check("Wallet CHECK constraints",
              "CHECK" in sql and "subscription_credits" in sql,
              "strict schema" if "CHECK" in sql else "no CHECK")

    # Wallet backfill — all users have wallets
    users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    wallet_count = conn.execute("SELECT COUNT(*) FROM wallet").fetchone()[0]
    check("Wallet backfill complete", wallet_count >= users_count,
          f"users={users_count}, wallets={wallet_count}")

    # No negative wallet balances
    neg = conn.execute(
        "SELECT COUNT(*) FROM wallet WHERE subscription_credits < 0 OR purchased_credits < 0"
    ).fetchone()[0]
    check("No negative wallet balances", neg == 0, f"negative={neg}")

    # Tier rename — no 'recon' tier
    recon_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE tier = 'recon'"
    ).fetchone()[0]
    check("No 'recon' tier (renamed to scout)", recon_count == 0, f"recon_users={recon_count}")

    # UNIQUE index on lead_unlocks
    idx = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='idx_lead_unlocks_dedupe'"
    ).fetchone()
    check("lead_unlocks dedupe index", idx is not None and "UNIQUE" in (idx[0] or ""))

    # UNIQUE index on leads(county, case_number)
    idx2 = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='idx_leads_county_case'"
    ).fetchone()
    check("leads county+case UNIQUE index",
          idx2 is not None and "UNIQUE" in (idx2[0] or ""))

    # Users have new columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    for col in ["subscription_status", "current_period_end", "founders_pricing"]:
        check(f"Users column: {col}", col in cols)

    # ── vNEXT Phase 0 checks ──────────────────────────────────────

    # 1. unlock_ledger_entries: table exists + has CHECK constraints
    ledger_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='unlock_ledger_entries'"
    ).fetchone()
    ledger_sql = (ledger_row[0] or "") if ledger_row else ""
    check("Table: unlock_ledger_entries + CHECK constraints",
          ledger_row is not None and "CHECK" in ledger_sql and "qty_remaining" in ledger_sql,
          "strict schema" if "CHECK" in ledger_sql else "table missing or no CHECK")

    # 2. asset_registry: table exists
    check("Table: asset_registry", "asset_registry" in tables)

    # 3. asset_unlocks: table exists + UNIQUE(user_id, asset_id) in DDL
    au_tbl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='asset_unlocks'"
    ).fetchone()
    au_sql = (au_tbl[0] or "") if au_tbl else ""
    check("Table: asset_unlocks + UNIQUE(user_id,asset_id) in DDL",
          "asset_unlocks" in tables and "UNIQUE" in au_sql and "user_id" in au_sql and "asset_id" in au_sql)

    # 4. unlock_spend_journal: table exists
    check("Table: unlock_spend_journal", "unlock_spend_journal" in tables)

    # 5. tax_assets: table exists + row_hash UNIQUE constraint
    ta_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='tax_assets'"
    ).fetchone()
    ta_sql = (ta_row[0] or "") if ta_row else ""
    check("Table: tax_assets + row_hash UNIQUE",
          ta_row is not None and "UNIQUE" in ta_sql and "row_hash" in ta_sql)

    # 6. users.role column exists
    check("Users column: role", "role" in cols)

    # 7. Ledger backfill: entries >= users with credits > 0
    if ledger_row is not None:
        ledger_count = conn.execute(
            "SELECT COUNT(*) FROM unlock_ledger_entries"
        ).fetchone()[0]
        users_with_credits = conn.execute(
            "SELECT COUNT(*) FROM users WHERE COALESCE(credits_remaining, 0) > 0"
        ).fetchone()[0]
        check("Ledger backfill complete",
              ledger_count >= users_with_credits,
              f"entries={ledger_count}, users_with_credits={users_with_credits}")
    else:
        check("Ledger backfill complete", False, "unlock_ledger_entries table missing")

    # 8. No expired ledger entries with remaining credits
    if ledger_row is not None:
        import time as _time
        expired_with_bal = conn.execute(
            "SELECT COUNT(*) FROM unlock_ledger_entries "
            "WHERE expires_ts IS NOT NULL AND expires_ts <= ? AND qty_remaining > 0",
            [int(_time.time())],
        ).fetchone()[0]
        check("No expired entries with remaining credits",
              expired_with_bal == 0, f"expired_with_balance={expired_with_bal}")
    else:
        check("No expired entries with remaining credits", False, "table missing")

    # 9. asset_registry backfill: count >= leads count
    if "asset_registry" in tables:
        registry_count = conn.execute("SELECT COUNT(*) FROM asset_registry").fetchone()[0]
        leads_total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        check("asset_registry backfill complete",
              registry_count >= leads_total,
              f"registry={registry_count}, leads={leads_total}")
    else:
        check("asset_registry backfill complete", False, "asset_registry table missing")

    # ── vNEXT Phase 10 checks (Gate 2) ───────────────────────────

    # 10. county_profiles: table exists with selectors_json + last_verified_ts
    cp_cols = {r[1] for r in conn.execute("PRAGMA table_info(county_profiles)").fetchall()}
    check("Table: county_profiles (selectors_json + last_verified_ts)",
          "county_profiles" in tables
          and "selectors_json" in cp_cols
          and "last_verified_ts" in cp_cols,
          f"cols={sorted(cp_cols)}" if cp_cols else "table missing")

    # 11. html_snapshots: UNIQUE(asset_id, snapshot_type, html_sha256) in DDL
    hs_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='html_snapshots'"
    ).fetchone()
    hs_sql = (hs_row[0] or "") if hs_row else ""
    check("html_snapshots UNIQUE(asset_id, snapshot_type, html_sha256)",
          hs_row is not None
          and "UNIQUE" in hs_sql
          and "html_sha256" in hs_sql
          and "snapshot_type" in hs_sql)

    # 12. evidence_documents: UNIQUE(asset_id, doc_family, file_sha256) + content_type col
    ed_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='evidence_documents'"
    ).fetchone()
    ed_sql = (ed_row[0] or "") if ed_row else ""
    ed_cols = {r[1] for r in conn.execute("PRAGMA table_info(evidence_documents)").fetchall()}
    check("evidence_documents UNIQUE(asset_id, doc_family, file_sha256)",
          ed_row is not None
          and "UNIQUE" in ed_sql
          and "file_sha256" in ed_sql
          and "doc_family" in ed_sql)

    # 13. evidence_documents has content_type column
    check("evidence_documents has content_type column",
          "content_type" in ed_cols,
          f"cols={sorted(ed_cols)}" if ed_cols else "table missing")

    # 14. extraction_events: status CHECK includes CAPTCHA_BLOCKED
    ee_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='extraction_events'"
    ).fetchone()
    ee_sql = (ee_row[0] or "") if ee_row else ""
    check("extraction_events status CHECK includes CAPTCHA_BLOCKED",
          ee_row is not None and "CAPTCHA_BLOCKED" in ee_sql)

    # 15. field_evidence: table exists
    check("Table: field_evidence", "field_evidence" in tables)

    # 16. ingestion_runs: status CHECK includes RUNNING/SUCCESS/FAILED/PARTIAL/FAILED_STALE
    ir_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='ingestion_runs'"
    ).fetchone()
    ir_sql = (ir_row[0] or "") if ir_row else ""
    check("ingestion_runs status CHECK (RUNNING/SUCCESS/FAILED/PARTIAL/FAILED_STALE)",
          ir_row is not None
          and all(v in ir_sql for v in ("RUNNING", "SUCCESS", "FAILED", "PARTIAL", "FAILED_STALE")))

    # 17. asset_registry has processing_status column (PRAGMA verify)
    ar_cols = {r[1] for r in conn.execute("PRAGMA table_info(asset_registry)").fetchall()}
    check("asset_registry has processing_status column",
          "processing_status" in ar_cols,
          f"found={sorted(ar_cols)}" if not "processing_status" in ar_cols else "")

    # 18. asset_registry has treasurer_transfer_flag column (PRAGMA verify)
    check("asset_registry has treasurer_transfer_flag column",
          "treasurer_transfer_flag" in ar_cols,
          f"found={sorted(ar_cols)}" if not "treasurer_transfer_flag" in ar_cols else "")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="VeriFuse Gauntlet Smoke Tests")
    parser.add_argument("--dry-run", action="store_true", help="DB-only checks, no HTTP")
    args = parser.parse_args()

    print("=" * 60)
    print("  VERIFUSE vNEXT — THE GAUNTLET (target: ≥48)")
    print("=" * 60)

    run_db_tests()
    if not args.dry_run:
        run_http_tests()

    print(f"\n{'=' * 60}")
    total = PASS + FAIL
    print(f"  Results: {PASS}/{total} PASS, {FAIL}/{total} FAIL")
    print(f"{'=' * 60}\n")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
