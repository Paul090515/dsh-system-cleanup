#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Commit tracked changes before packaging; ZIPs use exactly HEAD." >&2
  exit 2
fi
version="$(git show HEAD:package.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
mkdir -p dist
archive="$root/dist/system-cleanup-v$version.zip"
# Explicit files prevent runtime metadata, credentials and unrelated files entering a download.
git archive --format=zip --prefix=system-cleanup/ --output="$archive" HEAD -- \
  SKILL.md agents/openai.yaml references/safety-and-scope.md \
  scripts/safe_cleanup.py scripts/duplicates_scan.py scripts/cleanup.sh \
  scripts/cleanup.ps1 scripts/schedule.sh scripts/schedule.ps1 \
  scripts/check.sh scripts/package.sh \
  tests/test_safe_cleanup.py tests/test_duplicates_scan.py tests/test_package.py \
  lib/index.js package.json cordis.patch.yml README.md CHANGELOG.md LICENSE
python3 - "$archive" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    assert archive.testzip() is None, "Corrupt ZIP"
    names = set(archive.namelist())
    for path in ("SKILL.md", "agents/openai.yaml", "references/safety-and-scope.md",
                 "scripts/safe_cleanup.py", "scripts/duplicates_scan.py", "scripts/package.sh"):
        assert "system-cleanup/" + path in names, "Missing required resource: " + path
    assert all(name.startswith("system-cleanup/") and ".." not in name.split("/") for name in names)
print(sys.argv[1])
PY
