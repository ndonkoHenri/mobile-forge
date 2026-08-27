# /// script
# requires-python = ">=3.11"
# ///
"""Print values from tests/example-runner/overrides.toml.

Usage:
  example_override.py <recipe>/<example> <key> [<default>]   one scalar value
  example_override.py <recipe>/<example> --json              the whole table as JSON
                                                             (staged as _ci_rules.json)
Always exits 0 with the value on stdout — callers treat the output as data; a
broken overrides file must degrade to defaults, not red a whole shard.
"""

import json
import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: example_override.py <slug> <key>|--json [<default>]", file=sys.stderr)
        return 2
    slug, key = argv[0], argv[1]
    path = Path(__file__).resolve().parent.parent / "tests" / "example-runner" / "overrides.toml"
    try:
        table = tomllib.loads(path.read_text()).get(slug, {})
    except Exception:
        table = {}
    if key == "--json":
        print(json.dumps(table))
    else:
        default = argv[2] if len(argv) > 2 else ""
        print(table.get(key, default))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
