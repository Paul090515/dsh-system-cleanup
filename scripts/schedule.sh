#!/usr/bin/env bash
# Keep old callers fail-closed; scheduling belongs to the authorized host automation.
set -eu
echo "System scheduler mutation is disabled. Use the host's existing authorized heartbeat; see SKILL.md." >&2
exit 2
