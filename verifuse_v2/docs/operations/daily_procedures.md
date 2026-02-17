# Daily Operating Procedures

## Morning Checklist

1. **Run morning report**
   ```bash
   python -m verifuse_v2.scripts.morning_report
   ```
   Verify: new leads appeared, no scraper failures, Vertex AI budget under cap.

2. **Check API health**
   ```bash
   curl -s https://verifuse.tech/health | python -m json.tool
   ```
   Verify: `status: "ok"`, `wal_pages < 1000`, `total_leads` increasing.

3. **Run coverage report**
   ```bash
   python -m verifuse_v2.scripts.coverage_report
   ```
   Verify all active counties have recent data.

4. **Run data audit**
   ```bash
   python -m verifuse_v2.scripts.data_audit
   ```
   Check for: duplicates, orphaned records, grade distribution anomalies.

## Weekly Tasks

### Monday: Full Pipeline Run + Audit

```bash
# Run full scraper pipeline
python -m verifuse_v2.scrapers.runner

# Run daily healthcheck (regrade + dedup)
python -m verifuse_v2.daily_healthcheck

# Generate coverage report
python -m verifuse_v2.scripts.coverage_report

# Full data audit
python -m verifuse_v2.scripts.data_audit
```

### Thursday: Database Maintenance

```bash
# WAL checkpoint
sqlite3 $VERIFUSE_DB_PATH "PRAGMA wal_checkpoint(TRUNCATE);"

# Check DB size
ls -lh $VERIFUSE_DB_PATH*

# Disk space
df -h /home/schlieve001/
```

## Smoke Testing After Deploy

After any deploy, run the smoke test:

```bash
bash verifuse_v2/scripts/smoke_11_5.sh https://verifuse.tech
```

Expected: all tests PASS. Specifically verifies:
- Health endpoint returns OK
- Preview endpoint returns leads without PII
- Stats endpoint includes `verified_pipeline` and `total_raw_volume`
- Leads endpoint returns data

## Incident Response

### API Down
```bash
sudo systemctl status verifuse-api
sudo systemctl restart verifuse-api
journalctl -u verifuse-api --since "10 minutes ago"
```

### Scraper Failure
```bash
journalctl -u verifuse-scrapers.service --since "yesterday"
# Check pipeline_events for COUNTY_SCRAPE_ERROR events
sqlite3 $VERIFUSE_DB_PATH "SELECT * FROM pipeline_events WHERE event_type='COUNTY_SCRAPE_ERROR' ORDER BY created_at DESC LIMIT 10;"
```

### Database Locked
```bash
# Check for WAL buildup
ls -lh $VERIFUSE_DB_PATH*
# Force checkpoint
sqlite3 $VERIFUSE_DB_PATH "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Stripe Not Working
Check that `STRIPE_SECRET_KEY` is set in `secrets.env`. The API returns 503 on `/api/billing/checkout` if missing.

## Key Metrics to Monitor

| Metric | Normal Range | Action if Abnormal |
|--------|-------------|-------------------|
| New leads/day | 1-20 | Check scraper timers |
| WAL pages | < 1000 | Run WAL checkpoint |
| Vertex AI PDFs/day | < 40 | Review queue priority |
| Quarantine % | < 20% | Review quarantine reasons |
| Disk usage | < 80% | Clean old PDFs |
| API response time | < 500ms | Check DB indexes |
