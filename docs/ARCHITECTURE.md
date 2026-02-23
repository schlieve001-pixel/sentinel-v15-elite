# VeriFuse vNEXT Architecture

## End-to-End Dataflow

```
GovSoft (ASP.NET WebForms)
        │
        │  Playwright (headless chromium)
        ▼
govsoft_engine.py           ← county_profiles (base_url, captcha_mode, selectors_json)
  ├─ HTML snapshots → html_snapshots (gzip, sha256 UNIQUE)
  ├─ Documents → evidence_documents (vault/govsoft/{county}/{case}/original/)
  ├─ CAPTCHA HITL (sentinel file, 20min timeout → CAPTCHA_BLOCKED)
  └─ Leads table UPSERT (county+case_number UNIQUE key)
        │
        ▼
govsoft_extract.py
  ├─ parse_html_fields() → SALE_INFO snapshot → overbid_amount, bid, indebtedness
  ├─ validate_overbid() → GOLD/BRONZE, VALIDATED/NEEDS_REVIEW
  └─ asset_registry UPDATE (amount_cents, processing_status, data_grade)
        │
        ▼
ocr_processor.py            ← pdfplumber (text layer primary)
  │                            → Document AI (scanned/TIFF fallback)
  └─ field_evidence (bounding boxes, confidence, ocr_source)
        │
        ▼
equity_resolution_engine.py
  ├─ seed_lien_records() ← LIENOR_TAB html_snapshot
  ├─ _detect_explicit_transfer() ← TRANSFER_RE + dt/dd non-empty check
  └─ resolve() → equity_resolution (classification, net_owner_equity_cents)
        │
        ▼
FastAPI (api.py)
  ├─ GET /api/leads          → SafeAsset list (RBAC-masked)
  ├─ GET /api/lead/{id}      → SafeAsset + equity_resolution join
  ├─ POST /api/unlock/{id}   → full owner intel (FIFO credit debit)
  ├─ GET /api/assets/{id}/evidence → EvidenceDoc list (attorney-gated)
  └─ GET /api/evidence/{id}/download → secure FileResponse (vault path check)
        │
        ▼
React SPA (Vite + TypeScript)
  ├─ LeadDetail.tsx          → equity panel, evidence list (attorney-gated)
  ├─ ClassificationBadge.tsx → 5-state equity badge
  └─ Dashboard.tsx           → leads table, filtering, unlock CTA
```

## Database Tables (all migrations)

| Table | Migration | Purpose |
|---|---|---|
| `users` | 001 | Auth, RBAC role, tier, bar_number |
| `leads` | 001 | Core foreclosure data (county+case UNIQUE) |
| `lead_unlocks` | 001 | Unlock history (user+asset UNIQUE) |
| `wallet` | 001 | Credit balance per user |
| `transactions` | 001 | Credit transactions |
| `unlock_ledger_entries` | 002 | FIFO credit ledger |
| `asset_registry` | 003 | Canonical asset store (FORECLOSURE:CO:{county}:{case}) |
| `asset_unlocks` | 003 | Asset-level unlock join |
| `unlock_spend_journal` | 003 | Spend audit trail |
| `county_profiles` | 004 | GovSoft county config (base_url, captcha_mode, selectors) |
| `ingestion_runs` | 004 | Scraper run observability |
| `html_snapshots` | 004 | Raw GovSoft HTML (gzip, UNIQUE per sha256) |
| `evidence_documents` | 004 | Vault file metadata |
| `extraction_events` | 004 | Extraction pipeline status per asset |
| `field_evidence` | 004 | OCR bounding boxes |
| `lien_records` | 005 | Junior lien data from LIENOR_TAB |
| `equity_resolution` | 005 | Equity classification per asset |

## Equity Classifications

| Classification | Meaning |
|---|---|
| `OWNER_ELIGIBLE` | Net owner equity > 0 after lien deduction |
| `LIEN_ABSORBED` | Junior liens ≥ gross surplus — owner equity = 0 |
| `TREASURER_TRANSFERRED` | Explicit transfer text evidence confirmed |
| `NEEDS_REVIEW_TREASURER_WINDOW` | > 30 months since sale, no explicit transfer |
| `RESOLUTION_PENDING` | No surplus data or < 30 months elapsed |

## Data Grades

| Grade | Meaning |
|---|---|
| `GOLD` | Overbid validated: HTML fields match computed math |
| `SILVER` | Partial validation (manual review passed) |
| `BRONZE` | Mismatch or missing indebtedness — NEEDS_REVIEW |

## Key Constraints

- `asset_id` format: `FORECLOSURE:CO:{COUNTY_UPPER}:{case_number}`
- `SafeAsset.asset_id` = `leads.id` (UUID) — used for unlock/dossier/navigation
- `SafeAsset.registry_asset_id` = canonical FORECLOSURE:CO:... key — used for evidence/equity
- Vault path: `/var/lib/verifuse/vault/govsoft/{county}/{case_number}/original/`
- GovSoft identity: platform TYPE only — no hardcoded domains; county URLs from env vars
