#!/usr/bin/env bash
# VERIFUSE V2 — Atomic Deploy (Blue/Green Symlink Swap)
#
# Usage:
#   bash verifuse_v2/deploy/deploy.sh [version]
#   bash verifuse_v2/deploy/deploy.sh 8.0.0
#
# Creates:
#   ~/verifuse_titanium_prod/releases/v{version}/  — code copy
#   ~/verifuse_titanium_prod/current               — symlink to new release
#   ~/verifuse_titanium_prod/data/                  — persistent (never touched)
#   ~/verifuse_titanium_prod/logs/                  — persistent
#   ~/verifuse_titanium_prod/secrets.env            — JWT + API keys (chmod 600)

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
PROD_ROOT="$HOME/verifuse_titanium_prod"
GIT_REPO="$HOME/origin/continuity_lab"
VERSION="${1:-8.0.0}"
RELEASE_DIR="$PROD_ROOT/releases/v${VERSION}"
DATA_DIR="$PROD_ROOT/data"
LOGS_DIR="$PROD_ROOT/logs"
SECRETS_FILE="$PROD_ROOT/secrets.env"
DB_NAME="verifuse_v2.db"

echo "============================================================"
echo "  VERIFUSE ATOMIC DEPLOY — v${VERSION}"
echo "  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"

# ── Step 1: Create directory structure ───────────────────────────────
echo "[1/7] Creating directory structure..."
mkdir -p "$PROD_ROOT/releases"
mkdir -p "$DATA_DIR"
mkdir -p "$LOGS_DIR"

# ── Step 2: Generate secrets.env if it doesn't exist ─────────────────
if [ ! -f "$SECRETS_FILE" ]; then
    echo "[2/7] Generating secrets.env..."
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    API_KEY=$(python3 -c "import secrets; print('vfk_' + secrets.token_urlsafe(32))")
    cat > "$SECRETS_FILE" <<SECRETS_EOF
# VERIFUSE PRODUCTION SECRETS — generated $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# chmod 600 — DO NOT commit to git
VERIFUSE_JWT_SECRET=${JWT_SECRET}
VERIFUSE_API_KEY=${API_KEY}
VERIFUSE_DB_PATH=${DATA_DIR}/${DB_NAME}
GOOGLE_APPLICATION_CREDENTIALS=${HOME}/google_credentials.json
VERIFUSE_BASE_URL=https://verifuse.tech
SECRETS_EOF
    chmod 600 "$SECRETS_FILE"
    echo "  secrets.env created (chmod 600)"
else
    echo "[2/7] secrets.env already exists — skipping generation"
fi

# ── Step 3: WAL checkpoint on source DB before copy ──────────────────
echo "[3/7] WAL checkpoint on source database..."
SOURCE_DB="$GIT_REPO/verifuse_v2/data/$DB_NAME"
if [ -f "$SOURCE_DB" ]; then
    sqlite3 "$SOURCE_DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
    echo "  WAL checkpoint complete"
else
    echo "  WARNING: Source DB not found at $SOURCE_DB"
fi

# ── Step 4: Copy code to versioned release directory ─────────────────
echo "[4/7] Copying code to releases/v${VERSION}/..."
if [ -d "$RELEASE_DIR" ]; then
    echo "  WARNING: Release v${VERSION} already exists — overwriting"
    rm -rf "$RELEASE_DIR"
fi

mkdir -p "$RELEASE_DIR"
# Copy application code (exclude data, .venv, __pycache__, .git)
rsync -a \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='verifuse_v2/data' \
    --exclude='verifuse_v2/logs' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    "$GIT_REPO/" "$RELEASE_DIR/"

echo "  Code copied to $RELEASE_DIR"

# ── Step 5: Copy DB to persistent data dir (first deploy only) ───────
echo "[5/7] Setting up persistent data directory..."
if [ ! -f "$DATA_DIR/$DB_NAME" ]; then
    if [ -f "$SOURCE_DB" ]; then
        cp "$SOURCE_DB" "$DATA_DIR/$DB_NAME"
        echo "  Database copied to $DATA_DIR/$DB_NAME"
    else
        echo "  WARNING: No source DB to copy"
    fi
else
    echo "  Database already exists in data dir — not overwriting"
fi

# ── Step 6: Atomic symlink swap ──────────────────────────────────────
echo "[6/7] Atomic symlink swap..."
CURRENT_LINK="$PROD_ROOT/current"
# Use mv for atomic swap (rename is atomic on same filesystem)
ln -sfn "$RELEASE_DIR" "${CURRENT_LINK}.new"
mv -Tf "${CURRENT_LINK}.new" "$CURRENT_LINK"
echo "  current -> releases/v${VERSION}"

# ── Step 7: Restart systemd services ────────────────────────────────
echo "[7/7] Restarting services..."
if systemctl is-active --quiet verifuse-api 2>/dev/null; then
    sudo systemctl restart verifuse-api
    echo "  verifuse-api restarted"
else
    echo "  verifuse-api not active (skip restart)"
fi

# ── Summary ──────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  DEPLOY COMPLETE — v${VERSION}"
echo "============================================================"
echo "  Release:  $RELEASE_DIR"
echo "  Symlink:  $CURRENT_LINK -> releases/v${VERSION}"
echo "  Data:     $DATA_DIR/$DB_NAME"
echo "  Secrets:  $SECRETS_FILE"
echo "  Logs:     $LOGS_DIR/"
echo ""
echo "  Verify:   curl http://localhost:8000/health"
echo "============================================================"
