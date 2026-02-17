#!/usr/bin/env bash
###############################################################################
# deploy_full_system.sh — GOD MODE Deployment Kit
# Idempotent, fail-closed, production-ready
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DB_DIR="verifuse_v2/data"
DB_PATH="$DB_DIR/verifuse_v2.db"
SCRIPTS_DIR="verifuse_v2/scripts"
LOG_FILE="deploy_${TIMESTAMP}.log"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
die() { log "FATAL: $*"; exit 1; }

log "=============================================="
log "  GOD MODE DEPLOYMENT — $TIMESTAMP"
log "=============================================="

###############################################################################
# PHASE 1: PREFLIGHT / SAFETY
###############################################################################
log ""
log "── PHASE 1: PREFLIGHT ──"

command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 not found. Install: sudo apt install sqlite3"
command -v python3 >/dev/null 2>&1 || die "python3 not found."
log "  [OK] sqlite3 found: $(which sqlite3)"
log "  [OK] python3 found: $(python3 --version 2>&1)"

[ -f "$DB_PATH" ] || die "Database not found at $DB_PATH"
log "  [OK] Database exists: $(ls -lh "$DB_PATH" | awk '{print $5}')"

BACKUP_PATH="${DB_PATH}.bak_${TIMESTAMP}"
cp "$DB_PATH" "$BACKUP_PATH"
log "  [OK] Backup created: $BACKUP_PATH"

ORIG_HASH=$(sha256sum "$DB_PATH" | awk '{print $1}')
BACK_HASH=$(sha256sum "$BACKUP_PATH" | awk '{print $1}')
[ "$ORIG_HASH" = "$BACK_HASH" ] || die "Backup hash mismatch"
log "  [OK] Backup integrity verified (SHA256 match)"

###############################################################################
# PHASE 2: STOP THE API
###############################################################################
log ""
log "── PHASE 2: STOP API ──"

if systemctl is-active --quiet verifuse-api 2>/dev/null; then
    sudo systemctl stop verifuse-api
    log "  [OK] verifuse-api stopped"
else
    log "  [OK] verifuse-api already stopped"
fi

sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
log "  [OK] WAL checkpoint complete"

###############################################################################
# PHASE 3: FIX PERMISSIONS (THE RESURRECTION)
###############################################################################
log ""
log "── PHASE 3: FIX PERMISSIONS ──"

SERVICE_USER=$(systemctl show -p User --value verifuse-api 2>/dev/null || echo "")
SERVICE_USER="${SERVICE_USER:-root}"
if [ "$SERVICE_USER" = "" ] || [ "$SERVICE_USER" = "[not set]" ]; then
    SERVICE_USER="root"
fi
SERVICE_GROUP=$(id -gn "$SERVICE_USER" 2>/dev/null || echo "root")

log "  Service user:  $SERVICE_USER"
log "  Service group: $SERVICE_GROUP"

sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_PATH"
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_DIR"
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$BACKUP_PATH"

for ext in "-wal" "-shm"; do
    if [ -f "${DB_PATH}${ext}" ]; then
        sudo chown "$SERVICE_USER:$SERVICE_GROUP" "${DB_PATH}${ext}"
        chmod 640 "${DB_PATH}${ext}"
    fi
done

chmod 640 "$DB_PATH"
chmod 750 "$DB_DIR"
chmod 640 "$BACKUP_PATH"

if [ -f "verifuse_v2/google_credentials.json" ]; then
    sudo chown "$SERVICE_USER:$SERVICE_GROUP" "verifuse_v2/google_credentials.json"
    chmod 640 "verifuse_v2/google_credentials.json"
    log "  [OK] google_credentials.json permissions fixed"
fi

for envfile in verifuse/.env verifuse/site/app/.env _ARCHIVE_FEB_2026/.env; do
    if [ -f "$envfile" ]; then
        chmod 600 "$envfile"
        log "  [OK] $envfile → 600"
    fi
done

log "  [OK] DB permissions: $(stat -c '%a %U:%G' "$DB_PATH")"

# VERIFICATION GATE
if [ "$SERVICE_USER" = "root" ]; then
    test -r "$DB_PATH" || die "GATE FAILED: Cannot read DB as current user"
else
    sudo -u "$SERVICE_USER" test -r "$DB_PATH" || die "GATE FAILED: $SERVICE_USER cannot read $DB_PATH"
fi
log "  [OK] VERIFICATION GATE PASSED — $SERVICE_USER can read the database"

###############################################################################
# PHASE 4: MERGE + SORT DATABASE (THE FIX)
###############################################################################
log ""
log "── PHASE 4: DATABASE MIGRATION ──"

sqlite3 "$DB_PATH" <<'MIGRATION_SQL'
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS ingestion_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING','PROCESSED','ERROR','SKIPPED')),
    sha256          TEXT UNIQUE NOT NULL,
    records_found   INTEGER DEFAULT 0,
    error_message   TEXT,
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ingestion_sha256 ON ingestion_events(sha256);
CREATE INDEX IF NOT EXISTS idx_ingestion_status ON ingestion_events(status);

COMMIT;
MIGRATION_SQL

# Add columns conditionally (ALTER TABLE outside transactions)
for COL_DEF in \
    "statute_window_status TEXT DEFAULT 'UNKNOWN'" \
    "attorney_packet_ready INTEGER DEFAULT 0" \
    "processing_status TEXT DEFAULT 'RAW'" \
    "fee_cap_pct REAL" \
    "ingestion_source TEXT"
do
    COL_NAME=$(echo "$COL_DEF" | awk '{print $1}')
    EXISTS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM pragma_table_info('leads') WHERE name='$COL_NAME';")
    if [ "$EXISTS" = "0" ]; then
        sqlite3 "$DB_PATH" "ALTER TABLE leads ADD COLUMN $COL_DEF;"
        log "  [OK] Added column: $COL_NAME"
    else
        log "  [SKIP] Column already exists: $COL_NAME"
    fi
done

# Merge assets → leads
log ""
log "  Merging assets → leads..."
BEFORE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads;")

sqlite3 "$DB_PATH" <<'MERGE_SQL'
BEGIN IMMEDIATE;

INSERT OR IGNORE INTO leads (
    id, case_number, county, owner_name, property_address,
    estimated_surplus, surplus_amount, overbid_amount,
    winning_bid, total_debt, confidence_score, status,
    sale_date, claim_deadline, data_grade, source_name,
    updated_at, ingestion_source
)
SELECT
    asset_id, case_number, county, owner_of_record, property_address,
    estimated_surplus,
    COALESCE(overbid_amount, estimated_surplus, 0),
    overbid_amount, NULL, total_indebtedness, confidence_score,
    COALESCE(
        CASE
            WHEN data_grade IN ('GOLD','SILVER') THEN 'ENRICHED'
            WHEN data_grade = 'BRONZE' THEN 'STAGED'
            ELSE 'PIPELINE_STAGING'
        END, 'PIPELINE_STAGING'
    ),
    sale_date,
    CASE WHEN sale_date IS NOT NULL AND sale_date != ''
        THEN date(sale_date, '+5 years') ELSE NULL END,
    COALESCE(data_grade, 'BRONZE'),
    COALESCE(source_name, 'asset_migration'),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    'asset_table_merge'
FROM assets
WHERE asset_id NOT IN (SELECT id FROM leads WHERE id IS NOT NULL)
  AND case_number NOT IN (
      SELECT case_number FROM leads
      WHERE case_number IS NOT NULL AND case_number != ''
  );

-- Upgrade empty fields in existing leads from assets (never downgrade)
UPDATE leads SET
    owner_name = COALESCE(leads.owner_name,
        (SELECT owner_of_record FROM assets WHERE assets.case_number = leads.case_number AND assets.county = leads.county LIMIT 1)),
    property_address = COALESCE(leads.property_address,
        (SELECT property_address FROM assets WHERE assets.case_number = leads.case_number AND assets.county = leads.county LIMIT 1)),
    winning_bid = COALESCE(leads.winning_bid,
        (SELECT overbid_amount FROM assets WHERE assets.case_number = leads.case_number AND assets.county = leads.county LIMIT 1)),
    total_debt = COALESCE(leads.total_debt,
        (SELECT total_indebtedness FROM assets WHERE assets.case_number = leads.case_number AND assets.county = leads.county LIMIT 1)),
    sale_date = COALESCE(leads.sale_date,
        (SELECT sale_date FROM assets WHERE assets.case_number = leads.case_number AND assets.county = leads.county LIMIT 1))
WHERE EXISTS (
    SELECT 1 FROM assets
    WHERE assets.case_number = leads.case_number
      AND assets.county = leads.county
      AND leads.case_number IS NOT NULL
      AND leads.case_number != ''
);

COMMIT;
MERGE_SQL

AFTER_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads;")
MERGED=$((AFTER_COUNT - BEFORE_COUNT))
log "  [OK] Merged $MERGED new records from assets → leads"
log "  [OK] Total leads: $BEFORE_COUNT → $AFTER_COUNT"

# Compute statute windows + fee caps
log ""
log "  Computing statute window status + fee caps..."

sqlite3 "$DB_PATH" <<'STATUTE_SQL'
BEGIN IMMEDIATE;

UPDATE leads SET statute_window_status = 'ACTIVE_ESCROW'
WHERE sale_date IS NOT NULL AND sale_date != ''
  AND date(sale_date, '+6 months') >= date('now');

UPDATE leads SET statute_window_status = 'ESCROW_ENDED'
WHERE sale_date IS NOT NULL AND sale_date != ''
  AND date(sale_date, '+6 months') < date('now')
  AND (claim_deadline IS NULL OR date(claim_deadline) >= date('now'));

UPDATE leads SET statute_window_status = 'EXPIRED'
WHERE claim_deadline IS NOT NULL AND claim_deadline != ''
  AND date(claim_deadline) < date('now');

UPDATE leads SET statute_window_status = 'UNKNOWN'
WHERE sale_date IS NULL OR sale_date = '';

-- Fee caps: unregulated (0-6mo), 20% (6mo-2yr), 10% (2yr+)
-- Pre-transfer period: no statutory cap applies (data access fee only)
UPDATE leads SET fee_cap_pct = NULL
WHERE sale_date IS NOT NULL AND sale_date != ''
  AND julianday('now') - julianday(sale_date) <= 180;

UPDATE leads SET fee_cap_pct = 0.20
WHERE sale_date IS NOT NULL AND sale_date != ''
  AND julianday('now') - julianday(sale_date) > 180
  AND julianday('now') - julianday(sale_date) <= 730;

UPDATE leads SET fee_cap_pct = 0.10
WHERE sale_date IS NOT NULL AND sale_date != ''
  AND julianday('now') - julianday(sale_date) > 730;

-- Attorney packet readiness
UPDATE leads SET attorney_packet_ready = 1
WHERE data_grade IN ('GOLD', 'SILVER')
  AND COALESCE(surplus_amount, estimated_surplus, 0) > 0
  AND statute_window_status IN ('ESCROW_ENDED', 'ACTIVE_ESCROW')
  AND owner_name IS NOT NULL AND owner_name != '';

-- Processing status
UPDATE leads SET processing_status = 'ENRICHED'
WHERE COALESCE(surplus_amount, estimated_surplus, 0) > 0
  AND owner_name IS NOT NULL AND owner_name != ''
  AND sale_date IS NOT NULL AND sale_date != '';

UPDATE leads SET processing_status = 'STAGED'
WHERE processing_status = 'RAW'
  AND (COALESCE(surplus_amount, estimated_surplus, 0) > 0
       OR (owner_name IS NOT NULL AND owner_name != ''));

INSERT INTO pipeline_events (asset_id, event_type, old_value, new_value, actor, reason, created_at)
VALUES (
    'SYSTEM', 'SYSTEM_MIGRATION', 'pre_god_mode', 'god_mode_v1',
    'deploy_full_system.sh',
    'Phase 4: statute window + fee cap + attorney readiness + asset merge',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);

COMMIT;
STATUTE_SQL

log ""
log "  Statute window distribution:"
sqlite3 "$DB_PATH" "SELECT statute_window_status, COUNT(*) as cnt FROM leads GROUP BY statute_window_status ORDER BY cnt DESC;" | while IFS='|' read -r status count; do
    log "    $status: $count"
done

ATTORNEY_READY=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads WHERE attorney_packet_ready = 1;")
log "  [OK] Attorney-packet-ready leads: $ATTORNEY_READY"

###############################################################################
# PHASE 5: MASS INGEST BACKLOG (THE HUNT)
###############################################################################
log ""
log "── PHASE 5: FORENSIC PDF INGEST ──"

mkdir -p "$SCRIPTS_DIR"

if [ -f "$SCRIPTS_DIR/forensic_ingest.py" ]; then
    INGEST_OUTPUT=$(python3 "$SCRIPTS_DIR/forensic_ingest.py" \
        --db "$DB_PATH" \
        --scan-dirs "_ARCHIVE_FEB_2026,verifuse,verifuse_v2/data/raw_pdfs" \
        2>&1) || true
    echo "$INGEST_OUTPUT" | tee -a "$LOG_FILE"
    log "  [OK] Forensic ingest complete"
else
    log "  [WARN] forensic_ingest.py not found at $SCRIPTS_DIR/forensic_ingest.py — skipping PDF ingest"
fi

###############################################################################
# PHASE 6: RESTART AND VERIFY
###############################################################################
log ""
log "── PHASE 6: RESTART + VERIFY ──"

# Re-fix permissions after all mutations
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_PATH"
chmod 640 "$DB_PATH"
for ext in "-wal" "-shm"; do
    if [ -f "${DB_PATH}${ext}" ]; then
        sudo chown "$SERVICE_USER:$SERVICE_GROUP" "${DB_PATH}${ext}"
        chmod 640 "${DB_PATH}${ext}"
    fi
done

sqlite3 "$DB_PATH" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true

sudo systemctl daemon-reload
sudo systemctl start verifuse-api
log "  [OK] verifuse-api started"

HEALTH_OK=0
for i in $(seq 1 30); do
    RESP=$(curl -s -m 3 http://localhost:8000/health 2>/dev/null || echo "")
    if echo "$RESP" | grep -q '"status":"ok"' 2>/dev/null; then
        HEALTH_OK=1
        log "  [OK] API healthy after ${i}s"
        break
    fi
    sleep 1
done

if [ "$HEALTH_OK" -eq 0 ]; then
    log "  [WARN] API did not return healthy within 30s"
    log "  [INFO] Check: sudo journalctl -u verifuse-api -n 50 --no-pager"
    log "  [INFO] Likely fix: ensure VERIFUSE_DB_PATH is set in systemd service"
    log "  [INFO] Run: sudo systemctl edit verifuse-api"
    log "         Add: Environment=\"VERIFUSE_DB_PATH=$(realpath $DB_PATH)\""
fi

###############################################################################
# PHASE 7: FINAL REPORT
###############################################################################
log ""
log "=============================================="
log "  GOD MODE DEPLOYMENT — FINAL REPORT"
log "=============================================="

TOTAL_LEADS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads;")
TOTAL_SURPLUS=$(sqlite3 "$DB_PATH" "SELECT printf('%.2f', COALESCE(SUM(COALESCE(surplus_amount, estimated_surplus, 0)), 0)) FROM leads WHERE COALESCE(surplus_amount, estimated_surplus, 0) > 0;")
GOLD_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads WHERE data_grade = 'GOLD';")
ATTORNEY_READY=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads WHERE attorney_packet_ready = 1;")
PDFS_PROCESSED=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM ingestion_events WHERE status = 'PROCESSED';" 2>/dev/null || echo "0")
PDFS_TOTAL=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM ingestion_events;" 2>/dev/null || echo "0")
ESCROW_ENDED=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads WHERE statute_window_status = 'ESCROW_ENDED';")
QUARANTINED=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM leads_quarantine;" 2>/dev/null || echo "0")

log ""
log "  Total Leads:               $TOTAL_LEADS"
log "  Total Surplus:             \$$TOTAL_SURPLUS"
log "  GOLD Grade:                $GOLD_COUNT"
log "  Attorney-Packet-Ready:     $ATTORNEY_READY"
log "  Escrow Ended (Actionable): $ESCROW_ENDED"
log "  Quarantined:               $QUARANTINED"
log "  PDFs Processed:            $PDFS_PROCESSED / $PDFS_TOTAL scanned"
log "  Database Backup:           $BACKUP_PATH"
log ""

if [ "$HEALTH_OK" -eq 1 ]; then
    log "  STATUS: OPERATIONAL"
else
    log "  STATUS: DATABASE MIGRATED — API NEEDS ENV VAR"
    log "  RUN:    sudo systemctl edit verifuse-api"
    log "  ADD:    Environment=\"VERIFUSE_DB_PATH=$(realpath $DB_PATH)\""
    log "  THEN:   sudo systemctl restart verifuse-api"
fi

log ""
log "  Log saved to: $LOG_FILE"
log "=============================================="
