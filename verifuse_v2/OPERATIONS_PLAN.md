# VERIFUSE V2 — OPERATIONS PLAN
## Last Updated: February 14, 2026 (Sprint 2)

---

## SYSTEM STATUS: OPERATIONAL (11 Counties, 10 Engines, 734 Assets)

### Database Summary
| Metric | Value |
|--------|-------|
| Total Assets | 734 |
| Total Pipeline Value | $5,195,573.68 |
| GOLD-Grade Verified Leads | 6 |
| SILVER-Grade Leads | 7 |
| BRONZE-Grade Leads | 692 |
| Attorney-Ready (GOLD+SILVER) | 13 |
| Counties Active | 11 |
| Staging Records | 691 (688 promoted, 3 already existed) |
| GCP Project | canvas-sum-481614-f6 |
| API Server | FastAPI on :8000 |
| Frontend | React 19 + Vite 7 (production build at `dist/`) |
| Domain | verifuse.tech (Caddy reverse proxy) |

### County Breakdown
| County | Assets | Total Surplus | Data Source | Engine |
|--------|--------|--------------|-------------|--------|
| Eagle | 312 | $0 (needs enrichment) | Portal scraper | Staging |
| San Miguel | 250 | $0 (needs enrichment) | Portal scraper | Staging |
| Jefferson | 66 | $2,026,675 | CSV + portal | Manual + Staging |
| Adams | 39 | $258,106 | Weekly Post Sale PDF | #6 |
| Teller | 26 | $18,246 | GovEase portal | Staging |
| Denver | 17 | $1,421,452 | Monthly excess funds PDF | #1-3 |
| Arapahoe | 12 | $1,426,297 | Overbid list | Manual |
| El Paso | 5 | $0 (pre-sale) | Weekly Pre Sale PDF | #5 |
| Summit | 5 | $0 (needs enrichment) | GovEase portal | Staging |
| Douglas | 1 | $4,798 | Manual | Manual |
| Mesa | 1 | $40,000 | Manual | Manual |

---

## HOW TO RUN EACH COMPONENT

### 1. Database Migration (Idempotent — Safe to Run Anytime)
```bash
cd ~/origin/continuity_lab
python -m verifuse_v2.db.migrate_master
```
**What it does:** Checks all 11 tables, adds missing columns, creates indexes. Run this after any schema changes.

### 2. System Diagnostic
```bash
python -m verifuse_v2.verify_system
```
**What it does:** Tests 8 layers — database, schema, data integrity, credentials, Vertex AI, staging, API server, filesystem. Outputs GREEN LIGHT / YELLOW / RED status.

**Expected output:** 27/29 PASS (2 WARN = API server not running + duplicate cases)

### 3. Staging Promoter (Promote Portal Records to Assets)
```bash
# Dry run first:
python -m verifuse_v2.staging_promoter --dry-run

# Full promotion with PDF linking:
python -m verifuse_v2.staging_promoter --link-pdfs
```
**What it does:** Promotes 691 staging records from portal scrapers (Eagle, San Miguel, etc.) into the main assets table. These records already have structured data but no PDFs — they get BRONZE grade and need enrichment.

### 4. Engine #4 — Vertex AI PDF Extraction
```bash
# Pre-flight check only (no processing):
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/google_credentials.json"
python -m verifuse_v2.scrapers.vertex_engine --preflight-only

# Process 5 PDFs (test):
python -m verifuse_v2.scrapers.vertex_engine --limit 5

# Full batch (50 PDFs):
python -m verifuse_v2.scrapers.vertex_engine --limit 50

# Specify GCP project explicitly:
python -m verifuse_v2.scrapers.vertex_engine --project canvas-sum-481614-f6 --limit 50
```
**What it does:** Reads PDFs from `assets_staging` where `pdf_path IS NOT NULL AND status='STAGED'`, sends to Vertex AI (Gemini), extracts winning_bid/total_debt/sale_date, computes surplus and grade, inserts into `assets`.

**Requirements:**
- Valid `~/google_credentials.json` (service account with Vertex AI API enabled)
- `GOOGLE_APPLICATION_CREDENTIALS` env var set
- Staged records with `pdf_path` linked

### 5. County Scrapers
```bash
# Adams County (Post-Sale PDFs — BEST DATA):
python -m verifuse_v2.scrapers.adams_postsale_scraper

# El Paso County (Post-Sale PDFs):
python -m verifuse_v2.scrapers.elpaso_postsale_scraper

# Larimer County (Pre-Sale PDFs via GTS):
python -m verifuse_v2.scrapers.larimer_scraper

# Weld County (Pre-Sale PDFs):
python -m verifuse_v2.scrapers.weld_scraper

# Boulder County (Pre-Sale PDFs via GTS):
python -m verifuse_v2.scrapers.boulder_scraper

# Pueblo County (HTML schedule page):
python -m verifuse_v2.scrapers.pueblo_scraper

# Run ALL scrapers via pipeline:
python -c "from verifuse_v2.pipeline_manager import Governor; g = Governor(); print(g.run_pipeline())"
```

### 6. Daily Healthcheck
```bash
python -m verifuse_v2.daily_healthcheck
```
**What it does:** Re-evaluates every asset — computes confidence, completeness, grade, days_remaining. Promotes/demotes records between GOLD/SILVER/BRONZE/REJECT based on data quality.

### 7. API Server
```bash
# Start API server:
python -m uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000

# Or via systemd (production):
sudo cp verifuse_v2/deploy/verifuse-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable verifuse-api
sudo systemctl start verifuse-api

# Check health:
curl http://localhost:8000/health
curl http://localhost:8000/api/stats
curl http://localhost:8000/api/counties
```

### 8. React Frontend (Production Build)
```bash
cd verifuse/site/app
npm install
npm run build    # Output: dist/

# Dev server:
npm run dev      # http://localhost:5173
```

### 9. Caddy Reverse Proxy (Production)
```bash
sudo caddy run --config verifuse_v2/deploy/Caddyfile
```
**Routing:**
- `/api/*` → FastAPI on :8000
- `/health` → FastAPI on :8000
- `/*` → Static files from `verifuse/site/app/dist/`

---

## STRIPE BILLING SETUP

### Step 1: Create Products in Stripe Dashboard
Go to https://dashboard.stripe.com/products and create 3 products:

| Product Name | Price | Credits/Month |
|-------------|-------|--------------|
| VeriFuse Recon | $199/month | 5 credits |
| VeriFuse Operator | $399/month | 25 credits |
| VeriFuse Sovereign | $699/month | 100 credits |

### Step 2: Get Price IDs
After creating each product, copy the `price_xxx` ID from the Price section.

### Step 3: Set Environment Variables
Add to your systemd service file or `~/.bashrc`:
```bash
export STRIPE_SECRET_KEY="sk_live_..."          # or sk_test_... for testing
export STRIPE_WEBHOOK_SECRET="whsec_..."
export STRIPE_PRICE_RECON="price_..."
export STRIPE_PRICE_OPERATOR="price_..."
export STRIPE_PRICE_SOVEREIGN="price_..."
export VERIFUSE_BASE_URL="https://verifuse.tech"
export VERIFUSE_JWT_SECRET="$(openssl rand -hex 32)"
```

### Step 4: Set Up Stripe Webhook
In Stripe Dashboard → Developers → Webhooks → Add endpoint:
- **URL:** `https://verifuse.tech/api/webhooks/stripe`
- **Events to listen for:**
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.paid`

### Step 5: Test with Stripe Test Cards
| Card Number | Scenario |
|------------|----------|
| `4242 4242 4242 4242` | Success |
| `4000 0000 0000 9995` | Insufficient funds |
| `4000 0000 0000 0341` | Attach fails |
| `4000 0025 0000 3155` | Requires 3D Secure |

Use any future expiry date and any 3-digit CVC.

---

## CRON / SYSTEMD AUTOMATION

### Timer Units (in `verifuse_v2/deploy/`)

| Timer | Service | Schedule | Purpose |
|-------|---------|----------|---------|
| `verifuse-healthcheck.timer` | `verifuse-healthcheck.service` | Daily 6:00 AM UTC | Regrade all assets |
| `verifuse-scrapers.timer` | `verifuse-scrapers.service` | Thursdays 8:00 AM UTC | Run all 6 county scrapers + healthcheck |
| `verifuse-vertex.timer` | `verifuse-vertex.service` | Fridays 10:00 AM UTC | Process 100 staged PDFs via Vertex AI |

### Installing Timers
```bash
# Copy all service and timer files:
sudo cp verifuse_v2/deploy/verifuse-healthcheck.{service,timer} /etc/systemd/system/
sudo cp verifuse_v2/deploy/verifuse-scrapers.{service,timer} /etc/systemd/system/
sudo cp verifuse_v2/deploy/verifuse-vertex.{service,timer} /etc/systemd/system/
sudo cp verifuse_v2/deploy/verifuse-api.service /etc/systemd/system/

# Reload and enable:
sudo systemctl daemon-reload
sudo systemctl enable verifuse-api verifuse-healthcheck.timer verifuse-scrapers.timer verifuse-vertex.timer
sudo systemctl start verifuse-api verifuse-healthcheck.timer verifuse-scrapers.timer verifuse-vertex.timer

# Check status:
sudo systemctl list-timers verifuse-*
sudo systemctl status verifuse-api
```

### Logs
```bash
# API server:
journalctl -u verifuse-api -f

# Healthcheck:
cat verifuse_v2/logs/healthcheck.log

# Scrapers:
cat verifuse_v2/logs/scrapers.log

# Vertex AI:
cat verifuse_v2/logs/vertex.log
cat verifuse_v2/logs/engine4_audit.jsonl
```

---

## ENGINE REGISTRY

| # | Engine | Module | Data Source |
|---|--------|--------|-------------|
| 0 | Governor | `pipeline_manager.py` | Rate limiter & orchestrator |
| 1 | Signal Discovery | `scrapers/signal_denver.py` | Denver Public Trustee |
| 2 | Outcome Resolution | `scrapers/outcome_denver.py` | Denver Foreclosure Detail |
| 3 | Entity Enrichment | `enrichment/entity_resolver.py` | Denver Assessor |
| 4 | Vertex AI PDF Reader | `scrapers/vertex_engine.py` | Staged PDFs via Gemini |
| 5 | El Paso Post-Sale | `scrapers/elpaso_postsale_scraper.py` | El Paso Public Trustee |
| 6 | Adams Post-Sale | `scrapers/adams_postsale_scraper.py` | Adams Public Trustee |
| 7 | Larimer Pre-Sale | `scrapers/larimer_scraper.py` | Larimer Public Trustee |
| 8 | Weld Pre-Sale | `scrapers/weld_scraper.py` | Weld Public Trustee |
| 9 | Boulder Pre-Sale | `scrapers/boulder_scraper.py` | Boulder Public Trustee |
| 10 | Pueblo Schedule | `scrapers/pueblo_scraper.py` | Pueblo Public Trustee |

---

## API ENDPOINTS

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Server health + asset counts |
| GET | `/api/stats` | No | Dashboard summary |
| GET | `/api/counties` | No | County-level breakdown |
| GET | `/api/leads` | No | List leads (with obfuscation) |
| GET | `/api/lead/{id}` | No | Single lead detail |
| POST | `/api/auth/register` | No | Register attorney account |
| POST | `/api/auth/login` | No | Login, get JWT |
| GET | `/api/auth/me` | JWT | Current user profile |
| GET | `/api/user/unlocks` | JWT | Unlock history |
| POST | `/api/unlock/{id}` | JWT | Unlock lead (1 credit) |
| POST | `/api/unlock-restricted/{id}` | JWT | Unlock restricted lead |
| GET | `/api/dossier/{id}` | JWT | Download dossier PDF |
| GET | `/api/motion/{id}` | JWT | Download motion PDF |
| POST | `/api/billing/checkout` | JWT | Create Stripe checkout |
| POST | `/api/webhooks/stripe` | Stripe | Webhook handler |
| GET | `/api/admin/stats` | Admin | Full system stats |
| GET | `/api/admin/leads` | Admin | All leads unobfuscated |
| POST | `/api/admin/regrade` | Admin | Manual regrade |
| POST | `/api/admin/dedup` | Admin | Deduplicate DB |
| GET | `/api/admin/users` | Admin | List users |
| POST | `/api/admin/upgrade-user` | Admin | Upgrade user tier |

---

## TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| `vertex_engine: GOOGLE_APPLICATION_CREDENTIALS not set` | `export GOOGLE_APPLICATION_CREDENTIALS="$HOME/google_credentials.json"` |
| `vertex_engine: 0 ready` | Run `python -m verifuse_v2.staging_promoter --link-pdfs` to link PDFs |
| `verify_system: API Server WARN` | Start API: `python -m uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000` |
| `daily_healthcheck: no module` | `cd ~/origin/continuity_lab && pip install -r verifuse_v2/requirements.txt` |
| `Stripe checkout 400 error` | Check `STRIPE_PRICE_*` env vars are set with valid price IDs |
| `React build fails` | `cd verifuse/site/app && npm install && npm run build` |
| `Caddy TLS error` | Ensure DNS A record points to server IP, ports 80+443 open |
| `sqlite3 locked` | Stop all writers, check for stale connections |
| `Scraper 403/captcha` | Governor auto-applies 24h cooldown. Wait or check IP reputation |
| `PDF parse returns 0 records` | Check PDF format matches expected regex patterns in scraper |

---

## WHAT NEEDS TO HAPPEN NEXT (Priority Order)

### HIGH PRIORITY
1. **Enrich Eagle County (312 records)** — These are BRONZE with $0 surplus. Need to obtain actual foreclosure PDFs from Eagle County Public Trustee and process through Vertex AI.
2. **Enrich San Miguel County (250 records)** — Same situation as Eagle. Contact PT office for PDFs.
3. **Deploy API to production** — Install systemd services, start Caddy, verify Stripe webhook URL.
4. **Set Stripe price IDs** — Create products in Stripe Dashboard, get price_xxx IDs, update env vars.

### MEDIUM PRIORITY
5. **Run all scrapers** — `python -m verifuse_v2.scrapers.adams_postsale_scraper` etc. to pull latest data.
6. **Process PDFs through Vertex AI** — Any staging records with linked PDFs.
7. **Enable systemd timers** — Automate healthcheck (daily), scrapers (weekly), vertex (weekly).
8. **Set up DNS** — Point `verifuse.tech` A record to this server's IP.

### LOWER PRIORITY
9. **Add Arapahoe County scraper** — 12 existing manual records, could automate.
10. **Add Jefferson County scraper** — 66 records, mix of manual + portal.
11. **Marketing site updates** — Landing page stats auto-update from API.
12. **Attorney onboarding flow** — Test registration → Stripe → unlock → dossier flow end-to-end.

---

## FILE MAP

| File | Purpose |
|------|---------|
| `verifuse_v2/db/database.py` | Core DB abstraction (get_db, init_db, get_lead_by_id) |
| `verifuse_v2/db/schema.sql` | 9-table schema definition |
| `verifuse_v2/db/migrate_master.py` | Idempotent migration utility |
| `verifuse_v2/daily_healthcheck.py` | Asset regrading + confidence scoring |
| `verifuse_v2/verify_system.py` | 8-layer system diagnostic |
| `verifuse_v2/staging_promoter.py` | Promote staging → assets |
| `verifuse_v2/pipeline_manager.py` | Engine 0 (Governor) + pipeline orchestrator |
| `verifuse_v2/scrapers/vertex_engine.py` | Engine 4 (Vertex AI PDF extraction) |
| `verifuse_v2/scrapers/signal_denver.py` | Engine 1 (Denver signal discovery) |
| `verifuse_v2/scrapers/outcome_denver.py` | Engine 2 (Denver outcome resolution) |
| `verifuse_v2/scrapers/elpaso_postsale_scraper.py` | Engine 5 (El Paso) |
| `verifuse_v2/scrapers/adams_postsale_scraper.py` | Engine 6 (Adams) |
| `verifuse_v2/scrapers/larimer_scraper.py` | Engine 7 (Larimer) |
| `verifuse_v2/scrapers/weld_scraper.py` | Engine 8 (Weld) |
| `verifuse_v2/scrapers/boulder_scraper.py` | Engine 9 (Boulder) |
| `verifuse_v2/scrapers/pueblo_scraper.py` | Engine 10 (Pueblo) |
| `verifuse_v2/server/api.py` | FastAPI server (all endpoints) |
| `verifuse_v2/server/billing.py` | Stripe billing integration |
| `verifuse_v2/server/auth.py` | JWT authentication |
| `verifuse_v2/deploy/Caddyfile` | Reverse proxy config |
| `verifuse_v2/deploy/verifuse-api.service` | API systemd service |
| `verifuse_v2/deploy/verifuse-healthcheck.*` | Daily healthcheck timer |
| `verifuse_v2/deploy/verifuse-scrapers.*` | Weekly scrapers timer |
| `verifuse_v2/deploy/verifuse-vertex.*` | Weekly Vertex AI timer |
| `verifuse/site/app/` | React frontend (Vite + TypeScript) |
| `verifuse/site/app/.env` | Dev API URL (localhost:8000) |
| `verifuse/site/app/.env.production` | Production API URL (verifuse.tech) |
