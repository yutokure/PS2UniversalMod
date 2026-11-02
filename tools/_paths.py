"""Path shim for the scripts in tools/: puts the repository and the lab scripts on sys.path.

``import _paths`` (from a script run as ``python tools/x.py``) replaces the hard-coded absolute
paths the older tools used.  Locations come from ``core.config.paths`` (environment variables,
``config/local_config.json`` or the lab layout).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.config import paths  # noqa: E402

LAB = paths.lab_dir()
WORK = paths.dump_dir()
PCSX2_DIR = paths.pcsx2_dir()
SAVESTATES = paths.savestate_dir()
for _p in (str(paths.lab_scripts_dir()),):
    if _p not in sys.path:
        sys.path.insert(0, _p)
