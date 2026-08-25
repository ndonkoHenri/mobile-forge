# Shared helpers for the example-runner CI scripts (sourced, not executed).
# Callers must set OUT_DIR and WORK, and (for run_example_ladder) define the
# platform primitives:
#   dev_install <bundle>   install the app (nonzero = failure; wrap your own
#                          run_with_timeout — `timeout` cannot run functions)
#   dev_launch             start the app
#   dev_uninstall          remove the app + its data (must not fail the script)
#   dev_pull_log <out>     copy the app's console.log to <out> (missing = ok)
#   dev_screenshot <out>   capture the screen to <out> (failure = ok, empty file)
#   dev_alive              app process still exists
#   dev_foreground         app is the foreground UI (android only; iOS = alive)
# Kept bash-3.2-safe: the iOS driver runs on macOS's stock bash.

# GNU timeout on Linux, gtimeout (brew coreutils) on the macOS runners; fall
# back to running unbounded rather than failing the shard over a missing tool.
run_with_timeout() {
    _secs="$1"; shift
    if command -v timeout >/dev/null 2>&1; then timeout "$_secs" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$_secs" "$@"
    else echo "::warning::no timeout binary; running unbounded: $*" >&2; "$@"; fi
}

# numpy/bell-curve -> numpy--bell-curve (single '-' would be ambiguous:
# recipe and example names both contain dashes).
flat() { printf '%s' "$1" | sed 's|/|--|'; }

record_verdict() {  # <slug> <platform> <verdict> <detail>
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" > "$OUT_DIR/results/$(flat "$1").tsv"
}

_diff_ratio() {  # <a> <b> -> ratio on stdout ("1.0" when either capture is unusable)
    if [ -s "$1" ] && [ -s "$2" ]; then
        uv run --script "$CI_DIR/check_screenshot.py" diff "$1" "$2" 2>/dev/null \
            | sed -n 's/^ratio=//p' | grep . || echo "1.0"
    else
        echo "1.0"
    fi
}

# The per-example verdict ladder. Writes the verdict file, the screenshot and
# the console log; never returns nonzero (per-example failures are data, the
# shard result is decided by the workflow's report step).
run_example_ladder() {  # <slug> <bundle>
    slug="$1"; bundle="$2"
    f="$(flat "$slug")"
    shot="$WORK/cur.png"; base="$WORK/base.png"; prev="$WORK/prev.png"; clog="$WORK/console.log"
    rm -f "$shot" "$base" "$prev" "$clog"
    verdict=""; detail=""; ready=""

    dev_uninstall
    if ! dev_install "$bundle"; then
        record_verdict "$slug" "$PLATFORM" INSTALL_FAIL "install failed or timed out"
        return 0
    fi
    if ! dev_launch; then
        record_verdict "$slug" "$PLATFORM" INSTALL_FAIL "launch failed"
        dev_uninstall
        return 0
    fi

    # Boot-screen baseline: flet's boot overlay is a STATIC solid frame, so
    # "the screen stopped changing" alone cannot distinguish a rendered app
    # from a stuck boot — the settled capture must also DIFFER from this.
    # Captured immediately (Python boot takes seconds) so a fast-rendering
    # example can't already be on its final frame here.
    dev_screenshot "$base"

    deadline=$(( $(date +%s) + ${READY_TIMEOUT:-300} ))
    tick=0
    while [ "$(date +%s)" -lt "$deadline" ]; do
        tick=$((tick + 1))
        dev_pull_log "$clog"
        if [ -s "$clog" ]; then
            if grep -qF ">>>>>>>>>> UI CRASH $slug <<<<<<<<<<" "$clog" \
               || grep -q "Traceback (most recent call last)" "$clog"; then
                verdict=CRASH; detail="python traceback — see the console log"
                break
            fi
            if grep -qF ">>>>>>>>>> UI READY $slug <<<<<<<<<<" "$clog"; then
                ready=1
                break
            fi
        fi
        # A native crash (SIGSEGV in a .so) leaves no sentinel and no
        # traceback — without this check it would burn the whole timeout as
        # TIMEOUT. Grace of ~10s: process spawn after launch is async.
        if [ "$tick" -gt 5 ] && ! dev_alive; then
            dev_pull_log "$clog"
            if [ -s "$clog" ] && grep -q "Traceback (most recent call last)" "$clog"; then
                verdict=CRASH; detail="python traceback — see the console log"
            else
                verdict=DIED; detail="app process exited before UI READY (native crash?)"
            fi
            break
        fi
        sleep 2
    done
    if [ -z "$ready" ] && [ -z "$verdict" ]; then
        verdict=TIMEOUT; detail="no READY/CRASH sentinel within ${READY_TIMEOUT:-300}s"
    fi

    if [ -n "$ready" ]; then
        # Wait for the screen to settle: examples do real work in background
        # threads after first paint. "Settled" = consecutive captures differ in
        # <0.5% of pixels (byte-equality would never converge — most examples
        # show a ProgressRing at some point) AND the frame moved off the boot
        # baseline. Hitting the cap keeps the last capture but is reported.
        settle="$(uv run --script "$CI_DIR/example_override.py" "$slug" settle_seconds 60 2>/dev/null || true)"
        case "$settle" in (*[!0-9]*|"") settle=60 ;; esac
        settled=""
        sdeadline=$(( $(date +%s) + settle ))
        while [ "$(date +%s)" -lt "$sdeadline" ]; do
            sleep 5
            dev_screenshot "$shot"
            r_prev="$(_diff_ratio "$prev" "$shot")"
            r_base="$(_diff_ratio "$base" "$shot")"
            if awk "BEGIN{exit !($r_prev < 0.005 && $r_base > 0.02)}"; then
                settled=1
                break
            fi
            [ -s "$shot" ] && cp "$shot" "$prev"
        done
        [ -s "$shot" ] || dev_screenshot "$shot"

        # A dead or backgrounded app leaves the launcher on screen — visually
        # rich and stable, so it must be caught before any pixel check; only a
        # live foreground app whose frame still equals the boot baseline is
        # genuinely STUCK (a wedged renderer, or a splash whose logo would
        # beat the blank check — READY is a Python-side event, frames render
        # asynchronously).
        dev_pull_log "$clog"
        r_final="$(_diff_ratio "$base" "$shot")"
        if ! dev_alive; then
            verdict=DIED; detail="app process gone after UI READY"
        elif ! dev_foreground; then
            verdict=BACKGROUNDED; detail="app not in the foreground at capture time"
        elif awk "BEGIN{exit !($r_final < 0.02)}"; then
            verdict=STUCK; detail="screen never changed from the boot frame after UI READY"
        elif grep -q "Traceback (most recent call last)" "$clog"; then
            verdict=CRASH; detail="traceback after UI READY (background worker?)"
        else
            rcb=0
            uv run --script "$CI_DIR/check_screenshot.py" blank "$shot" || rcb=$?
            if [ "$rcb" = 10 ]; then
                verdict=BLANK; detail="screen is a near-solid frame"
            elif [ "$rcb" != 0 ]; then
                verdict=INFRA; detail="blank check itself failed (exit $rcb)"
            elif [ -n "$settled" ]; then
                verdict=PASS; detail="settled"
            else
                verdict=PASS; detail="still changing at the ${settle}s settle cap"
            fi
        fi
    else
        # Crash/timeout screens (flet's error card, a stuck boot) are worth
        # keeping too.
        dev_screenshot "$shot"
    fi

    [ -s "$shot" ] && cp "$shot" "$OUT_DIR/shots/$f.png"
    [ -s "$clog" ] && cp "$clog" "$OUT_DIR/logs/$f-console.log"
    record_verdict "$slug" "$PLATFORM" "$verdict" "$detail"
    echo "$slug: $verdict ($detail)"
    dev_uninstall
    return 0
}
