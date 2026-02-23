> Updated: February 23, 2026

# VeriFuse — System Architecture

## End-to-End Pipeline

```
GovSoft county site (ASP.NET WebForms)
        │
        ▼ Playwright (Chromium headless)
        │   __doPostBack form interactions
        │   Adaptive date-window bisection (max depth 6)
        │   Pagination scrape → case_number list
        │
        ▼ govsoft_engine.py — per-case capture
        │   Tab snapshots: SALE_INFO, LIENOR_TAB, DOCS_TAB (gzip → html_snapshots)
        │   Document download → evidence_documents
        │   BRONZE upsert → leads (sale_date parsed from SALE_INFO DT/DD)
        │
        ▼ Gate 4: govsoft_extract.py — dual-validation
        │   extract_sale_fields(): BeautifulSoup DT/DD parse
        │   validate_overbid(): Decimal math + voucher cross-check (fail-closed)
        │   _write_results(): BEGIN IMMEDIATE — leads + asset_registry +
        │                      surplus_math_audit (all 4 tables or none)
        │   Provenance guard: GOLD requires snapshot_id OR doc_id
        │
        ▼ SQLite WAL vault (verifuse_v2.db)
        │   WAL mode + busy_timeout=30 s + synchronous=NORMAL
        │   ThreadPoolExecutor (DB_EXECUTOR) in api.py — no blocking event loop
        │
        ▼ equity_resolution_engine.py
        │   seed_lien_records(): LIENOR_TAB parse → lien_records
        │   _detect_explicit_transfer(): CERTQH doc OR TRANSFER_RE html match
        │   resolve(): 5-tier classification with provenance citations
        │   Writes: equity_resolution (INSERT OR REPLACE — idempotent)
        │
        ▼ FastAPI (api.py)
        │   ThreadPoolExecutor: all sqlite3 in _run() closures
        │   RBAC: admin / attorney / public
        │   BFCache: Cache-Control: no-store on all authenticated routes
        │   Stripe webhooks + subscription tier enforcement
        │
        ▼ React 18 + TypeScript (Vite)
            JWT from localStorage (vf_token)
            AbortController on all fetch useEffects
            BFCache: pageshow revalidation on auth.tsx
```

---

## Database — Table Map

| Table | Purpose |
|---|---|
| `leads` | Primary case record. `data_grade` (GOLD/BRONZE), `sale_date`, `overbid_amount` |
| `asset_registry` | One row per asset_id. `processing_status`, `amount_cents` |
| `html_snapshots` | Gzipped raw HTML per tab per case. `snapshot_type` in (SALE_INFO, LIENOR_TAB, DOCS_TAB) |
| `evidence_documents` | Downloaded court docs. `doc_family` (OB, CDOT, etc.) |
| `field_evidence` | OCR-extracted field values from evidence_documents (Gate 5) |
| `extraction_events` | One event per extraction run per asset |
| `surplus_math_audit` | Every GOLD/BRONZE decision — bid, debt, math flags, provenance refs |
| `lien_records` | Junior liens per asset. `amount_cents`, `is_open`, `source` |
| `equity_resolution` | 5-tier classification result per asset |
| `govsoft_county_configs` | Universal adapter config per county. `base_url`, `search_path`, `page_limit` |
| `county_ingestion_runs` | Coverage audit results — browser_count vs db_count per window |
| `county_profiles` | Legacy county metadata (govsoft_county_configs is authoritative for scraping) |
| `users` | Auth. `role` in (admin, attorney, public) |
| `subscriptions` | Stripe subscription state |
| `unlock_ledger_entries` | Credit spend audit trail |
| `user_daily_lead_views` | Rate-limiting — one row per user/day/lead |
| `migrations_log` | Auto-migration tracking (006+ SQL files) |

---

## GOLD Promotion Rule

A lead is promoted to `data_grade = 'GOLD'` only when ALL of the following hold:

1. **HTML math:** `|overbid_at_sale − (successful_bid − total_indebtedness)| ≤ $0.01`
2. **Voucher cross-check:** If an OB (voucher) doc exists in `evidence_documents` and Gate 5 OCR has extracted the voucher amount, `|html_overbid − voucher_overbid| ≤ $0.01`. If the OB doc exists but OCR has not run yet, promotion is **blocked** (fail-closed) until Gate 5.
3. **Provenance:** At least one of `snapshot_id` (SALE_INFO html_snapshot) or `doc_id` (evidence_documents) must be populated. GOLD with neither is downgraded to BRONZE.

All three conditions are evaluated and the audit row is written to `surplus_math_audit` inside a single `BEGIN IMMEDIATE` transaction with the `leads` UPDATE. If either write fails, both roll back.

---

## Equity Classification — 5-Tier Logic

```
resolve(asset_id, conn):
  1. seed_lien_records()          — populate lien_records from LIENOR_TAB
  2. _get_gross_surplus_cents()   — asset_registry.amount_cents or leads.overbid_amount fallback
     → None if malformed asset_id → early return NEEDS_REVIEW_TREASURER_WINDOW
  3. _detect_explicit_transfer()  — CERTQH doc OR TRANSFER_RE html match
     → TREASURER_TRANSFERRED (never from time alone)
  4. gross == 0                   → RESOLUTION_PENDING
  5. liens >= gross > 0           → LIEN_ABSORBED
     + provenance check: LIENOR_TAB snapshot_id OR evidence_documents doc_id required
     → no provenance: NEEDS_REVIEW
  6. net > 0                      → OWNER_ELIGIBLE
  7. months >= 30 post-sale       → NEEDS_REVIEW_TREASURER_WINDOW
  8. default                      → RESOLUTION_PENDING
```

`NEEDS_REVIEW_TREASURER_WINDOW` is a distinct 5th classification — never auto-promoted to `TREASURER_TRANSFERRED` without explicit evidence.

---

## Coverage Audit

`verifuse_v2/scripts/coverage_audit.py` — compares browser-visible case count to DB case count for a county and date window.

```bash
python3 -m verifuse_v2.scripts.coverage_audit --county jefferson --days 60
# [JEFFERSON] Browser: 47 | DB: 47 | Delta: 0
# PASS: Perfect match. Pipeline integrity verified.
```

Exit codes: `0` = PASS, `1` = FAIL (delta > 0), `2` = UNKNOWN (count undetectable), `3` = ERROR (form state mismatch).

Every run writes a row to `county_ingestion_runs`.

---

## Security Model

- **BFCache:** All authenticated FastAPI routes emit `Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate`. Health + public preview routes are exempt.
- **RBAC:** Evidence endpoints require `role = 'attorney'` or `role = 'admin'`.
- **Stripe downgrade guard:** Tier rank enforced on subscription change — cannot downgrade to a tier that would orphan unlocked leads.
- **SQLite WAL:** Concurrent reads never block writes; `busy_timeout = 30 s` prevents "database is locked" under load.

---

## Adaptive Date-Window Bisection

The GovSoft adapter uses recursive bisection to handle counties with more cases than `page_limit` (default 90) in a single date window:

```
_search_window_recursive(date_from, date_to, depth=0):
  if total >= page_limit and window > 1 day:
    mid = date_from + (date_to - date_from) // 2   ← safe integer midpoint
    recurse(date_from, mid, depth+1)
    recurse(mid+1day, date_to, depth+1)
  elif window == 1 day and total >= page_limit:
    mark NEEDS_MANUAL_REVIEW_OVERFLOW
  else:
    paginate all cases in window
MAX_DEPTH = 6
```
