# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Merge example-shard results into one reviewable page.

Usage: make_gallery.py <extracted-artifacts-dir> <out-html>

Walks the dir for results/*.tsv (slug, platform, verdict, detail) and
shots/*.png, emits a self-contained HTML contact sheet (thumbnails inlined as
data URIs — GitHub artifacts have no preview, so one file must be enough to
eyeball a whole sweep) and prints a markdown summary table to stdout for the
step summary. Failures sort first. Exit 0 always: the shard jobs gate.
"""

import base64
import html
import io
import sys
from pathlib import Path

from PIL import Image

THUMB = (320, 640)
OK_VERDICTS = {"PASS"}


def load_results(root: Path) -> list[dict]:
    rows = {}
    for tsv in sorted(root.rglob("results/*.tsv")):
        parts = tsv.read_text().strip().split("\t")
        if len(parts) != 4:
            continue
        slug, platform, verdict, detail = parts
        flatname = tsv.stem
        shot = next(iter(tsv.parent.parent.glob(f"shots/{flatname}.png")), None)
        rows[(slug, platform)] = {
            "slug": slug,
            "platform": platform,
            "verdict": verdict,
            "detail": detail,
            "shot": shot,
        }
    return sorted(rows.values(), key=lambda r: (r["verdict"] in OK_VERDICTS, r["slug"], r["platform"]))


def thumb_uri(path: Path) -> str | None:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail(THUMB)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def main(argv: list[str]) -> int:
    root, out_html = Path(argv[0]), Path(argv[1])
    rows = load_results(root)
    if not rows:
        print("no results found", file=sys.stderr)
        out_html.write_text("<p>no results</p>")
        return 0

    cells = []
    for r in rows:
        ok = r["verdict"] in OK_VERDICTS
        uri = thumb_uri(r["shot"]) if r["shot"] else None
        img = f'<img src="{uri}" loading="lazy">' if uri else "<p>(no screenshot)</p>"
        cells.append(
            f'<figure class="{"ok" if ok else "fail"}">{img}'
            f"<figcaption><b>{html.escape(r['slug'])}</b> · {r['platform']}<br>"
            f'<span class="badge">{r["verdict"]}</span> {html.escape(r["detail"])}</figcaption></figure>'
        )
    n_fail = sum(1 for r in rows if r["verdict"] not in OK_VERDICTS)
    out_html.write_text(
        "<!doctype html><meta charset=utf-8><title>example screenshots</title><style>"
        "body{font:14px system-ui;margin:1rem;background:#fafafa}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1rem}"
        "figure{margin:0;padding:.5rem;border-radius:8px;background:#fff;border:2px solid #2da44e}"
        "figure.fail{border-color:#cf222e}img{max-width:100%;border:1px solid #ddd}"
        ".badge{font-weight:700}figure.fail .badge{color:#cf222e}figure.ok .badge{color:#2da44e}"
        f"</style><h1>Example run — {len(rows)} results, {n_fail} failing</h1><main>"
        + "".join(cells)
        + "</main>"
    )

    print(f"| example | platform | verdict | detail |")
    print(f"|---|---|---|---|")
    for r in rows:
        mark = "✅" if r["verdict"] in OK_VERDICTS else "❌"
        print(f"| `{r['slug']}` | {r['platform']} | {mark} {r['verdict']} | {r['detail']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
