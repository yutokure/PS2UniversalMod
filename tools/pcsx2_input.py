"""Direct PCSX2 input from Python (no MCP server, no GDB session).

The automated harness needs to walk the character while the camera runtime is
running.  Driving that through the MCP would open a second GDB session and
leave the VM paused, so the same Win32 PostMessageW path the MCP uses is called
directly against the verified render child window.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = r"C:\PS2CameraLab\vendor\PCSX2_MCP\src"
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

import win32gui  # noqa: E402
import win32process  # noqa: E402

import pcsx2_mcp.keyboard_input as kbi  # noqa: E402

CONFIG = Path(r"C:\PS2CameraLab\pcsx2\fork-B056de99\inis\PCSX2.ini")


def _pcsx2_pids() -> set[int]:
    import psutil
    return {p.info["pid"] for p in psutil.process_iter(["pid", "name"])
            if "pcsx2" in (p.info.get("name") or "").lower()}


def render_child() -> int:
    """Largest native child window of the PCSX2 Qt window."""
    pids = _pcsx2_pids()
    mains = []

    def cb(hwnd, _):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in pids and win32gui.GetClassName(hwnd).startswith("Qt") and win32gui.GetWindowText(hwnd):
            mains.append(hwnd)

    win32gui.EnumWindows(cb, None)
    if not mains:
        raise RuntimeError("no PCSX2 main window")
    best = None
    for parent in mains:
        children = []

        def ccb(hwnd, _):
            rect = win32gui.GetWindowRect(hwnd)
            children.append((abs(rect[2] - rect[0]) * abs(rect[3] - rect[1]), hwnd))

        win32gui.EnumChildWindows(parent, ccb, None)
        if children:
            area, hwnd = max(children)
            if best is None or area > best[0]:
                best = (area, hwnd)
    if best is None:
        raise RuntimeError("no render child window")
    return best[1]


_KB = kbi.BackgroundKeyboard()


def hold(buttons: dict[str, bool], hwnd: int | None = None) -> None:
    _KB.set_buttons(hwnd or render_child(), buttons, CONFIG)


def walk(steps: int = 3, ms: int = 220, button: str = "up") -> None:
    """Hold the forward direction.  ``up`` is the D-pad up binding, which FFX-2
    treats as "walk forward" exactly like the left stick."""
    hwnd = render_child()
    hold({button: True}, hwnd)
    try:
        import time
        for _ in range(steps):
            time.sleep(ms / 1000.0)
    finally:
        hold({button: False}, hwnd)


if __name__ == "__main__":
    print("render hwnd", hex(render_child()))
    walk(3)
    print("walked")
