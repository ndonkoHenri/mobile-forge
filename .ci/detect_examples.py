# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "jinja2"]
# ///
"""Select, filter and shard example apps for run-examples.yml's job matrices.

Env in:
  EVENT_NAME       github.event_name
  INPUT_EXAMPLES   dispatch input: "ALL", "<recipe>", "<recipe>/<example>" (comma-sep)
  INPUT_PLATFORMS  dispatch input, default "android,ios"
  INPUT_SHARDS     dispatch input, "" = auto from the time budget
  CHANGED_DIRS     space-separated changed dirs from tj-actions (push events)

Writes <platform>_matrix / <platform>_has_jobs to GITHUB_OUTPUT (stdout when
unset, for local runs) and a human summary to GITHUB_STEP_SUMMARY.

Filtering happens once, here: examples with a `skip` override, and platforms
a recipe opts out of (meta.yaml package.platforms — e.g. pyobjus is iOS-only,
psutil and pyjnius android-only). Shard counts come from a per-example time
budget so a big selection can never blow GitHub's 6h job cap; the per-shard
`timeout` lands on the job's timeout-minutes.
"""

import json
import math
import os
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import read_meta  # noqa: E402  (reuse the renderer the build matrix uses)

REPO = Path(__file__).resolve().parent.parent
SMOKE_EXAMPLES = ["numpy/bell-curve"]
PER_EXAMPLE_MINUTES = {"android": 8, "ios": 11}
SHARD_BUDGET_MINUTES = 240
MAX_SHARDS = {"android": 10, "ios": 8}
BASE_MINUTES = 30  # toolchain download + device boot, paid once per shard


def all_examples() -> list[str]:
    return sorted(
        f"{p.parent.parent.parent.name}/{p.parent.name}"
        for p in REPO.glob("recipes/*/examples/*/pyproject.toml")
    )


def resolve_requested(event: str, input_examples: str, changed_dirs: str, notes: list[str]) -> list[str]:
    known = all_examples()
    if event in ("workflow_dispatch", "workflow_call"):
        raw = (input_examples or "").strip()
        if raw == "ALL":
            return known
        picked: list[str] = []
        for item in [i.strip() for i in raw.split(",") if i.strip()]:
            if "/" in item:
                if item not in known:
                    sys.exit(f"::error::unknown example: {item}")
                picked.append(item)
            else:
                matches = [s for s in known if s.startswith(item + "/")]
                if not matches:
                    sys.exit(f"::error::recipe has no examples: {item}")
                picked += matches
        if not picked:
            notes.append(f"empty `examples` input — running the smoke set {SMOKE_EXAMPLES}")
            picked = SMOKE_EXAMPLES
        return sorted(set(picked))

    # push: only dirs that are still examples (a deleted example has nothing to run)
    picked = []
    for d in (changed_dirs or "").split():
        parts = Path(d).parts
        if len(parts) == 4 and parts[0] == "recipes" and parts[2] == "examples":
            slug = f"{parts[1]}/{parts[3]}"
            if slug in known:
                picked.append(slug)
            else:
                notes.append(f"changed dir `{d}` is no longer an example — skipped")
    if not picked:
        notes.append(f"no changed examples (harness-only push?) — running the smoke set {SMOKE_EXAMPLES}")
        picked = list(SMOKE_EXAMPLES)
    return sorted(set(picked))


def recipe_platforms(recipe: str, cache: dict[str, list[str]]) -> list[str]:
    if recipe not in cache:
        declared = read_meta.summary_line(str(REPO / "recipes" / recipe / "meta.yaml")).split("\t")[2]
        cache[recipe] = declared.split() if declared else ["android", "ios"]
    return cache[recipe]


def shard(examples: list[str], platform: str, input_shards: str) -> dict | None:
    n = len(examples)
    if n == 0:
        return None
    per = PER_EXAMPLE_MINUTES[platform]
    auto = math.ceil(n * per * 1.5 / SHARD_BUDGET_MINUTES)
    count = int(input_shards) if input_shards.strip().isdigit() and int(input_shards) > 0 else auto
    count = max(1, min(count, MAX_SHARDS[platform], n))
    buckets = [examples[i::count] for i in range(count)]
    return {
        "include": [
            {
                "shard": str(i + 1),
                "examples": ",".join(b),
                "timeout": min(350, BASE_MINUTES + math.ceil(len(b) * per * 1.5)),
            }
            for i, b in enumerate(buckets)
        ]
    }


def main() -> int:
    event = os.environ.get("EVENT_NAME", "workflow_dispatch")
    platforms = [
        p.strip().lower()
        for p in (os.environ.get("INPUT_PLATFORMS") or "android,ios").replace(" ", ",").split(",")
        if p.strip()
    ]
    unknown = [p for p in platforms if p not in ("android", "ios")]
    if unknown:
        # A typo'd platform list must not become an all-green no-op run.
        sys.exit(f"::error::unknown platform(s): {','.join(unknown)}")
    notes: list[str] = []
    requested = resolve_requested(
        event, os.environ.get("INPUT_EXAMPLES", ""), os.environ.get("CHANGED_DIRS", ""), notes
    )

    try:
        overrides = tomllib.loads((REPO / "tests/example-runner/overrides.toml").read_text())
    except FileNotFoundError:
        overrides = {}
    skipped = [(s, overrides[s]["skip"]) for s in requested if overrides.get(s, {}).get("skip")]
    requested = [s for s in requested if not overrides.get(s, {}).get("skip")]

    gate_cache: dict[str, list[str]] = {}
    per_platform = {
        plat: [s for s in requested if plat in recipe_platforms(s.split("/")[0], gate_cache)]
        for plat in ("android", "ios")
        if plat in platforms
    }

    out = open(os.environ["GITHUB_OUTPUT"], "a") if os.environ.get("GITHUB_OUTPUT") else sys.stdout
    lines = [f"### Examples selected ({len(requested)})", ""]
    for plat in ("android", "ios"):
        matrix = shard(per_platform.get(plat, []), plat, os.environ.get("INPUT_SHARDS", ""))
        print(f"{plat}_has_jobs={'true' if matrix else 'false'}", file=out)
        # Skipped jobs still evaluate their strategy expression; an empty
        # include list is the shape build-wheels-version.yml proved safe there.
        print(f"{plat}_matrix={json.dumps(matrix or {'include': []})}", file=out)
        if matrix:
            for e in matrix["include"]:
                lines.append(
                    f"- **{plat} shard {e['shard']}** ({e['timeout']} min cap): `{e['examples']}`"
                )
        else:
            lines.append(f"- **{plat}**: no examples to run")
    if skipped:
        lines += ["", "Skipped by overrides.toml:"] + [f"- `{s}` — {r}" for s, r in skipped]
    lines += [f"- note: {n}" for n in notes]
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text("\n".join(lines) + "\n")
    else:
        print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
