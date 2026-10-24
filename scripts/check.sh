#!/usr/bin/env bash
set -eu
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash -n "$root/scripts/cleanup.sh"
bash -n "$root/scripts/schedule.sh"
bash -n "$root/scripts/package.sh"
node --check "$root/lib/index.js"
test -f "$root/tests/test_safe_cleanup.py"
test -f "$root/tests/test_duplicates_scan.py"
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s "$root/tests" -v
if bash "$root/scripts/cleanup.sh" --apply >/dev/null 2>&1; then
  echo "legacy broad --apply must fail" >&2
  exit 1
fi
if bash "$root/scripts/schedule.sh" --install >/dev/null 2>&1; then
  echo "scheduler writes must fail" >&2
  exit 1
fi
node --input-type=module - "$root" <<'JS'
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const root = process.argv[2];
const plugin = await import(pathToFileURL(root + '/lib/index.js'));
let registered;
plugin.apply({ skills: { register: value => { registered = value; } } });
assert.equal(registered.name, 'system-cleanup');
assert.equal(registered.resourceBase.path, root);
assert.ok(registered.description.includes('macOS'));
assert.ok(registered.content.includes('scripts/safe_cleanup.py'));
console.log('DSH plugin registration verified');
JS
echo "checks passed (isolated fixtures only)"
