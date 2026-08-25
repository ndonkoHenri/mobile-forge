#!/usr/bin/env bash
# Device phase for one iOS-simulator example shard: mirror of
# run_examples_android.sh (see examples_common.sh for the shared ladder).
#
# Every simctl call uses an explicit UDID — `booted` turns ambiguous the
# moment a second simulator boots mid-shard (documented local-testing gotcha).

set -euo pipefail

CI_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$CI_DIR/examples_common.sh"

OUT_DIR="${OUT_DIR:-$PWD/example-out}"
WORK="${RUNNER_TEMP:-/tmp}/example-device"
PLATFORM=ios
BUNDLE=com.flet.example_runner
mkdir -p "$OUT_DIR/results" "$OUT_DIR/shots" "$OUT_DIR/logs" "$WORK"

# Same iPhone/iOS filter as the fallback: a leftover watchOS/tvOS companion
# sim must not become the shard's device.
UDID=$(xcrun simctl list devices booted -j \
    | jq -r '[.devices | to_entries[]
              | select(.key | contains("iOS"))
              | .value[]
              | select(.state=="Booted" and (.name | startswith("iPhone")))][0].udid // empty')
if [ -z "$UDID" ]; then
    UDID=$(xcrun simctl list devices available -j \
        | jq -r '.devices | to_entries[]
                 | select(.key | contains("iOS"))
                 | .value[]
                 | select(.isAvailable == true and (.name | startswith("iPhone")))
                 | .udid' \
        | head -1)
    [ -n "$UDID" ] || { echo "::error::no iPhone simulator available"; exit 3; }
    echo "Booting simulator $UDID"
    xcrun simctl boot "$UDID"
fi
xcrun simctl bootstatus "$UDID" -b

APP_PID=""
REMOTE_LOG=""

dev_install() {
    rm -rf "$WORK/app"
    mkdir -p "$WORK/app"
    tar -xzf "$1" -C "$WORK/app"
    app_dir=$(find "$WORK/app" -maxdepth 1 -name '*.app' | head -1)
    [ -n "$app_dir" ] || return 1
    run_with_timeout 180 xcrun simctl install "$UDID" "$app_dir"
}
dev_uninstall() { xcrun simctl uninstall "$UDID" "$BUNDLE" >/dev/null 2>&1 || true; }
dev_launch() {
    # `simctl launch` prints "<bundle-id>: <pid>"; sim apps are host processes,
    # so that pid is what dev_alive kill -0 probes.
    launch_out=$(run_with_timeout 60 xcrun simctl launch "$UDID" "$BUNDLE") || return 1
    APP_PID="${launch_out##*: }"
    REMOTE_LOG="$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data)/Library/Caches/console.log"
}
dev_pull_log()   { [ -n "$REMOTE_LOG" ] && [ -f "$REMOTE_LOG" ] && cp "$REMOTE_LOG" "$1" || true; }
dev_screenshot() { xcrun simctl io "$UDID" screenshot "$1" >/dev/null 2>&1 || true; }
dev_alive()      { [ -n "$APP_PID" ] && kill -0 "$APP_PID" 2>/dev/null; }
dev_foreground() { dev_alive; }   # no cheap foreground probe on the sim

uv run --script "$CI_DIR/check_screenshot.py" >/dev/null 2>&1 || true
uv run --script "$CI_DIR/example_override.py" _ _ >/dev/null 2>&1 || true

infra=""
found=""
for tgz in "$OUT_DIR"/bundles/*.app.tgz; do
    [ -e "$tgz" ] || continue
    found=1
    f="$(basename "$tgz" .app.tgz)"
    slug="$(printf '%s' "$f" | sed 's|--|/|')"
    echo "::group::run $slug"
    if [ -n "$infra" ] || ! xcrun simctl list devices -j \
        | jq -e --arg u "$UDID" '[.devices[][] | select(.udid==$u and .state=="Booted")] | length > 0' >/dev/null; then
        infra=1
        record_verdict "$slug" "$PLATFORM" INFRA "simulator lost before this example ran"
    else
        run_example_ladder "$slug" "$tgz"
    fi
    echo "::endgroup::"
done
[ -n "$found" ] || echo "no .app bundles in $OUT_DIR/bundles/ — nothing to run"
