#!/usr/bin/env python3
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "shared"))
from build import build
build("16-vdr-analytics", "dataroom.html")
