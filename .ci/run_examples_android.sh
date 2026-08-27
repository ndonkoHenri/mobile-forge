#!/usr/bin/env bash
# Device phase for one android example shard: install/launch each APK in
# $OUT_DIR/bundles/, run the verdict ladder (examples_common.sh), collect
# screenshots + console logs. Runs inside reactivecircus/android-emulator-
# runner's `script:` field — a single line, for the same shell-splitting
# reason documented in run_android_test.sh.
#
# Exit: 0 (per-example results carry the signal; the report step gates),
# 3 only when the device itself is unusable from the start.

set -euo pipefail

CI_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$CI_DIR/examples_common.sh"

OUT_DIR="${OUT_DIR:-$PWD/example-out}"
WORK="${RUNNER_TEMP:-/tmp}/example-device"
PLATFORM=android
PKG=com.flet.example_runner
REMOTE_LOG="/data/data/$PKG/cache/console.log"
mkdir -p "$OUT_DIR/results" "$OUT_DIR/shots" "$OUT_DIR/logs" "$WORK"

dev_install()    { run_with_timeout 180 adb install "$1" >/dev/null; }
dev_uninstall()  { adb uninstall "$PKG" >/dev/null 2>&1 || true; }
dev_launch()     { adb shell am start -n "$PKG/.MainActivity" >/dev/null; }
dev_pull_log()     { adb pull "$REMOTE_LOG" "$1" >/dev/null 2>&1 || true; }
dev_pull_verdict()  { adb pull "/data/data/$PKG/cache/_ci_verdict.json" "$1" >/dev/null 2>&1 || true; }
dev_clear_verdict() { adb shell rm -f "/data/data/$PKG/cache/_ci_verdict.json" >/dev/null 2>&1 || true; }
dev_screenshot() { adb exec-out screencap -p > "$1" 2>/dev/null || true; }
dev_alive()      { [ -n "$(adb shell pidof "$PKG" 2>/dev/null | tr -d '[:space:]')" ]; }
dev_foreground() {
    adb shell dumpsys activity activities 2>/dev/null \
        | grep -E "mResumedActivity|topResumedActivity" | grep -q "$PKG"
}

# adb root (userdebug AVD) is what lets us read the app-private console.log;
# retried because adbd can answer before it is fully up (see wait_for_console.sh).
rooted=0
for _ in 1 2 3 4 5 6; do
    if adb root >/dev/null 2>&1; then rooted=1; break; fi
    sleep 5
done
[ "$rooted" = 1 ] || { echo "::error::adb root failed — cannot read console.log"; exit 3; }
adb wait-for-device

# Warm the uv script envs now so a cold cache can never masquerade as a
# mid-ladder INFRA failure.
uv run --script "$CI_DIR/check_screenshot.py" >/dev/null 2>&1 || true
uv run --script "$CI_DIR/example_override.py" _ _ >/dev/null 2>&1 || true

infra=""
found=""
for apk in "$OUT_DIR"/bundles/*.apk; do
    [ -e "$apk" ] || continue
    found=1
    f="$(basename "$apk" .apk)"
    slug="$(printf '%s' "$f" | sed 's|--|/|')"
    echo "::group::run $slug"
    if [ -n "$infra" ] || ! adb get-state >/dev/null 2>&1; then
        infra=1
        record_verdict "$slug" "$PLATFORM" INFRA "emulator lost before this example ran"
    else
        run_example_ladder "$slug" "$apk"
    fi
    echo "::endgroup::"
done
[ -n "$found" ] || echo "no APKs in $OUT_DIR/bundles/ — nothing to run"
