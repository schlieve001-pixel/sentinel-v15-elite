#!/usr/bin/env bash
# VERIFUSE V2 — Launch Script
# Run this to start the full stack locally for development/testing.
#
# Usage: bash verifuse_v2/deploy/launch.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
V2="$ROOT/verifuse_v2"
SITE="$ROOT/verifuse/site/app"

echo "═══════════════════════════════════════════════════"
echo "  VERIFUSE V2 — Launch Sequence"
echo "═══════════════════════════════════════════════════"

# ── 1. Check Python venv ──────────────────────────────────────────
if [ ! -d "$ROOT/.venv" ]; then
    echo "[1/5] Creating Python venv..."
    python3 -m venv "$ROOT/.venv"
fi
source "$ROOT/.venv/bin/activate"

# ── 2. Install Python deps ───────────────────────────────────────
echo "[2/5] Installing Python dependencies..."
pip install -q fastapi uvicorn bcrypt pyjwt stripe fpdf pillow requests beautifulsoup4 2>/dev/null

# ── 3. Initialize database ──────────────────────────────────────
echo "[3/5] Initializing database..."
python3 -c "
from verifuse_v2.db import database as db
db.init_db()
print('  Database ready at:', db.DB_PATH)
"

# ── 4. Check if migration needed ────────────────────────────────
DB_COUNT=$(python3 -c "
from verifuse_v2.db import database as db
with db.get_db() as conn:
    n = conn.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
    print(n)
" 2>/dev/null || echo "0")

if [ "$DB_COUNT" = "0" ]; then
    echo "[3b/5] Running V1 → V2 migration..."
    python3 -m verifuse_v2.db.migrate
else
    echo "  $DB_COUNT assets already in database — skipping migration"
fi

# ── 5. Build frontend ──────────────────────────────────────────
echo "[4/5] Building frontend..."
if command -v npm &>/dev/null || [ -s "$HOME/.nvm/nvm.sh" ]; then
    [ -s "$HOME/.nvm/nvm.sh" ] && source "$HOME/.nvm/nvm.sh"
    (cd "$SITE" && npm install --silent 2>/dev/null && npx vite build 2>/dev/null)
    echo "  Frontend built to $SITE/dist/"
else
    echo "  WARNING: npm not found — skipping frontend build"
fi

# ── 6. Start API server ────────────────────────────────────────
echo "[5/5] Starting API server on :8000..."
echo ""
echo "═══════════════════════════════════════════════════"
echo "  API:       http://localhost:8000"
echo "  Health:    http://localhost:8000/health"
echo "  Frontend:  Run 'cd $SITE && npx vite' for dev server"
echo "  Docs:      http://localhost:8000/docs"
echo "═══════════════════════════════════════════════════"
echo ""

uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000 --reload
