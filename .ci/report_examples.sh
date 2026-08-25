#!/usr/bin/env bash
# Summarize one shard's per-example verdicts and gate the job.
#
# Env: EXAMPLES (comma-separated slugs assigned to this shard), PLATFORM,
# SHARD; optional OUT_DIR. An example with no verdict file is reported as
# NO_RESULT and fails the shard — a phase that died mid-loop (or a silently
# stale bundle) must never read as green.

set -euo pipefail

CI_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$CI_DIR/examples_common.sh"
OUT_DIR="${OUT_DIR:-$PWD/example-out}"

fails=0
table="| example | verdict | detail |
|---|---|---|"
for slug in $(echo "$EXAMPLES" | tr ',' ' '); do
    tsv="$OUT_DIR/results/$(flat "$slug").tsv"
    if [ -f "$tsv" ]; then
        verdict="$(cut -f3 "$tsv")"
        detail="$(cut -f4 "$tsv")"
    else
        verdict=NO_RESULT
        detail="no verdict recorded — the shard died before this example"
    fi
    if [ "$verdict" = "PASS" ]; then mark="✅"; else mark="❌"; fails=$((fails + 1)); fi
    table="$table
| \`$slug\` | $mark $verdict | $detail |"
done

{
    echo "### 📱 Examples — $PLATFORM shard ${SHARD:-1}"
    echo
    echo "$table"
    echo
    echo "Screenshots + console logs: \`example-results-$PLATFORM-shard${SHARD:-1}-*\` artifact; installable bundles: \`example-ap*s-shard${SHARD:-1}-*\`."
} >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"

echo "$fails failing example(s)"
[ "$fails" = 0 ]
