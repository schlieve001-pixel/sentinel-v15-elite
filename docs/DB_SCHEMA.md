# VeriFuse Database Schema

All tables use SQLite. Migrations are in `verifuse_v2/migrations/` and run via `bin/vf migrate`.

## Migration Files

| File | Phase | Contents |
|---|---|---|
| `001_baseline.sql` | 1 | users, leads, lead_unlocks, wallet, transactions, stripe_events, founders_redemptions, rate_limits, audit_log, user_daily_lead_views, email_verifications, subscriptions |
| `002_fifo_ledger.sql` | 2 | unlock_ledger_entries, subscriptions update |
| `003_vnext_foundation.sql` | 3 | asset_registry, asset_unlocks, unlock_spend_journal, tax_assets |
| `004_ingestion_evidence.sql` | 4 | county_profiles, ingestion_runs, html_snapshots, evidence_documents, extraction_events, field_evidence |
| `005_equity_resolution.sql` | 5 | lien_records, equity_resolution |

## Key Tables

### `users`
Primary key: `user_id` (UUID).

| Column | Type | Notes |
|---|---|---|
| `user_id` | TEXT PK | JWT `sub` claim |
| `email` | TEXT UNIQUE | Login identifier |
| `tier` | TEXT | `scout` / `operator` / `sovereign` |
| `role` | TEXT | `public` / `approved_attorney` / `admin` |
| `bar_number` | TEXT | Attorney bar number |
| `is_admin` | INTEGER | 0/1 convenience flag |
| `subscription_status` | TEXT | Stripe subscription state |

### `leads`
Primary key: `id` (UUID). UNIQUE on `(county, case_number)`.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | Used as `SafeAsset.asset_id` in API |
| `county` | TEXT | e.g. `jefferson` |
| `case_number` | TEXT | GovSoft case number |
| `overbid_amount` | REAL | Dollars |
| `data_grade` | TEXT | GOLD / SILVER / BRONZE |
| `processing_status` | TEXT | PENDING / EXTRACTED / VALIDATED / NEEDS_REVIEW / CAPTCHA_BLOCKED |

### `asset_registry`
Canonical asset store. `asset_id` = `FORECLOSURE:CO:{COUNTY}:{case}`.

| Column | Type | Notes |
|---|---|---|
| `asset_id` | TEXT PK | Canonical key |
| `county` | TEXT | |
| `source_id` | TEXT | GovSoft case number |
| `amount_cents` | INTEGER | Gross overbid in cents |
| `data_grade` | TEXT | |
| `processing_status` | TEXT | CHECK enum |
| `treasurer_transfer_flag` | INTEGER | 0/1 (explicit transfer confirmed) |
| `event_ts` | INTEGER | Sale date epoch (NULL if unknown) |

### `html_snapshots`
UNIQUE on `(asset_id, snapshot_type, html_sha256)`.

| Column | Notes |
|---|---|
| `snapshot_type` | SEARCH_RESULTS / CASE_DETAIL / SALE_INFO / LIENOR_TAB / DOCS_TAB |
| `raw_html_gzip` | BLOB, gzip-compressed |
| `html_sha256` | Dedup key |

### `evidence_documents`
UNIQUE on `(asset_id, doc_family, file_sha256)`.

| Column | Notes |
|---|---|
| `filename` | Raw filename from GovSoft (stored as-is) |
| `doc_type` | Free text (no CHECK) |
| `doc_family` | CHECK: BID / COP / NED / PTD / OB / NOTICE / INVOICE / OTHER |
| `file_path` | Absolute vault path (sanitized filename on disk) |
| `content_type` | MIME type (application/pdf, image/tiff, etc.) |

### `equity_resolution`
UNIQUE on `asset_id`.

| Column | Notes |
|---|---|
| `classification` | CHECK: LIEN_ABSORBED / OWNER_ELIGIBLE / TREASURER_TRANSFERRED / RESOLUTION_PENDING / NEEDS_REVIEW_TREASURER_WINDOW |
| `gross_surplus_cents` | From `asset_registry.amount_cents` |
| `junior_liens_total_cents` | Sum of open `lien_records` |
| `net_owner_equity_cents` | `max(0, gross - liens)` |

### `lien_records`

| Column | Notes |
|---|---|
| `lien_type` | CHECK: IRS / HOA / MORTGAGE / JUDGMENT / OTHER |
| `amount_cents` | Lien amount in cents |
| `is_open` | 1 = open (contributes to equity deduction) |
| `source` | `govsoft_html` or `test` |

## Common Join Patterns

```sql
-- Lead with equity data (used by /api/lead/{id})
SELECT l.*, ar.asset_id AS registry_asset_id,
       er.gross_surplus_cents, er.net_owner_equity_cents, er.classification
FROM leads l
LEFT JOIN asset_registry ar ON ar.county = l.county AND ar.source_id = l.case_number
LEFT JOIN equity_resolution er ON er.asset_id = ar.asset_id
WHERE l.id = ?;

-- Evidence for an asset
SELECT * FROM evidence_documents
WHERE asset_id = 'FORECLOSURE:CO:JEFFERSON:J2500358'
ORDER BY doc_family, filename;

-- Lien summary
SELECT SUM(amount_cents) FROM lien_records
WHERE asset_id = ? AND is_open = 1;
```
