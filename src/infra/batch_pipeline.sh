#!/bin/bash
# Batch process all unprocessed dates
cd /home/mi/.openclaw/workspace

DATES=(
  20251110 20251118 20251119 20251120 20251121
  20251124 20251125 20251126 20251201 20251204
  20251205 20251206 20251208 20251209 20251210
  20251215 20251216 20251217 20251218 20251219
  20251222 20251223 20251224 20251225 20251226
  20251227 20251229 20251230 20251231
  20260112 20260113 20260114
  20260121 20260122 20260123 20260124 20260125
)

SUCCESS=0
FAIL=0
ERRORS=""

for DATE in "${DATES[@]}"; do
  echo "=== Processing $DATE ==="
  OUTPUT=$(python3 src/actions/planning/daily_pipeline.py --date "$DATE" --force 2>&1)
  EXIT_CODE=$?
  echo "$OUTPUT"
  if [ $EXIT_CODE -eq 0 ]; then
    SUCCESS=$((SUCCESS + 1))
    echo "✅ $DATE done"
  else
    FAIL=$((FAIL + 1))
    ERRORS="$ERRORS\n$DATE: $(echo $OUTPUT | head -c 200)"
    echo "❌ $DATE failed"
  fi
  echo ""
done

echo "============================="
echo "SUMMARY: $SUCCESS success, $FAIL failed"
if [ -n "$ERRORS" ]; then
  echo -e "ERRORS:$ERRORS"
fi
