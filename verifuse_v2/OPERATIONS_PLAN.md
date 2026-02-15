# VERIFUSE V2 — TITANIUM OPERATIONS PLAN
## Last Updated: February 15, 2026 (Sprint 5 — Schema Unification + Enterprise Engine)

---

## SYSTEM STATUS: TITANIUM v4.0

| Metric | Value |
|--------|-------|
| Total Leads | 714 |
| Enriched (with surplus data) | 26 |
| Total Pipeline | $4,323,324.65 |
| Counties | 10 (Jefferson, Arapahoe, Denver, Adams, Teller, Douglas, Mesa, Eagle, San Miguel, Summit) |
| Database | SQLite WAL at `VERIFUSE_DB_PATH` |
| API Version | Titanium v4.0 (leads-native) |
| Tables | 11 (leads, assets, users, lead_unlocks, legal_status, pipeline_events, statute_authority, scraper_registry, blacklist, user_addons, attorney_view) |

---

## 1. ARCHITECTURE — HOW THE SYSTEM WORKS

### 1.1 Single Source of Truth

Every component reads `VERIFUSE_DB_PATH` from the environment. No hardcoded paths.

```
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
```

If this env var is missing, every script fails fast with a clear error.

### 1.2 Data Flow

```
[Public Trustee PDFs] → [Scrapers] → [leads table] → [API] → [Frontend]
                                         ↓
                              [Vertex AI Engine] (enrichment)
                                         ↓
                              [leads.winning_bid, total_debt, surplus_amount]
```

### 1.3 The `leads` Table (Canonical Data Model)

| Column | Type | Source |
|--------|------|--------|
| id | TEXT PK | Generated hash |
| case_number | TEXT | Scraped from PDF/website |
| county | TEXT | From source |
| owner_name | TEXT | Scraped |
| property_address | TEXT | Scraped |
| estimated_surplus | REAL | Scraped (raw, pre-verification) |
| record_hash | TEXT | Dedup fingerprint |
| winning_bid | REAL | Vertex AI extraction |
| total_debt | REAL | Vertex AI extraction |
| surplus_amount | REAL | Computed: max(0, winning_bid - total_debt) |
| overbid_amount | REAL | Vertex AI extraction |
| confidence_score | REAL | 0.0-1.0 completeness metric |
| status | TEXT | STAGED/ENRICHED/NEW |
| sale_date | TEXT | ISO date of foreclosure sale |
| claim_deadline | TEXT | sale_date + 180 days (C.R.S. § 38-38-111) |
| data_grade | TEXT | GOLD/SILVER/BRONZE/IRON/REJECT |
| source_name | TEXT | Which engine produced this lead |
| vertex_processed | INTEGER | 0/1 — has Vertex AI touched this? |
| updated_at | TEXT | ISO timestamp |

### 1.4 API Access Control (Hybrid Gate)

```
                        ┌──────────────┐
                        │  Sale Date   │
                        └──────┬───────┘
                               │
                   ┌───────────┼───────────┐
                   │           │           │
              < 180 days   ≥ 180 days   Past deadline
                   │           │           │
              RESTRICTED   ACTIONABLE   EXPIRED
                   │           │           │
         attorney + tier    any paid     LOCKED
         (OPERATOR/SOV)      user       (cannot unlock)
```

- Status is computed at runtime from UTC dates. NEVER stored.
- SafeAsset (no PII) is the default projection. FullAsset only after unlock.
- Credit deduction is atomic: `BEGIN IMMEDIATE` transaction.

---

## 2. PRODUCTION FILES — WHAT EACH FILE DOES

### 2.1 Schema & Migrations

| File | Purpose |
|------|---------|
| `verifuse_v2/db/fix_leads_schema.py` | Auto-patcher: converts `leads` VIEW → TABLE, adds revenue columns, backfills from `assets`. Idempotent. |
| `verifuse_v2/db/migrate_titanium.py` | Adds Titanium columns to `assets`, creates `lead_unlocks`, backfills deadlines. |
| `verifuse_v2/db/migrate_master.py` | Original V2 migration (staging table, pipeline events). |
| `verifuse_v2/db/database.py` | DAL: get_connection(), get_db(), CRUD for users/leads/unlocks. |
| `verifuse_v2/db/schema.sql` | Full DDL for all 11 tables. |

**Run order:** `fix_leads_schema.py` → `migrate_titanium.py` (both idempotent)

### 2.2 Engines & Scrapers

| File | Engine # | Target | Output |
|------|----------|--------|--------|
| `scrapers/vertex_engine_enterprise.py` | Enterprise | All PDFs in `data/raw_pdfs/` | Upserts into `leads` table |
| `scrapers/vertex_engine_production.py` | #4 | `assets_staging` → `assets` | For staging pipeline |
| `scrapers/jefferson_scraper.py` | #1 | Jefferson County website | Direct to `assets` |
| `scrapers/adams_postsale_scraper.py` | #6 | Adams County PDFs | Direct to `assets` |
| `scrapers/elpaso_postsale_scraper.py` | #5 | El Paso County PDFs | Direct to `assets` |
| `scrapers/tax_lien_scraper.py` | #2 | Denver excess funds | Direct to `assets` |
| `scrapers/larimer_scraper.py` | #7 | Larimer County | Direct to `assets` |
| `scrapers/weld_scraper.py` | #8 | Weld County | Direct to `assets` |
| `scrapers/boulder_scraper.py` | #9 | Boulder County | Direct to `assets` |
| `scrapers/pueblo_scraper.py` | #10 | Pueblo County | Direct to `assets` |

### 2.3 API Server

| File | Purpose |
|------|---------|
| `server/api.py` | FastAPI server, queries `leads` table, NULL-safe, CORS, rate limiting |
| `server/auth.py` | JWT auth, bcrypt passwords, register/login |
| `server/models.py` | Pydantic models (Lead, SafeAsset, FullAsset) |
| `server/billing.py` | Stripe integration |
| `server/dossier_gen.py` | PDF dossier generation |
| `server/obfuscator.py` | PII obfuscation (text → image) |

### 2.4 Verification & Health

| File | Purpose |
|------|---------|
| `verify_system.py` | Green Light diagnostic: DB, schema, data, credentials, API |
| `daily_healthcheck.py` | Regrade assets, compute confidence/completeness |

---

## 3. HOW TO RUN THE SYSTEM

### 3.1 Environment Setup

```bash
# Required env vars
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
export VERIFUSE_JWT_SECRET=<your-secret>

# Install dependencies
pip install -r verifuse_v2/requirements.txt
```

### 3.2 Schema Setup (idempotent — safe to run multiple times)

```bash
python -m verifuse_v2.db.fix_leads_schema        # Patch leads table
python -m verifuse_v2.db.migrate_titanium         # Titanium columns
```

### 3.3 Run Scrapers (populate leads)

```bash
# Scrape county websites
python -m verifuse_v2.scrapers.jefferson_scraper
python -m verifuse_v2.scrapers.adams_postsale_scraper
python -m verifuse_v2.scrapers.elpaso_postsale_scraper

# Enrich with Vertex AI (requires Google credentials)
python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run  # test first
python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 50  # real run
```

### 3.4 Start API Server

```bash
cd /home/schlieve001/origin/continuity_lab
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### 3.5 Verify System Health

```bash
python -m verifuse_v2.verify_system
curl http://localhost:8000/health
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/leads?limit=5
```

---

## 4. CURRENT DATA QUALITY REPORT

### 4.1 County Pipeline

| County | Leads | Enriched | Surplus | Grade |
|--------|-------|----------|---------|-------|
| Jefferson | 64 | 3 | $1,826,675 | High-value, low enrichment |
| Arapahoe | 12 | 12 | $1,426,297 | Fully enriched |
| Denver | 8 | 8 | $1,007,308 | Fully enriched |
| Adams | 35 | 0 | $0 | Needs Vertex AI enrichment |
| Teller | 26 | 1 | $18,245 | Needs enrichment |
| Douglas | 1 | 1 | $4,797 | Small |
| Mesa | 1 | 1 | $40,000 | Single lead |
| Eagle | 312 | 0 | $0 | No surplus data — REJECT grade |
| San Miguel | 250 | 0 | $0 | No surplus data — REJECT grade |
| Summit | 5 | 0 | $0 | No surplus data |

### 4.2 Grade Distribution

| Grade | Count | Meaning |
|-------|-------|---------|
| GOLD | 70 | Surplus > $10K, confidence > 0.8 |
| SILVER | 2 | Surplus > $5K, confidence > 0.6 |
| BRONZE | 39 | Has surplus data |
| REJECT | 603 | No financial data, need enrichment or removal |

### 4.3 Immediate Actions Needed

1. **Run Vertex AI Enterprise Engine on 14 PDFs** — Will enrich Adams (35 leads) and Denver leads
2. **Scrape Jefferson County Post-Sale PDFs** — 61 of 64 Jefferson leads lack winning_bid
3. **Purge Eagle (312) + San Miguel (250)** — These are REJECT-grade with zero surplus. Either find their source PDFs or remove them
4. **Download more county PDFs** — Larimer, Weld, Boulder, Pueblo scrapers exist but need fresh data files

---

## 5. WHAT HAS BEEN DONE

### Sprint 1 (Feb 10-11): Foundation
- Built 7 county scrapers (Jefferson, Denver, Adams, El Paso, Arapahoe, Teller, Douglas)
- Created unified `assets` table with 734 records
- Built FastAPI server with JWT auth, Stripe billing

### Sprint 2 (Feb 12): Engine #4
- Fixed Vertex AI engine (preflight, backoff, audit log)
- Built staging promoter for assets_staging → assets
- Created systemd timer for automated runs

### Sprint 3 (Feb 13): Infrastructure
- Fixed port conflict (API on 8000, frontend on 4173)
- Installed systemd timers for healthcheck, engine runs
- DNS configuration guide

### Sprint 4 (Feb 14): Titanium Architecture
- Titanium schema (migrate_titanium.py)
- Pydantic models with computed status
- API rewrite with rate limiting, NULL-safe projections
- Built 4 new county scrapers (Larimer, Weld, Boulder, Pueblo)

### Sprint 5 (Feb 15): Schema Unification + Enterprise Engine
- Converted `leads` from VIEW → real TABLE (fix_leads_schema.py)
- Enriched leads with data from assets table (691 debt, 680 confidence, 79 sale dates)
- Built vertex_engine_enterprise.py (scans PDFs, upserts into leads)
- Rewrote api.py to query leads table (not assets)
- All SafeAsset fields are Optional[float] = None (Black Screen fix)
- Double Gate: RESTRICTED = attorney + (OPERATOR|SOVEREIGN)

---

## 6. WHAT STILL NEEDS TO BE DONE

### Critical Path (Do First)

| # | Task | Impact | Status |
|---|------|--------|--------|
| 1 | Run `vertex_engine_enterprise` with live Vertex AI | Enriches 14 PDFs → winning_bid + total_debt for Adams, Denver, El Paso | READY (needs GOOGLE_APPLICATION_CREDENTIALS) |
| 2 | Download fresh county PDFs | Jefferson post-sale, Arapahoe weekly | Manual download from trustee websites |
| 3 | Purge or enrich Eagle/San Miguel (562 REJECT leads) | Clean up grade distribution | Decision: keep or remove |
| 4 | Set `VERIFUSE_DB_PATH` in systemd services | All services use canonical path | Quick config change |
| 5 | Frontend deployment | Connect to API v4 endpoints | Vite build + deploy |

### Revenue Acceleration

| # | Task | Impact |
|---|------|--------|
| 6 | Stripe webhook integration | Enable paid tier upgrades |
| 7 | Attorney verification flow | Enable RESTRICTED lead access |
| 8 | Dossier generation | PDF reports for unlocked leads |
| 9 | Email notifications | Alert attorneys to new GOLD leads |

### Scale

| # | Task | Impact |
|---|------|--------|
| 10 | Cron job: weekly PDF download from trustee sites | Automated lead refresh |
| 11 | PostgreSQL migration (Supabase) | Scale beyond SQLite limits |
| 12 | Multi-state expansion (TX, AZ, NV) | 10x lead volume |

---

## 7. HOW TO GET TO 100+ VERIFIED LEADS

### Current State: 26 enriched leads with real surplus data

### Path to 100+ Verified Leads:

**Phase 1: Enrich existing data (gets to ~80 verified)**
1. Run `vertex_engine_enterprise` on 14 PDFs in `data/raw_pdfs/` → extracts winning_bid, total_debt for Adams (35), El Paso, Denver
2. For Jefferson (64 leads, only 3 enriched): Download post-sale PDFs from Jefferson County Public Trustee weekly list
3. Regrade all leads after enrichment

**Phase 2: New county scraping (gets to 100+)**
1. Download Larimer County Public Trustee surplus list
2. Download Weld County excess funds page
3. Download Boulder County trustee data
4. Run each county scraper → inserts into assets → schema patcher syncs to leads

**Phase 3: Continuous pipeline (100+ per month)**
1. Automate weekly PDF downloads via cron
2. Run `vertex_engine_enterprise` weekly on new PDFs
3. Run `daily_healthcheck.py` to regrade

### Key Insight: The 691 leads with `total_debt` data but no `winning_bid` are the low-hanging fruit. Those debt figures came from the original scrape. If we can get the post-sale results (which list winning bids), we can compute surplus = bid - debt for all 691 leads in one pass.

---

## 8. REVOLUTIONARY IDEAS — BECOMING COLORADO'S #1 SURPLUS PLATFORM

### 8.1 Competitive Moat: Data Quality > Data Quantity
- Every competitor scrapes the same public trustee websites. The moat is **verification depth**: winning_bid + total_debt + sale_date + owner = GOLD grade. Most competitors only have estimated_surplus (unverified).
- **Action:** Prioritize Vertex AI enrichment over new county expansion.

### 8.2 The Attorney Funnel
- Free tier (RECON): See obfuscated leads (county, surplus range, grade). 5 unlocks/month.
- Paid tier (OPERATOR, $49/mo): 25 unlocks. Access to ACTIONABLE leads.
- Premium tier (SOVEREIGN, $149/mo): 100 unlocks. Access to RESTRICTED leads (< 6 months post-sale = first-mover advantage).
- **The RESTRICTED window is the killer feature.** Attorneys who act within 180 days of sale get the case before anyone else.

### 8.3 Automated Motion Generator
- Build `server/motion_gen.py` to generate Colorado surplus recovery motions
- Pre-filled with case number, owner name, surplus amount, statute citation
- Attorneys save hours of paperwork → willingness to pay increases dramatically

### 8.4 Multi-Source Verification
- Cross-reference Public Trustee data with county assessor records (property value)
- If assessed_value > total_debt AND winning_bid > total_debt → GOLD confidence
- Adds a third verification layer competitors don't have

### 8.5 Real-Time Alerts
- Email/SMS when new GOLD leads appear in an attorney's target county
- First-mover advantage = attorney pays premium for speed
- Technical: webhook on INSERT into leads WHERE data_grade = 'GOLD'

### 8.6 County Coverage Map (Colorado)
```
Tier 1 (Active):  Jefferson, Denver, Arapahoe, Adams, El Paso, Teller, Douglas, Mesa
Tier 2 (Built):   Larimer, Weld, Boulder, Pueblo
Tier 3 (Scraped): Eagle, San Miguel, Summit
Tier 4 (Target):  Broomfield, Douglas, Park, Clear Creek, Gilpin
```
Goal: Cover every Front Range county (Denver metro + I-25 corridor) by Q2 2026.

### 8.7 SOTA Technical Advantages
1. **Vertex AI + Gemini for PDF parsing** — No manual data entry, sub-$0.01 per extraction
2. **Dynamic status computation** — Attorneys always see current legal window status
3. **Atomic credit system** — No race conditions on unlock (BEGIN IMMEDIATE)
4. **JSONL audit trail** — Full provenance for every data point
5. **Idempotent everything** — Every script is safe to run repeatedly

---

## 9. SYSTEM TOPOLOGY

```
┌─────────────────────────────────────────────────────┐
│                    VERIFUSE V2                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌──────────┐  │
│  │ Scrapers │───→│  leads table │←───│ Vertex AI│  │
│  │ (10 eng) │    │  (714 rows)  │    │ Enterprise│  │
│  └──────────┘    └──────┬───────┘    └──────────┘  │
│                         │                           │
│                    ┌────┴────┐                      │
│                    │  API    │                      │
│                    │ v4.0   │                      │
│                    │ :8000   │                      │
│                    └────┬────┘                      │
│                         │                           │
│              ┌──────────┴──────────┐                │
│              │   Frontend (Vite)   │                │
│              │   :4173 / :3000     │                │
│              └─────────────────────┘                │
│                                                     │
│  ENV: VERIFUSE_DB_PATH, GOOGLE_APPLICATION_CREDS    │
│  Auth: JWT (HS256, 72h expiry)                      │
│  Billing: Stripe (recon/operator/sovereign)          │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 10. QUICK REFERENCE

```bash
# Schema patch (always safe to run)
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
python -m verifuse_v2.db.fix_leads_schema

# Vertex AI enrichment (dry-run first)
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run
python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 50

# Start API
VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db \
  uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/health
curl http://localhost:8000/api/leads?limit=5
curl http://localhost:8000/api/stats
```
