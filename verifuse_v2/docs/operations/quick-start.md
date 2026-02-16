# Quick Start Guide

How to bring the VeriFuse V2 system up from scratch.

---

## Step 0: Pre-Flight Check

**First command of every day:**

```bash
python -m verifuse_v2.scripts.morning_report
```

This shows: new leads (24h), scraper failures, Vertex AI budget, top GOLD leads, scoreboard, API health. If this runs clean, the system is healthy.

---

## Step 1: Environment Variables

Create `/home/schlieve001/verifuse_titanium_prod/secrets.env`:

```bash
# Required
VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
VERIFUSE_JWT_SECRET=<generate-a-64-char-random-secret>
VERIFUSE_API_KEY=<generate-a-32-char-random-key>

# Stripe (required for billing)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_RECON=price_...
STRIPE_PRICE_OPERATOR=price_...
STRIPE_PRICE_SOVEREIGN=price_...
VERIFUSE_BASE_URL=https://verifuse.tech

# Vertex AI (optional, for AI enrichment)
GOOGLE_APPLICATION_CREDENTIALS=/home/schlieve001/origin/continuity_lab/verifuse_v2/google_credentials.json
```

Lock down the secrets file:

```bash
chmod 600 /home/schlieve001/verifuse_titanium_prod/secrets.env
```

Source for your current shell:

```bash
export $(cat /home/schlieve001/verifuse_titanium_prod/secrets.env | grep -v '^#' | xargs)
```

---

## Step 2: Install Dependencies

```bash
cd /home/schlieve001/origin/continuity_lab
python -m venv .venv
source .venv/bin/activate
pip install -r verifuse_v2/requirements.txt
```

---

## Step 3: Initialize Database

If starting fresh (no existing `verifuse_v2.db`):

```bash
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db

# Run migrations to create all tables
python -m verifuse_v2.db.migrate
python -m verifuse_v2.db.migrate_titanium
python -m verifuse_v2.db.migrate_master
python -m verifuse_v2.db.migrate_sprint11
```

Verify the database:

```bash
sqlite3 $VERIFUSE_DB_PATH ".tables"
# Should show: leads, users, lead_unlocks, leads_quarantine, pipeline_events,
#              vertex_usage, vertex_queue, download_audit, lead_provenance
```

---

## Step 4: Start the API Server

Manual start (for testing):

```bash
source .venv/bin/activate
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
export VERIFUSE_JWT_SECRET=<your-secret>

uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://localhost:8000/health
# Returns: {"status": "ok", "engine": "titanium_api_v4", ...}
```

For production, use systemd (see Step 6).

---

## Step 5: Create Admin User

```bash
python -c "
from verifuse_v2.db.database import upgrade_to_admin
upgrade_to_admin('your@email.com', credits=9999)
print('Admin created')
"
```

Or register via the API and then promote:

```bash
# Register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@verifuse.tech", "password": "SecurePass123", "full_name": "Admin"}'

# Promote to admin
python -c "
from verifuse_v2.db.database import upgrade_to_admin
upgrade_to_admin('admin@verifuse.tech')
"
```

---

## Step 6: Install systemd Services

```bash
cd /home/schlieve001/origin/continuity_lab/verifuse_v2/deploy

# Copy service files
sudo cp verifuse-api.service /etc/systemd/system/
sudo cp verifuse-scrapers.service /etc/systemd/system/
sudo cp verifuse-scrapers.timer /etc/systemd/system/
sudo cp verifuse-healthcheck.service /etc/systemd/system/
sudo cp verifuse-healthcheck.timer /etc/systemd/system/
sudo cp verifuse-orchestrator.service /etc/systemd/system/
sudo cp verifuse-orchestrator.timer /etc/systemd/system/
sudo cp verifuse-vertex.service /etc/systemd/system/
sudo cp verifuse-vertex.timer /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable verifuse-api
sudo systemctl start verifuse-api

# Enable timers
sudo systemctl enable verifuse-scrapers.timer
sudo systemctl start verifuse-scrapers.timer

# Verify
sudo systemctl status verifuse-api
sudo systemctl list-timers | grep verifuse
```

---

## Step 7: Set Up Caddy (SSL + Reverse Proxy)

Install Caddy:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

Deploy the Caddyfile:

```bash
sudo cp /home/schlieve001/origin/continuity_lab/verifuse_v2/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

**Prerequisites:**
- DNS A record for `verifuse.tech` pointing to your server IP
- Ports 80 and 443 open in firewall
- React frontend built: `cd verifuse/site/app && npm run build`

Caddy automatically obtains and renews Let's Encrypt TLS certificates.

---

## Step 8: Build Frontend

```bash
cd /home/schlieve001/origin/continuity_lab/verifuse/site/app
npm install
npm run build
# Output: dist/ directory served by Caddy
```

---

## Step 9: Run Initial Scrape

```bash
# Check county status
python -m verifuse_v2.scrapers.runner --status

# Dry run first (discover PDFs without downloading)
python -m verifuse_v2.scrapers.runner --all --dry-run

# Full run
python -m verifuse_v2.scrapers.runner --all

# Process downloaded PDFs through Engine V2
python -m verifuse_v2.scrapers.engine_v2

# Score and grade all leads
python -m verifuse_v2.core.pipeline --evaluate-all

# Clean up ghost leads
python -m verifuse_v2.db.quarantine
```

---

## Step 10: Verify Production

```bash
# API health
curl https://verifuse.tech/health

# Leads endpoint
curl https://verifuse.tech/api/leads?limit=5

# Stats
curl https://verifuse.tech/api/stats

# Morning report
python -m verifuse_v2.scripts.morning_report
```

---

## Daily Routine

1. **Morning:** `python -m verifuse_v2.scripts.morning_report`
2. **Automated:** Scrapers run at 2 AM via systemd timer
3. **As needed:** `python -m verifuse_v2.core.pipeline --evaluate-all` to re-score
4. **Weekly:** `python -m verifuse_v2.db.quarantine` to clean ghost leads
5. **Monitor:** `journalctl -u verifuse-api --since "1 hour ago"`
