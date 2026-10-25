"""The second half of tests/test_forge_pro_ui.py (pivot edit, undo of view changes, every object editable, pro-only
keys, the pro workspace, snapping, the scene checks): the whole suite ran past its one-minute limit, so it runs as
three suites of the same checks (test_forge_pro3_ui.py: Forge dressed as a pro package). Under a minute.

    python tests/test_forge_pro2_ui.py
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["LOKI_FORGE_PRO_PART"] = "2"
sys.argv = [str(Path(__file__).with_name("test_forge_pro_ui.py"))]
runpy.run_path(sys.argv[0], run_name="__main__")
