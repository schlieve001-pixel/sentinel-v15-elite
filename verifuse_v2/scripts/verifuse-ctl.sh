#!/usr/bin/env bash
# verifuse-ctl.sh — VeriFuse Operations Control Script
# Usage: ./verifuse_v2/scripts/verifuse-ctl.sh <command>
#
# Commands:
#   status     — Show API service status, DB stats, wallet summary
#   logs       — Tail API server logs (last 50 lines)
#   restart    — Restart the API service
#   proofs     — Run production proofs (health, config, preview, smoke)
#   inventory  — Show lead inventory health
#   stripe-reconcile — Show Stripe event processing stats

set -euo pipefail

DB="${VERIFUSE_DB_PATH:-/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db}"
API="http://localhost:8000"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; }
info() { echo -e "  ${YELLOW}[INFO]${NC} $1"; }

case "${1:-help}" in
  status)
    echo "=== VeriFuse System Status ==="
    echo ""
    # Service status
    if systemctl is-active --quiet verifuse-api 2>/dev/null; then
      ok "verifuse-api service: active"
    else
      fail "verifuse-api service: inactive"
    fi
    # Health check
    if curl -sf "$API/health" > /dev/null 2>&1; then
      ok "API health: responsive"
    else
      fail "API health: unreachable"
    fi
    # DB stats
    echo ""
    echo "--- Database ---"
    if [ -f "$DB" ]; then
      ok "DB file: $DB ($(du -h "$DB" | cut -f1))"
      echo "  Leads:    $(sqlite3 "$DB" 'SELECT COUNT(*) FROM leads')"
      echo "  Users:    $(sqlite3 "$DB" 'SELECT COUNT(*) FROM users')"
      echo "  Unlocks:  $(sqlite3 "$DB" 'SELECT COUNT(*) FROM lead_unlocks')"
      echo "  Wallets:  $(sqlite3 "$DB" 'SELECT COUNT(*) FROM wallet')"
      echo "  Founders: $(sqlite3 "$DB" 'SELECT COUNT(*) FROM founders_redemptions')/$(grep FOUNDERS_MAX_SLOTS /etc/verifuse/verifuse.env 2>/dev/null | cut -d= -f2 || echo '?')"
    else
      fail "DB file not found: $DB"
    fi
    # Git
    echo ""
    echo "--- Git ---"
    echo "  Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
    echo "  SHA:    $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
    ;;

  logs)
    echo "=== API Server Logs (last 50) ==="
    sudo journalctl -u verifuse-api -n 50 --no-pager
    ;;

  restart)
    echo "Restarting verifuse-api..."
    sudo systemctl restart verifuse-api
    sleep 3
    if systemctl is-active --quiet verifuse-api; then
      ok "Service restarted successfully"
    else
      fail "Service failed to start"
      sudo journalctl -u verifuse-api -n 10 --no-pager
    fi
    ;;

  proofs)
    echo "=== Production Proofs ==="
    echo ""
    # Health
    HEALTH=$(curl -sf "$API/health" 2>/dev/null)
    if [ $? -eq 0 ]; then
      ok "Health endpoint"
      echo "  $HEALTH" | python3 -m json.tool 2>/dev/null | head -5
    else
      fail "Health endpoint unreachable"
    fi
    echo ""
    # Public config
    CONFIG=$(curl -sf "$API/api/public-config" 2>/dev/null)
    if [ $? -eq 0 ]; then
      ok "Public config"
      echo "  $CONFIG" | python3 -m json.tool 2>/dev/null
    else
      fail "Public config unreachable"
    fi
    echo ""
    # Preview leads
    PREVIEW=$(curl -sf "$API/api/preview/leads?limit=1" 2>/dev/null)
    if echo "$PREVIEW" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d.get('leads',[])) > 0" 2>/dev/null; then
      ok "Preview endpoint returns leads"
    else
      fail "Preview endpoint empty or failed"
    fi
    echo ""
    # Vary header
    VARY=$(curl -sf -D- "$API/health" 2>/dev/null | grep -i "^Vary:" || echo "")
    if [ -n "$VARY" ]; then
      ok "Vary header present: $VARY"
    else
      info "No Vary header (may be normal for health)"
    fi
    ;;

  inventory)
    echo "=== Lead Inventory Health ==="
    if [ ! -f "$DB" ]; then
      fail "DB not found"
      exit 1
    fi
    echo ""
    sqlite3 -header -column "$DB" "
      SELECT
        'Total' as metric, COUNT(*) as value FROM leads
      UNION ALL SELECT
        'Active (surplus>100, not REJECT)', COUNT(*) FROM leads
        WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100 AND data_grade != 'REJECT'
      UNION ALL SELECT
        'GOLD grade', COUNT(*) FROM leads WHERE data_grade = 'GOLD'
      UNION ALL SELECT
        'SILVER grade', COUNT(*) FROM leads WHERE data_grade = 'SILVER'
      UNION ALL SELECT
        'BRONZE grade', COUNT(*) FROM leads WHERE data_grade = 'BRONZE'
      UNION ALL SELECT
        'REJECT grade', COUNT(*) FROM leads WHERE data_grade = 'REJECT'
      UNION ALL SELECT
        'New (last 7d)', COUNT(*) FROM leads WHERE sale_date >= date('now', '-7 days')
      UNION ALL SELECT
        'Quarantined', COUNT(*) FROM leads_quarantine;
    "
    echo ""
    echo "--- By County ---"
    sqlite3 -header -column "$DB" "
      SELECT county, COUNT(*) as leads,
        ROUND(SUM(COALESCE(estimated_surplus, surplus_amount, 0)), 2) as total_surplus
      FROM leads
      WHERE COALESCE(estimated_surplus, surplus_amount, 0) > 100
      GROUP BY county ORDER BY total_surplus DESC LIMIT 15;
    "
    ;;

  stripe-reconcile)
    echo "=== Stripe Event Processing ==="
    if [ ! -f "$DB" ]; then
      fail "DB not found"
      exit 1
    fi
    sqlite3 -header -column "$DB" "
      SELECT type, COUNT(*) as count, MAX(received_at) as last_received
      FROM stripe_events GROUP BY type ORDER BY count DESC;
    "
    echo ""
    echo "--- Transaction Summary ---"
    sqlite3 -header -column "$DB" "
      SELECT type, COUNT(*) as count, SUM(credits) as total_credits
      FROM transactions GROUP BY type ORDER BY count DESC;
    "
    ;;

  help|*)
    echo "verifuse-ctl — VeriFuse Operations Control"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  status            Service status, DB stats, wallet summary"
    echo "  logs              Tail API server logs"
    echo "  restart           Restart the API service"
    echo "  proofs            Run production proofs"
    echo "  inventory         Lead inventory health report"
    echo "  stripe-reconcile  Stripe event processing stats"
    echo ""
    ;;
esac
