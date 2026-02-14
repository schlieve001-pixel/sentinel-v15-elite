# VERIFUSE V2 — TITANIUM OPERATIONS PLAN
## Last Updated: February 14, 2026 (Sprint 4 — Titanium Architecture Lock)

---

## SYSTEM STATUS: TITANIUM (11 Counties, 10 Engines, 734 Assets, $5.19M Pipeline)

### Architecture Invariants (Non-Negotiable)
| # | Invariant | Implementation |
|---|-----------|----------------|
| 1 | Dynamic Status | `RESTRICTED/ACTIONABLE/EXPIRED` computed at runtime from UTC dates. NEVER stored. |
| 2 | Hybrid Access Gate | RESTRICTED (0-6mo) → Verified attorneys only. ACTIONABLE (>6mo) → Any paid user. EXPIRED → Locked. |
| 3 | Projection Redaction | `SafeAsset` (no PII) by default. `FullAsset` only with valid `lead_unlocks` record. |
| 4 | Atomic Transactions | Credit deduction + unlock in single `BEGIN IMMEDIATE` transaction. |
| 5 | Strict CORS | Only `verifuse.tech`, `www.verifuse.tech`, `localhost:3000`, `localhost:5173`. |

### Database Summary
| Metric | Value |
|--------|-------|
| Total Assets | 734 |
| Total Pipeline Value | $5,195,573.68 |
| GOLD-Grade Leads | 6 |
| SILVER-Grade Leads | 7 |
| BRONZE-Grade Leads | 692 |
| Assets with claim_deadline | 103 |
| Assets with surplus_amount | 41 |
| Lead Unlocks (migrated) | 4 |
| Counties Active | 11 |
| Staging Records | 691 |
| GCP Project | canvas-sum-481614-f6 |
| API Server | FastAPI Titanium v3.0.0 on :8000 |
| Frontend | React 19 + Vite 7 (255KB JS, 16KB CSS) |
| Domain | verifuse.tech (DNS PENDING — see below) |
| VM IP | 34.69.230.82 (GCP) |

### County Breakdown
| County | Assets | Surplus | Status | Data Source | Engine |
|--------|--------|---------|--------|-------------|--------|
| Eagle | 312 | $0 (needs PDFs) | BRONZE | Portal scraper | Staging |
| San Miguel | 250 | $0 (needs PDFs) | BRONZE | Portal scraper | Staging |
| Jefferson | 66 | $2,026,675 | SILVER | CSV + portal | Manual + Staging |
| Adams | 39 | $258,106 | GOLD/SILVER | Weekly Post Sale PDF | #6 |
| Teller | 26 | $18,246 | BRONZE | GovEase portal | Staging |
| Denver | 17 | $1,421,452 | GOLD/SILVER | Monthly excess funds PDF | #1-3 |
| Arapahoe | 12 | $1,426,297 | GOLD | Overbid list | Manual |
| El Paso | 5 | $0 (pre-sale) | BRONZE | Weekly Pre Sale PDF | #5 |
| Summit | 5 | $0 (needs enrichment) | BRONZE | GovEase portal | Staging |
| Douglas | 1 | $4,798 | SILVER | Manual | Manual |
| Mesa | 1 | $40,000 | SILVER | Manual | Manual |

---

## CRITICAL: DNS SETUP (MUST DO FIRST)

The domain `verifuse.tech` is registered on **Porkbun** but nameservers currently point to **Netlify's NS** (dns1-4.p05.nsone.net) with **NO A record configured**.

### Fix DNS via Porkbun (Recommended)
1. Log into https://porkbun.com → Domain Management → `verifuse.tech`
2. Change nameservers back to Porkbun defaults
3. Add DNS records:

| Type | Host | Answer | TTL |
|------|------|--------|-----|
| A | *(blank/root)* | `34.69.230.82` | 600 |
| A | `www` | `34.69.230.82` | 600 |

### After DNS is configured:
```bash
dig verifuse.tech A +short    # Should return: 34.69.230.82
sudo systemctl restart caddy   # Get fresh TLS certs
curl -I https://verifuse.tech/health
```

---

## TITANIUM SCHEMA (5 Production Files)

### File 1: `verifuse_v2/db/schema.sql`
- 13 tables with `PRAGMA foreign_keys = ON`
- `lead_unlocks` table: `UNIQUE(user_id, lead_id)`, FK to users + assets
- `users.attorney_status` CHECK constraint: `NONE/PENDING/VERIFIED/REJECTED`
- V2 financial columns: `winning_bid`, `total_debt`, `surplus_amount`, `claim_deadline`
- Compound indexes on lead_unlocks, sale_date, claim_deadline

### File 2: `verifuse_v2/db/migrate_titanium.py`
- Idempotent migration — safe to run multiple times
- Adds columns WITHOUT mutating existing data
- Backfills: `claim_deadline` (103 rows), `surplus_amount` (41 rows), `total_debt` (14 rows)
- Migrates legacy `unlocks` → `lead_unlocks` table

### File 3: `verifuse_v2/server/models.py`
- `Lead` model: `@computed_field status` — RESTRICTED/ACTIONABLE/EXPIRED from UTC dates
- `SafeAsset`: County, city hint, case number, status, rounded surplus. NO owner name, NO street.
- `FullAsset(SafeAsset)`: Adds owner_name, property_address, winning_bid, total_debt

### File 4: `verifuse_v2/server/api.py`
- Strict CORS: only 4 allowed origins
- `slowapi` rate limiting: 100/min global, 5/min register, 10/min login
- `POST /api/leads/{id}/unlock`: BEGIN IMMEDIATE atomic transaction
- `POST /api/attorney/verify`: Sets status to PENDING
- `GET /api/leads`: Returns `List[SafeAsset]`, filters expired leads
- Honeypot injection on every leads response

### File 5: `verifuse_v2/scrapers/vertex_engine_production.py`
- Atomic lockfile (`os.O_CREAT | os.O_EXCL`) — prevents concurrent runs
- Idempotent: `if lead.winning_bid and lead.total_debt: continue`
- Safety gate: only writes if `confidence > 0.8` AND `bid >= debt`
- Structured JSONL audit to `logs/engine4_audit.jsonl`

---

## HOW TO RUN EACH COMPONENT

### 1. Titanium Migration (Idempotent — Always Safe)
```bash
cd ~/origin/continuity_lab
python -m verifuse_v2.db.migrate_titanium
```
**Run this:** After every schema change or fresh deployment.

### 2. System Diagnostic
```bash
python -m verifuse_v2.verify_system
```
**Expected:** 28/29 PASS, 1 WARN (duplicate cases), 0 FAIL → GREEN LIGHT

### 3. API Server
```bash
# Production (systemd):
sudo systemctl restart verifuse-api
sudo systemctl status verifuse-api
journalctl -u verifuse-api -f

# Dev (manual):
python -m uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Vertex AI Engine (Titanium Production)
```bash
# Pre-flight only:
GOOGLE_APPLICATION_CREDENTIALS="$HOME/google_credentials.json" \
  python -m verifuse_v2.scrapers.vertex_engine_production --preflight-only

# Process 10 PDFs (test):
python -m verifuse_v2.scrapers.vertex_engine_production --limit 10

# Dry run (validate PDFs, no Vertex calls):
python -m verifuse_v2.scrapers.vertex_engine_production --limit 50 --dry-run
```

### 5. County Scrapers
```bash
# Individual:
python -m verifuse_v2.scrapers.adams_postsale_scraper
python -m verifuse_v2.scrapers.elpaso_postsale_scraper
python -m verifuse_v2.scrapers.larimer_scraper
python -m verifuse_v2.scrapers.weld_scraper
python -m verifuse_v2.scrapers.boulder_scraper
python -m verifuse_v2.scrapers.pueblo_scraper

# All via pipeline:
python -c "from verifuse_v2.pipeline_manager import Governor; g = Governor(); print(g.run_pipeline())"
```

### 6. Daily Healthcheck
```bash
python -m verifuse_v2.daily_healthcheck
```

### 7. Staging Promoter
```bash
python -m verifuse_v2.staging_promoter --dry-run        # Preview
python -m verifuse_v2.staging_promoter --link-pdfs       # Full run
```

### 8. React Frontend Build
```bash
cd verifuse/site/app
npm install && npm run build    # Output: dist/
```

---

## API ENDPOINTS (Titanium)

### Public (No Auth)
| Method | Path | Rate Limit | Description |
|--------|------|-----------|-------------|
| GET | `/health` | None | Health check + asset counts |
| GET | `/api/stats` | None | Dashboard summary |
| GET | `/api/counties` | None | County breakdown |
| GET | `/api/leads` | 100/min | Browse leads as `SafeAsset[]` (no PII) |
| GET | `/api/lead/{id}` | 100/min | Single lead (SafeAsset or FullAsset if unlocked) |
| GET | `/api/dossier/{id}` | None | Download teaser dossier PDF |

### Authenticated (JWT Required)
| Method | Path | Rate Limit | Description |
|--------|------|-----------|-------------|
| POST | `/api/auth/register` | 5/min | Register account |
| POST | `/api/auth/login` | 10/min | Login, get JWT |
| GET | `/api/auth/me` | None | User profile + attorney_status |
| POST | `/api/attorney/verify` | None | Submit bar number (→ PENDING) |
| POST | `/api/leads/{id}/unlock` | **5/min** | **Atomic unlock** (credit + record) |
| GET | `/api/user/unlocks` | None | Unlock history |
| POST | `/api/billing/checkout` | None | Create Stripe checkout |
| POST | `/api/webhooks/stripe` | None | Stripe webhook handler |

### Admin Only
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats` | Full system stats |
| GET | `/api/admin/leads` | All leads unredacted |
| POST | `/api/admin/regrade` | Manual regrade all assets |
| POST | `/api/admin/dedup` | Deduplicate database |
| GET | `/api/admin/users` | List all users |
| POST | `/api/admin/upgrade-user` | Promote user to admin |
| POST | `/api/admin/verify-attorney` | Verify/reject attorney |

---

## STRIPE BILLING SETUP

### Step 1: Create Products in Stripe Dashboard
Go to https://dashboard.stripe.com/products and create 3 products:

| Product Name | Price | Credits/Month | Daily API Limit |
|-------------|-------|--------------|-----------------|
| VeriFuse Recon | $199/month | 5 credits | 50 views/day |
| VeriFuse Operator | $399/month | 25 credits | 200 views/day |
| VeriFuse Sovereign | $699/month | 100 credits | 500 views/day |

### Step 2: Copy Price IDs
After creating each product, copy the `price_xxx` ID from the Price section.

### Step 3: Update systemd Service File
```bash
sudo nano /etc/systemd/system/verifuse-api.service
```
Replace the PLACEHOLDER values:
```ini
Environment="STRIPE_SECRET_KEY=sk_live_..."
Environment="STRIPE_WEBHOOK_SECRET=whsec_..."
Environment="STRIPE_PRICE_SCOUT=price_..."
Environment="STRIPE_PRICE_OPERATOR=price_..."
Environment="STRIPE_PRICE_SOVEREIGN=price_..."
Environment="VERIFUSE_JWT_SECRET=<run: openssl rand -hex 32>"
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart verifuse-api
```

### Step 4: Set Up Stripe Webhook
Stripe Dashboard → Developers → Webhooks → Add endpoint:
- **URL:** `https://verifuse.tech/api/webhooks/stripe`
- **Events:** `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`

### Step 5: Test
| Card Number | Scenario |
|------------|----------|
| `4242 4242 4242 4242` | Success |
| `4000 0000 0000 9995` | Insufficient funds |
| `4000 0025 0000 3155` | 3D Secure required |

---

## SYSTEMD AUTOMATION

### Active Services
| Service | Port | Manager | Status |
|---------|------|---------|--------|
| FastAPI (uvicorn) | 8000 | `verifuse-api.service` | Running |
| Caddy | 80, 443 | `caddy.service` | Running (TLS pending DNS) |

### Active Timers
| Timer | Schedule | Next Run | Purpose |
|-------|----------|----------|---------|
| `verifuse-healthcheck` | Daily 6:00 AM UTC | Daily | Regrade all assets |
| `verifuse-scrapers` | Thursdays 8:00 AM UTC | Feb 19 | Run all 6 county scrapers |
| `verifuse-vertex` | Fridays 10:00 AM UTC | Feb 20 | Process 100 PDFs (Titanium engine) |

### Timer Management
```bash
# Status:
sudo systemctl list-timers verifuse-*

# Manual trigger:
sudo systemctl start verifuse-healthcheck.service
sudo systemctl start verifuse-scrapers.service
sudo systemctl start verifuse-vertex.service

# Logs:
journalctl -u verifuse-api -f
cat verifuse_v2/logs/healthcheck.log
cat verifuse_v2/logs/scrapers.log
cat verifuse_v2/logs/vertex.log
cat verifuse_v2/logs/engine4_audit.jsonl
```

---

## COUNTY-BY-COUNTY: WHAT YOU MUST DO MANUALLY

### Counties That Are AUTOMATED (No Manual Work)
| County | Scraper | Automation | Data Quality |
|--------|---------|-----------|-------------|
| Adams | `adams_postsale_scraper.py` | Weekly Thursday | GOLD — has bid, debt, overbid, sale_date |
| El Paso | `elpaso_postsale_scraper.py` | Weekly Thursday | SILVER — pre-sale, no overbid yet |
| Larimer | `larimer_scraper.py` | Weekly Thursday | BRONZE — GTS portal scrape |
| Weld | `weld_scraper.py` | Weekly Thursday | BRONZE — excess funds page |
| Boulder | `boulder_scraper.py` | Weekly Thursday | BRONZE — GTS portal scrape |
| Pueblo | `pueblo_scraper.py` | Weekly Thursday | BRONZE — HTML schedule page |
| Denver | `signal_denver.py` + `outcome_denver.py` | Via healthcheck | GOLD — excess funds PDF |

### Counties That Need MANUAL Action
| County | Records | What You Must Do | How to Automate |
|--------|---------|-----------------|-----------------|
| **Eagle** | 312 (BRONZE, $0) | **Go to Eagle County Public Trustee website.** Download their post-sale/excess funds PDFs. Place in `verifuse_v2/data/raw_pdfs/eagle/`. Then run: `python -m verifuse_v2.scrapers.vertex_engine_production --limit 312` | Build `eagle_scraper.py` that hits their PT website programmatically |
| **San Miguel** | 250 (BRONZE, $0) | **Go to San Miguel County Public Trustee.** Same as Eagle — get post-sale PDFs. | Build `sanmiguel_scraper.py` |
| **Jefferson** | 66 (SILVER, $2M) | Data exists from CSV import. **Verify sale_dates are correct.** Some records missing total_indebtedness. Check https://www.jeffco.us/2222/Public-Trustee | Build `jefferson_scraper.py` for weekly updates |
| **Arapahoe** | 12 (GOLD, $1.4M) | **Currently manual.** Check https://www.arapahoegov.com/1524/Public-Trustee for new excess funds lists. | Build `arapahoe_scraper.py` |
| **Teller** | 26 (BRONZE, $18K) | Data from GovEase portal. **Need actual sale PDFs** to extract bid/debt. | Build `teller_pdf_scraper.py` using GovEase API |
| **Summit** | 5 (BRONZE, $0) | Same as Teller — GovEase data, needs PDF enrichment. | Part of GovEase scraper expansion |
| **Douglas** | 1 (SILVER, $4.8K) | Single manual record. **Verify data is current.** | Add to Arapahoe-area scraper |
| **Mesa** | 1 (SILVER, $40K) | Single manual record. **Verify data is current.** | Build `mesa_scraper.py` (low priority, only 1 record) |

### Priority Action Items for County Expansion
1. **Eagle County PDFs** (312 records, highest volume) — Download from PT office
2. **San Miguel County PDFs** (250 records) — Download from PT office
3. **Build Jefferson auto-scraper** (66 records, $2M surplus)
4. **Build Arapahoe auto-scraper** (12 records, $1.4M surplus — highest per-record value)

---

## CREDENTIAL STATUS

| Credential | Location | Status | Action Needed |
|------------|----------|--------|--------------|
| Google Service Account | `~/google_credentials.json` | VALID (canvas-sum-481614-f6) | None |
| Stripe Secret Key | systemd env | PLACEHOLDER | Set real `sk_live_...` or `sk_test_...` |
| Stripe Webhook Secret | systemd env | PLACEHOLDER | Set real `whsec_...` |
| Stripe Price IDs (3) | systemd env | PLACEHOLDER | Create products in Stripe Dashboard |
| JWT Secret | systemd env | PLACEHOLDER | Run `openssl rand -hex 32` |
| DNS A Record | Porkbun/Netlify | MISSING | Add A → 34.69.230.82 |

---

## ENGINE REGISTRY

| # | Engine | Module | Data Source | Titanium? |
|---|--------|--------|-------------|-----------|
| 0 | Governor | `pipeline_manager.py` | Rate limiter & orchestrator | - |
| 1 | Signal Discovery | `scrapers/signal_denver.py` | Denver Public Trustee | - |
| 2 | Outcome Resolution | `scrapers/outcome_denver.py` | Denver Foreclosure Detail | - |
| 3 | Entity Enrichment | `enrichment/entity_resolver.py` | Denver Assessor | - |
| 4 | **Vertex AI (Titanium)** | `scrapers/vertex_engine_production.py` | Staged PDFs via Gemini | YES |
| 5 | El Paso Post-Sale | `scrapers/elpaso_postsale_scraper.py` | El Paso Public Trustee | - |
| 6 | Adams Post-Sale | `scrapers/adams_postsale_scraper.py` | Adams Public Trustee | - |
| 7 | Larimer Pre-Sale | `scrapers/larimer_scraper.py` | Larimer Public Trustee | - |
| 8 | Weld Pre-Sale | `scrapers/weld_scraper.py` | Weld Public Trustee | - |
| 9 | Boulder Pre-Sale | `scrapers/boulder_scraper.py` | Boulder Public Trustee | - |
| 10 | Pueblo Schedule | `scrapers/pueblo_scraper.py` | Pueblo Public Trustee | - |

---

## TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| `Lead status always UNKNOWN` | Asset missing `sale_date`. Run vertex_engine_production to extract. |
| `RESTRICTED leads can't be unlocked` | User needs `attorney_status = 'VERIFIED'`. Admin: `POST /api/admin/verify-attorney` |
| `402 Insufficient credits` | User out of credits. Upgrade tier or wait for monthly reset. |
| `410 Lead expired` | Claim deadline passed. Lead is permanently locked. |
| `429 Rate limit` | Unlock: max 5/min per user. Global: 100/min per IP. |
| `CORS error in browser` | Only 4 origins allowed. Check `api.py` CORS config. |
| `vertex_engine: lockfile exists` | Another instance running, or stale lock. Check PID in `.vertex_engine.lock` |
| `vertex_engine: 0 ready` | No staged records with PDFs. Run `staging_promoter --link-pdfs` |
| `verifuse-api crash-looping` | Port 8000 in use. `ss -tlnp | grep 8000` then kill conflicting process |
| `Caddy TLS error` | DNS A record not configured → 34.69.230.82 |
| `Stripe checkout 400` | Price IDs not set in systemd env. See Stripe Setup section. |
| `Migration fails` | Run: `python -m verifuse_v2.db.migrate_titanium` (idempotent, safe to retry) |

---

## FILE MAP (Titanium)

| File | Purpose | Titanium? |
|------|---------|-----------|
| `verifuse_v2/db/schema.sql` | 13-table schema with FK, CHECK constraints | YES |
| `verifuse_v2/db/migrate_titanium.py` | Idempotent migration (lead_unlocks, attorney_status) | YES |
| `verifuse_v2/db/database.py` | Core DB abstraction (FK=ON, WAL mode) | Updated |
| `verifuse_v2/server/models.py` | Lead, SafeAsset, FullAsset with computed status | YES |
| `verifuse_v2/server/api.py` | Titanium API guard (CORS, rate limit, atomic unlock) | YES |
| `verifuse_v2/server/auth.py` | JWT auth (bcrypt, 72h tokens) | Existing |
| `verifuse_v2/server/billing.py` | Stripe billing (checkout, webhooks, credit reset) | Existing |
| `verifuse_v2/server/obfuscator.py` | PII → Base64 PNG (anti-OCR) | Existing |
| `verifuse_v2/server/dossier_gen.py` | Intelligence dossier PDF generator | Existing |
| `verifuse_v2/server/motion_gen.py` | Motion for disbursement PDF | Existing |
| `verifuse_v2/scrapers/vertex_engine_production.py` | Titanium Vertex AI engine (lockfile, idempotent, safety gate) | YES |
| `verifuse_v2/scrapers/vertex_engine.py` | Legacy engine (kept for backward compat) | Legacy |
| `verifuse_v2/daily_healthcheck.py` | Daily regrade + scrape + report | Existing |
| `verifuse_v2/verify_system.py` | 8-layer diagnostic (GREEN LIGHT) | Existing |
| `verifuse_v2/staging_promoter.py` | Promote staging → assets | Existing |
| `verifuse_v2/pipeline_manager.py` | Engine 0 (Governor) | Existing |
| `verifuse_v2/requirements.txt` | Python deps (+ slowapi, pydantic) | Updated |
| `verifuse/site/app/` | React frontend | Existing |
| `verifuse_v2/deploy/` | Systemd service + timer units | Updated |

---

## WHAT NEEDS TO HAPPEN NEXT (Priority Order)

### CRITICAL (Do These First — 30 minutes total)
1. **Fix DNS** → Add A record `34.69.230.82` in Porkbun. Then `sudo systemctl restart caddy`.
2. **Set Stripe credentials** → Create products, get price IDs, update systemd env vars.
3. **Set JWT secret** → `openssl rand -hex 32`, update in systemd service file.

### HIGH PRIORITY (This Week)
4. **Download Eagle County PDFs** (312 records) → Place in `data/raw_pdfs/eagle/`, run vertex engine.
5. **Download San Miguel County PDFs** (250 records) → Same process.
6. **Run all scrapers** → `python -c "from verifuse_v2.pipeline_manager import Governor; g = Governor(); print(g.run_pipeline())"` or wait for Thursday's automated run.
7. **Process available PDFs** → `python -m verifuse_v2.scrapers.vertex_engine_production --limit 50`

### MEDIUM PRIORITY (Next Sprint)
8. **Build auto-scrapers** for Jefferson ($2M) and Arapahoe ($1.4M) counties.
9. **Test end-to-end flow** → Register → Login → Browse → Checkout → Unlock → Dossier.
10. **Attorney verification flow** → Register with bar number → Admin verifies → Unlock RESTRICTED leads.

### LOWER PRIORITY
11. **Build scrapers** for Teller, Summit, Douglas, Mesa counties.
12. **Marketing site** → Auto-update stats from API.
13. **Monitoring/alerting** → Email on scraper failures.

### COMPLETED (Sprint 4 — Titanium)
- [x] Rewrote `schema.sql` with lead_unlocks, attorney_status, V2 financial columns
- [x] Created `migrate_titanium.py` — idempotent, backfilled 103 claim_deadlines
- [x] Created `models.py` — Lead with computed status, SafeAsset/FullAsset projections
- [x] Rewrote `api.py` — strict CORS, slowapi rate limiting, atomic BEGIN IMMEDIATE unlocks
- [x] Rewrote `vertex_engine_production.py` — lockfile, idempotency, safety gate
- [x] All 5 files verified working: API v3.0.0 running, 28/29 PASS diagnostic
- [x] Installed slowapi + pydantic in requirements.txt
- [x] Updated vertex systemd timer to use Titanium production engine
