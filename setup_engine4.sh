#!/bin/bash
# setup_engine4.sh — Configure Google Cloud credentials for VeriFuse OCR engine.
#
# SECURITY: NEVER hardcode service account keys in this file.
# Supply credentials via one of the following methods:
#
#   Option A — Application Default Credentials (ADC, recommended):
#     gcloud auth application-default login
#     export GOOGLE_CLOUD_PROJECT="your-project-id"
#
#   Option B — Service account key file via .env:
#     Add to /etc/verifuse/verifuse.env (mode 600, owned by verifuse):
#       GOOGLE_APPLICATION_CREDENTIALS=/etc/verifuse/google_credentials.json
#       GOOGLE_CLOUD_PROJECT=your-project-id
#     Then: sudo chmod 600 /etc/verifuse/google_credentials.json
#
# NEVER commit a credentials JSON file to this repository.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="${VAULT_ROOT:-/var/lib/verifuse}"

# Resolve project from environment; abort if not set.
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-}"

if [[ -z "$GOOGLE_CLOUD_PROJECT" ]]; then
  echo "ERROR: GOOGLE_CLOUD_PROJECT is not set." >&2
  echo "       Set it in /etc/verifuse/verifuse.env or export it before running." >&2
  exit 1
fi

if [[ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
  # Try ADC — gcloud writes to a well-known location
  ADC_PATH="$HOME/.config/gcloud/application_default_credentials.json"
  if [[ -f "$ADC_PATH" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="$ADC_PATH"
    echo "[setup_engine4] Using ADC credentials: $ADC_PATH"
  else
    echo "ERROR: GOOGLE_APPLICATION_CREDENTIALS is not set and ADC file not found." >&2
    echo "       Run: gcloud auth application-default login" >&2
    echo "       Or set GOOGLE_APPLICATION_CREDENTIALS in /etc/verifuse/verifuse.env" >&2
    exit 1
  fi
fi

echo "[setup_engine4] Project : $GOOGLE_CLOUD_PROJECT"
echo "[setup_engine4] Creds   : $GOOGLE_APPLICATION_CREDENTIALS"
echo "[setup_engine4] Vault   : $VAULT_ROOT"
echo "[setup_engine4] Repo    : $REPO_ROOT"

# Persist env to .bashrc only if not already present (non-secret values only).
grep -q "GOOGLE_CLOUD_PROJECT" ~/.bashrc \
  || echo "export GOOGLE_CLOUD_PROJECT=\"$GOOGLE_CLOUD_PROJECT\"" >> ~/.bashrc

pip install google-cloud-aiplatform google-cloud-storage pillow --quiet

echo "✅ ENGINE #4 READY"
