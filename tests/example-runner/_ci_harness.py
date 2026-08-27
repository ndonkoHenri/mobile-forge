"""CI entrypoint (built with `--module-name _ci_harness`): instruments ft.run,
executes the example's own main module unmodified, then runs content checks.

Sentinels (host greps console.log for these, slug-pinned because every example
shares one app id and a stale log must never be read as the next example's):
  UI READY   — the example's main() returned; control tree submitted.
  UI CRASH   — main() raised; re-raised so flet still shows its error card.
  UI CHECKED — the checks worker wrote its verdict sidecar (_ci_verdict.json,
               same dir as console.log; atomic write).

Checks (worker thread started at READY):
  L1  no visible text matches ERROR_RE, unless an `error_allow` regex exempts
      the line.
  L2  every `expect` regex matches the visible text; no `forbid` regex does.
Rules come from _ci_rules.json staged next to this file (stage_example.sh
bakes them from tests/example-runner/overrides.toml); absent file = L1 only.

Semantics are wait-until-satisfied: the tree is dumped every POLL seconds and
the checks pass when they hold on two CONSECUTIVE dumps (background threads
fill panels after READY; a single instant read races them — and examples that
tick forever, like clocks, still pass as soon as the rules hold twice).
Only at VERDICT_TIMEOUT is the last dump's failure list reported. The worker
never prints tracebacks: its own failure must not satisfy the host's post-READY
Traceback grep.
"""

import dataclasses
import inspect
import json
import os
import re
import runpy
import threading
import time
import traceback

import flet as ft
import flet.app

SLUG = "__EXAMPLE_SLUG__"

POLL = 2.0
DEFAULT_VERDICT_TIMEOUT = 90
# Crash-SHAPED patterns, not vocabulary: healthy screens legitimately say
# "rms error", "no exception", "an exception crosses the switch" (scipy,
# pyclipper, greenlet, ...), while the codebase's canonical failure rendering
# is f"{type(exc).__name__}: {exc}" -> "SomeError: ..." and self-check panels
# print uppercase FAIL. Bare lowercase words are deliberately NOT matched.
ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)"
    r"|\b[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\s*:"
    r"|(?i:\bunhandled exception\b)"
    r"|\bFAIL(?:ED|URE)?\b"
)
MAX_NODES = 15000
MAX_DEPTH = 80
MAX_LINE = 500
MAX_TREE_BYTES = 30000

# Field names harvested as visible text when their value is a str/number.
TEXT_FIELDS = frozenset(
    "value label text title subtitle hint_text helper_text error_text "
    "counter_text tooltip message semantics_label prefix_text suffix_text "
    "content".split()
)
# Payloads and backrefs the walk must never descend into or harvest.
SKIP_FIELDS = frozenset("src src_base64 data page parent ref key".split())


def _sentinel(kind: str) -> None:
    print(f">>>>>>>>>> UI {kind} {SLUG} <<<<<<<<<<", flush=True)


def _load_rules() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ci_rules.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _walk(node, lines: list, seen: set, depth: int) -> None:
    if depth > MAX_DEPTH or len(lines) >= MAX_NODES or id(node) in seen:
        return
    seen.add(id(node))
    if not dataclasses.is_dataclass(node):
        return
    for fld in dataclasses.fields(node):
        name = fld.name
        if name.startswith("_") or name in SKIP_FIELDS:
            continue
        try:
            val = getattr(node, name, None)
        except Exception:
            continue
        if val is None or isinstance(val, (bytes, bytearray)):
            continue
        if isinstance(val, (str, int, float, bool)) and not isinstance(val, bool):
            if name in TEXT_FIELDS and str(val).strip():
                lines.append(str(val).replace("\t", " ")[:MAX_LINE])
        elif isinstance(val, (list, tuple)):
            for item in list(val):
                _walk(item, lines, seen, depth + 1)
        else:
            _walk(val, lines, seen, depth + 1)


def _dump_tree(page) -> str:
    lines: list = []
    seen: set = set()
    _walk(page, lines, seen, 0)
    # overlay/dialogs live in underscore fields the generic walk skips; error
    # text routed to a SnackBar or AlertDialog must not escape the gate.
    for slot in ("_overlay", "_dialogs"):
        _walk(getattr(page, slot, None), lines, seen, 0)
    return "\n".join(lines)


def _compile_rules(rules: dict):
    """Compile the override regexes once; a bad pattern is an author error
    surfaced as a rules-failure, never a worker crash."""
    bad = []
    compiled = {"error_allow": [], "forbid": [], "expect": []}
    for kind in compiled:
        pats = rules.get(kind, [])
        if not isinstance(pats, list):  # a bare string would iterate per character
            bad.append({"rule": "rules", "detail": f"{kind} must be a LIST of regexes"})
            continue
        for pat in pats:
            try:
                compiled[kind].append(re.compile(pat))
            except (re.error, TypeError) as exc:
                bad.append({"rule": "rules", "detail": f"bad {kind} regex {pat!r}: {exc}"})
    return compiled, bad


def _evaluate(text: str, compiled: dict) -> list:
    """Return the list of {rule, detail} failures for one dump."""
    failures = []
    for line in text.splitlines():
        m = ERROR_RE.search(line)
        if m and not any(a.search(line) for a in compiled["error_allow"]):
            failures.append(
                {"rule": "error-text", "detail": f"visible text looks broken: {line[:200]!r}"}
            )
    for rx in compiled["forbid"]:
        for line in text.splitlines():
            if rx.search(line):
                failures.append(
                    {"rule": "forbid", "detail": f"{rx.pattern!r} matched {line[:150]!r}"}
                )
                break
    for rx in compiled["expect"]:
        if not rx.search(text):
            failures.append({"rule": "expect", "detail": f"{rx.pattern!r} not found on screen"})
    return failures


def _write_sidecar(payload: dict) -> None:
    console = os.environ.get("FLET_APP_CONSOLE")
    out_dir = os.path.dirname(console) if console else os.getcwd()
    path = os.path.join(out_dir, "_ci_verdict.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def _checks_worker(page) -> None:
    # Fully armored: any escape from this thread would print a traceback into
    # console.log and satisfy the host's CRASH grep for a healthy app.
    timeout = DEFAULT_VERDICT_TIMEOUT
    rules_info = {"loaded": False, "expect": 0, "forbid": 0, "error_allow": 0}
    try:
        rules = _load_rules()
        try:
            timeout = int(rules.get("verdict_timeout", DEFAULT_VERDICT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_VERDICT_TIMEOUT
        compiled, bad = _compile_rules(rules)
        rules_info = {
            "loaded": bool(rules),
            "expect": len(compiled["expect"]),
            "forbid": len(compiled["forbid"]),
            "error_allow": len(compiled["error_allow"]),
        }
        if bad:
            _finish(False, bad, "", timeout, rules_info)
            return
        deadline = time.time() + timeout
        prev_dump = None
        prev_ok = False
        last_dump = ""
        last_failures = [{"rule": "dump", "detail": "tree was never readable"}]
        dump_errors = 0

        while time.time() < deadline:
            try:
                dump = _dump_tree(page)
                dump_errors = 0
            except Exception as exc:  # worker threads mutate lists mid-walk; retry
                dump_errors += 1
                if dump_errors >= 10:
                    last_failures = [
                        {"rule": "dump", "detail": f"tree walk kept failing: {type(exc).__name__}"}
                    ]
                    break
                time.sleep(POLL)
                continue
            last_dump = dump
            failures = _evaluate(dump, compiled)
            last_failures = failures
            ok_now = not failures
            # Two consecutive passing dumps: rules that hold across one poll
            # interval are settled enough — byte-identical dumps are NOT
            # required, or forever-ticking examples (clocks) could only pass
            # at timeout.
            if ok_now and (prev_ok or dump == prev_dump):
                _finish(True, [], dump, timeout, rules_info)
                return
            prev_ok = ok_now
            prev_dump = dump
            time.sleep(POLL)

        _finish(False, last_failures, last_dump, timeout, rules_info)
    except Exception as exc:
        _finish(
            False,
            [{"rule": "dump", "detail": f"checks worker died: {type(exc).__name__}"}],
            "",
            timeout,
            rules_info,
        )


def _finish(ok: bool, failures: list, dump: str, timeout, rules_info: dict) -> None:
    tree = dump[:MAX_TREE_BYTES] + ("\n…(truncated)" if len(dump) > MAX_TREE_BYTES else "")
    try:
        _write_sidecar(
            {
                "slug": SLUG,
                "ok": ok,
                "failures": failures,
                "timeout": timeout,
                # Provenance: expect rules that silently failed to reach the
                # device would otherwise pass vacuously — the driver compares
                # these counts against the repo's overrides.
                "rules": rules_info,
                "tree": tree,
            }
        )
        _sentinel("CHECKED")
    except Exception:
        # No sidecar -> the host reports NO_CHECKS; a print here could feed
        # the CRASH grep, so stay silent.
        pass


_real_run = flet.app.run


def _instrumented_run(main, *args, **kwargs):
    def _start_checks(page):
        threading.Thread(target=_checks_worker, args=(page,), daemon=True).start()

    if inspect.iscoroutinefunction(main):

        async def wrapped(page):
            try:
                await main(page)
            except Exception:
                traceback.print_exc()
                _sentinel("CRASH")
                raise
            _sentinel("READY")
            _start_checks(page)

    else:

        def wrapped(page):
            try:
                main(page)
            except Exception:
                traceback.print_exc()
                _sentinel("CRASH")
                raise
            _sentinel("READY")
            _start_checks(page)

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
