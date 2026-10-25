"""The third part of tests/test_forge_ui.py: the Creature way (controls, not JSON, make a model shown in the four
panels; the advanced spec refuses an invalid one). Under a minute.

    python tests/test_forge_ui3.py
"""
import os
import runpy
import sys
from pathlib import Path

os.environ["LOKI_FORGE_UI_PART"] = "3"
sys.argv = [str(Path(__file__).with_name("test_forge_ui.py"))]
runpy.run_path(sys.argv[0], run_name="__main__")
