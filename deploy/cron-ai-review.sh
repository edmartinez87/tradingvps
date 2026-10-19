#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
SECRET=$(grep '^WEBHOOK_CRON_SECRET=' backend.env | cut -d= -f2-)
curl -fsS -X POST http://127.0.0.1:8001/api/cron/ai-review \
  -H "Authorization: Bearer $SECRET" \
  -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$(date -u +%F)\"}"
echo
