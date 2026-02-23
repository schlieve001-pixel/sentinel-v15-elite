# Database Schema Reference

**Engine:** SQLite 3 with WAL (Write-Ahead Logging) mode
**Location:** `verifuse_v2/data/verifuse_v2.db`
**Connection:** `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;`

---

## Table: `leads`

The canonical lead store. One row per foreclosure surplus opportunity.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | TEXT | PRIMARY KEY | Deterministic lead ID (`{county}_reg_{sha256[:12]}`) |
| `case_number` | TEXT | | County foreclosure case number (e.g., `A123456`, `2024-001234`) |
| `county` | TEXT | | Colorado county name (e.g., `Denver`, `Adams`, `El Paso`) |
| `owner_name` | TEXT | | Former property owner (PII -- only revealed on unlock) |
| `property_address` | TEXT | | Full property address (PII -- only revealed on unlock) |
| `estimated_surplus` | REAL | 0.0 | Estimated surplus amount (may differ from verified) |
| `winning_bid` | REAL | 0.0 | Auction winning bid amount |
| `total_debt` | REAL | 0.0 | Total indebtedness at time of sale |
| `surplus_amount` | REAL | 0.0 | Verified surplus: `winning_bid - total_debt` |
| `overbid_amount` | REAL | 0.0 | Explicit overbid from county records |
| `confidence_score` | REAL | 0.0 | Confidence Function C output (0.0 to 1.0) |
| `data_grade` | TEXT | `BRONZE` | Quality tier: `GOLD`, `SILVER`, `BRONZE`, `IRON`, `REJECT`, `PIPELINE_STAGING` |
| `sale_date` | TEXT | | ISO date of foreclosure sale (`YYYY-MM-DD`) |
| `claim_deadline` | TEXT | | ISO date by which surplus must be claimed |
| `source_name` | TEXT | | Parser/engine that created this record |
| `source_link` | TEXT | | URL to the source document |
| `evidence_file` | TEXT | | Local path to the source PDF |
| `pdf_filename` | TEXT | | Name of the parsed PDF file |
| `record_hash` | TEXT | | SHA256 of the source record for dedup |
| `vertex_processed` | INTEGER | 0 | Whether Vertex AI has enriched this record |
| `vertex_processed_at` | TEXT | | Timestamp of Vertex AI processing |
| `extraction_notes` | TEXT | | Parser notes, warnings, or flags |
| `status` | TEXT | `STAGED` | Pipeline status: `STAGED`, `ENRICHED`, `REVIEW_REQUIRED` |
| `attorney_packet_ready` | INTEGER | 0 | 1 if lead passes attorney-ready validation |
| `updated_at` | TEXT | | ISO timestamp of last update |

**Indexes:**
- Primary key on `id`
- Index on `case_number` (for dedup lookups)
- Index on `county` (for filtered queries)
- Index on `data_grade` (for scoreboard)

---

## Table: `users`

Subscriber accounts. Tracks authentication, billing, and access control.

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `user_id` | TEXT | PRIMARY KEY | UUID v4 |
| `email` | TEXT | UNIQUE | Login email |
| `password_hash` | TEXT | | bcrypt hash |
| `full_name` | TEXT | `''` | Display name |
| `firm_name` | TEXT | `''` | Law firm name |
| `bar_number` | TEXT | `''` | Colorado bar number |
| `firm_address` | TEXT | `''` | Firm address (required for letter generation) |
| `tier` | TEXT | `recon` | Subscription tier: `recon`, `operator`, `sovereign` |
| `credits_remaining` | INTEGER | 5 | Lead unlock credits for current billing cycle |
| `credits_reset_at` | TEXT | | Timestamp of last credit reset |
| `is_active` | INTEGER | 1 | Account active flag |
| `is_admin` | INTEGER | 0 | Admin privileges |
| `attorney_status` | TEXT | `NONE` | Attorney verification: `NONE`, `PENDING`, `VERIFIED` |
| `verified_attorney` | INTEGER | 0 | Legacy boolean for attorney verification |
| `stripe_customer_id` | TEXT | | Stripe customer ID |
| `stripe_subscription_id` | TEXT | | Stripe subscription ID |
| `created_at` | TEXT | | Account creation timestamp |
| `last_login_at` | TEXT | | Last login timestamp |

---

## Table: `lead_unlocks`

Audit trail of every lead unlock. Tracks who viewed PII and when.

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | TEXT | FK to `users.user_id` |
| `lead_id` | TEXT | FK to `leads.id` |
| `unlocked_at` | TEXT | ISO timestamp |
| `ip_address` | TEXT | Client IP from X-Forwarded-For |
| `plan_tier` | TEXT | User's tier at time of unlock |

**Composite key:** `(user_id, lead_id)` -- a user can only unlock a lead once.

---

## Table: `leads_quarantine`

Holds leads removed from the main `leads` table. Same schema as `leads` plus quarantine metadata.

| Column | Type | Description |
|--------|------|-------------|
| (all columns from `leads`) | | Mirror of leads table schema |
| `quarantine_reason` | TEXT | Why the lead was quarantined (e.g., `VERTEX_GHOST_ZERO_VALUE`, `PORTAL_DEBT_ONLY_NO_SURPLUS`) |
| `quarantined_at` | TEXT | ISO timestamp of quarantine action |

**Quarantine reasons:**
- `VERTEX_GHOST_ZERO_VALUE` -- Vertex AI artifact with confidence <= 0.15 and zero surplus
- `PORTAL_DEBT_ONLY_NO_SURPLUS` -- Eagle/San Miguel records with debt but no surplus

---

## Table: `pipeline_events`

Immutable audit log. Every state change, grade change, unlock, quarantine, and scraper run is recorded here.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | AUTOINCREMENT primary key |
| `asset_id` | TEXT | Lead ID or `SYSTEM` for system-level events |
| `event_type` | TEXT | Event category (see below) |
| `old_value` | TEXT | State before the change |
| `new_value` | TEXT | State after the change |
| `actor` | TEXT | Who/what triggered the event |
| `reason` | TEXT | Human-readable explanation |
| `created_at` | TEXT | ISO timestamp |

**Event types:**
- `GRADE_CHANGE` -- Lead grade upgraded/downgraded
- `LEAD_UNLOCK` -- User unlocked a lead (credits deducted)
- `QUARANTINE_GHOSTS` -- Batch ghost lead quarantine
- `DEMOTE_JEFFERSON` -- Jefferson false-GOLD demotion
- `SCRAPER_SUCCESS` -- Successful scraper run
- `SCRAPER_ERROR` -- Failed scraper run
- `DEDUP` -- Duplicate records removed
- `VERTEX_PROCESS` -- Vertex AI enrichment event

---

## Table: `vertex_usage`

Tracks daily Vertex AI API usage for budget control (50 PDFs/day cap).

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | AUTOINCREMENT |
| `date` | TEXT | ISO date (`YYYY-MM-DD`) |
| `pdf_filename` | TEXT | Name of processed PDF |
| `cost_usd` | REAL | Estimated cost in USD |
| `tokens_in` | INTEGER | Input token count |
| `tokens_out` | INTEGER | Output token count |
| `model` | TEXT | Model name (e.g., `gemini-2.0-flash`) |
| `created_at` | TEXT | Timestamp |

---

## Table: `vertex_queue`

Queue for PDFs waiting for Vertex AI processing.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | AUTOINCREMENT |
| `pdf_path` | TEXT | Path to the PDF file |
| `county` | TEXT | County name |
| `status` | TEXT | `PENDING`, `PROCESSING`, `COMPLETE`, `FAILED` |
| `priority` | INTEGER | Higher = processed first |
| `created_at` | TEXT | Queued timestamp |
| `processed_at` | TEXT | Completion timestamp |
| `error` | TEXT | Error message if failed |

---

## Table: `download_audit`

Tracks every document download (dossiers, letters, case packets) for compliance.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | AUTOINCREMENT |
| `user_id` | TEXT | FK to `users.user_id` |
| `lead_id` | TEXT | FK to `leads.id` |
| `doc_type` | TEXT | `DOSSIER_DOCX`, `DOSSIER_PDF`, `LETTER`, `CASE_PACKET` |
| `granted` | INTEGER | 1 if access was granted, 0 if denied |
| `ip_address` | TEXT | Client IP |
| `created_at` | TEXT | Timestamp (auto-generated) |

---

## Table: `lead_provenance`

SHA256 provenance chain linking leads to their source documents.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | AUTOINCREMENT |
| `lead_id` | TEXT | FK to `leads.id` |
| `source_url` | TEXT | URL of the source document |
| `source_hash` | TEXT | SHA256 hash of the source file |
| `extracted_at` | TEXT | When the data was extracted |
| `parser_name` | TEXT | Which parser produced the record |
| `confidence` | REAL | Confidence score at extraction time |

**Note:** A lead must have at least one `lead_provenance` row before it can be marked `attorney_packet_ready=1`.

---

## Entity Relationship Summary

```
users ──────────┐
    │            │
    │ 1:N        │ 1:N
    ▼            ▼
lead_unlocks   download_audit
    │
    │ N:1
    ▼
leads ──────────┐
    │            │
    │ 1:N        │ 1:N
    ▼            ▼
pipeline_events  lead_provenance

leads ─── (quarantine) ──► leads_quarantine

vertex_queue ─── (processing) ──► vertex_usage
```

---

## Quick Audit Queries

```sql
-- Total leads by grade
SELECT data_grade, COUNT(*), SUM(surplus_amount)
FROM leads GROUP BY data_grade;

-- Leads with surplus > $10K
SELECT county, case_number, surplus_amount, confidence_score
FROM leads WHERE surplus_amount > 10000
ORDER BY surplus_amount DESC;

-- Recent unlocks
SELECT u.email, lu.lead_id, lu.unlocked_at, lu.plan_tier
FROM lead_unlocks lu JOIN users u ON lu.user_id = u.user_id
ORDER BY lu.unlocked_at DESC LIMIT 20;

-- Quarantined lead count by reason
SELECT quarantine_reason, COUNT(*)
FROM leads_quarantine GROUP BY quarantine_reason;

-- Pipeline events in last 24 hours
SELECT event_type, COUNT(*) FROM pipeline_events
WHERE created_at >= datetime('now', '-1 day')
GROUP BY event_type;
```
