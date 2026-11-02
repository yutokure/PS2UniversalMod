"""Launcher that works no matter which ``python`` is on PATH.

``python gui/camera_controller/app.py`` only works if *that* interpreter has
PySide6.  This script instead looks for a Python that does, in this order:

1. ``<repo>/.venv``                       - a venv created next to the project
2. ``<repo>/../python/venv``              - the lab venv used during development
3. the interpreter running this script (if it already has PySide6)
4. ``py -3`` / ``python`` on PATH

and then re-executes the GUI with it.  Nothing is installed and nothing is
modified; if no suitable interpreter exists it prints the exact command needed.

    python run_gui.py
    python run_gui.py --screenshot shot.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "gui" / "camera_controller" / "app.py"


def has_pyside6(python: Path) -> bool:
    try:
        res = subprocess.run([str(python), "-c", "import PySide6"],
                             capture_output=True, timeout=60)
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def candidates() -> list[Path]:
    out: list[Path] = []
    for base in (ROOT / ".venv", ROOT.parent / "python" / "venv"):
        for rel in ("Scripts/python.exe", "bin/python"):
            p = base / rel
            if p.exists():
                out.append(p)
    out.append(Path(sys.executable))
    return out


def main() -> int:
    args = sys.argv[1:]
    for python in candidates():
        if python != Path(sys.executable) and not has_pyside6(python):
            continue
        if python == Path(sys.executable):
            try:
                import PySide6  # noqa: F401
            except ModuleNotFoundError:
                continue
        print(f"PS2UniversalCamera: using {python}")
        return subprocess.call([str(python), str(APP), *args])

    sys.stderr.write(
        "No Python interpreter with PySide6 was found.\n"
        f"  project     : {ROOT}\n"
        f"  this python : {sys.executable}\n\n"
        "Create a virtual environment next to the project and install the deps:\n"
        f'  "{sys.executable}" -m venv "{ROOT / ".venv"}"\n'
        f'  "{ROOT / ".venv" / "Scripts" / "python.exe"}" -m pip install -r '
        f'"{ROOT / "requirements.txt"}"\n'
        "then run PS2UniversalCamera.bat again.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
