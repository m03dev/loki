"""The second part of tests/test_forge_dock_ui.py: a bar over the viewport (the sculpt brush bar) has a grip, dragging
it moves the bar and keeps it. The whole suite ran past its one-minute limit, so it runs as two. Under a minute.

    python tests/test_forge_dock2_ui.py
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["LOKI_FORGE_DOCK_PART"] = "2"
sys.argv = [str(Path(__file__).with_name("test_forge_dock_ui.py"))]
runpy.run_path(sys.argv[0], run_name="__main__")
