# VeriFuse Runbook

## Start / Stop / Restart

```bash
# API server
bin/vf api-start
bin/vf api-stop
bin/vf api-restart

# Scraper timer (nightly 02:00)
systemctl enable --now verifuse-scrapers.timer
systemctl stop verifuse-scrapers.timer
systemctl disable verifuse-scrapers.timer

# Full service status
bin/vf status
```

## Logs

```bash
bin/vf logs-api        # tail API logs
bin/vf logs-scraper    # tail scraper logs
journalctl -u verifuse-scrapers --since "2 hours ago"
```

## Migrations

Migrations are idempotent — safe to re-run.

```bash
bin/vf migrate
```

Always run migrations before restarting the API after a code deploy.

## Health Check

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
# Expected: {"status": "ok", "db": "ok", ...}
```

## Gauntlet

```bash
bin/vf gauntlet        # full test including HTTP
bin/vf gauntlet --dry-run   # DB tests only (no server required)
# Target: >= 60 PASS
```

## Backup and Restore

```bash
# Backup (timestamped .bak file, online — DB stays live)
bin/vf backup-db

# Restore (ONLY when API is stopped)
bin/vf api-stop
cp "${VERIFUSE_DB_PATH}.bak.TIMESTAMP" "${VERIFUSE_DB_PATH}"
bin/vf api-start
```

## Common Failure Scenarios

### API fails to start — migration error
```bash
bin/vf migrate          # run migrations, check for errors
bin/vf api-restart
```

### Ingestion run stuck (stale RUNNING row)
The `ingest_runner` automatically marks RUNNING rows older than 2 hours as FAILED_STALE on startup. To manually clean up:
```bash
bin/vf db-shell
sqlite> UPDATE ingestion_runs SET status='FAILED_STALE', end_ts=strftime('%s','now')
        WHERE status='RUNNING' AND start_ts < strftime('%s','now') - 7200;
```

### Timer overlap blocked (flock)
If a scraper run is already in progress, the timer will fail with "Resource temporarily unavailable". This is expected and safe — the running job continues uninterrupted. Check:
```bash
bin/vf logs-scraper
systemctl show verifuse-scrapers.timer --property=LastTriggerUSec
```

### CAPTCHA blocking ingestion
See docs/INGESTION.md — HITL sentinel file procedure.

### Vault disk space
```bash
du -sh /var/lib/verifuse/vault/
# Evidence PDFs/TIFFs accumulate. Archive old cases as needed.
```

### Frontend not updating
```bash
bin/vf rebuild-frontend
# Then clear browser cache or hard-reload
```

## Timer Overlap Protection

`flock -n` (non-blocking) on `/var/lock/verifuse-ingest.lock` protects against:
1. systemd timer firing while a previous run is still active
2. Manual `bin/vf scraper-run-single` colliding with a timer-triggered run

If the lock is held, the new attempt exits immediately (no duplicate work).
The ongoing run completes normally. This is logged in journalctl.
