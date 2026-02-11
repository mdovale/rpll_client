"""Pytest conftest: ensure gui package is importable when running tests from repo root."""
import os
import sys

_gui_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _gui_dir not in sys.path:
    sys.path.insert(0, _gui_dir)
