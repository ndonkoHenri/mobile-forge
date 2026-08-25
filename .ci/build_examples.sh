#!/usr/bin/env bash
# Build every example in $EXAMPLES (comma-separated <recipe>/<example> slugs)
# for $PLATFORM (android|ios) against the PUBLISHED wheels the examples pin.
#
# Env: EXAMPLES, PLATFORM, FLET_CLI_VERSION; optional OUT_DIR, BUILD_TIMEOUT.
# Effects: installable bundles in $OUT_DIR/bundles/ (<recipe>--<example>.apk,
# or .app.tgz on iOS — tar keeps the bundle's exec bits, which the artifact
# zip would drop), failure verdicts in $OUT_DIR/results/, failed-build logs in
# $OUT_DIR/logs/. Individual build failures are verdicts, not script errors.
# Emits has_bundles=true|false to $GITHUB_OUTPUT for the device step's gate.

set -euo pipefail

CI_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$CI_DIR/.." && pwd)"
. "$CI_DIR/examples_common.sh"

OUT_DIR="${OUT_DIR:-$PWD/example-out}"
SCRATCH="${RUNNER_TEMP:-/tmp}/example-scratch"
BUILD_TIMEOUT="${BUILD_TIMEOUT:-1500}"
mkdir -p "$OUT_DIR/bundles" "$OUT_DIR/results" "$OUT_DIR/logs" "$OUT_DIR/shots"

for slug in $(echo "$EXAMPLES" | tr ',' ' '); do
    f="$(flat "$slug")"
    log="$OUT_DIR/logs/$f-build.log"
    echo "::group::build $slug"
    if ! "$REPO_ROOT/tests/example-runner/stage_example.sh" "$slug" "$SCRATCH"; then
        record_verdict "$slug" "$PLATFORM" BUILD_FAIL "staging failed"
        echo "::endgroup::"
        continue
    fi

    # --python-version deliberately omitted: flet resolves it from the
    # example's requires-python, exactly like an end user's build — a recipe
    # published for fewer pythons than flet's default surfaces here as
    # RESOLVE_FAIL, which is genuine republish signal, not noise.
    if [ "$PLATFORM" = "android" ]; then
        target_args="apk --arch x86_64"
    else
        target_args="ios-simulator"
    fi
    rc=0
    (cd "$SCRATCH" && run_with_timeout "$BUILD_TIMEOUT" \
        uvx --from "flet-cli==$FLET_CLI_VERSION" flet build $target_args \
            --bundle-id com.flet.example_runner --module-name _ci_harness \
            -vv --yes </dev/null) >"$log" 2>&1 || rc=$?

    if [ "$rc" -ne 0 ]; then
        tail -40 "$log"
        if grep -q "No matching distribution found" "$log"; then
            record_verdict "$slug" "$PLATFORM" RESOLVE_FAIL "pip could not resolve the pinned deps for the mobile target"
        elif [ "$rc" = 124 ]; then
            record_verdict "$slug" "$PLATFORM" BUILD_FAIL "flet build timed out after ${BUILD_TIMEOUT}s"
        else
            record_verdict "$slug" "$PLATFORM" BUILD_FAIL "flet build exited $rc — see $f-build.log"
        fi
    else
        # Guarded like the build itself: one packaging anomaly must become a
        # per-example verdict, never a whole-shard abort under set -e.
        bundled=0
        if [ "$PLATFORM" = "android" ]; then
            if cp "$SCRATCH"/build/apk/*.apk "$OUT_DIR/bundles/$f.apk" 2>/dev/null; then bundled=1; fi
        else
            if (cd "$SCRATCH/build/ios-simulator" && tar -czf "$OUT_DIR/bundles/$f.app.tgz" ./*.app) 2>/dev/null; then bundled=1; fi
        fi
        if [ "$bundled" = 1 ]; then
            rm -f "$log"   # keep only failed-build logs; success logs are -vv noise
        else
            record_verdict "$slug" "$PLATFORM" BUILD_FAIL "flet build succeeded but produced no bundle at the expected path"
        fi
    fi

    rm -rf "$SCRATCH"   # each build tree is GBs; only shared caches may stay
    df -h / | tail -1
    echo "::endgroup::"
done

if [ -n "${GITHUB_OUTPUT:-}" ]; then
    if ls "$OUT_DIR"/bundles/* >/dev/null 2>&1; then
        echo "has_bundles=true" >> "$GITHUB_OUTPUT"
    else
        echo "has_bundles=false" >> "$GITHUB_OUTPUT"
    fi
fi
