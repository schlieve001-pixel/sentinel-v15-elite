# VERIFUSE FORENSIC AUDIT — COMPLETE SYSTEM INTELLIGENCE REPORT

**Date:** February 16, 2026
**Analyst:** Claude Opus 4.6
**Scope:** Full codebase, all databases, environment, security, disk, deployment
**Classification:** INTERNAL — CONTAINS ARCHITECTURAL INTELLIGENCE

---

## TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [The Three Systems — What You Actually Have](#2-the-three-systems)
3. [Where Your Money Lives (Database Intelligence)](#3-database-intelligence)
4. [The Pipeline — How Data Flows (And Where It Breaks)](#4-the-pipeline)
5. [Lost Capabilities — What the Archive Has That V2 Doesn't](#5-lost-capabilities)
6. [New Capabilities — What V2 Built That the Archive Never Had](#6-new-capabilities)
7. [Environment & Venv Health](#7-environment-health)
8. [Security Posture](#8-security-posture)
9. [Disk & Infrastructure](#9-disk-infrastructure)
10. [The Optimal Architecture — Where Your Best Setup Lives](#10-optimal-architecture)
11. [Revolutionary Suggestions — Making This SOTA](#11-revolutionary-suggestions)
12. [Priority Fix List — Exact Commands](#12-priority-fix-list)

---

## 1. EXECUTIVE SUMMARY

You have **three separate systems** that each contain critical pieces of a complete surplus recovery platform. None of them is complete alone. The optimal setup is a **merge** — taking the best of each and unifying them into one production system.

### The Scorecard

| System | Data Collection | Data Quality | Legal Compliance | Attorney Tools | API/Frontend | Deployment |
|--------|----------------|-------------|------------------|----------------|-------------|------------|
| **Archive** | 9/10 | 3/10 | 0/10 | 0/10 | 0/10 | 0/10 |
| **Verifuse V1** | 8/10 | 9/10 | 9/10 | 10/10 | 0/10 | 0/10 |
| **Verifuse V2** | 6/10 | 7/10 | 5/10 | 3/10 | 8/10 | 6/10 |
| **Optimal Merge** | **10/10** | **10/10** | **10/10** | **10/10** | **10/10** | **10/10** |

### The Bottom Line

- **$8.2M in tracked surplus** across all databases (overlapping — real unique is ~$4.3M)
- **17 actionable leads** with surplus > $50K (the money-makers)
- **10 leads in attorney_view** ready for filing ($1.39M combined surplus)
- **95% of your leads table is noise** — 814 of 855 records have $0 surplus
- **Your API is currently DOWN** (crash loop — missing one env var)
- **5 critical capabilities are stranded in the archive**, not available in production
- **Your venv is 9.5 GB** because of PyTorch/NVIDIA — you don't need GPU libs on this server
- **3 exposed API keys** (Alpaca, Airtable, Google credentials) are world-readable

---

## 2. THE THREE SYSTEMS

### System A: The Archive (`_ARCHIVE_FEB_2026/`)
**What it is:** Your original surplus engine. The scrappy startup that actually collected the data.

**Unique strengths:**
- **7 Palm Beach County Selenium scrapers** — Florida market entry (84 verified leads)
- **5 Colorado Treasury scrapers** — state-held escheated funds nobody else touches
- **7-year historical backtest** (`verifuse_time_traveler.py`) — statute window analysis 2018-2026
- **Junior lien detection** (`verifuse_auto_parties.py`) — parses defendant lists for competing claims
- **Airtable sync** — 699 records in cloud backup
- **Douglas County month-only parser** — handles "Jun-24" dates
- **Fee cap progression logic** — Unregulated → 20% → 10% based on time since sale

**What it lacks:** No state machine, no validation, no attorney tools, no API, no deployment.

### System B: Verifuse V1 (`verifuse/`)
**What it is:** The enterprise-grade architecture. The legal machine.

**Unique strengths:**
- **4-tier pipeline state machine** — PIPELINE → QUALIFIED → ATTORNEY → CLOSED
- **BS Detector** — kills date-as-surplus, whale cap, negative surplus, ratio tests
- **Outcome Harvester** — post-sale PDF scraping for Jefferson, Arapahoe, Adams, Denver
- **3-page Word dossier generator** — editable, attorney-ready, with pre-written motions
- **CO Rule 7.3 compliant mail room** — batch solicitation letter generation
- **7-section case packets** — HTML → PDF evidence bundles
- **Scraper registry with gap tracking** — knows exactly what each county provides
- **Statute authority table** — seeded with C.R.S. citations for 16+ counties
- **Append-only audit log** — forensic pipeline_events table

**What it lacks:** No API, no frontend, no deployment, no Stripe billing.

### System C: Verifuse V2 (`verifuse_v2/`)
**What it is:** The production API. The deployed system (when it's running).

**Unique strengths:**
- **FastAPI with NULL-safe projections** — no Black Screen of Death
- **Double-gate unlock system** — C.R.S. § 38-38-111 compliant
- **Atomic credit deduction** — BEGIN IMMEDIATE transactions
- **React frontend deployed** at verifuse.tech via Caddy
- **Stripe billing integration** (code complete, keys not configured)
- **Vertex AI PDF extraction** (Gemini 2.0) — enterprise ghost prevention
- **Deterministic parser registry** — AdamsParser, DenverExcessParser, etc.
- **systemd services + timers** — automated scraper scheduling

**What it lacks:** Missing V1's attorney tools, missing archive's treasury/lien scrapers, table routing is broken (assets vs leads split-brain).

---

## 3. DATABASE INTELLIGENCE

### Three Databases, One Truth

| Database | Location | Leads | Surplus | Role |
|----------|----------|-------|---------|------|
| `verifuse_v2.db` | `verifuse_v2/data/` | 855 (leads) + 714 (assets) | ~$4.3M | **PRODUCTION** |
| `verifuse_vault.db` | `verifuse/data/` | 714 (assets via VIEW) | ~$4.3M | V1 mirror |
| `verifuse_vault.db` | `_ARCHIVE/data/` | 32 leads + 653 pipeline | ~$4.3M | Original |

The V1 and V2 `assets` tables are identical (714 rows). V2 added 855 rows in a separate `leads` table from Vertex AI extraction. **The data is fragmented across two tables.**

### The Big Fish (Your 17 Money-Makers)

| # | Owner | County | Surplus | Grade | Action Needed |
|---|-------|--------|---------|-------|---------------|
| 1 | THE WAVE INVESTMENT TEAM | Jefferson | $1,057,501 | BRONZE | Promote to GOLD |
| 2 | LOUISE THOMAS & RYAN L. THOMAS | Jefferson | $427,063 | BRONZE | Promote to GOLD |
| 3 | ROBERT V. KIRK | Arapahoe | $380,969 | GOLD | ATTORNEY READY |
| 4 | RALPH F. MALITO & CHERYL A. MALITO | Jefferson | $342,112 | BRONZE | Promote to GOLD |
| 5 | SUSAN SHORT | Arapahoe | $249,692 | GOLD | ATTORNEY READY |
| 6 | DAVID J. GOODMAN | Arapahoe | $249,589 | GOLD | ATTORNEY READY |
| 7 | Johanes Nakamoto & Teresa Nakamoto | Adams | $215,305 | GOLD | ATTORNEY READY |
| 8 | MIKE FEHRENBACHER | Denver | $157,121 | IRON | Needs enrichment |
| 9 | WALES, JAMES G. | Denver | $146,847 | REJECT | Review — may be recoverable |
| 10 | RAVI VAMSI PATCHIGOLLA et al. | Arapahoe | $124,799 | GOLD | ATTORNEY READY |
| 11 | BETH JO SONSE | Denver | $118,490 | IRON | Needs enrichment |
| 12 | BRADLEY BUCHOLZ & JOSELYN BUCHOLZ | Arapahoe | $107,923 | GOLD | ATTORNEY READY |
| 13 | JOHN L. MONAGHAN & HELEN E. PETERSEN | Arapahoe | $102,700 | GOLD | ATTORNEY READY |
| 14 | L. LEE LOEB | Denver | $68,412 | IRON | Needs enrichment |
| 15 | LINDA C. WILSON | Arapahoe | $59,282 | GOLD | ATTORNEY READY |
| 16 | JOHN A WHITE | Denver | $53,835 | GOLD | ATTORNEY READY |
| 17 | CHERI M. CRAWFORD | Arapahoe | $50,497 | GOLD | ATTORNEY READY |

**Combined value of top 17: $3.9M**
**Attorney-ready right now (GOLD): $1.39M across 10 leads**

### The Noise Problem

| Category | Count | % of Total | Surplus | Action |
|----------|-------|-----------|---------|--------|
| Eagle (debt-only portal scrapes) | 312 | 36% | $0 | DELETE or quarantine |
| San Miguel (debt-only portal scrapes) | 250 | 29% | $0 | DELETE or quarantine |
| El Paso (pre-sale, quarantined) | 114 | 13% | $0 | Already quarantined |
| Pipeline staging (no enrichment) | 567 | 66% | $0 | Need post-sale follow-up |
| **Actionable leads with surplus** | **41** | **4.8%** | **$4.3M** | **THESE ARE YOUR BUSINESS** |

**Recommendation:** Quarantine Eagle and San Miguel records. They're GovEase debt-only scrapes with zero financial data. They dilute your metrics and slow queries.

### Attorney View (Ready to File)

10 records currently in `attorney_view` — ALL Arapahoe county, ALL GOLD grade:

| Owner | Surplus | Days Until Deadline |
|-------|---------|-------------------|
| CHERI M. CRAWFORD | $50,497 | 954 days |
| ROBERT V. KIRK | $380,969 | 1,010 days |
| JOHN L. MONAGHAN et al. | $102,700 | 1,163 days |
| DANIEL P. POND | $34,333 | 1,331 days |
| DAVID J. GOODMAN | $249,589 | 1,450 days |
| RAVI VAMSI PATCHIGOLLA et al. | $124,799 | 1,478 days |
| BRADLEY BUCHOLZ et al. | $107,923 | 1,478 days |
| LINDA C. WILSON | $59,282 | 1,562 days |
| SUSAN SHORT | $249,692 | 1,765 days |
| BRIAN MAHLER | $27,641 | 1,765 days |

**$1,387,425 ready for attorney filing. Deadlines are 2.5-4.8 years out. No rush, but no reason to wait.**

### The Jefferson Problem

Your 3 biggest leads (THE WAVE $1.05M, THOMAS $427K, MALITO $342K) are all Jefferson County, all BRONZE grade. They're stuck because:
- Jefferson's site has reCAPTCHA blocking automated enrichment
- CSV import worked for surplus amounts but didn't fill all Tier 2 fields
- Missing fields: `recorder_link`, `lien_type`, `statute_window`

**Fix:** Manual enrichment. Pull the case numbers from the DB, look up recorder links on Jefferson's site, fill the missing fields, promote to GOLD. This unlocks $1.8M.

---

## 4. THE PIPELINE — WHERE IT BREAKS

### Current Data Flow

```
Raw Sources (PDFs, CSVs, Web)
    │
    ├──→ County Scrapers ──→ `assets` table ──→ (ORPHANED — API doesn't read this)
    │
    ├──→ Engine V2 ──→ `leads` table ──→ API reads this ──→ Frontend
    │
    └──→ Vertex AI ──→ `leads` table ──→ API reads this ──→ Frontend
                   └──→ `assets` table (production engine only)
```

### The Split-Brain Problem

**Root cause:** Two tables serve the same purpose but aren't synchronized.

| Component | Writes To | Reads From |
|-----------|-----------|------------|
| County scrapers (Adams, Denver, etc.) | `assets` | — |
| Engine V2 (deterministic parser) | `leads` | — |
| Vertex Production | `assets` | — |
| Vertex Enterprise | `leads` | — |
| `database.py` (shared module) | `assets` | `assets` |
| `api.py` (the actual API) | — | `leads` |
| `auth.py` | — | `users` via `database.py` |

**Impact:** 714 records in `assets` are invisible to the API. The API serves 855 records from `leads`. Some overlap, some don't.

### The Fix (Two Options)

**Option A (Quick):** Create `leads` as a VIEW over `assets`
```sql
DROP TABLE leads;  -- after backing up
CREATE VIEW leads AS SELECT
  asset_id AS id, county, case_number, owner_of_record AS owner_name,
  property_address, estimated_surplus, ...
FROM assets;
```

**Option B (Proper):** Consolidate everything into `leads` table, migrate all scrapers to write to `leads`, deprecate `assets`. This is what V2 was trying to do but didn't finish.

**Recommendation:** Option B. The `leads` table has the right schema for the API. Migrate the 714 `assets` records into `leads`, update scrapers to write to `leads`, and delete the `assets` table.

---

## 5. LOST CAPABILITIES — Critical Missing Pieces

### Tier 1: HIGH IMPACT (Get These Back)

#### 1. Colorado Treasury Scraping
**What:** Searches state treasury for escheated funds (3+ years old)
**Where:** `_ARCHIVE/verifuse_treasury_sniper.py`, `verifuse_time_traveler.py`
**Why it matters:** After 3 years, county surplus transfers to state treasury. 30% fee cap zone. Nobody else is scraping this systematically.
**Recovery effort:** Medium — port Selenium logic to new `verifuse_v2/scrapers/treasury_scraper.py`

#### 2. Statute Fee Cap Progression
**What:** Computes attorney fee caps based on time since sale
**Where:** `_ARCHIVE/verifuse_time_traveler.py`
```
0-6 months:  Unregulated (no statutory cap — data access fee only)
6mo-2 years: 20% (C.R.S. 38-38-111)
2+ years:    10% (RUUPA)
```
**Why it matters:** This is how attorneys price their services. Without it, you can't tell them what they'll earn.
**Recovery effort:** LOW — copy one function into `api.py`

#### 3. Junior Lien Detection
**What:** Parses defendant lists from case searches, flags banks/HOAs/IRS
**Where:** `_ARCHIVE/verifuse_auto_parties.py`
**Why it matters:** A $200K surplus with 3 junior liens is worth $0. Without lien detection, attorneys waste time on uncollectable cases.
**Recovery effort:** HIGH — requires Selenium + legal keyword database

#### 4. Douglas County Parser
**What:** Handles month-only dates ("Jun-24") from Douglas Treasurer
**Where:** `_ARCHIVE/force_import.py` → `parse_douglas_raw()`
**Why it matters:** $28K in Douglas surplus not being ingested
**Recovery effort:** LOW — copy regex into engine_v2

#### 5. Palm Beach County Scrapers
**What:** 7 Selenium variants for Florida foreclosure auctions
**Where:** `_ARCHIVE/surplus_engine_pbc/hunter_*.py`
**Why it matters:** Florida = 1-year statute (faster turnover). 84 leads already captured. Different market = diversification.
**Recovery effort:** Medium — port best variant to `verifuse_v2/scrapers/pbc_scraper.py`

### Tier 2: MEDIUM IMPACT

#### 6. Airtable Sync
**What:** Bi-directional sync to Airtable for attorney collaboration
**Where:** `_ARCHIVE/airtable_sync.py`
**Recovery effort:** Medium

#### 7. Source File Hashing (SHA-256)
**What:** Cryptographic provenance chain for every record
**Where:** `_ARCHIVE/force_import.py`
**Recovery effort:** LOW — add column + hashlib call

---

## 6. NEW CAPABILITIES — What V1/V2 Built That's Excellent

### From Verifuse V1 (NOT in V2 yet — must port)

| Capability | File | Value |
|-----------|------|-------|
| Pipeline state machine | `verifuse/core/pipeline.py` | Systematic lead qualification |
| BS Detector (date-as-surplus, whale cap) | `verifuse/scrapers/hunter_engine.py` | Prevents garbage data |
| 3-page Word dossier | `verifuse/attorney/dossier_generator.py` | Attorney work product |
| CO Rule 7.3 mail room | `verifuse/legal/mail_room.py` | Legal compliance |
| 7-section case packets | `verifuse/attorney/case_packet.py` | Evidence bundles |
| Outcome harvester (post-sale PDFs) | `verifuse/scrapers/outcome_harvester.py` | Data others miss |
| Scraper coverage registry | `verifuse/scrapers/registry.py` | Audit trail |

### From Verifuse V2 (Already in production)

| Capability | File | Value |
|-----------|------|-------|
| NULL-safe API projections | `server/api.py` | No frontend crashes |
| Double-gate unlock (C.R.S. compliance) | `server/api.py` | Legal protection |
| Atomic credit transactions | `server/api.py` | Billing integrity |
| Deterministic parser registry | `scrapers/registry.py` | Testable extraction |
| Vertex AI with ghost prevention | `scrapers/vertex_engine_enterprise.py` | Smart PDF parsing |
| React frontend + Caddy deployment | `deploy/` + `site/app/` | Live at verifuse.tech |
| systemd timers for automation | `deploy/*.timer` | Scheduled scraping |

---

## 7. ENVIRONMENT & VENV HEALTH

### Python Environment

| Property | Value | Status |
|----------|-------|--------|
| Python version | 3.11.2 | OK |
| Pip version | 26.0.1 | Current |
| Venv isolation | `system-site-packages = false` | Good |
| Venv size | **9.5 GB** | BLOATED |
| Package count | ~300+ | Excessive |
| Key imports (17 tested) | All pass | Healthy |
| Dependency conflicts | 5 groups | Manageable |

### What's Wrong With the Venv

**Problem 1: GPU libraries on a non-GPU server (9.5 GB → should be ~500 MB)**
```
PyTorch 2.9.1          (~2 GB)
NVIDIA CUDA runtime    (~3 GB)
NVIDIA cuDNN           (~1 GB)
torchvision            (~500 MB)
torchaudio             (~300 MB)
onnxruntime            (~300 MB)
```
You're running on a GCP VM with no GPU. These libraries do nothing but waste disk.

**Problem 2: Trading libraries mixed with production**
```
vectorbt, alpaca-trade-api, stable-baselines3, xgboost, streamlit
```
These are for renaissance_lab (trading research). They don't belong in the production API venv.

**Problem 3: pandas 3.0 breaks dependencies**
```
streamlit requires pandas<3   → has 3.0.0 (BROKEN)
vectorbt requires pandas<3.0  → has 3.0.0 (BROKEN)
```

**Problem 4: 8 orphaned venvs consuming disk**
```
/home/schlieve001/verifuse-validation/venv/
/home/schlieve001/archives/vf_ai_lab_OLD/.venv/
/home/schlieve001/verifuse_full_audit/sentinel_mk7/venv/
/home/schlieve001/verifuse_env/
/home/schlieve001/origin/.venv/
/home/schlieve001/origin/verifuse_surplus_engine/venv/
/home/schlieve001/verifuse-rti-stack/.venv/
```

### How to Fix the Venv

**Option A: Clean rebuild (recommended)**
```bash
# 1. Export what you actually need
pip freeze | grep -v nvidia | grep -v torch | grep -v cuda > /tmp/prod_requirements.txt

# 2. Create a clean production venv
python3.11 -m venv ~/verifuse_prod_venv

# 3. Install only production deps
~/verifuse_prod_venv/bin/pip install -r verifuse_v2/requirements.txt

# 4. Update systemd to use new venv
# ExecStart=~/verifuse_prod_venv/bin/python -m uvicorn ...
```

**Option B: Remove GPU packages from existing venv**
```bash
pip uninstall torch torchvision torchaudio nvidia-cuda-runtime-cu12 \
  nvidia-cudnn-cu12 nvidia-cublas-cu12 onnxruntime-gpu \
  stable-baselines3 vectorbt alpaca-trade-api streamlit xgboost -y
```

**Estimated savings:** 8-9 GB disk space.

---

## 8. SECURITY POSTURE

### Critical Issues

| # | Issue | Risk | Location | Fix |
|---|-------|------|----------|-----|
| 1 | **JWT secret is placeholder** | CRITICAL | systemd service | Generate real secret |
| 2 | **API service is DOWN** (crash loop) | CRITICAL | missing `VERIFUSE_DB_PATH` | Add env var |
| 3 | **Alpaca API key exposed** | HIGH | `_ARCHIVE/.env` (world-readable) | `chmod 600` or delete |
| 4 | **Airtable PAT exposed** | HIGH | `verifuse/.env` (world-readable) | `chmod 600` or delete |
| 5 | **Google credentials world-readable** | HIGH | `verifuse_v2/google_credentials.json` | `chmod 600` |
| 6 | **SQLite DBs world-readable** | MEDIUM | Both `.db` files | `chmod 600` |
| 7 | **Dev IP in CORS whitelist** | LOW | `api.py` line 270 | Remove `34.69.230.82` |
| 8 | **JWT in localStorage** | MEDIUM | `auth.tsx` | Move to httpOnly cookie |

### What's Already Good

- SSH: key-only auth, root login disabled, fail2ban active
- Git: `.gitignore` comprehensive, no secrets tracked
- Caddy: HSTS, X-Frame-Options DENY, auto-TLS
- Python source: zero hardcoded secrets (they're in env vars)
- Rate limiting: 5/min register, 10/min login, 10/min unlock
- PII protection: SafeAsset projection strips addresses until unlock

### Immediate Security Fixes

```bash
# 1. Generate real JWT secret
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
echo "New JWT secret: $JWT_SECRET"

# 2. Fix file permissions
chmod 600 /home/schlieve001/origin/continuity_lab/verifuse_v2/google_credentials.json
chmod 600 /home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
chmod 600 /home/schlieve001/origin/continuity_lab/verifuse/data/verifuse_vault.db
chmod 600 /home/schlieve001/origin/continuity_lab/verifuse/.env
chmod 600 /home/schlieve001/origin/continuity_lab/_ARCHIVE_FEB_2026/.env

# 3. Fix systemd service (requires sudo)
# Add to [Service] section:
#   Environment="VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db"
#   Environment="VERIFUSE_JWT_SECRET=<the-secret-from-step-1>"

# 4. Reload and restart
# sudo systemctl daemon-reload
# sudo systemctl restart verifuse-api
```

---

## 9. DISK & INFRASTRUCTURE

### Disk Usage

```
/dev/sda1: 197 GB total, 122 GB used (65%), 68 GB free

/home/schlieve001/origin/continuity_lab/ breakdown:
  9.5 GB  .venv/           (BLOATED — GPU libs)
  1.5 GB  _ARCHIVE_FEB_2026/  (dead weight, already in git history)
  649 MB  renaissance_lab/  (trading data CSVs)
  165 MB  verifuse/        (V1 system)
  7.7 MB  verifuse_v2/     (production system — lean!)
```

### What to Clean

| Item | Size | Action | Savings |
|------|------|--------|---------|
| GPU packages in .venv | ~8 GB | Uninstall or rebuild venv | 8 GB |
| 8 orphaned venvs | ~5-15 GB (est.) | Delete | 5-15 GB |
| `_ARCHIVE/archives/*.zip` | 554 MB | Already in git — delete | 554 MB |
| `_ARCHIVE/ngrok-v3-stable-linux-amd64.tgz` | 11 MB | Delete | 11 MB |
| `_ARCHIVE/cloudflared.deb` | 20 MB | Delete | 20 MB |
| `renaissance_lab/tape/history_sota*.csv` (dupes) | ~300 MB | Keep only latest | 300 MB |
| **Total recoverable** | | | **~15-25 GB** |

### System Resources

| Resource | Value | Status |
|----------|-------|--------|
| RAM | 20 GB total, 15 GB available | Healthy |
| CPUs | 4 cores | Healthy |
| Load average | 0.96 (under core count) | Healthy |
| Swap | 4 GB (0% used) | Excellent |
| Disk | 65% used | Monitor (clean venvs to improve) |

### Unknown Ports

| Port | Binding | Concern |
|------|---------|---------|
| 8080 | 0.0.0.0 (external) | Node process — what is this? |
| 20201 | external | Unknown process |
| 20202 | 0.0.0.0 (external) | Unknown process |

**Recommendation:** Investigate ports 8080, 20201, 20202. If not needed, close them.

---

## 10. THE OPTIMAL ARCHITECTURE — Your Best Setup

### The Merge Strategy

The best system is **Verifuse V2 as the chassis** with V1's attorney tools and the archive's scraper intelligence bolted on.

```
OPTIMAL ARCHITECTURE:
═══════════════════════════════════════════════════════════════

                    ┌──────────────────────┐
                    │   verifuse.tech      │
                    │   (Caddy + TLS)      │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐  ┌─────▼──────┐  ┌──────▼─────────┐
    │ React Frontend │  │ FastAPI    │  │ Stripe         │
    │ (Vite/TS)      │  │ (V2 API)  │  │ Webhooks       │
    └────────────────┘  └─────┬──────┘  └────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼─────────┐
    │ Attorney Tools │ │ Lead       │ │ Credit System  │
    │ (FROM V1)      │ │ Pipeline   │ │ (V2)           │
    │ - Dossier Gen  │ │ (FROM V1)  │ │ - Unlock gate  │
    │ - Mail Room    │ │ - BS Detect│ │ - Atomic txns  │
    │ - Case Packets │ │ - State MC │ │ - Audit trail  │
    │ - Motion Gen   │ │ - Scoring  │ │                │
    └────────────────┘ └─────┬──────┘ └────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼──────┐  ┌────────▼──────┐  ┌─────────▼─────┐
│ County        │  │ AI Engines   │  │ Treasury +    │
│ Scrapers (V2) │  │ (V2)         │  │ PBC (ARCHIVE) │
│ - Adams       │  │ - Engine V2  │  │ - Treasury    │
│ - Denver      │  │ - Vertex AI  │  │ - Palm Beach  │
│ - Jefferson   │  │ - Registry   │  │ - Lien Detect │
│ - Boulder     │  │              │  │ - Time Travel │
│ - El Paso     │  │              │  │               │
│ - Larimer     │  │              │  │               │
│ - Weld        │  │              │  │               │
│ - Pueblo      │  │              │  │               │
└───────────────┘  └──────────────┘  └───────────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                    ┌────────▼────────┐
                    │  UNIFIED DB     │
                    │  `leads` table  │
                    │  (ONE table)    │
                    │  + pipeline_events │
                    │  + statute_authority │
                    │  + attorney_view │
                    └─────────────────┘
```

### What Moves Where

| Component | Source | Destination | Action |
|-----------|--------|-------------|--------|
| Pipeline state machine | `verifuse/core/pipeline.py` | `verifuse_v2/core/pipeline.py` | Port |
| BS Detector | `verifuse/scrapers/hunter_engine.py` | `verifuse_v2/scrapers/validator.py` | Port |
| Dossier generator | `verifuse/attorney/dossier_generator.py` | `verifuse_v2/server/dossier_gen.py` | Replace stub |
| Mail room | `verifuse/legal/mail_room.py` | `verifuse_v2/legal/mail_room.py` | Port |
| Case packets | `verifuse/attorney/case_packet.py` | `verifuse_v2/attorney/case_packet.py` | Port |
| Treasury scraper | `_ARCHIVE/verifuse_treasury_sniper.py` | `verifuse_v2/scrapers/treasury_scraper.py` | Port |
| PBC scrapers | `_ARCHIVE/surplus_engine_pbc/` | `verifuse_v2/scrapers/pbc_scraper.py` | Port best variant |
| Fee cap logic | `_ARCHIVE/verifuse_time_traveler.py` | `verifuse_v2/server/api.py` | Copy function |
| Lien detection | `_ARCHIVE/verifuse_auto_parties.py` | `verifuse_v2/legal/lien_analyzer.py` | Port |
| Douglas parser | `_ARCHIVE/force_import.py` | `verifuse_v2/scrapers/registry.py` | Add parser |

---

## 11. REVOLUTIONARY SUGGESTIONS — Making This SOTA

### Insight 1: You're Sitting on a Legal Intelligence Moat

Nobody else has:
- **Deterministic PDF parsers** for 8 Colorado counties
- **Vertex AI extraction** with ghost prevention
- **Statute window computation** with fee cap progression
- **Junior lien detection** from case party analysis
- **Treasury scraping** for escheated funds

This isn't a SaaS app. This is a **legal intelligence platform**. The value isn't the software — it's the **data pipeline** that no one else has built.

### Insight 2: Your Pricing Is Wrong

Current: $199/$399/$699 per month for 5/25/100 credits.

The math: 10 GOLD leads in attorney_view = $1.39M combined surplus. At 20% contingency (C.R.S. fee cap), that's $278K in attorney fees. You're charging $699/month for access to $278K in fees.

**Suggestion:** Per-lead pricing, not subscription:
- ACTIONABLE lead unlock: $99 (owner name + address + case details)
- RESTRICTED lead unlock (attorney only): $249 (full dossier + motion template)
- Dossier generation: $49 per lead
- Batch mail room: $29 per letter

At $249 per RESTRICTED unlock, your 10 attorney-ready leads = $2,490 revenue. An attorney recovering $380K from Robert V. Kirk at 20% contingency ($76K fee) will happily pay $249 for the lead.

### Insight 3: The Real Product Is the Dossier

Attorneys don't want a dashboard. They want:
1. A name and address (who to contact)
2. A case number and surplus amount (what to file for)
3. A pre-written motion (what to file)
4. Proof that no competing liens exist (risk assessment)
5. A compliance letter to send (Rule 7.3)

You have ALL of these across your three systems. The V1 dossier generator + mail room + case packet is the actual product. The V2 API is just the delivery mechanism.

### Insight 4: Treasury Scraping Is Your Unfair Advantage

After 3 years, surplus funds transfer from county to state treasury. Most people stop looking. Your `verifuse_time_traveler.py` goes back to 2018 — that's 8 years of unclaimed funds that nobody is systematically recovering.

The fee cap drops to 10% for treasury claims, but the volume is enormous. Colorado's state treasury holds **millions** in unclaimed foreclosure surplus.

### Insight 5: Automate the Jefferson Bottleneck

Your 3 biggest leads ($1.8M combined) are stuck at BRONZE because Jefferson has reCAPTCHA. But you already have the CSV import path working. The fix:

1. Manual browser session → download CSV monthly
2. `force_import.py` ingests it
3. Engine V2 enriches with deterministic parser
4. Pipeline promotes to GOLD
5. Attorney gets notified

This is a 10-minute manual task per month that unlocks $1.8M in pipeline. Automate the rest, accept the manual download.

### Insight 6: Pre-Sale Counties Are a Gold Mine Waiting

Boulder, El Paso, Larimer, Weld have 400+ pre-sale leads with $0 surplus. After the auction, some of these WILL have surplus. The outcome harvester from V1 was designed exactly for this — follow up after the sale, capture the overbid.

Right now, these leads sit in PIPELINE_STAGING forever. With the outcome harvester on a timer, they'd auto-promote when surplus appears.

### Insight 7: The Florida Market Is Different

Palm Beach = 1-year statute (vs 5-year Colorado). This means:
- Faster turnover (leads expire quickly, but new ones appear constantly)
- Less competition (shorter window = fewer people bothering)
- Higher urgency premium (attorneys pay more for time-sensitive leads)

Your 84 PBC leads from the archive prove the scrapers work. Reactivating them is a new market at near-zero marginal cost.

### Insight 8: Build the Attorney API

Instead of attorneys using your web dashboard, give them an API:
```
GET /api/v1/leads?county=Arapahoe&grade=GOLD&min_surplus=50000
POST /api/v1/dossier/{lead_id}  → returns .docx
POST /api/v1/motion/{lead_id}   → returns pre-filled motion
POST /api/v1/letter/{lead_id}   → returns Rule 7.3 letter
```

Charge per API call. Let attorney firms integrate into their own case management systems. This is the B2B play.

---

## 12. PRIORITY FIX LIST — Exact Steps

### IMMEDIATE (Do Now — Get the API Running)

```bash
# Step 1: Fix the systemd service
sudo tee /etc/systemd/system/verifuse-api.service.d/override.conf << 'EOF'
[Service]
Environment="VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db"
Environment="VERIFUSE_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
EOF

sudo systemctl daemon-reload
sudo systemctl restart verifuse-api

# Step 2: Verify
curl -s http://localhost:8000/health | python3 -m json.tool
```

### TODAY (Security Hardening)

```bash
# Fix file permissions
chmod 600 ~/origin/continuity_lab/verifuse_v2/google_credentials.json
chmod 600 ~/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
chmod 600 ~/origin/continuity_lab/verifuse/data/verifuse_vault.db
chmod 600 ~/origin/continuity_lab/verifuse/.env
chmod 600 ~/origin/continuity_lab/_ARCHIVE_FEB_2026/.env

# Investigate unknown ports
ss -tlnp | grep -E "8080|20201|20202"
```

### THIS WEEK (Data Cleanup)

1. Quarantine Eagle (312) and San Miguel (250) zero-value records
2. Manually enrich Jefferson top 3 leads ($1.8M) → promote to GOLD
3. Review Denver REJECT leads (WALES $146K) — may be recoverable
4. Run quarantine.py to clean ghost data
5. Port fee cap function from archive to API

### THIS SPRINT (Capability Merge)

1. Port V1 dossier generator → replace V2 text stub with real DOCX output
2. Port V1 pipeline state machine → add to V2 ingestion pipeline
3. Port V1 BS Detector → add to V2 engine_v2 post-processing
4. Port archive treasury scraper → new V2 scraper + timer
5. Clean venv (remove GPU/trading packages, save ~8 GB)
6. Delete orphaned venvs (save ~5-15 GB)

### THIS MONTH (Production Launch)

1. Configure Stripe (real keys, real products)
2. Rebuild frontend with production env vars
3. Install all systemd timers
4. Port outcome harvester → set up post-sale follow-up automation
5. Add monitoring (healthcheck alerts, disk space alerts)
6. Test full flow: register → login → browse → unlock → dossier download

---

## FINAL ASSESSMENT

**Your best setup is Verifuse V2 as the production chassis, enhanced with V1's attorney intelligence and the archive's scraper reach.** The code quality across all three systems is genuinely strong — the V1 state machine is enterprise-grade, the V2 API is production-ready, and the archive scrapers have real domain expertise embedded in them.

The gap isn't code quality — it's **integration**. Three excellent systems that don't talk to each other. The table split-brain (`assets` vs `leads`) is the #1 technical debt. Fix that, merge the capabilities, and you have something nobody else has: a **full-stack legal intelligence platform** that goes from raw county PDF → attorney-ready motion in a single pipeline.

You're closer than you think. The $1.39M in attorney-ready leads is real money. The $1.8M in Jefferson BRONZE leads is one manual enrichment session away from being real money. The treasury scraper opens up a market nobody is serving.

**Make the merge. Fix the table routing. Get the API running. Ship.**

---

*Report generated by Claude Opus 4.6 — February 16, 2026*
*All file paths, code snippets, and data values sourced directly from the live codebase.*
