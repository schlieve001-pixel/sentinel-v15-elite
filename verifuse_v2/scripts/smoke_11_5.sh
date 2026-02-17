#!/usr/bin/env bash
# Sprint 11.5 Smoke Test (Hardening PR)
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

check_header() {
  local desc="$1" url="$2" header="$3" expect="$4"
  local val
  # Use -D- with GET (not -I/HEAD) so GET-only endpoints don't 405
  val=$(curl -s -D- -o /dev/null "$url" 2>/dev/null | grep -i "^$header:" | head -1 || echo "")
  if echo "$val" | grep -qi "$expect"; then
    echo "  PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (header '$header' missing or unexpected: $val)"
    FAIL=$((FAIL + 1))
  fi
}

check_status() {
  local desc="$1" url="$2" expect_code="$3"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$code" = "$expect_code" ]; then
    echo "  PASS: $desc (HTTP $code)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $desc (expected HTTP $expect_code, got $code)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Sprint 11.5 Smoke Test (Hardening PR) ==="
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
check "GET /api/leads has preview_key field" "$BASE/api/leads?limit=3" "preview_key"
check "GET /api/leads has unlocked_by_me field" "$BASE/api/leads?limit=3" "unlocked_by_me"

echo ""
echo "[5] Sample Dossier"
# Extract first preview_key from preview endpoint
PREVIEW_KEY=$(curl -sf "$BASE/api/preview/leads?limit=1" 2>/dev/null | grep -o '"preview_key":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "")
if [ -n "$PREVIEW_KEY" ]; then
  check_status "Sample dossier returns 200" "$BASE/api/dossier/sample/$PREVIEW_KEY" "200"
  check_header "Sample dossier Content-Type" "$BASE/api/dossier/sample/$PREVIEW_KEY" "content-type" "application/pdf"
  check_header "Sample dossier Cache-Control" "$BASE/api/dossier/sample/$PREVIEW_KEY" "cache-control" "no-store"
  check_status "Bad preview_key returns 404" "$BASE/api/dossier/sample/000000000000000000000000" "404"
else
  echo "  SKIP: No preview leads available for sample dossier test"
fi

echo ""
echo "[6] Vary Header"
check_header "Vary includes Authorization" "$BASE/health" "vary" "Authorization"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
echo "All smoke tests passed."
