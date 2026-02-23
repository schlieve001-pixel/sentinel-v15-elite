> Updated: February 23, 2026

# VeriFuse — Operator Runbook

## bin/vf Command Reference

```bash
bin/vf migrate                            # Apply all pending SQL migrations (001–009+)
bin/vf serve                              # FastAPI dev server on :8000
bin/vf gauntlet                           # Full test suite — must pass 62+
bin/vf scrape <county>                    # Run govsoft date-window scrape
bin/vf scrape <county> --case J2500346    # Single-case scrape
bin/vf scrape <county> --days 30          # Override lookback window (default 60)
bin/vf coverage <county> --days 60        # Browser vs DB coverage audit
```

---

## Database Operations

### WAL Mode
The database runs in WAL (Write-Ahead Log) mode. Never change this.

```bash
sqlite3 verifuse_v2/data/verifuse_v2.db "PRAGMA journal_mode"
# Expected: wal
```

WAL allows concurrent reads without blocking writes. `busy_timeout = 30000 ms` is set on every connection. If you see "database is locked" errors, check for hung processes holding a write lock:

```bash
lsof verifuse_v2/data/verifuse_v2.db
```

### Backup
```bash
# Hot backup (WAL-safe — use sqlite3 .backup, not cp)
sqlite3 verifuse_v2/data/verifuse_v2.db ".backup /tmp/verifuse_backup_$(date +%Y%m%d_%H%M%S).db"
```

### Migrations
Migrations 001–005 are applied by `run_migrations.py` in numbered phases.
Migrations 006+ are auto-discovered: any `0NN_*.sql` file not yet in `migrations_log` is applied in order.

```bash
bin/vf migrate          # Safe to run repeatedly — all migrations are idempotent
```

To check which migrations have been applied:
```bash
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT filename, datetime(applied_ts, 'unixepoch') FROM migrations_log ORDER BY filename"
```

---

## Scraper Operations

### Running a County Scrape
```bash
# Jefferson County — 60-day rolling window (default)
bin/vf scrape jefferson

# Arapahoe County — 30-day window
bin/vf scrape arapahoe --days 30

# Single case
bin/vf scrape jefferson --case J2500346
```

### CAPTCHA HITL (Human-in-the-Loop)
Some counties have `captcha_mode = 'entry'` in `govsoft_county_configs`. When the scraper hits a CAPTCHA gate, it pauses and prints:

```
[HITL] County: jefferson, Case: J2500346
[HITL] Solve CAPTCHA in browser, then press Enter to continue (or 'skip' to skip):
```

Open the browser (set `GOVSOFT_HEADLESS=0` to see it), solve the CAPTCHA, then press Enter. Type `skip` to skip the case and continue the run.

```bash
GOVSOFT_HEADLESS=0 bin/vf scrape jefferson --case J2500346
```

### County Config
County scraper config lives in `govsoft_county_configs`:

```bash
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT county, base_url, search_path, page_limit, captcha_mode, active FROM govsoft_county_configs"
```

To add a new county:
```sql
INSERT INTO govsoft_county_configs
  (county, base_url, requires_accept_terms, captcha_mode, documents_enabled, active, search_path)
VALUES ('newcounty', 'https://example.govsoft.com/', 1, 'none', 1, 1, '/SearchDetails.aspx');
```

---

## Coverage Audit

The coverage audit compares the browser-visible case count (from the GovSoft search results page) to the DB count for a given county and date window.

```bash
python3 -m verifuse_v2.scripts.coverage_audit --county jefferson --days 60
# [JEFFERSON] Browser: 47 | DB: 47 | Delta: 0
# PASS: Perfect match. Pipeline integrity verified.

python3 -m verifuse_v2.scripts.coverage_audit --county arapahoe --days 60
```

**Exit codes:**
- `0` — PASS: browser count == DB count (or DB >= browser)
- `1` — FAIL: delta > 0 (cases in browser not in DB — run a scrape)
- `2` — UNKNOWN: browser count undetectable (manual verification required)
- `3` — ERROR: form state mismatch after submission

Results are written to `county_ingestion_runs`:
```bash
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT county, browser_count, db_count, delta, status, datetime(run_ts,'unixepoch')
   FROM county_ingestion_runs ORDER BY run_ts DESC LIMIT 10"
```

---

## Gate 4 — Dual-Validation

Gate 4 runs automatically after each case is scraped. To re-run extraction for a specific asset:

```bash
python3 -m verifuse_v2.ingest.govsoft_extract --asset-id FORECLOSURE:CO:JEFFERSON:J2500346
```

Check audit results:
```bash
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT asset_id, data_grade, match_html_math, match_voucher, snapshot_id
   FROM surplus_math_audit
   WHERE asset_id LIKE '%JEFFERSON%'
   ORDER BY audit_ts DESC LIMIT 10"
```

**BRONZE / NEEDS_REVIEW common causes:**
- Voucher (OB doc) present but Gate 5 OCR not yet run — blocked fail-closed until OCR
- `successful_bid` or `total_indebtedness` missing from SALE_INFO HTML
- Math mismatch > $0.01 — requires manual review
- No SALE_INFO snapshot — case scraped before SALE_INFO tab was available

---

## Equity Resolution

```bash
python3 -c "
import sqlite3
from verifuse_v2.core.equity_resolution_engine import resolve
db = sqlite3.connect('verifuse_v2/data/verifuse_v2.db')
db.row_factory = sqlite3.Row
result = resolve('FORECLOSURE:CO:JEFFERSON:J2500346', db)
print(result)
"
```

Check recent classifications:
```bash
sqlite3 verifuse_v2/data/verifuse_v2.db \
  "SELECT asset_id, classification, notes FROM equity_resolution ORDER BY resolved_ts DESC LIMIT 10"
```

---

## Common Failures

### "database is locked"
1. Check for hung processes: `lsof verifuse_v2/data/verifuse_v2.db`
2. Kill the hung process or wait for `busy_timeout` (30 s)
3. If persistent, check WAL file: `ls -la verifuse_v2/data/verifuse_v2.db-wal` — if > 10 MB, a checkpoint is overdue. Run: `sqlite3 verifuse_v2/data/verifuse_v2.db "PRAGMA wal_checkpoint(TRUNCATE)"`

### Scraper timeout / download failed
- GovSoft document downloads sometimes time out. The scraper logs `Doc download failed for ...` and continues.
- Increase timeout: set `GOVSOFT_DOC_TIMEOUT=60000` (ms) env var
- Check headless: `GOVSOFT_HEADLESS=0 bin/vf scrape jefferson --case J2500346` to watch the browser

### Coverage FAIL (delta > 0)
1. Run a full scrape for the county: `bin/vf scrape jefferson --days 60`
2. Re-run the audit: `bin/vf coverage jefferson --days 60`
3. If delta persists, check for CONTINUANCE cases (sale postponed — no sale_date yet)

### Migration fails
- All migrations use `IF NOT EXISTS` — safe to re-run
- If a pre-hook fails (e.g., dedupe probe on `user_daily_lead_views`), check the log output and fix data manually before re-running `bin/vf migrate`

### BFCache PII leak (manual test)
1. Log in → navigate to `/leads` → log out → press Back in browser
2. Expected: page does NOT show PII (redirect to login or blank)
3. If PII is visible: check `Cache-Control: no-store` header on `/api/leads`:
   `curl -si http://localhost:8000/api/leads -H "Authorization: Bearer $TOKEN" | grep -i cache-control`

---

## Stress Test

```bash
export VF_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"..."}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
export API_BASE=http://localhost:8000

python3 verifuse_v2/scripts/stress_test.py
# Expected: PASS: 0 database lock errors, 0 5xx errors
```
