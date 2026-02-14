#!/usr/bin/env bash
# ============================================================================
# PROJECT TITAN — LAUNCHPAD
# ============================================================================
# Starts the Triple Node RTI Ecosystem:
#   WITNESS (8000) — Capture Engine
#   JUDGE   (8001) — Forensic Verifier
#   VAULT   (8002) — Merkle-Chained Ledger
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Colors
G='\033[0;32m'
R='\033[0;31m'
Y='\033[1;33m'
C='\033[0;36m'
W='\033[1;37m'
NC='\033[0m'

echo ""
echo -e "${G}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${G}║${W}        VERIFUSE PROJECT TITAN — LAUNCHPAD               ${G}║${NC}"
echo -e "${G}║${C}        RTI Protocol v3.0 | Triple Node                  ${G}║${NC}"
echo -e "${G}║${C}        Patent App #63/923,069                           ${G}║${NC}"
echo -e "${G}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ---- KILL OLD PROCESSES ----
echo -e "${Y}[1/5] Cleaning old processes...${NC}"
pkill -f "witness/server.py" 2>/dev/null || true
pkill -f "judge/api.py" 2>/dev/null || true
pkill -f "vault/store.py" 2>/dev/null || true
sleep 1
echo -e "${G}      Done.${NC}"

# ---- CHECK DEPENDENCIES ----
echo -e "${Y}[2/5] Checking dependencies...${NC}"
if ! python3 -c "import fastapi, uvicorn, pydantic, httpx" 2>/dev/null; then
    echo -e "${Y}      Installing dependencies...${NC}"
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
fi
echo -e "${G}      All dependencies OK.${NC}"

# ---- START VAULT (Port 8002) ----
echo -e "${Y}[3/5] Starting VAULT (Port 8002)...${NC}"
cd "$SCRIPT_DIR"
python3 vault/store.py > "$LOG_DIR/vault.log" 2>&1 &
VAULT_PID=$!
echo -e "${G}      VAULT started (PID: $VAULT_PID)${NC}"
sleep 1

# ---- START JUDGE (Port 8001) ----
echo -e "${Y}[4/5] Starting JUDGE (Port 8001)...${NC}"
python3 judge/api.py > "$LOG_DIR/judge.log" 2>&1 &
JUDGE_PID=$!
echo -e "${G}      JUDGE started (PID: $JUDGE_PID)${NC}"
sleep 1

# ---- START WITNESS (Port 8000) ----
echo -e "${Y}[5/5] Starting WITNESS (Port 8000)...${NC}"
python3 witness/server.py > "$LOG_DIR/witness.log" 2>&1 &
WITNESS_PID=$!
echo -e "${G}      WITNESS started (PID: $WITNESS_PID)${NC}"
sleep 2

# ---- HEALTH CHECK ----
echo ""
echo -e "${C}Running health checks...${NC}"

check_service() {
    local name=$1 url=$2
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "  ${G}[ONLINE]${NC} $name — $url"
        return 0
    else
        echo -e "  ${R}[FAILED]${NC} $name — $url"
        return 1
    fi
}

check_service "WITNESS" "http://localhost:8000/"
check_service "JUDGE  " "http://localhost:8001/health"
check_service "VAULT  " "http://localhost:8002/health"

# ---- PRINT ACCESS INFO ----
echo ""
echo -e "${G}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${G}║${W}  ALL SYSTEMS ONLINE                                     ${G}║${NC}"
echo -e "${G}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${G}║${NC}                                                          ${G}║${NC}"
echo -e "${G}║${NC}  WITNESS:  ${C}http://localhost:8000${NC}                         ${G}║${NC}"
echo -e "${G}║${NC}  JUDGE:    ${C}http://localhost:8001/docs${NC}                    ${G}║${NC}"
echo -e "${G}║${NC}  VAULT:    ${C}http://localhost:8002/docs${NC}                    ${G}║${NC}"
echo -e "${G}║${NC}                                                          ${G}║${NC}"
echo -e "${G}║${NC}  Logs:     ${Y}$LOG_DIR/${NC}                ${G}║${NC}"
echo -e "${G}║${NC}                                                          ${G}║${NC}"
echo -e "${G}║${NC}  PIDs:     Witness=$WITNESS_PID  Judge=$JUDGE_PID  Vault=$VAULT_PID      ${G}║${NC}"
echo -e "${G}║${NC}                                                          ${G}║${NC}"
echo -e "${G}║${NC}  Stop all: ${R}kill $WITNESS_PID $JUDGE_PID $VAULT_PID${NC}                       ${G}║${NC}"
echo -e "${G}║${NC}                                                          ${G}║${NC}"
echo -e "${G}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ---- TUNNEL (if available) ----
if command -v bore &> /dev/null; then
    echo -e "${Y}bore detected — starting tunnel to witness...${NC}"
    bore local 8000 --to bore.pub &
elif command -v cloudflared &> /dev/null; then
    echo -e "${Y}cloudflared detected — starting tunnel...${NC}"
    cloudflared tunnel --url http://localhost:8000 > "$LOG_DIR/tunnel.log" 2>&1 &
    sleep 3
    TUNNEL_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_DIR/tunnel.log" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        echo -e "${G}  TUNNEL: ${C}$TUNNEL_URL${NC}"
    fi
else
    echo -e "${Y}No tunnel tool found. For remote access install cloudflared:${NC}"
    echo -e "${C}  sudo dpkg -i cloudflared.deb${NC}"
    echo -e "${C}  Then re-run this script.${NC}"
fi

echo ""
echo -e "${W}Open ${C}http://localhost:8000${W} in your browser to begin.${NC}"
echo -e "${Y}Press Ctrl+C to stop all services.${NC}"
echo ""

# ---- KEEP ALIVE ----
wait
