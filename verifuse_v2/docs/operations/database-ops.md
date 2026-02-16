# Database Operations

**Engine:** SQLite 3
**Mode:** WAL (Write-Ahead Logging)
**Location:** `verifuse_v2/data/verifuse_v2.db`

---

## WAL Mode

VeriFuse uses WAL mode for concurrent read/write access. The API server reads while scrapers write, without blocking.

```sql
-- Verify WAL mode
PRAGMA journal_mode;
-- Should return: wal
```

### WAL Checkpoint

The WAL file (`verifuse_v2.db-wal`) grows as writes accumulate. Checkpointing merges the WAL back into the main database file.

```bash
# Manual checkpoint (run periodically or before backup)
sqlite3 $VERIFUSE_DB_PATH "PRAGMA wal_checkpoint(TRUNCATE);"
```

The quarantine script (`quarantine.py`) always runs a WAL checkpoint before any mutations.

**When to checkpoint:**
- Before creating a database backup
- If the WAL file exceeds 100 MB
- If the `/health` endpoint shows `wal_pages` > 1000
- Before copying the database to another machine

---

## Backup

### Quick Backup

```bash
# Step 1: Checkpoint WAL
sqlite3 $VERIFUSE_DB_PATH "PRAGMA wal_checkpoint(TRUNCATE);"

# Step 2: Copy the database file
cp $VERIFUSE_DB_PATH /home/schlieve001/backups/verifuse_v2_$(date +%Y%m%d_%H%M%S).db
```

### Online Backup (Recommended)

SQLite's `.backup` command creates a consistent snapshot even while the database is in use:

```bash
sqlite3 $VERIFUSE_DB_PATH ".backup /home/schlieve001/backups/verifuse_v2_$(date +%Y%m%d).db"
```

### Automated Backup Script

```bash
#!/bin/bash
BACKUP_DIR=/home/schlieve001/backups
DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
sqlite3 $DB_PATH ".backup $BACKUP_DIR/verifuse_v2_$TIMESTAMP.db"

# Keep only last 7 backups
ls -t $BACKUP_DIR/verifuse_v2_*.db | tail -n +8 | xargs rm -f 2>/dev/null

echo "Backup complete: $BACKUP_DIR/verifuse_v2_$TIMESTAMP.db"
```

---

## Quarantine

The quarantine engine moves low-quality leads from `leads` to `leads_quarantine`:

```bash
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
python -m verifuse_v2.db.quarantine
```

### What Gets Quarantined

| Criteria | Reason Code |
|----------|-------------|
| `confidence_score <= 0.15` AND `surplus_amount = 0` AND source is post-sale continuance | `VERTEX_GHOST_ZERO_VALUE` |
| County is Eagle or San Miguel AND surplus = 0 | `PORTAL_DEBT_ONLY_NO_SURPLUS` |

Additionally, Jefferson County false-GOLD leads (GOLD grade but no bid data and zero surplus) are **demoted** to `PIPELINE_STAGING` (not moved to quarantine).

### Review Quarantined Leads

```sql
-- Count by reason
SELECT quarantine_reason, COUNT(*) as cnt
FROM leads_quarantine
GROUP BY quarantine_reason;

-- View specific quarantined leads
SELECT id, county, case_number, surplus_amount, confidence_score, quarantine_reason
FROM leads_quarantine
ORDER BY quarantined_at DESC
LIMIT 20;
```

### Restore a Lead from Quarantine

```sql
-- Move a lead back to leads (manual recovery)
INSERT INTO leads SELECT * FROM leads_quarantine WHERE id = '<lead_id>';
DELETE FROM leads_quarantine WHERE id = '<lead_id>';
```

---

## Migrations

Migrations are in `verifuse_v2/db/migrate*.py`. They are run manually and are idempotent (safe to run multiple times).

```bash
# Base schema
python -m verifuse_v2.db.migrate

# Titanium schema (Sprint 6)
python -m verifuse_v2.db.migrate_titanium

# Master schema (Sprint 9)
python -m verifuse_v2.db.migrate_master

# Sprint 11 schema
python -m verifuse_v2.db.migrate_sprint11

# Fix leads schema (if needed)
python -m verifuse_v2.db.fix_leads_schema

# Migrate billing plans
python -m verifuse_v2.db.migrate_plans
```

### Adding a Column

To add a column to the leads table:

```sql
ALTER TABLE leads ADD COLUMN new_column TEXT DEFAULT '';
```

SQLite does not support `ALTER TABLE ... DROP COLUMN` or `ALTER TABLE ... MODIFY COLUMN`. To restructure a table, you must create a new table, copy data, drop old, and rename.

---

## Quick Audit Queries

### Lead Inventory

```sql
-- Total leads by grade
SELECT data_grade, COUNT(*) as cnt,
       COALESCE(SUM(surplus_amount), 0) as total_surplus,
       COALESCE(AVG(surplus_amount), 0) as avg_surplus
FROM leads
GROUP BY data_grade
ORDER BY total_surplus DESC;

-- Leads by county
SELECT county, COUNT(*) as cnt,
       COALESCE(SUM(surplus_amount), 0) as total
FROM leads
WHERE surplus_amount > 0
GROUP BY county
ORDER BY total DESC;

-- GOLD leads with high surplus
SELECT id, county, case_number, surplus_amount,
       confidence_score, sale_date, claim_deadline
FROM leads
WHERE data_grade = 'GOLD'
ORDER BY surplus_amount DESC
LIMIT 20;
```

### Lead Quality

```sql
-- Leads missing key fields
SELECT county,
    SUM(CASE WHEN owner_name IS NULL OR owner_name = '' THEN 1 ELSE 0 END) as no_owner,
    SUM(CASE WHEN property_address IS NULL OR property_address = '' THEN 1 ELSE 0 END) as no_addr,
    SUM(CASE WHEN sale_date IS NULL THEN 1 ELSE 0 END) as no_date,
    COUNT(*) as total
FROM leads
GROUP BY county
ORDER BY total DESC;

-- Confidence score distribution
SELECT
    CASE
        WHEN confidence_score >= 0.8 THEN 'HIGH (>=0.8)'
        WHEN confidence_score >= 0.5 THEN 'MEDIUM (0.5-0.8)'
        WHEN confidence_score > 0 THEN 'LOW (<0.5)'
        ELSE 'ZERO'
    END as bracket,
    COUNT(*) as cnt
FROM leads
GROUP BY bracket;
```

### User Activity

```sql
-- Active users
SELECT user_id, email, tier, credits_remaining, last_login_at
FROM users
WHERE is_active = 1
ORDER BY last_login_at DESC;

-- Unlock history
SELECT u.email, lu.lead_id, lu.plan_tier, lu.unlocked_at
FROM lead_unlocks lu
JOIN users u ON lu.user_id = u.user_id
ORDER BY lu.unlocked_at DESC
LIMIT 20;

-- Credit usage by tier
SELECT u.tier, COUNT(*) as unlocks,
       COUNT(DISTINCT lu.user_id) as unique_users
FROM lead_unlocks lu
JOIN users u ON lu.user_id = u.user_id
GROUP BY u.tier;
```

### Pipeline Health

```sql
-- Recent pipeline events
SELECT event_type, COUNT(*) as cnt
FROM pipeline_events
WHERE created_at >= datetime('now', '-24 hours')
GROUP BY event_type
ORDER BY cnt DESC;

-- Scraper success rate
SELECT
    REPLACE(asset_id, 'SCRAPER:', '') as county,
    SUM(CASE WHEN event_type='SCRAPER_SUCCESS' THEN 1 ELSE 0 END) as ok,
    SUM(CASE WHEN event_type='SCRAPER_ERROR' THEN 1 ELSE 0 END) as err
FROM pipeline_events
WHERE event_type LIKE 'SCRAPER_%'
  AND created_at >= datetime('now', '-7 days')
GROUP BY county;
```

### Database Size

```sql
-- Table sizes (approximate row counts)
SELECT 'leads' as tbl, COUNT(*) as rows FROM leads
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'lead_unlocks', COUNT(*) FROM lead_unlocks
UNION ALL SELECT 'leads_quarantine', COUNT(*) FROM leads_quarantine
UNION ALL SELECT 'pipeline_events', COUNT(*) FROM pipeline_events
UNION ALL SELECT 'vertex_usage', COUNT(*) FROM vertex_usage
UNION ALL SELECT 'vertex_queue', COUNT(*) FROM vertex_queue
UNION ALL SELECT 'download_audit', COUNT(*) FROM download_audit
UNION ALL SELECT 'lead_provenance', COUNT(*) FROM lead_provenance;
```

---

## Integrity Checks

```bash
# SQLite integrity check
sqlite3 $VERIFUSE_DB_PATH "PRAGMA integrity_check;"
# Should return: ok

# Foreign key check
sqlite3 $VERIFUSE_DB_PATH "PRAGMA foreign_key_check;"
# Should return empty (no violations)

# Quick optimization (do not run while API is under load)
sqlite3 $VERIFUSE_DB_PATH "PRAGMA optimize;"
```

---

## Emergency: Database Recovery

If the database file is corrupted:

```bash
# Try to recover
sqlite3 $VERIFUSE_DB_PATH ".recover" | sqlite3 recovered.db

# Or dump and reload
sqlite3 $VERIFUSE_DB_PATH ".dump" > dump.sql
sqlite3 new_verifuse_v2.db < dump.sql
```

If WAL is corrupted but the main DB file is fine:

```bash
# Delete WAL and SHM files (data in WAL will be lost)
rm $VERIFUSE_DB_PATH-wal $VERIFUSE_DB_PATH-shm
```
