# VERIFUSE V2 — TITANIUM OPERATIONS PLAN
## Last Updated: February 15, 2026 (Sprint 9 — Master Builder)

---

## SYSTEM STATUS: TITANIUM v4.2

| Metric | Value |
|--------|-------|
| Total Leads | ~855 (post-quarantine) |
| Quarantined | ~114 ghost leads |
| GOLD Grade | 80+ |
| Total Pipeline Value | $4,995,735+ |
| Counties | 10 active (Jefferson, Arapahoe, Denver, Adams, Teller, Douglas, Mesa, Eagle, San Miguel, Summit) |
| Database | SQLite WAL at `VERIFUSE_DB_PATH` |
| API Version | Titanium v4.2 (leads-native, legal-hardened) |
| Frontend | Vite + React + TypeScript at `:4173` |
| Backend | FastAPI + Uvicorn at `:8000` |
| Auth | JWT HS256 (72h) + API key for admin endpoints |
| Deploy | Blue/green atomic symlink at `~/verifuse_titanium_prod/` |

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
│  PDF Downloader          │  verifuse_v2/jobs/pdf_downloader.py
│  (counties.yaml config)  │  Scrapes 10 county sites for PDFs
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  PDF Classifier          │  classify_pdf() in vertex_engine_enterprise.py
│  DENY/ALLOW/UNKNOWN      │  Blocks continuance/postponement PDFs
└────────────┬────────────┘
             │ ALLOW + UNKNOWN only
             ▼
┌─────────────────────────┐
│  Vertex AI Enterprise    │  Gemini 2.0 Flash extraction
│  Safe Upsert (no $0      │  Never overwrites existing data with $0/NULL
│   overwrites)            │  $0 surplus new leads → quarantine
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  leads table (~855)      │  Canonical data store
│  leads_quarantine (~114) │  Ghost leads segregated
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  API v4.2 (api.py)       │
│  FastAPI + JWT + CORS     │
│  6-month legal engine     │
│  Rate limiting (slowapi)  │
│  :8000                   │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Frontend (Vite/React)   │
│  :4173 (dev)             │
│  verifuse.tech (prod)    │
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
| claim_deadline | TEXT | Computed | `sale_date + 6 calendar months` (C.R.S. 38-38-111) |
| data_grade | TEXT | Computed | GOLD / SILVER / BRONZE / IRON / REJECT |
| source_name | TEXT | Engine | Which engine produced this lead |
| vertex_processed | INTEGER | Flag | 0/1 has Vertex AI touched this |
| updated_at | TEXT | Auto | ISO timestamp |
| source_link | TEXT | Provenance | URL of source document |
| evidence_file | TEXT | Provenance | Path to evidence file |
| pdf_filename | TEXT | Provenance | Source PDF filename |
| vertex_processed_at | TEXT | Provenance | ISO timestamp of Vertex extraction |
| extraction_notes | TEXT | Provenance | Freeform notes from extraction |

### 1.4 Access Control (Legal Gate System)

```
                    ┌──────────────┐
                    │  Sale Date   │
                    └──────┬───────┘
                           │
               ┌───────────┼───────────┐
               │           │           │
          < 6 months   >= 6 months  Past deadline
          (calendar)   (calendar)
               │           │           │
          RESTRICTED   ACTIONABLE   EXPIRED
               │           │           │
     attorney + tier    any paid     LOCKED
     (OPERATOR/SOV)      user       (cannot unlock)
```

**CRITICAL LEGAL NOTE:** C.R.S. § 38-38-111 specifies SIX CALENDAR MONTHS (not 180 days). We use `dateutil.relativedelta(months=6)` for legally precise arithmetic. Violation is a Class 2 Misdemeanor.

- Status is computed at **runtime** from UTC dates. NEVER stored in DB.
- **SafeAsset** (no PII) is the default projection.
- **FullAsset** (with PII) only after unlock + credit deduction.
- Credit deduction is **atomic**: `BEGIN IMMEDIATE` transaction prevents race conditions.

---

## 2. FRONTEND-BACKEND CONTRACT

### 2.1 API Endpoints (Complete)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | System health + scoreboard + WAL status |
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
| `GET` | `/api/admin/leads` | API Key | Raw lead data (admin) |
| `GET` | `/api/admin/quarantine` | API Key | Quarantined leads (admin) |
| `GET` | `/api/admin/users` | API Key | All users (admin) |

### 2.2 Legal Disclaimers

All responses include legal context:

- **Health endpoint**: `legal_disclaimer` field
- **Unlock restricted**: Requires `disclaimer_accepted: true` in body
- **UNLOCK_DISCLAIMER**: "I certify I am a licensed legal professional and understand C.R.S. § 38-38-111 restrictions on inducing compensation agreements during the six calendar month holding period."

### 2.3 Auth Token Flow

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

## 3. PRODUCTION FILES

### 3.1 Schema & Migrations

| File | Purpose |
|------|---------|
| `db/fix_leads_schema.py` | Adds columns to `leads` table. **REFUSES** VIEW→TABLE auto-conversion (anti-wipe safety). Manual only. |
| `db/quarantine.py` | Moves ghost leads to `leads_quarantine`, demotes Jefferson false-GOLDs |
| `db/database.py` | DAL + WAL checkpoint utility |
| `db/schema.sql` | Full DDL for all tables including `leads_quarantine` |

### 3.2 Engines & Pipeline

| File | Purpose |
|------|---------|
| `scrapers/vertex_engine_enterprise.py` | PDF Classification Gate + Gemini 2.0 Flash extraction + Safe Upsert + Quarantine routing |
| `scrapers/engine_v2.py` | Local PDF parsing via parser registry |
| `scrapers/registry.py` | ABC `CountyParser` with `detect()`, `extract()`, `score()` |
| `jobs/orchestrator.py` | Full pipeline: Download → Classify → Extract → Upsert |
| `jobs/pdf_downloader.py` | Scrapes county websites for new PDFs |
| `config/counties.yaml` | County configuration (URLs, patterns, intervals) |

### 3.3 API Server

| File | Purpose |
|------|---------|
| `server/api.py` | FastAPI — all endpoints, 6-month legal engine, safe JSON parsing, admin API key |
| `server/auth.py` | JWT auth (HS256, 72h), bcrypt, register/login |
| `server/billing.py` | Stripe integration — checkout, webhooks, credit reset |

### 3.4 Operations

| File | Purpose |
|------|---------|
| `ops/create_superuser.py` | Upserts master admin account (idempotent) |
| `deploy/deploy.sh` | Atomic blue/green deploy with symlink swap |
| `deploy/verifuse-api.service` | systemd API server |
| `deploy/verifuse-orchestrator.service` | systemd orchestrator (one-shot) |
| `deploy/verifuse-orchestrator.timer` | Daily 06:00 UTC trigger |

---

## 4. HOW TO RUN THE SYSTEM

### 4.1 Environment Setup

```bash
# Required
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json
export VERIFUSE_JWT_SECRET=<your-secret>

# Admin endpoints
export VERIFUSE_API_KEY=<your-api-key>

# Optional (Stripe billing — sandbox mode)
export STRIPE_SECRET_KEY=sk_test_...
export STRIPE_WEBHOOK_SECRET=whsec_...

# Install dependencies
pip install -r verifuse_v2/requirements.txt
```

### 4.2 Schema Setup (idempotent, manual only)

```bash
python -m verifuse_v2.db.fix_leads_schema
```

**WARNING:** Never run migrations at boot time. Migrations are manual-only to prevent data wipes.

### 4.3 Create Superuser

```bash
python -m verifuse_v2.ops.create_superuser
```

Creates/updates: `verifuse.tech@gmail.com` with sovereign tier, 999999 credits, admin=YES, attorney=VERIFIED.

### 4.4 Run the Full Pipeline

```bash
# Full pipeline (download + classify + extract)
python -m verifuse_v2.jobs.orchestrator

# Skip download (just extract existing PDFs)
python -m verifuse_v2.jobs.orchestrator --skip-download

# Dry run (no Vertex calls)
python -m verifuse_v2.jobs.orchestrator --dry-run

# Single county
python -m verifuse_v2.jobs.orchestrator --county Denver --limit 20
```

### 4.5 Run Individual Components

```bash
# Download PDFs only
python -m verifuse_v2.jobs.pdf_downloader
python -m verifuse_v2.jobs.pdf_downloader --county Denver

# Vertex extraction only
python -m verifuse_v2.scrapers.vertex_engine_enterprise --dry-run
python -m verifuse_v2.scrapers.vertex_engine_enterprise --limit 50

# Engine V2 (local parsing)
python -m verifuse_v2.scrapers.engine_v2
```

### 4.6 Start API Server

```bash
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### 4.7 Quarantine Ghost Leads

```bash
python -m verifuse_v2.db.quarantine
```

### 4.8 Deploy to Production

```bash
bash verifuse_v2/deploy/deploy.sh
```

Creates `~/verifuse_titanium_prod/` with atomic symlink swap, WAL checkpoint, and service restart.

### 4.9 Health Check

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/leads?limit=5
```

---

## 5. SAFETY SYSTEMS

### 5.1 Anti-Wipe Protections

| Protection | Description |
|-----------|-------------|
| No boot-time migrations | API startup only logs DB identity (inode + SHA256), never mutates |
| VIEW→TABLE refused | `fix_leads_schema.py` refuses auto-conversion, requires manual intervention |
| Safe upsert | Vertex engine never overwrites existing data with $0.00 or NULL |
| WAL checkpoint | Always checkpoint before DB copy/move operations |
| DB identity logging | Every boot logs path, inode, SHA256 to prove all components share one DB |

### 5.2 Ghost Lead Prevention

| Gate | Description |
|------|-------------|
| PDF Classification | DENY list blocks continuance/postponement/docket PDFs before Vertex |
| Zero-surplus quarantine | New leads with $0 surplus → `leads_quarantine` (not `leads`) |
| Safe upsert | Existing leads never downgraded to $0 |

### 5.3 Legal Compliance

| Statute | Requirement | Implementation |
|---------|------------|----------------|
| C.R.S. § 38-38-111 | 6 calendar month holding period | `relativedelta(months=6)` — NOT 180 days |
| C.R.S. § 38-38-111 | No inducing compensation during restriction | Double Gate: attorney + OPERATOR/SOVEREIGN |
| C.R.S. § 38-13-1304 | 2-year lockout after State transfer | Tracked via `claim_deadline` |

---

## 6. SPRINT HISTORY

### Sprint 1 (Feb 10-11): Foundation
- 7 county scrapers, unified `assets` table (734 records), FastAPI + JWT + Stripe

### Sprint 2 (Feb 12): Engine #4
- Vertex AI engine, staging promoter, systemd timer

### Sprint 3 (Feb 13): Infrastructure
- Port conflict fix, systemd timers, DNS guide

### Sprint 4 (Feb 14): Titanium Architecture
- Titanium schema, Pydantic models, rate limiting, 4 new scrapers

### Sprint 5 (Feb 15a): Schema Unification
- `leads` VIEW → TABLE, Enterprise engine, API rewrite to leads-native

### Sprint 6 (Feb 15b): Titanium Registry
- Parser registry (ABC), Engine V2, 40 records extracted, confidence function C

### Sprint 7 (Feb 15c): Frontend Contract
- Gemini 2.0 fix, frontend Lead interface, dossier/billing/restricted endpoints

### Sprint 8 (Feb 15d): Phase 2 Hardening
- Atomic deploy, quarantine engine (114 ghosts), provenance columns
- API key middleware, Titanium Scoreboard health endpoint, WAL utilities
- Hardened systemd services, admin endpoints

### Sprint 9 (Feb 15e): Master Builder
- **A) Anti-Wipe:** Removed boot-time migration, DB identity logging (inode+SHA256), VIEW→TABLE conversion locked
- **B) Vertex Gating:** PDF classifier (DENY/ALLOW/UNKNOWN), safe upsert (never overwrite with $0), quarantine routing for $0 new leads, 6-month claim deadline fix
- **C) Legal Engine:** `relativedelta(months=6)` for C.R.S. § 38-38-111, LEGAL_DISCLAIMER + UNLOCK_DISCLAIMER constants, bad JSON returns 400 not 500
- **D) Master Login:** `ops/create_superuser.py` — sovereign tier, 999999 credits, admin, attorney VERIFIED
- **E) Full Automation:** `jobs/orchestrator.py` (download→classify→extract), `jobs/pdf_downloader.py`, `config/counties.yaml` (10 counties), systemd timer (daily 06:00 UTC)
- **Smoke tests:** 23/23 passed (TIT-021)

---

## 7. QUICK REFERENCE

```bash
# Environment
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
export GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/google_credentials.json

# Setup
python -m verifuse_v2.db.fix_leads_schema      # Schema (manual only)
python -m verifuse_v2.ops.create_superuser      # Admin account

# Run pipeline
python -m verifuse_v2.jobs.orchestrator         # Full pipeline
python -m verifuse_v2.jobs.orchestrator --dry-run  # Preview

# Start server
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000

# Health
curl http://localhost:8000/health
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/leads?limit=5

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"verifuse.tech@gmail.com","password":"#Roxies1badgirl"}'
```
