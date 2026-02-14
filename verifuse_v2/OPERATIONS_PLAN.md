# VERIFUSE V2 — OPERATIONS PLAN
## Last Updated: February 14, 2026 (Sprint 3 — Infrastructure Audit)

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
| VM IP | 34.69.230.82 (GCP) |
| Domain Registrar | Porkbun (registered 2026-02-06) |
| DNS Nameservers | Netlify nsone.net (NEEDS FIX — see below) |
| Systemd API | verifuse-api.service (enabled, running) |
| Systemd Timers | 3 active (healthcheck daily, scrapers Thu, vertex Fri) |

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

## CRITICAL: DNS SETUP (MUST DO FIRST)

The domain `verifuse.tech` is registered on **Porkbun** but nameservers currently point to **Netlify's NS** (dns1-4.p05.nsone.net) with **NO A record configured**. This means:
- The domain does NOT resolve (`NXDOMAIN`)
- Caddy cannot obtain TLS certificates from Let's Encrypt
- The site is unreachable from the internet

### Option A: Fix DNS via Porkbun (Recommended)
1. Log into https://porkbun.com → Domain Management → `verifuse.tech`
2. Click **"DNS"** or **"Edit DNS Records"**
3. **Change nameservers back to Porkbun's defaults** (if currently set to Netlify):
   - Go to "Nameservers" → "Use Porkbun NS" or similar
   - Porkbun NS: `maceio.ns.porkbun.com`, `salvador.ns.porkbun.com`
4. Add these DNS records:

| Type | Host | Answer | TTL |
|------|------|--------|-----|
| A | *(blank/root)* | `34.69.230.82` | 600 |
| A | `www` | `34.69.230.82` | 600 |

### Option B: Fix DNS via Netlify
If you want to keep Netlify nameservers:
1. Log into https://app.netlify.com → Domains → `verifuse.tech`
2. Add DNS records:

| Type | Name | Value |
|------|------|-------|
| A | @ | `34.69.230.82` |
| A | www | `34.69.230.82` |

### After DNS is configured:
```bash
# Verify DNS resolution (may take 5-60 minutes to propagate):
dig verifuse.tech A +short
# Should return: 34.69.230.82

# Restart Caddy to get fresh TLS certs:
sudo systemctl restart caddy

# Verify TLS:
curl -I https://verifuse.tech/health
```

### Firewall Note
The VM's iptables INPUT policy is ACCEPT (all ports open). GCP firewall rules control external access. Ensure the GCP firewall allows:
- **TCP 80** (HTTP — needed for Let's Encrypt ACME challenge)
- **TCP 443** (HTTPS — production traffic)
- **TCP 22** (SSH)

Check in GCP Console → VPC Network → Firewall Rules, or:
```bash
gcloud compute firewall-rules list --filter="network:default"
```

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

**Expected output:** 28/29 PASS, 1 WARN (duplicate cases), 0 FAIL → GREEN LIGHT

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
| `verifuse-api.service crash-looping` | Check if nohup/manual uvicorn is holding port 8000: `ss -tlnp \| grep 8000` then `kill <PID>` and `sudo systemctl restart verifuse-api` |
| `Caddy NXDOMAIN errors` | DNS A record not configured. See "CRITICAL: DNS SETUP" section |
| `Caddy staging certs` | Clear staging cache: `sudo rm -rf /var/lib/caddy/.local/share/caddy/acme/acme-staging-*` then `sudo systemctl restart caddy` |
| `systemctl list-timers shows no verifuse timers` | Copy units from `verifuse_v2/deploy/` to `/etc/systemd/system/`, run `daemon-reload`, `enable --now` |

---

## WHAT NEEDS TO HAPPEN NEXT (Priority Order)

### CRITICAL (Do These First)
1. **Fix DNS** — See "CRITICAL: DNS SETUP" section above. Without this, the site is unreachable and Caddy can't get TLS certs. This is a 5-minute task in Porkbun or Netlify.
2. **Set Stripe price IDs** — Create 3 products in Stripe Dashboard, get `price_xxx` IDs, update `/etc/systemd/system/verifuse-api.service` Environment lines, then `sudo systemctl daemon-reload && sudo systemctl restart verifuse-api`.
3. **Set JWT secret** — Generate with `openssl rand -hex 32`, update `VERIFUSE_JWT_SECRET` in the service file.

### HIGH PRIORITY
4. **Enrich Eagle County (312 records)** — These are BRONZE with $0 surplus. Need to obtain actual foreclosure PDFs from Eagle County Public Trustee and process through Vertex AI.
5. **Enrich San Miguel County (250 records)** — Same situation as Eagle. Contact PT office for PDFs.
6. **Run all scrapers for fresh data** — `python -c "from verifuse_v2.pipeline_manager import Governor; g = Governor(); print(g.run_pipeline())"` or wait for Thursday's automated run.
7. **Process PDFs through Vertex AI** — 38 staged records have linked PDFs. Run: `python -m verifuse_v2.scrapers.vertex_engine --limit 38`

### MEDIUM PRIORITY
8. **Test end-to-end attorney flow** — Register → Login → Browse leads → Stripe checkout → Unlock → Download dossier. Requires DNS + Stripe to be working first.
9. **Add Arapahoe County scraper** — 12 existing manual records, could automate.
10. **Add Jefferson County scraper** — 66 records, mix of manual + portal.

### LOWER PRIORITY
11. **Marketing site updates** — Landing page stats auto-update from API.
12. **Set up monitoring/alerting** — Email alerts on scraper failures, low asset counts.

### COMPLETED (Sprint 3)
- [x] Killed stale nohup process, systemd now manages API (PID-managed, auto-restart)
- [x] Installed and enabled all 3 systemd timers (healthcheck daily 6AM, scrapers Thu 8AM, vertex Fri 10AM)
- [x] System diagnostic: 28/29 PASS, 0 FAIL, GREEN LIGHT
- [x] Infrastructure audit completed — identified DNS as root cause of all deployment issues
- [x] Cleared stale Caddy staging cert cache

---

## INFRASTRUCTURE MAP

### Server
- **GCP VM:** `verifuse-dev-box` at `34.69.230.82`
- **GCP Project:** `canvas-sum-481614-f6`
- **OS:** Debian 12 (Linux 6.1.0-43-cloud-amd64)
- **Python:** 3.11+ in `.venv/`

### Services Running
| Service | Port | Manager | Status |
|---------|------|---------|--------|
| FastAPI (uvicorn) | 8000 | systemd `verifuse-api.service` | Running |
| Caddy | 80, 443 | systemd `caddy.service` | Running (TLS pending DNS) |

### Systemd Timers Active
| Timer | Schedule | Next Run |
|-------|----------|----------|
| verifuse-healthcheck | Daily 6:00 AM UTC | Tomorrow |
| verifuse-scrapers | Thursdays 8:00 AM UTC | Feb 19 |
| verifuse-vertex | Fridays 10:00 AM UTC | Feb 20 |

### Credentials
| Credential | Location | Status |
|------------|----------|--------|
| Google Service Account | `~/google_credentials.json` | Valid (canvas-sum-481614-f6) |
| Stripe Secret Key | systemd env `STRIPE_SECRET_KEY` | PLACEHOLDER — needs real key |
| Stripe Webhook Secret | systemd env `STRIPE_WEBHOOK_SECRET` | PLACEHOLDER — needs real key |
| Stripe Price IDs (3) | systemd env `STRIPE_PRICE_*` | PLACEHOLDER — needs real IDs |
| JWT Secret | systemd env `VERIFUSE_JWT_SECRET` | PLACEHOLDER — needs `openssl rand -hex 32` |

### Key Config Files
| File | Location | Purpose |
|------|----------|---------|
| Caddyfile | `/etc/caddy/Caddyfile` | Reverse proxy + TLS |
| API Service | `/etc/systemd/system/verifuse-api.service` | API server config + env vars |
| Timer Units | `/etc/systemd/system/verifuse-*.timer` | Automation schedules |
| Google Creds | `~/google_credentials.json` | Vertex AI authentication |
| React Build | `verifuse/site/app/dist/` | Production frontend (255KB JS, 16KB CSS) |

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
