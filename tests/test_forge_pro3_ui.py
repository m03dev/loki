"""The third part of tests/test_forge_pro_ui.py: Forge dressed as a pro package (the menu bar, shelf, tool box, status
line, UI elements, INPUTS, the Outliner's cameras and search, Ctrl+Space). The whole suite ran past its one-minute
limit, so it runs as three suites of the same checks. Under a minute.

    python tests/test_forge_pro3_ui.py
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["LOKI_FORGE_PRO_PART"] = "3"
sys.argv = [str(Path(__file__).with_name("test_forge_pro_ui.py"))]
runpy.run_path(sys.argv[0], run_name="__main__")
