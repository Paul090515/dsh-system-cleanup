#!/usr/bin/env bash
set -eu

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash -n "$root/scripts/cleanup.sh"
bash -n "$root/scripts/schedule.sh"
node --check "$root/lib/index.js"

if bash "$root/scripts/cleanup.sh" --min-age-days 0 >/dev/null 2>&1; then
  echo "expected --min-age-days 0 to fail" >&2
  exit 1
fi
if bash "$root/scripts/cleanup.sh" --no-trash >/dev/null 2>&1; then
  echo "expected removed --no-trash option to fail" >&2
  exit 1
fi

echo "checks passed"
