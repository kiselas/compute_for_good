#!/usr/bin/env bash
# Forced SSH command. The key cannot open a shell, forward ports or invoke arbitrary commands.
set -Eeuo pipefail
command=${SSH_ORIGINAL_COMMAND:-}
if [[ $command =~ ^/opt/compute-for-good/bin/deploy-release\ ([0-9a-f]{40})$ ]]; then
    exec /opt/compute-for-good/bin/deploy-release "${BASH_REMATCH[1]}"
fi
echo 'This key permits only an exact ComputeForGood release deployment' >&2
exit 2
