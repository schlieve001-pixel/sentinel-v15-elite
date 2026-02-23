# VeriFuse Operations Guide

Production operations reference for the VeriFuse platform.

## System Overview

| Component | Technology | Port | Managed By |
|-----------|------------|------|------------|
| API Server | FastAPI + Uvicorn | 8000 | systemd (`verifuse-api`) |
| Frontend | React 19 + Vite | — | Caddy static files |
| TLS Proxy | Caddy | 443 | systemd (`caddy`) |
| Database | SQLite (WAL mode) | — | File-based |
| Secrets | `/etc/verifuse/verifuse.env` | — | systemd EnvironmentFile |

## Service Management

```bash
# Status
sudo systemctl status verifuse-api
sudo systemctl status caddy

# Restart
sudo systemctl restart verifuse-api
sudo systemctl reload caddy          # Caddy supports hot reload

# Logs
sudo journalctl -u verifuse-api -f              # Follow live
sudo journalctl -u verifuse-api -n 100           # Last 100 lines
sudo journalctl -u verifuse-api --since "1h ago" # Last hour
```

## verifuse-ctl CLI

The operations control script at `verifuse_v2/scripts/verifuse-ctl.sh`:

```bash
./verifuse_v2/scripts/verifuse-ctl.sh status           # Service + DB + Git
./verifuse_v2/scripts/verifuse-ctl.sh logs              # Last 50 log lines
./verifuse_v2/scripts/verifuse-ctl.sh restart            # Restart + verify
./verifuse_v2/scripts/verifuse-ctl.sh proofs             # Health, config, preview, Vary
./verifuse_v2/scripts/verifuse-ctl.sh inventory          # Lead inventory breakdown
./verifuse_v2/scripts/verifuse-ctl.sh stripe-reconcile   # Stripe event + transaction stats
```

## Database Management

### Location
- Production: `/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db`
- Env var: `VERIFUSE_DB_PATH`

### Backups

```bash
# Manual backup
cp verifuse_v2/data/verifuse_v2.db "verifuse_v2/data/backup_$(date +%s).db"

# WAL checkpoint (flush pending writes)
sqlite3 verifuse_v2/data/verifuse_v2.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Migrations

```bash
# Run all pending migrations (safe, idempotent, file-locked)
python3 verifuse_v2/migrations/run_migrations.py

# Specify custom DB path
python3 verifuse_v2/migrations/run_migrations.py --db /path/to/db
```

Migration runner behavior:
- Acquires file lock (`/tmp/verifuse_migrate.lock`) — fails fast if another migration running
- Applies SQLite hardening pragmas (WAL, FK, busy_timeout)
- Adds missing columns to `users` table
- Renames tier `recon` → `scout`
- Deduplicates leads (county + case_number)
- Creates new tables (wallet, transactions, etc.)
- Makes county+case index UNIQUE
- Backfills wallet from `users.credits_remaining`

### Key Tables

| Table | Purpose |
|-------|---------|
| `leads` | All scraped lead data |
| `users` | User accounts |
| `wallet` | Dual-credit wallet (subscription + purchased) |
| `transactions` | Immutable transaction ledger |
| `lead_unlocks` | Unlock records (deduplicated) |
| `stripe_events` | Webhook idempotency |
| `founders_redemptions` | Founders pricing slots |
| `audit_log` | Financial + admin action log |
| `user_daily_lead_views` | Per-user daily view tracking |
| `rate_limits` | Rate limit timestamps |

## Secrets Management

### Production Secrets File

Location: `/etc/verifuse/verifuse.env`
Permissions: `600` (owner read/write only)
Loaded by: systemd `EnvironmentFile` directive

```bash
# View (requires sudo)
sudo cat /etc/verifuse/verifuse.env

# Edit
sudo nano /etc/verifuse/verifuse.env

# After editing, restart to pick up changes
sudo systemctl daemon-reload
sudo systemctl restart verifuse-api
```

### Rotating Secrets

```bash
# Generate new secrets
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'  # JWT
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'  # HMAC

# Update /etc/verifuse/verifuse.env with new values
sudo nano /etc/verifuse/verifuse.env

# Restart (invalidates all existing JWT tokens)
sudo systemctl restart verifuse-api
```

**Warning**: Rotating `VERIFUSE_JWT_SECRET` invalidates all active sessions.
Rotating `PREVIEW_HMAC_SECRET` changes all preview keys (bookmarks break).

## Stripe Configuration

### Setup

1. Create products in Stripe Dashboard:
   - "VeriFuse Scout" → $49/month recurring
   - "VeriFuse Operator" → $149/month recurring
   - "VeriFuse Sovereign" → $499/month recurring
   - "VeriFuse Starter Pack" → $19 one-time

2. Copy price IDs to `/etc/verifuse/verifuse.env`:
   ```
   STRIPE_TEST_PRICE_SCOUT=price_xxx
   STRIPE_TEST_PRICE_OPERATOR=price_xxx
   STRIPE_TEST_PRICE_SOVEREIGN=price_xxx
   STRIPE_TEST_PRICE_STARTER=price_xxx
   ```

3. Set webhook endpoint in Stripe Dashboard:
   - URL: `https://verifuse.tech/api/webhook`
   - Events: `checkout.session.completed`, `invoice.payment_succeeded`, `customer.subscription.deleted`

4. Copy webhook signing secret:
   ```
   STRIPE_TEST_WEBHOOK_SECRET=whsec_xxx
   ```

### Going Live

1. Set `STRIPE_MODE=live` in env file
2. Populate `STRIPE_LIVE_*` variables
3. Restart service

## Deployment

### Standard Deploy

```bash
# Pull latest code
git checkout main && git pull

# Run migrations (safe, idempotent)
python3 verifuse_v2/migrations/run_migrations.py

# Build frontend
cd verifuse/site/app && npm ci && npm run build && cd -

# Restart API
sudo systemctl restart verifuse-api

# Verify
./verifuse_v2/scripts/verifuse-ctl.sh proofs
python3 verifuse_v2/tests/smoke_gauntlet.py
```

### Rollback Procedure

```bash
# 1. Stop service
sudo systemctl stop verifuse-api

# 2. Restore database backup
cp verifuse_v2/data/backup_omega_final_<timestamp>.db verifuse_v2/data/verifuse_v2.db

# 3. Revert code
git checkout <last-known-good-sha>

# 4. Rebuild frontend
cd verifuse/site/app && npm run build && cd -

# 5. Restart
sudo systemctl start verifuse-api

# 6. Verify
./verifuse_v2/scripts/verifuse-ctl.sh proofs
```

## Monitoring

### Health Endpoint

```bash
curl -s https://verifuse.tech/health | python3 -m json.tool
```

Returns: status, engine version, DB path, WAL pages, lead counts by grade, quarantine count, verified total.

### Inventory Health

```bash
curl -s https://verifuse.tech/api/inventory_health | python3 -m json.tool
```

Returns: active_leads, total_leads, new_last_7d, completeness_pct.

### Frontend Health Poll

The Dashboard polls `/health` every 30 seconds. Indicator shows:
- Green dot + "SYSTEM LIVE" when healthy
- Red dot + "SYSTEM ERROR" when unreachable

### Audit Log

```bash
# Recent audit entries
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT created_at, user_id, action FROM audit_log ORDER BY created_at DESC LIMIT 20;"

# Unlock activity
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT created_at, user_id, action, meta_json FROM audit_log WHERE action='lead_unlock' ORDER BY created_at DESC LIMIT 10;"
```

## Troubleshooting

### API Won't Start

```bash
# Check logs
sudo journalctl -u verifuse-api -n 50 --no-pager

# Common issues:
# - VERIFUSE_DB_PATH not set → check /etc/verifuse/verifuse.env
# - VERIFUSE_JWT_SECRET not set → add to env file
# - Port 8000 in use → check with: ss -tlnp | grep 8000
# - Python deps missing → pip install -r verifuse_v2/requirements.txt
```

### Database Locked

```bash
# Check WAL status
sqlite3 verifuse_v2/data/verifuse_v2.db "PRAGMA wal_checkpoint(PASSIVE);"

# Force checkpoint
sqlite3 verifuse_v2/data/verifuse_v2.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Migration Lock Stuck

```bash
# Remove stale lock
rm -f /tmp/verifuse_migrate.lock

# Re-run
python3 verifuse_v2/migrations/run_migrations.py
```

### Stripe Webhooks Not Working

```bash
# Check event processing
./verifuse_v2/scripts/verifuse-ctl.sh stripe-reconcile

# Verify webhook secret matches Stripe Dashboard
sudo grep WEBHOOK_SECRET /etc/verifuse/verifuse.env

# Check Caddy is proxying /api/webhook to port 8000
```
