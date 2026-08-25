# /// script
# requires-python = ">=3.11"
# ///
"""Print one value from tests/example-runner/overrides.toml.

Usage: example_override.py <recipe>/<example> <key> [<default>]
Always exits 0 with the value (or the default) on stdout — callers treat the
output as data; a broken overrides file must degrade to defaults, not red a
whole shard.
"""

import sys
import tomllib
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: example_override.py <slug> <key> [<default>]", file=sys.stderr)
        return 2
    slug, key = argv[0], argv[1]
    default = argv[2] if len(argv) > 2 else ""
    path = Path(__file__).resolve().parent.parent / "tests" / "example-runner" / "overrides.toml"
    try:
        print(tomllib.loads(path.read_text()).get(slug, {}).get(key, default))
    except Exception:
        print(default)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
