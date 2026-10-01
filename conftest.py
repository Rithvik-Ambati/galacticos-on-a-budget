"""Ensures the repo root (where engine/, config/, db/ live) is importable regardless
of which directory pytest is invoked from."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
