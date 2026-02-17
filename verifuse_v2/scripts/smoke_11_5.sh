#!/usr/bin/env bash
# Sprint 11.5 Smoke Test
# Usage: bash verifuse_v2/scripts/smoke_11_5.sh [BASE_URL]

set -euo pipefail

BASE="${1:-http://localhost:8000}"
PASS=0
FAIL=0

check() {
  local desc="$1" url="$2" expect="$3"
  local body
  body=$(curl -sf "$url" 2>/dev/null || echo "CURL_FAIL")
  if echo "$body" | grep -q "$expect"; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected '$expect')"
    FAIL=$((FAIL + 1))
  fi
}

check_absent() {
  local desc="$1" url="$2" forbidden="$3"
  local body
  body=$(curl -sf "$url" 2>/dev/null || echo "CURL_FAIL")
  if echo "$body" | grep -qi "$forbidden"; then
    echo "  FAIL: $desc (found forbidden '$forbidden')"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $desc (no '$forbidden' leak)"
    PASS=$((PASS + 1))
  fi
}

echo "=== Sprint 11.5 Smoke Test ==="
echo "Target: $BASE"
echo ""

echo "[1] Health Check"
check "GET /health returns ok" "$BASE/health" "ok"

echo ""
echo "[2] Preview Endpoint"
check "GET /api/preview/leads returns leads" "$BASE/api/preview/leads?limit=3" "preview_key"
check_absent "Preview has no asset_id" "$BASE/api/preview/leads?limit=3" "asset_id"
check_absent "Preview has no case_number" "$BASE/api/preview/leads?limit=3" "case_number"
check_absent "Preview has no owner_name" "$BASE/api/preview/leads?limit=3" "owner_name"
check_absent "Preview has no property_address" "$BASE/api/preview/leads?limit=3" "property_address"

echo ""
echo "[3] Stats Endpoint"
check "GET /api/stats returns verified_pipeline" "$BASE/api/stats" "verified_pipeline"
check "GET /api/stats returns total_raw_volume" "$BASE/api/stats" "total_raw_volume"

echo ""
echo "[4] Leads Endpoint (default filters)"
check "GET /api/leads returns leads" "$BASE/api/leads?limit=3" "leads"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "All smoke tests passed."
