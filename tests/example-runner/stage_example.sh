#!/usr/bin/env bash
# Stage one example app into a scratch dir for a CI device run.
#
# Usage: stage_example.sh <recipe>/<example> <dest-dir>
#
# Copies recipes/<recipe>/examples/<example>/ verbatim (minus build junk) and
# adds src/_ci_harness.py — the instrumented entrypoint the workflow builds
# with `flet build --module-name _ci_harness`. The example's own files are
# never edited, so CI runs exactly what the docs ship.

set -euo pipefail

SLUG="${1:?usage: $0 <recipe>/<example> <dest-dir>}"
DEST="${2:?usage: $0 <recipe>/<example> <dest-dir>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RECIPE="${SLUG%%/*}"
EXAMPLE="${SLUG#*/}"
SRC_DIR="$REPO_ROOT/recipes/$RECIPE/examples/$EXAMPLE"

[ -f "$SRC_DIR/pyproject.toml" ] || { echo "::error::not an example dir: $SRC_DIR" >&2; exit 1; }
[ -f "$SRC_DIR/src/main.py" ] || { echo "::error::example has no src/main.py: $SRC_DIR" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$SRC_DIR/." "$DEST/"
rm -rf "$DEST/build" "$DEST/.ruff_cache" "$DEST/src/__pycache__"

# Bake the slug into the sentinel so a stale console.log from a previous
# example in the same shard can never be read as this one's result.
sed "s|__EXAMPLE_SLUG__|$SLUG|" "$SCRIPT_DIR/_ci_harness.py" > "$DEST/src/_ci_harness.py"

echo "Staged $SLUG -> $DEST"
