"""The second part of tests/test_forge_ui.py (materials: a Material Maker graph applied and saved; the 900x600
layout; construction history: the poly ops, editable, Delete History, DynaMesh as a re-runnable step, a sculpt
stroke as a history step): the whole suite ran past its one-minute limit, so it runs as three. Under a minute.

    python tests/test_forge_ui2.py
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["LOKI_FORGE_UI_PART"] = "2"
sys.argv = [str(Path(__file__).with_name("test_forge_ui.py"))]
runpy.run_path(sys.argv[0], run_name="__main__")
