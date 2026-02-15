# VERIFUSE V2 — TITANIUM OPERATIONS PLAN
## Last Updated: February 15, 2026 (Sprint 7 — System Hardening + Frontend Contract)

---

## SYSTEM STATUS: TITANIUM v4.1

| Metric | Value |
|--------|-------|
| Total Leads | 734 |
| Enriched (with surplus data) | 38 ENRICHED, 129 STAGED |
| GOLD Grade | 80 |
| Total Pipeline Value | $4,995,642.07 |
| Counties | 10 (Jefferson, Arapahoe, Denver, Adams, Teller, Douglas, Mesa, Eagle, San Miguel, Summit) |
| Database | SQLite WAL at `VERIFUSE_DB_PATH` |
| API Version | Titanium v4.1 (leads-native, frontend-aligned) |
| Frontend | Vite + React + TypeScript at `:4173` |
| Backend | FastAPI + Uvicorn at `:8000` |
| Tables | 11 (leads, assets, users, lead_unlocks, legal_status, pipeline_events, statute_authority, scraper_registry, blacklist, user_addons, sqlite_sequence) |

---

## 1. ARCHITECTURE

### 1.1 Single Source of Truth

Every component reads `VERIFUSE_DB_PATH` from the environment. No hardcoded paths.

```
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
```

If this env var is missing, every script fails fast with a clear error.

### 1.2 Data Flow

```
[County Public Trustee Websites]
         │
         ▼
┌─────────────────────────┐
│    Scrapers (10 engines) │
│  jefferson, adams,       │
│  elpaso, denver, etc.    │
└────────────┬────────────┘
             │ INSERT/UPSERT
             ▼
┌─────────────────────────┐
│     leads table (734)    │◄──── Engine V2 (registry.py + engine_v2.py)
│  case_number, county,    │      Routes PDFs through parsers
│  owner_name, address,    │
│  surplus_amount, etc.    │◄──── Vertex AI Enterprise (vertex_engine_enterprise.py)
└────────────┬────────────┘      Gemini 2.0 Flash extraction
             │
             ▼
┌─────────────────────────┐
│   API v4.1 (api.py)      │
│   FastAPI + JWT + CORS   │
│   Rate limiting (slowapi) │
│   :8000                  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Frontend (Vite/React)  │
│   :4173 (dev)            │
│   :3000 (preview)        │
│   verifuse.tech (prod)   │
└─────────────────────────┘
```

### 1.3 The `leads` Table (Canonical Data Model)

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| id | TEXT PK | Generated hash | Deterministic: `{county}_vertex_{sha256[:12]}` |
| case_number | TEXT | Scraped | Court case or reception number |
| county | TEXT | From source | Colorado county name |
| owner_name | TEXT | Scraped | Property owner / borrower |
| property_address | TEXT | Scraped | Full street address |
| estimated_surplus | REAL | Scraped (raw) | Pre-verification surplus estimate |
| record_hash | TEXT | Computed | Dedup fingerprint |
| winning_bid | REAL | Vertex AI | Auction sale price |
| total_debt | REAL | Vertex AI | Total indebtedness/liens |
| surplus_amount | REAL | Computed | `max(0, winning_bid - total_debt)` |
| overbid_amount | REAL | Vertex AI | Overbid / excess amount |
| confidence_score | REAL | Computed | 0.0-1.0 completeness metric |
| status | TEXT | Pipeline | PIPELINE_STAGING / STAGED / ENRICHED / NEW |
| sale_date | TEXT | Scraped | ISO date of foreclosure sale |
| claim_deadline | TEXT | Computed | `sale_date + 180 days` (C.R.S. 38-38-111) |
| data_grade | TEXT | Computed | GOLD / SILVER / BRONZE / IRON / REJECT |
| source_name | TEXT | Engine | Which engine produced this lead |
| vertex_processed | INTEGER | Flag | 0/1 has Vertex AI touched this |
| updated_at | TEXT | Auto | ISO timestamp |

### 1.4 Access Control (Hybrid Gate System)

```
                    ┌──────────────┐
                    │  Sale Date   │
                    └──────┬───────┘
                           │
               ┌───────────┼───────────┐
               │           │           │
          < 180 days   >= 180 days  Past deadline
               │           │           │
          RESTRICTED   ACTIONABLE   EXPIRED
               │           │           │
     attorney + tier    any paid     LOCKED
     (OPERATOR/SOV)      user       (cannot unlock)
```

- Status is computed at **runtime** from UTC dates. NEVER stored in DB.
- **SafeAsset** (no PII) is the default projection.
- **FullAsset** (with PII) only after unlock + credit deduction.
- Credit deduction is **atomic**: `BEGIN IMMEDIATE` transaction prevents race conditions.

---

## 2. FRONTEND-BACKEND CONTRACT

### 2.1 API Endpoints (Complete)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | System health + DB stats |
| `GET` | `/api/leads` | No | Paginated leads (SafeAsset projection) |
| `GET` | `/api/lead/{id}` | No | Single lead detail (frontend Lead interface) |
| `GET` | `/api/stats` | No | Dashboard statistics |
| `GET` | `/api/counties` | No | County breakdown |
| `POST` | `/api/auth/register` | No | User registration |
| `POST` | `/api/auth/login` | No | JWT login |
| `GET` | `/api/auth/me` | Yes | Current user info |
| `POST` | `/api/leads/{id}/unlock` | Yes | Unlock lead (internal) |
| `POST` | `/api/unlock/{id}` | Yes | Unlock lead (frontend-compatible) |
| `POST` | `/api/unlock-restricted/{id}` | Yes | Unlock restricted lead + disclaimer |
| `GET` | `/api/dossier/{id}` | Yes | Download dossier (must be unlocked) |
| `POST` | `/api/billing/checkout` | Yes | Create Stripe checkout session |
| `POST` | `/api/billing/upgrade` | Yes | Direct tier upgrade + credit refill |

### 2.2 Frontend Lead Interface → Backend Mapping

| Frontend Field | Backend Source | Notes |
|----------------|---------------|-------|
| `asset_id` | `leads.id` | Renamed for frontend |
| `county` | `leads.county` | Direct |
| `state` | Hardcoded `"CO"` | Colorado only |
| `case_number` | `leads.case_number` | Direct |
| `asset_type` | Hardcoded `"Foreclosure Surplus"` | |
| `estimated_surplus` | `leads.surplus_amount` | Falls back to `estimated_surplus` |
| `surplus_verified` | Computed | `bid > 0 AND debt > 0 AND confidence >= 0.7` |
| `data_grade` | `leads.data_grade` | GOLD/SILVER/BRONZE/IRON/REJECT |
| `record_class` | `leads.data_grade` | Alias |
| `sale_date` | `leads.sale_date` | ISO date string |
| `claim_deadline` | `leads.claim_deadline` | `sale_date + 180 days` |
| `days_to_claim` | Computed | `claim_deadline - today` |
| `deadline_passed` | Computed | `days_to_claim < 0` |
| `restriction_status` | Computed | RESTRICTED / ACTIONABLE / EXPIRED |
| `restriction_end_date` | Computed | `sale_date + 180 days` |
| `blackout_end_date` | Same as above | |
| `days_until_actionable` | Computed | Days until restriction lifts |
| `address_hint` | Computed | City/county from address (no street) |
| `owner_img` | `null` | Not implemented |
| `completeness_score` | `leads.confidence_score` | Alias |
| `confidence_score` | `leads.confidence_score` | Direct |
| `data_age_days` | `null` | Not tracked |

### 2.3 Stats Response Shape

| Field | Type | Source |
|-------|------|--------|
| `total_assets` | int | `COUNT(*) FROM leads` |
| `total_leads` | int | Same (backward compat) |
| `attorney_ready` | int | Leads with surplus > $1,000 |
| `with_surplus` | int | Same (backward compat) |
| `gold_grade` | int | `COUNT(*) WHERE data_grade = 'GOLD'` |
| `total_claimable_surplus` | float | `SUM(surplus_amount)` |
| `counties` | array | `{county, cnt, total}` grouped |

### 2.4 Auth Token Flow

```
Frontend                              Backend
   │                                     │
   │  POST /api/auth/login               │
   │  { email, password }                │
   │ ──────────────────────────────────► │
   │                                     │  bcrypt verify
   │  ◄──────────────────────────────── │
   │  { token: "JWT...", user: {...} }   │
   │                                     │
   │  localStorage.setItem("vf_token")   │
   │                                     │
   │  GET /api/leads                     │
   │  Authorization: Bearer {token}      │
   │ ──────────────────────────────────► │
   │                                     │  pyjwt.decode(HS256)
   │  ◄──────────────────────────────── │
   │  { count, leads: [...] }            │
```

- JWT secret: `VERIFUSE_JWT_SECRET` env var
- Algorithm: HS256
- Expiry: 72 hours
- Storage: `localStorage` key `vf_token`

---

## 3. PRODUCTION FILES — EVERY FILE EXPLAINED

### 3.1 Schema & Migrations

| File | Purpose | Idempotent |
|------|---------|------------|
| `db/fix_leads_schema.py` | Converts `leads` VIEW → TABLE, adds revenue columns, backfills from `assets` | Yes |
| `db/migrate_titanium.py` | Adds Titanium columns to `assets`, creates `lead_unlocks`, backfills deadlines | Yes |
| `db/migrate_master.py` | Original V2 migration (staging table, pipeline events) | Yes |
| `db/database.py` | DAL: `get_connection()`, `get_db()`, CRUD for users/leads/unlocks | - |
| `db/schema.sql` | Full DDL for all tables | - |

**Run order:** `fix_leads_schema.py` → `migrate_titanium.py` (both idempotent)

### 3.2 Engines & Scrapers

| File | Engine | Target | Output |
|------|--------|--------|--------|
| `scrapers/vertex_engine_enterprise.py` | Enterprise | All PDFs in `data/raw_pdfs/` | Upserts into `leads` table via Gemini 2.0 Flash |
| `scrapers/engine_v2.py` | V2 Registry | All PDFs via parser registry | Routes through `registry.py` parsers |
| `scrapers/registry.py` | Parser Registry | ABC `CountyParser` | `detect()`, `extract()`, `score()` interface |
| `scrapers/vertex_engine_production.py` | #4 | `assets_staging` → `assets` | Staging pipeline |
| `scrapers/jefferson_scraper.py` | #1 | Jefferson County website | Direct to `assets` |
| `scrapers/adams_postsale_scraper.py` | #6 | Adams County PDFs | Direct to `assets` |
| `scrapers/elpaso_postsale_scraper.py` | #5 | El Paso County PDFs | Direct to `assets` |
| `scrapers/tax_lien_scraper.py` | #2 | Denver excess funds | Direct to `assets` |
| `scrapers/larimer_scraper.py` | #7 | Larimer County | Direct to `assets` |
| `scrapers/weld_scraper.py` | #8 | Weld County | Direct to `assets` |
| `scrapers/boulder_scraper.py` | #9 | Boulder County | Direct to `assets` |
| `scrapers/pueblo_scraper.py` | #10 | Pueblo County | Direct to `assets` |

### 3.3 API Server

| File | Purpose |
|------|---------|
| `server/api.py` | FastAPI server — all endpoints, queries `leads` table, NULL-safe projections, CORS, rate limiting, frontend-compatible routes |
| `server/auth.py` | JWT auth (HS256, 72h expiry), bcrypt passwords, register/login |
| `server/models.py` | Pydantic models (Lead, SafeAsset, FullAsset) |
| `server/billing.py` | Stripe integration — checkout sessions, webhooks, credit reset |
| `server/dossier_gen.py` | PDF dossier generation (fpdf) — 4-section layout, verification watermark |
| `server/obfuscator.py` | PII obfuscation (text → image rendering) |

### 3.4 Parser Registry (Titanium)

| Parser | File Pattern | Counties |
|--------|-------------|----------|
| `AdamsParser` | `adams*.pdf` | Adams |
| `DenverExcessParser` | `denver*.pdf`, `excess*.pdf` | Denver |
| `ElPasoPreSaleParser` | `elpaso*pre*.pdf` | El Paso (pre-sale) |
| `ElPasoPostSaleParser` | `elpaso*post*.pdf` | El Paso (post-sale) |
| `GenericExcessFundsParser` | `*.pdf` (fallback) | Any county |

**Confidence Function C:**
```
C = 0.25*I(bid) + 0.25*I(debt) + 0.15*I(date) + 0.15*I(addr) + 0.10*I(owner) + 0.10*V(delta)
```
Where `V(delta) = 1.0 if |surplus - (bid - debt)| <= $5` (math consistency check).

### 3.5 Deploy & Operations

| File | Purpose |
|------|---------|
| `deploy/verifuse-vertex.service` | systemd service for Vertex AI engine runs |
| `verify_system.py` | Green Light diagnostic: DB, schema, data, credentials, API |
| `daily_healthcheck.py` | Regrade assets, compute confidence/completeness |

---

## 4. HOW TO RUN THE SYSTEM

### 4.1 Environment Setup

```bash
# Required env vars
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
export VERIFUSE_JWT_SECRET=<your-secret>

# Optional (for Stripe billing)
export STRIPE_SECRET_KEY=sk_...
export STRIPE_WEBHOOK_SECRET=whsec_...
export STRIPE_PRICE_RECON=price_...
export STRIPE_PRICE_OPERATOR=price_...
export STRIPE_PRICE_SOVEREIGN=price_...

# Install dependencies
pip install -r verifuse_v2/requirements.txt
```

### 4.2 Schema Setup (idempotent)

```bash
python -m verifuse_v2.db.fix_leads_schema
python -m verifuse_v2.db.migrate_titanium
```

### 4.3 Run Scrapers

```bash
# County scrapers (populate leads)
python -m verifuse_v2.scrapers.jefferson_scraper
python -m verifuse_v2.scrapers.adams_postsale_scraper
python -m verifuse_v2.scrapers.elpaso_postsale_scraper

# Engine V2 — local PDF parsing via registry
python -m verifuse_v2.scrapers.engine_v2 --dry-run
python -m verifuse_v2.scrapers.engine_v2

# Vertex AI Enterprise — Gemini 2.0 Flash extraction
python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run
python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 50
```

### 4.4 Start API Server

```bash
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### 4.5 Start Frontend

```bash
cd verifuse/site/app
npm run dev -- --host 0.0.0.0 --port 4173
```

### 4.6 Verify System Health

```bash
python -m verifuse_v2.verify_system
curl http://localhost:8000/health
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/leads?limit=5
curl http://localhost:8000/api/lead/$(curl -s http://localhost:8000/api/leads?limit=1 | python3 -c "import sys,json; print(json.load(sys.stdin)['leads'][0]['id'])")
```

---

## 5. DATA QUALITY REPORT

### 5.1 Lead Status Distribution

| Status | Count | Description |
|--------|-------|-------------|
| PIPELINE_STAGING | 567 | Eagle + San Miguel pre-sale data, awaiting auction results |
| STAGED | 129 | Scraped, awaiting Vertex AI enrichment |
| ENRICHED | 38 | Fully processed with financial data |
| **Total** | **734** | |

### 5.2 Grade Distribution

| Grade | Count | Criteria |
|-------|-------|----------|
| GOLD | 80 | Surplus > $10K, confidence > 0.8 |
| SILVER | 2 | Surplus > $5K, confidence > 0.6 |
| BRONZE | 42 | Has surplus data |
| IRON | 10 | Minimal data |
| REJECT | 600 | No financial data |
| **Total** | **734** | |

### 5.3 County Pipeline

| County | Leads | Surplus | Status |
|--------|-------|---------|--------|
| Jefferson | 64 | $1,826,675 | High-value, 3 enriched, 61 need post-sale PDFs |
| Arapahoe | 12 | $1,426,297 | Fully enriched |
| Denver | 15 | $1,421,519 | Enriched via Engine V2 + Vertex AI |
| Adams | 48 | $258,108 | 13 enriched via Engine V2, 35 need Vertex AI |
| Mesa | 1 | $40,000 | Single lead |
| Teller | 26 | $18,246 | 1 enriched, needs more data |
| Douglas | 1 | $4,798 | Small |
| Eagle | 312 | $0 | Pre-sale data (debt only, no auction results) |
| San Miguel | 250 | $0 | Pre-sale data (debt only, no auction results) |
| Summit | 5 | $0 | No surplus data |

---

## 6. COUNTY DATA SOURCES

### 6.1 Active Sources (Colorado Public Trustees)

| County | Source URL | Data Available |
|--------|-----------|----------------|
| Jefferson | https://www.jeffco.us/787/Public-Trustee | Post-sale surplus lists (PDF) |
| Arapahoe | https://www.arapahoegov.com/1318/Public-Trustee | Foreclosure sale results |
| Denver | https://www.denvergov.org/Government/Agencies-Departments-Offices/Public-Trustee | Excess funds listing (PDF) |
| Adams | https://adcogov.org/public-trustee | Post-sale results (PDF) |
| El Paso | https://publictrustee.elpasoco.com/ | Pre-sale & post-sale PDFs |
| Teller | https://www.co.teller.co.us/PublicTrustee/ | Foreclosure listings |
| Douglas | https://www.douglas.co.us/public-trustee/ | Sale results |
| Mesa | https://www.mesacounty.us/public-trustee | Surplus funds listing |
| Larimer | https://www.larimer.gov/public-trustee | Weekly sale results |
| Weld | https://www.weldgov.com/departments/public_trustee | Excess funds |
| Boulder | https://www.bouldercounty.org/property-and-land/public-trustee/ | Sale results |
| Pueblo | https://www.pueblocounty.us/340/Public-Trustee | Foreclosure data |

### 6.2 Data Refresh Strategy

1. **Weekly**: Download fresh PDFs from Jefferson, Adams, Denver, El Paso
2. **Bi-weekly**: Scrape Arapahoe, Teller, Douglas, Mesa
3. **Monthly**: Check Larimer, Weld, Boulder, Pueblo for new listings
4. **Continuous**: Run Engine V2 + Vertex AI Enterprise on new PDFs

---

## 7. AUTOMATED PIPELINE DESIGN

### 7.1 Current Pipeline (Manual)

```
1. Download PDFs from county websites (manual)
2. Place in verifuse_v2/data/raw_pdfs/{county}/
3. Run engine_v2.py (local parsing via registry)
4. Run vertex_engine_enterprise.py (Gemini 2.0 Flash)
5. Check results: python -m verifuse_v2.verify_system
```

### 7.2 Target Pipeline (Automated)

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Cron (weekly)   │────▸│  PDF Downloader   │────▸│  raw_pdfs/      │
│  systemd timer   │     │  (per county)     │     │  {county}/*.pdf │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Engine V2       │
                                                  │  (registry.py)   │
                                                  │  Local parsing   │
                                                  └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Vertex AI       │
                                                  │  Enterprise      │
                                                  │  (Gemini 2.0)    │
                                                  └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Daily Health    │
                                                  │  Check           │
                                                  │  (regrade all)   │
                                                  └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Alert System    │
                                                  │  (new GOLD →     │
                                                  │   email notify)  │
                                                  └─────────────────┘
```

### 7.3 systemd Timers

```ini
# verifuse-vertex.service — runs Vertex AI engine
[Service]
Environment=VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
Environment=GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
ExecStart=python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 100

# verifuse-healthcheck.timer — daily regrade
[Timer]
OnCalendar=*-*-* 06:00:00
```

---

## 8. SPRINT HISTORY

### Sprint 1 (Feb 10-11): Foundation
- Built 7 county scrapers (Jefferson, Denver, Adams, El Paso, Arapahoe, Teller, Douglas)
- Created unified `assets` table with 734 records
- Built FastAPI server with JWT auth, Stripe billing

### Sprint 2 (Feb 12): Engine #4
- Fixed Vertex AI engine (preflight, backoff, audit log)
- Built staging promoter for `assets_staging` → `assets`
- Created systemd timer for automated runs

### Sprint 3 (Feb 13): Infrastructure
- Fixed port conflict (API on 8000, frontend on 4173)
- Installed systemd timers for healthcheck, engine runs
- DNS configuration guide

### Sprint 4 (Feb 14): Titanium Architecture
- Titanium schema (`migrate_titanium.py`)
- Pydantic models with computed status
- API rewrite with rate limiting, NULL-safe projections
- Built 4 new county scrapers (Larimer, Weld, Boulder, Pueblo)

### Sprint 5 (Feb 15a): Schema Unification + Enterprise Engine
- Converted `leads` from VIEW → real TABLE (`fix_leads_schema.py`)
- Enriched leads with data from assets table (691 debt, 680 confidence, 79 sale dates)
- Built `vertex_engine_enterprise.py` (scans PDFs, upserts into leads)
- Rewrote `api.py` to query leads table (not assets)
- All SafeAsset fields are `Optional[float] = None` (Black Screen fix)
- Double Gate: RESTRICTED = attorney + (OPERATOR|SOVEREIGN)

### Sprint 6 (Feb 15b): Titanium Registry + Engine V2
- Built `registry.py`: Abstract Base Class `CountyParser` with `detect()`, `extract()`, `score()`
- Confidence Function C with variance check `V(delta)`
- 5 parsers: Adams, Denver Excess, El Paso Pre/Post-Sale, Generic
- `engine_v2.py`: Scans all PDFs, routes through parser registry
- **Results: 40 records extracted, 40 ENRICHED, 20 updated + 20 inserted**
- 2 new GOLD leads from Adams ($215K + $37K), 7 GOLD from Denver excess
- Vertex AI confirmed: `gemini-2.0-flash` on project `canvas-sum-481614-f6`

### Sprint 7 (Feb 15c): System Hardening + Frontend Contract
- Fixed `vertex_engine_enterprise.py` default model: `gemini-1.5-flash` → `gemini-2.0-flash`
- Updated systemd service with `VERIFUSE_DB_PATH` and `VERIFUSE_JWT_SECRET` env vars
- Added missing API endpoints for frontend compatibility:
  - `GET /api/lead/{id}` — single lead detail with full frontend Lead interface
  - `POST /api/unlock/{id}` — frontend-compatible unlock route
  - `POST /api/unlock-restricted/{id}` — restricted unlock with disclaimer
  - `GET /api/dossier/{id}` — dossier download (requires unlock)
  - `POST /api/billing/checkout` — Stripe checkout session creation
- Fixed `/api/stats` response to include `total_assets`, `attorney_ready`, `gold_grade`
- Comprehensive operations plan rewrite with frontend-backend contract

---

## 9. WHAT STILL NEEDS TO BE DONE

### Critical Path (Do First)

| # | Task | Impact | Effort |
|---|------|--------|--------|
| 1 | Run `vertex_engine_enterprise` with Vertex AI | Enriches PDFs → surplus for Adams, Denver, El Paso | 30 min |
| 2 | Download fresh Jefferson post-sale PDFs | 61 of 64 leads lack winning_bid | Manual |
| 3 | Decision on Eagle (312) + San Miguel (250) | 562 REJECT leads — keep for when auction data appears, or remove | Decision |
| 4 | Deploy API v4.1 with `sudo systemctl restart verifuse-api` | Frontend sees new endpoints | 5 min |
| 5 | Fix frontend env: `VITE_API_BASE_URL` vs `VITE_API_URL` in `.env.production` | Production build uses wrong var | 5 min |

### Revenue Acceleration

| # | Task | Impact |
|---|------|--------|
| 6 | Configure Stripe price IDs in env | Enable paid tier upgrades |
| 7 | Attorney verification flow | Enable RESTRICTED lead access |
| 8 | Wire up fpdf dossier generation | Professional PDF reports |
| 9 | Email notifications for new GOLD leads | Attorney retention |

### Scale

| # | Task | Impact |
|---|------|--------|
| 10 | Automated weekly PDF downloads (cron) | No manual data refresh |
| 11 | PostgreSQL migration (Supabase) | Scale beyond SQLite |
| 12 | Multi-state expansion (TX, AZ, NV) | 10x lead volume |

---

## 10. HOW TO GET TO 100+ VERIFIED LEADS

### Current: 80 GOLD + 2 SILVER + 42 BRONZE = 124 leads with surplus data

### Path to 100+ GOLD leads:

**Phase 1: Enrich existing (gets to ~100 GOLD)**
1. Run `vertex_engine_enterprise` on remaining PDFs
2. Download Jefferson post-sale PDFs → compute surplus for 61 leads
3. Regrade all leads after enrichment

**Phase 2: New county data (100+ GOLD)**
1. Download Larimer, Weld, Boulder, Pueblo surplus PDFs
2. Run each county scraper + Engine V2
3. Weekly cadence maintains flow

**Key insight:** The 600 REJECT leads mostly have `total_debt` data but no `winning_bid`. Post-sale PDFs contain winning bids. One pass through Vertex AI on post-sale data could convert hundreds of REJECT → GOLD.

---

## 11. COMPETITIVE STRATEGY

### 11.1 Moat: Verification Depth > Data Quantity
Every competitor scrapes the same public trustee sites. The moat is **verification depth**: `winning_bid + total_debt + sale_date + owner = GOLD grade`. Most competitors only have `estimated_surplus` (unverified).

### 11.2 The Attorney Funnel
- **RECON** (Free): See obfuscated leads (county, surplus range, grade). 5 unlocks/month.
- **OPERATOR** ($49/mo): 25 unlocks. ACTIONABLE leads.
- **SOVEREIGN** ($149/mo): 100 unlocks. RESTRICTED leads (first-mover advantage).

### 11.3 The RESTRICTED Window (Killer Feature)
Attorneys who act within 180 days of sale get the case before anyone else. This first-mover advantage is worth premium pricing.

### 11.4 County Coverage (Colorado)
```
Active (10): Jefferson, Denver, Arapahoe, Adams, El Paso, Teller, Douglas, Mesa, Eagle, San Miguel
Built (4):   Larimer, Weld, Boulder, Pueblo
Target:      Broomfield, Park, Clear Creek, Gilpin, Summit
Goal:        Every Front Range county by Q2 2026
```

---

## 12. QUICK REFERENCE

```bash
# Schema patch (always safe to run)
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
python -m verifuse_v2.db.fix_leads_schema

# Engine V2 (local parsing)
python -m verifuse_v2.scrapers.engine_v2 --dry-run
python -m verifuse_v2.scrapers.engine_v2

# Vertex AI enrichment
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run
python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 50

# Start API
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000

# Health check
curl http://localhost:8000/health
curl http://localhost:8000/api/leads?limit=5
curl http://localhost:8000/api/stats
```
