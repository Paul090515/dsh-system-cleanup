#!/usr/bin/env bash
# Compatibility entry: the legacy broad --apply flags are deliberately rejected.
set -eu
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -eq 0 ]; then
  set -- inspect
fi
exec python3 "$root/scripts/safe_cleanup.py" "$@"
