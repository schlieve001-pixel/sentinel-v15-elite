# Monitoring

## Morning Report

The morning report is the primary daily health check. Run it first thing every day:

```bash
python -m verifuse_v2.scripts.morning_report
```

Output sections:

```
============================================================
  VERIFUSE -- MORNING REPORT
  2026-02-16 08:00 UTC
============================================================

--- NEW LEADS (Last 24h) ---
  New leads:     12
  Total surplus: $234,567.00

--- SCRAPER HEALTH ---
  No recent failures

--- VERTEX AI BUDGET ---
  PDFs today:    3/50
  Est. cost:     $0.12

--- TOP NEW GOLD LEADS ---
  1. Denver       |  $125,000.00 | SMITH, JOHN
  2. Adams        |   $78,500.00 | DOE, JANE
  ...

--- SCOREBOARD ---
  GOLD          15 leads    $1,234,567.00
  SILVER        42 leads      $567,890.00
  BRONZE       128 leads      $345,678.00
  IRON          23 leads        $0.00

--- API HEALTH ---
  http://localhost:8000/health: OK

============================================================
```

---

## Health Endpoint

The `/health` endpoint provides real-time system status:

```bash
curl https://verifuse.tech/health | python -m json.tool
```

Response:

```json
{
    "status": "ok",
    "engine": "titanium_api_v4",
    "db": "/home/schlieve001/.../verifuse_v2.db",
    "wal_pages": 0,
    "total_leads": 185,
    "scoreboard": [
        {"data_grade": "GOLD", "lead_count": 15, "verified_surplus": 1234567.00},
        {"data_grade": "SILVER", "lead_count": 42, "verified_surplus": 567890.00},
        {"data_grade": "BRONZE", "lead_count": 128, "verified_surplus": 345678.00}
    ],
    "quarantined": 23,
    "verified_total": 2148135.00,
    "legal_disclaimer": "Forensic information service only..."
}
```

Key fields to monitor:
- `status`: Must be `"ok"`
- `wal_pages`: Should be low (< 1000). High values mean WAL is not checkpointing.
- `total_leads`: Should only increase over time
- `quarantined`: Number of leads in quarantine

---

## Log Locations

### systemd Journal

```bash
# API server logs
journalctl -u verifuse-api --since "1 hour ago"
journalctl -u verifuse-api -f                    # Live tail

# Scraper logs
journalctl -u verifuse-scrapers.service --since "yesterday"

# Health check logs
journalctl -u verifuse-healthcheck.service --since "1 hour ago"

# All VeriFuse services
journalctl -u 'verifuse-*' --since "today"
```

### Application Logs

```
verifuse_v2/logs/
  engine_v2_anomalies.jsonl    # Records that scored below 0.5 threshold
```

### Caddy Logs

```bash
journalctl -u caddy --since "1 hour ago"
```

---

## pipeline_events Table

The `pipeline_events` table is an append-only audit log. Every significant system event is recorded here.

### Query Recent Events

```sql
-- Last 20 events
SELECT event_type, asset_id, reason, created_at
FROM pipeline_events
ORDER BY created_at DESC
LIMIT 20;
```

### Scraper Health

```sql
-- Scraper success/failure counts (last 7 days)
SELECT
    event_type,
    COUNT(*) as count,
    MIN(created_at) as earliest,
    MAX(created_at) as latest
FROM pipeline_events
WHERE event_type LIKE 'SCRAPER_%'
  AND created_at >= datetime('now', '-7 days')
GROUP BY event_type;
```

### Grade Changes

```sql
-- Recent grade upgrades/downgrades
SELECT asset_id, old_value, new_value, reason, created_at
FROM pipeline_events
WHERE event_type = 'GRADE_CHANGE'
ORDER BY created_at DESC
LIMIT 20;
```

### Unlock Activity

```sql
-- Recent unlocks with credit details
SELECT asset_id, actor, old_value, new_value, reason, created_at
FROM pipeline_events
WHERE event_type = 'LEAD_UNLOCK'
ORDER BY created_at DESC
LIMIT 20;
```

### Quarantine Events

```sql
-- Quarantine batches
SELECT new_value, reason, created_at
FROM pipeline_events
WHERE event_type LIKE 'QUARANTINE%' OR event_type LIKE 'DEMOTE%'
ORDER BY created_at DESC
LIMIT 10;
```

---

## Alerts and Thresholds

### Things to Watch For

| Metric | Warning Threshold | Action |
|--------|------------------|--------|
| API health returns non-200 | Any failure | `sudo systemctl restart verifuse-api` |
| WAL pages > 1000 | Checkpoint stalled | Run `PRAGMA wal_checkpoint(TRUNCATE)` |
| No new leads in 48 hours | Scrapers may be failing | Check scraper logs and timer status |
| Vertex AI PDFs/day > 40 | Approaching daily cap of 50 | Review queue priority |
| Quarantine > 50% of total leads | Data quality issue | Review quarantine reasons |
| Disk usage > 80% | Running out of space | Clean old PDFs: `du -sh verifuse_v2/data/raw_pdfs/` |

### Manual Health Checks

```bash
# Is the API responding?
curl -s -o /dev/null -w "%{http_code}" https://verifuse.tech/health

# Is the database accessible?
sqlite3 $VERIFUSE_DB_PATH "SELECT COUNT(*) FROM leads;"

# Are timers active?
systemctl list-timers | grep verifuse

# Disk space
df -h /home/schlieve001/

# WAL file size
ls -lh $VERIFUSE_DB_PATH*
```

---

## Vertex AI Budget Monitoring

Vertex AI has a daily cap of 50 PDFs to control costs.

```sql
-- Today's Vertex usage
SELECT COUNT(*) as pdfs, SUM(cost_usd) as total_cost
FROM vertex_usage
WHERE date = date('now');

-- Usage trend (last 7 days)
SELECT date, COUNT(*) as pdfs, SUM(cost_usd) as cost
FROM vertex_usage
WHERE date >= date('now', '-7 days')
GROUP BY date
ORDER BY date;

-- Pending queue
SELECT COUNT(*) as pending
FROM vertex_queue
WHERE status = 'PENDING';
```

---

## Systemd Timer Verification

```bash
# List all VeriFuse timers
systemctl list-timers | grep verifuse

# Expected output:
# NEXT                         LEFT          LAST                         PASSED  UNIT
# Sun 2026-02-17 02:00:00 UTC  17h left      Sat 2026-02-16 02:12:34 UTC 5h ago  verifuse-scrapers.timer
```

If a timer shows "n/a" for NEXT, it may be disabled:

```bash
sudo systemctl enable verifuse-scrapers.timer
sudo systemctl start verifuse-scrapers.timer
```
