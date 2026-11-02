"""Enable or disable the stock-camera hook in the PCSX2 cheats file.

The hook makes the game's own field camera read the orbit slots written by the mod.
It is applied by the runtime (core/camera_runtime), not from the cheats file: it is
on while the orbit or the free camera is used and off in the original camera, so
the stock camera does not depend on the mod being open.  ``enable`` is retired for
that reason.  ``disable`` removes an old copy of the block if one is still in the
cheats file.

    python tools/stock_hook.py status
    python tools/stock_hook.py disable
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHEATS = Path(r"C:\PS2CameraLab\pcsx2\fork-B056de99\cheats\8A6D7F14.pnach")
HOOK = ROOT / "patches" / "stock_camera_hook.pnach.txt"
MARK = "=== Stock camera hook"


def _hook_block() -> str:
    return HOOK.read_text(encoding="utf-8")


def status() -> bool:
    """True when hook words are still in the cheats file (they should not be)."""
    return "patch=1,EE,001A9604" in CHEATS.read_text(encoding="utf-8")


def enable() -> None:
    # Writing the hook at boot would apply it with no runtime to feed it, and the
    # stock camera would then aim at stale slots.  The runtime owns the hook now.
    print("not enabled: the runtime applies the hook while the orbit is on")


def disable() -> None:
    text = CHEATS.read_text(encoding="utf-8")
    if MARK not in text:
        print("already disabled")
        return
    head = text[:text.index(MARK)].rstrip("\n") + "\n"
    CHEATS.write_text(head, encoding="utf-8")
    print("disabled")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "enable":
        enable()
    elif cmd == "disable":
        disable()
    print("hook words in cheats file:", status())
