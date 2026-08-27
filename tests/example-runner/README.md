# example-runner

CI harness for running the recipe example apps (`recipes/*/examples/*`) on a
real Android emulator / iOS simulator — driven by
`.github/workflows/run-examples.yml`.

Unlike the recipe-tester, this never builds wheels: examples pin **published**
versions, so a run is `flet build` + device only. A push touching an example
runs just the changed examples; `workflow_dispatch` takes an explicit list or
`ALL`, sharded automatically to stay under GitHub's 6h job cap.

## How an example is judged

`stage_example.sh` copies the example verbatim and adds `src/_ci_harness.py`;
the workflow builds with `--module-name _ci_harness --bundle-id
com.flet.example_runner`. The harness patches `ft.run`, then executes the
example's `main` module as `__main__` (so the `if __name__ == "__main__"`
guard fires). When the example's `main(page)` returns, a `UI READY <slug>`
sentinel reaches console.log; a raise prints the traceback + `UI CRASH`.

The host (`.ci/run_examples_{android,ios}.sh` → `.ci/examples_common.sh`) then:

1. waits for READY/CRASH (or times out),
2. on READY, waits for the screen to settle — captures every 5s until
   consecutive frames differ in <0.5% of pixels *and* differ from the static
   boot screen (default cap 60s; `settle_seconds` in `overrides.toml`),
3. checks the app is still alive and foregrounded (a post-READY crash leaves
   the launcher on screen — stable, non-blank, and wrong),
4. fails near-solid frames (`.ci/check_screenshot.py`: OS chrome cropped,
   colors quantized, dominant-color + distinct-color thresholds).

After READY the harness also runs **content checks** from a worker thread: it
dumps the visible control-tree text every 2s and, wait-until-satisfied (two
consecutive passing dumps, or fail at `verdict_timeout`), enforces:

- **L1 (universal)** — no visible text is *crash-shaped*: a
  `Traceback (most recent call last)` line, a `SomeError:` /
  `Some.Exception:` class rendering (the codebase's canonical
  `f"{type(exc).__name__}: {exc}"` surface), "unhandled exception", or an
  uppercase self-check `FAIL`/`FAILED`/`FAILURE` — unless an `error_allow`
  regex in `overrides.toml` exempts the line. Deliberately not vocabulary
  matching: healthy screens legitimately say "rms error" or "no exception".
- **L2 (per-example)** — every `expect` regex matches, no `forbid` regex does.
  These snippets are the example's checked-in baseline: they travel in the
  same PR as the example, no golden files, no update workflow.

The outcome is written atomically to `_ci_verdict.json` beside console.log
and announced with a `UI CHECKED` sentinel; the driver classifies failures as
`ERROR_TEXT` / `EXPECT_FAIL` (`NO_CHECKS` if the sidecar never appears).
`EXAMPLE_CHECKS=report` (the workflow's `checks` input) records the outcome
in the detail column without failing — the soak mode for calibrating
allowlists across all examples before gating.

Verdicts: `PASS`, `RESOLVE_FAIL` (pip couldn't resolve the pins for the
mobile target — usually "recipe needs a republish"), `BUILD_FAIL`,
`INSTALL_FAIL`, `TIMEOUT`, `CRASH`, `DIED`, `BACKGROUNDED`, `BLANK`,
`STUCK`, `ERROR_TEXT`, `EXPECT_FAIL`, `NO_CHECKS`, `NO_RESULT`, `INFRA`.
Anything but PASS fails the shard; the report step and the run-level
`example-gallery-*` artifact (self-contained HTML contact sheet) show
verdict + screenshot per example.

## Artifacts

- `example-apks-shard*` / `example-apps-shard*` — the installable bundles.
  Try one locally without rebuilding anything:

  ```bash
  adb install numpy--bell-curve.apk
  adb shell am start -n com.flet.example_runner/.MainActivity
  ```

  ```bash
  tar -xzf numpy--bell-curve.app.tgz
  xcrun simctl install booted *.app && xcrun simctl launch booted com.flet.example_runner
  ```

- `example-results-*` — screenshots, console logs, verdict files per shard.
- `example-gallery-*` — one HTML page with every screenshot, failures first.

## Local loop (one example, no CI)

```bash
./tests/example-runner/stage_example.sh numpy/bell-curve /tmp/ex
cd /tmp/ex
uvx --from flet-cli==0.86.5 flet build apk --arch arm64-v8a \
    --bundle-id com.flet.example_runner --module-name _ci_harness --yes
```

Then install/launch as above and read
`/data/data/com.flet.example_runner/cache/console.log` (rootable AVD — see the
`local-recipe-testing` skill) or the sim container's `Library/Caches/console.log`.

`overrides.toml` holds the per-example knobs (`skip`, `settle_seconds`).
The CI scripts collect everything under `example-out/` (gitignored).
