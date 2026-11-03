#!/usr/bin/env bash
# Аудит ландшафта и сверка его вывода с эталоном expected.txt.
set -euo pipefail
cd "$(dirname "$0")"

out=$(mktemp)
trap 'rm -f "$out"' EXIT

python3 audit.py > "$out"
cat "$out"
status=0
diff -u expected.txt "$out" || status=1
echo
if [ "$status" -eq 0 ]; then
  echo "OK: вывод совпадает с expected.txt"
else
  echo "FAIL: вывод расходится с expected.txt"
fi
exit "$status"
