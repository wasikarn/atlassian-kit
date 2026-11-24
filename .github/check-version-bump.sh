#!/usr/bin/env bash
# Fails when plugin content changed since $1 but plugin.json's version did not:
# `claude plugin update` compares the version number only, so an unbumped change never reaches installs.
set -euo pipefail
base=${1:?usage: check-version-bump.sh BASE_SHA}
if [[ "$base" =~ ^0+$ ]] || ! git cat-file -e "$base^{commit}" 2>/dev/null; then echo "no usable base; skipping"; exit 0; fi
changed=$(git diff --name-only "$base" HEAD -- skills agents hooks ':!*/test_*.py' ':!hooks/testdata')
[ -z "$changed" ] && { echo "no plugin content changed"; exit 0; }
old=$(git show "$base:.claude-plugin/plugin.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')
new=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
if [ "$old" = "$new" ]; then echo "FAIL: plugin content changed but version stays $new:"; echo "$changed"; exit 1; fi
echo "version $old -> $new"
