#!/usr/bin/env python3
"""
Assemble a demo page from the shared layer.

    house.css  +  viz.js  +  <demo>/src/page.template.html  +  <demo>/data/results.json

Keeping the stylesheet and chart toolkit shared is the point: every demo in the
repo reads as one system, and a fix to a scale or a mark spec lands everywhere.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"


def build(demo: str, output: str) -> Path:
    d = ROOT / "demos" / demo
    html = (d / "src" / "page.template.html").read_text()
    data = json.loads((d / "data" / "results.json").read_text())

    for token, text in (("__CSS__", (SHARED / "house.css").read_text()),
                        ("__VIZ__", (SHARED / "viz.js").read_text())):
        if token not in html:
            raise SystemExit(f"{demo}: template is missing {token}")
        html = html.replace(token, text)

    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("__DATA__", payload)
    if "__" in html.replace("__", "", 0) and any(t in html for t in ("__CSS__", "__VIZ__", "__DATA__")):
        raise SystemExit(f"{demo}: unsubstituted placeholder remains")

    out = d / output
    out.write_text(html)
    print(f"built demos/{demo}/{output}  ({out.stat().st_size / 1024:.0f} KB)")
    return out
