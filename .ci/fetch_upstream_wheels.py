#!/usr/bin/env python3
"""Put upstream PyPI wheels into dist/, retagged and marked, for the upstream-wheel evaluation.

Filename retagging makes them outrank forge's published wheel: pip sorts on tag priority before
build tag, so android_21 would lose to our android_24. The UPSTREAM_EVAL file inside dist-info
lets the tester prove on the device which wheel actually loaded.
"""
import argparse
import json
import re
import urllib.request
import zipfile
from pathlib import Path

IOS_SLICES = ("arm64_iphoneos", "arm64_iphonesimulator", "x86_64_iphonesimulator")


def mobile_targets(files: list[str], py: str, platform: str) -> list[tuple[str, str]]:
    """(upstream filename, retagged filename) for this Python's native wheels on a platform."""
    tag = f"cp{py.replace('.', '')}"
    out = []
    for fn in files:
        if f"-{tag}-" not in fn:
            continue
        if platform == "android" and re.search(r"-android_\d+_x86_64\.whl$", fn):
            out.append((fn, re.sub(r"-android_\d+_", "-android_24_", fn)))
        elif platform == "ios" and re.search(r"-ios_\d+_\d+_(" + "|".join(IOS_SLICES) + r")\.whl$", fn):
            out.append((fn, fn))
    return out


def pure_targets(files: list[str], platform: str) -> list[tuple[str, str]]:
    """One platform-tagged copy of the pure wheel per slice the build resolves."""
    pure = [fn for fn in files if fn.endswith("-none-any.whl")]
    if not pure:
        return []
    fn = pure[0]
    stem = re.sub(r"-py[0-9.py]+-none-any\.whl$", "", fn)
    plats = ["android_24_x86_64"] if platform == "android" else [f"ios_13_0_{s}" for s in IOS_SLICES]
    return [(fn, f"{stem}-py3-none-{p}.whl") for p in plats]


def add_marker(src: Path, dst: Path, original: str) -> None:
    """Copy a wheel, adding the provenance marker to its dist-info."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        info = next(n.split("/")[0] for n in zin.namelist() if n.split("/")[0].endswith(".dist-info"))
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr(f"{info}/UPSTREAM_EVAL", original)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=["mobile", "pure"])
    p.add_argument("--pkg", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--python", required=True)
    p.add_argument("--platform", required=True, choices=["android", "ios"])
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()

    with urllib.request.urlopen(f"https://pypi.org/pypi/{a.pkg}/{a.version}/json", timeout=60) as r:
        urls = {f["filename"]: f["url"] for f in json.load(r)["urls"]}
    names = sorted(urls)
    targets = mobile_targets(names, a.python, a.platform) if a.mode == "mobile" else pure_targets(names, a.platform)
    if a.mode == "mobile" and a.platform == "ios" and not any("arm64_iphonesimulator" in t[0] for t in targets):
        targets = []  # the arm64 runner cannot run what the other slices would give it

    a.out.mkdir(parents=True, exist_ok=True)
    for original, final in targets:
        tmp = a.out / f"{final}.download"
        urllib.request.urlretrieve(urls[original], tmp)
        add_marker(tmp, a.out / final, original)
        tmp.unlink()
    print(json.dumps({"found": bool(targets), "wheels": [t[0] for t in targets]}))


if __name__ == "__main__":
    main()
