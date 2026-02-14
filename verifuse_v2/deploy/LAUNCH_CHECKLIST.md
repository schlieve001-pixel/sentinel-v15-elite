# VERIFUSE V2 — Production Launch Checklist

## Pre-Launch (Do These First)

### 1. DNS
- [ ] A record: `verifuse.tech` → your server IP
- [ ] Optional: `www.verifuse.tech` → same IP (Caddy handles redirect)

### 2. Environment Variables
Create `/etc/verifuse.env` or set in systemd:
```
VERIFUSE_JWT_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_RECON=price_...
STRIPE_PRICE_OPERATOR=price_...
STRIPE_PRICE_SOVEREIGN=price_...
VERIFUSE_BASE_URL=https://verifuse.tech
```

### 3. Stripe Setup
- [ ] Create Stripe account (or use existing)
- [ ] Create 3 Products in Stripe Dashboard:
  - VeriFuse Recon: $199/month recurring
  - VeriFuse Operator: $399/month recurring
  - VeriFuse Sovereign: $699/month recurring
- [ ] Copy each Price ID into env vars above
- [ ] Add webhook endpoint: `https://verifuse.tech/api/webhooks/stripe`
  - Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`

### 4. Database Migration
```bash
source .venv/bin/activate
python3 -m verifuse_v2.db.migrate
```
Verify: should report 714 assets migrated, 12 GOLD, 12 ATTORNEY.

## Deploy Steps

### 5. Install System Dependencies
```bash
sudo apt update && sudo apt install -y caddy python3-venv
```

### 6. Python Environment
```bash
cd /home/schlieve001/origin/continuity_lab
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn bcrypt pyjwt stripe fpdf pillow requests beautifulsoup4
```

### 7. Build Frontend
```bash
# If node not installed:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.0/install.sh | bash
source ~/.nvm/nvm.sh
nvm install 22

cd verifuse/site/app
npm install
npx vite build
```

### 8. Install Services
```bash
# API service
sudo cp verifuse_v2/deploy/verifuse-api.service /etc/systemd/system/
# Edit the service file to set real env vars:
sudo systemctl edit verifuse-api
# Then:
sudo systemctl daemon-reload
sudo systemctl enable verifuse-api
sudo systemctl start verifuse-api

# Caddy
sudo cp verifuse_v2/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

### 9. Verify
```bash
# API health
curl https://verifuse.tech/health

# Should return:
# {"status":"ok","engine":"product_api","version":"2.0.0","assets":714,...}

# Frontend
curl -s https://verifuse.tech | head -5
# Should show HTML with <div id="root">
```

## Post-Launch

### 10. Smoke Test
- [ ] Visit https://verifuse.tech — landing page loads with live stats
- [ ] Click "BROWSE ASSETS" — dashboard shows real leads
- [ ] Register a test account — receives JWT
- [ ] Login with test account — dashboard shows tier + credits
- [ ] Click DOSSIER on a lead — PDF downloads
- [ ] Click UNLOCK INTEL — redirects to login if not auth'd, or deducts credit and reveals PII
- [ ] Check Stripe test payment (use test mode first)

### 11. Security
- [ ] JWT secret is NOT the default dev value
- [ ] No Airtable API keys in frontend code
- [ ] CORS origins in api.py include `https://verifuse.tech`
- [ ] Honeypot TRAP_999 present in /api/leads response
- [ ] Accessing TRAP_999 detail returns 403 and blacklists IP

### 12. Monitoring
```bash
# Check API logs
sudo journalctl -u verifuse-api -f

# Check Caddy logs
sudo journalctl -u caddy -f
```

## Quick Reference

| Component | Location |
|---|---|
| API server | `verifuse_v2/server/api.py` |
| Database | `verifuse_v2/data/verifuse_v2.db` |
| Frontend build | `verifuse/site/app/dist/` |
| Caddy config | `verifuse_v2/deploy/Caddyfile` |
| systemd service | `verifuse_v2/deploy/verifuse-api.service` |
| Launch script (dev) | `verifuse_v2/deploy/launch.sh` |
