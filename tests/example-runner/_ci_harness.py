"""CI entrypoint (built with `--module-name _ci_harness`): instruments ft.run,
then executes the example's own main module unmodified.

READY means the example's main() returned without raising — the control tree
was submitted to Flutter, so the host can start watching the screen. CRASH
re-raises so flet still shows its error card and the traceback reaches
console.log. The slug in the sentinel pins the result to THIS example: every
example installs under the same app id, so an unmarked sentinel left in a
stale console.log could be read as the next example's result.
"""

import inspect
import runpy
import traceback

import flet as ft
import flet.app

SLUG = "__EXAMPLE_SLUG__"


def _sentinel(kind: str) -> None:
    print(f">>>>>>>>>> UI {kind} {SLUG} <<<<<<<<<<", flush=True)


_real_run = flet.app.run


def _instrumented_run(main, *args, **kwargs):
    if inspect.iscoroutinefunction(main):

        async def wrapped(page):
            try:
                await main(page)
            except Exception:
                traceback.print_exc()
                _sentinel("CRASH")
                raise
            _sentinel("READY")

    else:

        def wrapped(page):
            try:
                main(page)
            except Exception:
                traceback.print_exc()
                _sentinel("CRASH")
                raise
            _sentinel("READY")

    return _real_run(wrapped, *args, **kwargs)


# Patch the flet.app module global too: the deprecated ft.app() wrapper
# resolves `run` through that namespace, not the package attribute.
flet.app.run = _instrumented_run
ft.run = _instrumented_run

try:
    # run_name="__main__" fires the examples' `if __name__ == "__main__"` guard
    # (101 of 103 examples gate ft.run behind it).
    runpy.run_module("main", run_name="__main__", alter_sys=True)
except Exception:
    traceback.print_exc()
    _sentinel("CRASH")
    raise
