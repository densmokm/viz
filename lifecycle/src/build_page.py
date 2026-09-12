#!/usr/bin/env python3
"""Build the lifecycle home page from the shared catalogue."""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
html = (ROOT / "lifecycle" / "src" / "page.template.html").read_text()
html = html.replace("__CSS__", (ROOT / "shared" / "house.css").read_text())
data = json.loads((ROOT / "shared" / "catalogue.json").read_text())
html = html.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
out = ROOT / "lifecycle" / "index.html"
out.write_text(html)
print(f"built lifecycle/index.html  ({out.stat().st_size/1024:.0f} KB)")
