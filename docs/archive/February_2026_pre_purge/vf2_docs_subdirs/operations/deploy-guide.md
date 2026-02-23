# Deploy Guide

Complete deployment reference for VeriFuse V2 on a Debian/Ubuntu VPS.

---

## systemd Services

All service files are in `verifuse_v2/deploy/`. Copy them to `/etc/systemd/system/` and run `sudo systemctl daemon-reload`.

### verifuse-api.service

The core API server.

```ini
[Unit]
Description=VeriFuse V2 API Server (Titanium)
After=network.target

[Service]
Type=simple
User=schlieve001
WorkingDirectory=/home/schlieve001/origin/continuity_lab
ExecStart=/home/schlieve001/origin/continuity_lab/.venv/bin/uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3
EnvironmentFile=/home/schlieve001/verifuse_titanium_prod/secrets.env
MemoryMax=512M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
```

**Commands:**
```bash
sudo systemctl enable verifuse-api
sudo systemctl start verifuse-api
sudo systemctl status verifuse-api
sudo systemctl restart verifuse-api
journalctl -u verifuse-api -f              # Live logs
journalctl -u verifuse-api --since "1h"    # Last hour
```

### verifuse-scrapers.timer

Runs all enabled county scrapers daily at 2:00 AM with 15-minute jitter.

```ini
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=900
```

```bash
sudo systemctl enable verifuse-scrapers.timer
sudo systemctl start verifuse-scrapers.timer

# Check next scheduled run
systemctl list-timers | grep verifuse

# Manually trigger
sudo systemctl start verifuse-scrapers.service
```

### verifuse-healthcheck.timer

Periodic health checks.

### verifuse-orchestrator.timer

Pipeline orchestration (Engine V2 + scoring + quarantine).

### verifuse-vertex.timer

Vertex AI processing queue for non-standard PDFs.

---

## Caddy Configuration

File: `verifuse_v2/deploy/Caddyfile`

```
verifuse.tech {
    # API routes -> FastAPI backend
    handle /api/* {
        reverse_proxy localhost:8000
    }

    # Health check
    handle /health {
        reverse_proxy localhost:8000
    }

    # Stripe webhooks
    handle /api/webhooks/* {
        reverse_proxy localhost:8000
    }

    # React SPA -- static files, fallback to index.html
    handle {
        root * /home/schlieve001/origin/continuity_lab/verifuse/site/app/dist
        try_files {path} /index.html
        file_server
    }

    # Security headers
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }

    encode gzip
}
```

**Install Caddy:**
```bash
sudo apt install caddy
sudo cp verifuse_v2/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy
```

Caddy handles:
- Automatic TLS certificate provisioning via Let's Encrypt (ACME)
- Certificate renewal (automatic, no cron needed)
- HTTP to HTTPS redirect
- Gzip compression
- Security headers

**Prerequisites:**
- DNS A record: `verifuse.tech` -> server public IP
- Ports 80 and 443 open
- React app built in `/home/schlieve001/origin/continuity_lab/verifuse/site/app/dist`

---

## Environment Variables

All secrets are stored in `/home/schlieve001/verifuse_titanium_prod/secrets.env` (chmod 600). The systemd service loads this via `EnvironmentFile=`.

| Variable | Required | Example |
|----------|----------|---------|
| `VERIFUSE_DB_PATH` | Yes | `/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db` |
| `VERIFUSE_JWT_SECRET` | Yes | 64-character random string |
| `VERIFUSE_API_KEY` | Yes | 32-character random key for admin endpoints |
| `STRIPE_SECRET_KEY` | Billing | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Billing | `whsec_...` |
| `STRIPE_PRICE_RECON` | Billing | `price_...` |
| `STRIPE_PRICE_OPERATOR` | Billing | `price_...` |
| `STRIPE_PRICE_SOVEREIGN` | Billing | `price_...` |
| `VERIFUSE_BASE_URL` | Optional | `https://verifuse.tech` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Vertex AI | Path to Google Cloud credentials JSON |

**Generate secrets:**
```bash
# JWT secret
python -c "import secrets; print(secrets.token_hex(32))"

# API key
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Override per-service env vars without editing the unit file:**
```bash
sudo systemctl edit verifuse-api
# Add under [Service]:
#   Environment="EXTRA_VAR=value"
sudo systemctl restart verifuse-api
```

---

## SSL/TLS

Caddy manages SSL automatically. No manual certificate configuration is needed.

**To verify:**
```bash
curl -v https://verifuse.tech/health 2>&1 | grep "SSL certificate"
```

**If Caddy cannot obtain a certificate:**
1. Verify DNS resolves: `dig verifuse.tech +short`
2. Verify ports open: `sudo ss -tlnp | grep -E ':(80|443)'`
3. Check Caddy logs: `journalctl -u caddy --since "1h"`

---

## Deploy Workflow

### Standard Deploy (Sprint Update)

```bash
cd /home/schlieve001/origin/continuity_lab

# Pull latest code
git pull origin sprint-11

# Install any new dependencies
source .venv/bin/activate
pip install -r verifuse_v2/requirements.txt

# Run database migrations
python -m verifuse_v2.db.migrate_sprint11

# Rebuild frontend
cd verifuse/site/app
npm install
npm run build
cd /home/schlieve001/origin/continuity_lab

# Restart services
sudo systemctl restart verifuse-api
sudo systemctl restart caddy

# Verify
curl https://verifuse.tech/health
python -m verifuse_v2.scripts.morning_report
```

### Rollback

```bash
git log --oneline -5           # Find previous commit
git checkout <commit-hash>     # Roll back code
sudo systemctl restart verifuse-api
```

---

## Firewall Configuration

```bash
# Allow HTTP, HTTPS, and SSH
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Verify
sudo ufw status
```

Port 8000 should NOT be exposed publicly -- Caddy proxies all traffic.

---

## Resource Monitoring

```bash
# Memory usage
systemctl show verifuse-api --property=MemoryCurrent

# CPU usage
top -p $(pgrep -f uvicorn)

# Disk usage
du -sh verifuse_v2/data/
du -sh verifuse_v2/data/raw_pdfs/

# SQLite WAL file size
ls -lh verifuse_v2/data/verifuse_v2.db*
```
