#!/usr/bin/env python3
"""Render a tutorial page from its content module."""
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tutorials" / "src"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SRC / "content" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TUTORIAL


def build(name, output):
    t = load(name)
    html = (SRC / "page.template.html").read_text()
    html = html.replace("__CSS__", (ROOT / "shared" / "house.css").read_text())
    html = html.replace("__TITLE__", t["title"])
    html = html.replace("__DATA__", json.dumps(t, separators=(",", ":")).replace("</", "<\\/"))
    out = ROOT / "tutorials" / output
    out.write_text(html)
    print(f"built tutorials/{output}  ({out.stat().st_size/1024:.0f} KB)")
    return out


if __name__ == "__main__":
    for name, output in [("t09", "revenue-decomposition.html"), ("t01", "alt-data-triangulation.html"),
                         ("t16", "vdr-analytics.html"), ("t18", "synergy-tracking.html")]:
        if len(sys.argv) > 1 and sys.argv[1] not in name:
            continue
        build(name, output)
