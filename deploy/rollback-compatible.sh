#!/usr/bin/env bash
# Operator-only: refuse rollback when the target image cannot read this schema.
set -Eeuo pipefail
BASE=/opt/compute-for-good
sha=${1:-}
if [[ -z "$sha" ]]; then sha=$(cat "$BASE/previous-sha"); fi
[[ $# -le 1 && "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'Exact previous release SHA required' >&2; exit 2; }
# Compatibility is checked inside deploy-release's flock, never before it.
export CFG_REQUIRE_COMPATIBLE_SCHEMA=1
exec "$BASE/bin/deploy-release" "$sha"
