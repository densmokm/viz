#!/usr/bin/env python3
"""Splice results.json into the page template. Keeps the demo one command from raw data."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
data = json.loads((BASE / "data" / "results.json").read_text())
html = (Path(__file__).parent / "page.template.html").read_text()
payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
out = BASE / "revenue-bridge.html"
out.write_text(html.replace("__DATA__", payload))
print(f"built {out.relative_to(BASE.parent.parent)}  ({out.stat().st_size/1024:.0f} KB)")
