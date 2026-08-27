# Shared helpers for the example-runner CI scripts (sourced, not executed).
# Callers must set OUT_DIR and WORK, and (for run_example_ladder) define the
# platform primitives:
#   dev_install <bundle>   install the app (nonzero = failure; wrap your own
#                          run_with_timeout — `timeout` cannot run functions)
#   dev_launch             start the app
#   dev_uninstall          remove the app + its data (must not fail the script)
#   dev_pull_log <out>     copy the app's console.log to <out> (missing = ok)
#   dev_pull_verdict <out> copy the app's _ci_verdict.json to <out> (missing = ok)
#   dev_clear_verdict      delete a leftover on-device _ci_verdict.json (must not fail)
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
    # An install over surviving app data (a silently-failed uninstall) could
    # replay the previous example's sidecar; clear it before the app starts.
    dev_clear_verdict
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

        # L1/L2 content checks: wait for the harness's CHECKED sentinel, pull
        # the _ci_verdict.json sidecar, validate (slug must match — a stale
        # sidecar surviving a silently-failed uninstall must never be read as
        # this example's result), classify. EXAMPLE_CHECKS: gate (default,
        # verdict-bearing) | report (annotate only — the soak mode) | off.
        case "${EXAMPLE_CHECKS:-gate}" in
            (gate|report|off) ;;
            (*) echo "::warning::unknown EXAMPLE_CHECKS='${EXAMPLE_CHECKS:-}' — treating as gate"
                EXAMPLE_CHECKS=gate ;;
        esac
        checks_state=""; checks_detail=""
        if [ "${EXAMPLE_CHECKS:-gate}" != "off" ]; then
            # Wait budget follows the example's own verdict_timeout override —
            # the worker's clock started at READY, so now+vt+slack over-waits
            # slightly rather than truncating a slow example's checks.
            vt="$(uv run --script "$CI_DIR/example_override.py" "$slug" verdict_timeout 90 2>/dev/null || true)"
            case "$vt" in (*[!0-9]*|"") vt=90 ;; esac
            cdeadline=$(( $(date +%s) + vt + 45 ))
            while [ "$(date +%s)" -lt "$cdeadline" ]; do
                dev_pull_log "$clog"
                grep -qF ">>>>>>>>>> UI CHECKED $slug <<<<<<<<<<" "$clog" && break
                dev_alive || break   # a dead app will never deliver — save the wait
                sleep 2
            done
            vfile="$WORK/verdict.json"
            rm -f "$vfile"
            dev_pull_verdict "$vfile"
            [ -s "$vfile" ] && cp "$vfile" "$OUT_DIR/logs/$f-verdict.json" 2>/dev/null || true
            ok_val="$(jq -r .ok "$vfile" 2>/dev/null || true)"
            slug_ok="$(jq -r --arg s "$slug" '.slug == $s' "$vfile" 2>/dev/null || true)"
            if [ ! -s "$vfile" ] || [ "$slug_ok" != "true" ] \
               || { [ "$ok_val" != "true" ] && [ "$ok_val" != "false" ]; }; then
                checks_state=NO_CHECKS
                checks_detail="checks verdict missing, stale or unreadable"
            elif [ "$ok_val" = "false" ]; then
                checks_detail="$(jq -r '[.failures[].detail] | join("; ") | .[0:300]' "$vfile" 2>/dev/null | tr '\t\n|' '   ' || true)"
                if jq -e '[.failures[] | select(.rule=="error-text")] | length > 0' "$vfile" >/dev/null 2>&1; then
                    checks_state=ERROR_TEXT
                else
                    checks_state=EXPECT_FAIL
                fi
            else
                # Provenance: expect rules that never reached the device would
                # pass vacuously (a future packaging change could eat the
                # staged _ci_rules.json without any other symptom).
                n_local="$(uv run --script "$CI_DIR/example_override.py" "$slug" --json 2>/dev/null | jq -r '(.expect // []) | length' 2>/dev/null || true)"
                n_dev="$(jq -r '.rules.expect // 0' "$vfile" 2>/dev/null || true)"
                case "$n_local" in (''|*[!0-9]*) n_local=0 ;; esac
                case "$n_dev" in (''|*[!0-9]*) n_dev=0 ;; esac
                if [ "$n_local" -gt 0 ] && [ "$n_dev" -eq 0 ]; then
                    checks_state=NO_CHECKS
                    checks_detail="expect rules never reached the device (staging/packaging gap)"
                fi
            fi
        fi

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
        elif [ "${EXAMPLE_CHECKS:-gate}" = "gate" ] \
             && { [ "$checks_state" = ERROR_TEXT ] || [ "$checks_state" = EXPECT_FAIL ]; }; then
            verdict=$checks_state; detail="$checks_detail"
        elif grep -q "Traceback (most recent call last)" "$clog"; then
            # A genuine post-READY traceback outranks NO_CHECKS: the missing
            # sidecar is usually a CONSEQUENCE of the crash, not the story.
            verdict=CRASH; detail="traceback after UI READY (background worker?)"
        elif [ "${EXAMPLE_CHECKS:-gate}" = "gate" ] && [ "$checks_state" = NO_CHECKS ]; then
            verdict=NO_CHECKS; detail="$checks_detail"
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
        # Soak mode: the checks outcome rides along in the detail column
        # instead of bearing the verdict, so an ALL sweep measures the
        # would-be failure surface without going red.
        if [ "${EXAMPLE_CHECKS:-gate}" = "report" ] && [ -n "$checks_state" ]; then
            detail="$detail [checks(report): $checks_state — $checks_detail]"
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
