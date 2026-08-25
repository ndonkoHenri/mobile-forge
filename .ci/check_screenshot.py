# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Screenshot verdict helpers for the example runner.

  check_screenshot.py blank <img>    -> "blank=0|1 dominant=F colors=N"; exit 10 when blank
  check_screenshot.py diff <a> <b>   -> "ratio=F" (fraction of pixels that changed)

blank: the OS chrome (status/nav bars — a clock and battery icon would keep a
truly dead frame under any threshold) is cropped off, colors are quantized to
8 levels per channel so antialiasing collapses into its base color, and the
frame is blank when one color dominates or almost no distinct colors remain.
Every shipped example settles to an appbar + text, which no solid boot/splash
frame can imitate; a legitimately sparse UI still lands well under the
dominance threshold once text pixels quantize away from the surface color.
"""

import sys

from PIL import Image, ImageChops

CROP_TOP = 0.04
CROP_BOTTOM = 0.06
# Calibrated on synthetic frames: a sparse-but-real UI (appbar strip + a dozen
# small text lines at 1080x2280) measures dominant~0.996 / colors~21, while
# solid boot frames measure 1.0 / 1-3 — so dominance alone must sit above
# 0.996 and the color floor does the heavy lifting (antialiased text always
# spreads into many quantized buckets; a flat frame never does).
BLANK_DOMINANT = 0.997
BLANK_MIN_COLORS = 8
DIFF_CHANNEL_DELTA = 16  # per-channel noise floor before a pixel counts as changed

_QUANT = bytes(((v >> 5) << 5) for v in range(256)) * 3


def _load(path: str) -> Image.Image:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return img.crop((0, int(h * CROP_TOP), w, int(h * (1 - CROP_BOTTOM))))


def blank(path: str) -> int:
    img = _load(path).point(_QUANT)
    total = img.size[0] * img.size[1]
    colors = img.getcolors(maxcolors=total) or []
    dominant = max(count for count, _ in colors) / total
    is_blank = dominant > BLANK_DOMINANT or len(colors) < BLANK_MIN_COLORS
    print(f"blank={int(is_blank)} dominant={dominant:.4f} colors={len(colors)}")
    return 10 if is_blank else 0


def diff(a: str, b: str) -> int:
    ia, ib = _load(a), _load(b)
    if ia.size != ib.size:
        print("ratio=1.0000")
        return 0
    delta = ImageChops.difference(ia, ib).convert("L")
    changed = delta.point(lambda v: 255 if v > DIFF_CHANNEL_DELTA else 0)
    ratio = changed.histogram()[255] / (ia.size[0] * ia.size[1])
    print(f"ratio={ratio:.4f}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "blank":
        return blank(argv[1])
    if len(argv) >= 3 and argv[0] == "diff":
        return diff(argv[1], argv[2])
    print("usage: check_screenshot.py blank <img> | diff <a> <b>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
