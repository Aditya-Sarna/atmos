#!/usr/bin/env bash
# Local / CI helper: check Atmos Craft Score gate.
# Usage:
#   ATMOS_API_URL=http://localhost:8000 \
#   ATMOS_PROJECT_ID=proj_xxx \
#   ATMOS_CRAFT_TOKEN=craft_xxx \
#   ./integrations/craft-gate.sh [threshold]
set -euo pipefail
API="${ATMOS_API_URL:?set ATMOS_API_URL}"
PID="${ATMOS_PROJECT_ID:?set ATMOS_PROJECT_ID}"
TOK="${ATMOS_CRAFT_TOKEN:?set ATMOS_CRAFT_TOKEN}"
THR="${1:-${ATMOS_CRAFT_THRESHOLD:-70}}"
URL="${API%/}/api/projects/${PID}/craft/gate?threshold=${THR}"
CODE=$(curl -sS -o /tmp/atmos-craft-gate.json -w "%{http_code}" \
  -H "X-Atmos-Token: ${TOK}" "$URL" || true)
cat /tmp/atmos-craft-gate.json
echo
[[ "$CODE" == "200" ]] || exit 1
