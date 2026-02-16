#!/usr/bin/env bash
set -euo pipefail

# ── Sprint 11 Deploy Script ────────────────────────────────────────
# Production-grade deployment with backup, migration, build, and smoke test.
#
# Usage:
#   ./deploy_sprint_11.sh             # Standard deploy (requires clean tree)
#   ./deploy_sprint_11.sh --force     # Skip dirty tree check
#   ./deploy_sprint_11.sh --commit    # Auto-commit before deploying

VENV_PYTHON="/home/schlieve001/origin/continuity_lab/.venv/bin/python"
VENV_PIP="/home/schlieve001/origin/continuity_lab/.venv/bin/pip"
WORK_DIR="/home/schlieve001/origin/continuity_lab"

FORCE=false
DO_COMMIT=false

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        --commit) DO_COMMIT=true ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

cd "$WORK_DIR"
echo "=================================================="
echo "  SPRINT 11 DEPLOY"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "=================================================="

# ── Step 0: Checkout sprint-11 ───────────────────────────────────
echo ""
echo "[0] Checking out sprint-11 branch..."
git checkout sprint-11

# ── Step 1: Dirty tree check ─────────────────────────────────────
echo ""
echo "[1] Checking working tree..."
if [ "$DO_COMMIT" = true ]; then
    if [ -n "$(git status --porcelain)" ]; then
        echo "  Auto-committing changes..."
        git add -A
        git commit -m "Sprint 11 pre-deploy auto-commit"
    fi
elif [ "$FORCE" != true ]; then
    if [ -n "$(git status --porcelain)" ]; then
        echo "  ERROR: Repo dirty! Use --force to skip or --commit to auto-commit"
        git status --short
        exit 1
    fi
fi
echo "  Working tree OK"

# ── Step 2: Set DB path ──────────────────────────────────────────
DB_PATH="${VERIFUSE_DB_PATH:-/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db}"
echo ""
echo "[2] DB path: $DB_PATH"

if [ ! -f "$DB_PATH" ]; then
    echo "  WARNING: Database file not found at $DB_PATH"
fi

# ── Step 3: Timestamped backup ───────────────────────────────────
BACKUP_PATH="${DB_PATH}.bak_$(date +%Y%m%d_%H%M%S)"
echo ""
echo "[3] Backing up database..."
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_PATH"
    echo "  Backup: $BACKUP_PATH"
else
    echo "  Skipping backup (no DB file)"
fi

# ── Step 4: Install dependencies ─────────────────────────────────
echo ""
echo "[4] Installing Python dependencies..."
$VENV_PIP install -r verifuse_v2/requirements.txt -q

# ── Step 5: Run idempotent migrations ────────────────────────────
echo ""
echo "[5] Running Sprint 11 migrations..."
export VERIFUSE_DB_PATH="$DB_PATH"
$VENV_PYTHON -m verifuse_v2.db.migrate_sprint11

# ── Step 6: Build frontend ───────────────────────────────────────
echo ""
echo "[6] Building frontend..."
if [ -d "verifuse/site/app" ]; then
    cd verifuse/site/app
    if [ -f "package.json" ]; then
        npm run build 2>&1 || echo "  WARNING: Frontend build failed (non-fatal)"
    fi
    cd "$WORK_DIR"
else
    echo "  Skipping frontend build (directory not found)"
fi

# ── Step 7: Restart API ──────────────────────────────────────────
echo ""
echo "[7] Restarting API service..."
sudo systemctl restart verifuse-api 2>/dev/null || echo "  WARNING: systemctl restart failed (service may not exist)"

# ── Step 8: Local smoke test ─────────────────────────────────────
echo ""
echo "[8] Local smoke test..."
sleep 2
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "  localhost:8000/health — OK"
elif curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "  localhost:8000/api/health — OK"
else
    echo "  WARNING: Local health check failed (API may still be starting)"
fi

# ── Step 9: Public smoke test ────────────────────────────────────
echo ""
echo "[9] Public smoke test..."
if curl -sf https://verifuse.tech/health > /dev/null 2>&1; then
    echo "  verifuse.tech/health — OK"
elif curl -sf https://verifuse.tech/api/health > /dev/null 2>&1; then
    echo "  verifuse.tech/api/health — OK"
else
    echo "  WARNING: Public health check failed"
fi

# ── Step 10: Morning report ──────────────────────────────────────
echo ""
echo "[10] Running morning report..."
$VENV_PYTHON -m verifuse_v2.scripts.morning_report 2>/dev/null || echo "  WARNING: Morning report failed"

# ── Rollback instructions ────────────────────────────────────────
echo ""
echo "=================================================="
echo "  DEPLOY COMPLETE"
echo "=================================================="
echo ""
echo "ROLLBACK:"
if [ -f "$BACKUP_PATH" ]; then
    echo "  cp $BACKUP_PATH $DB_PATH && git checkout main && sudo systemctl restart verifuse-api"
else
    echo "  git checkout main && sudo systemctl restart verifuse-api"
fi
echo ""
