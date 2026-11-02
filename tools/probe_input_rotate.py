"""Does FFX-2 itself rotate the field camera from any pad input?

If some button (L2/R2/L1/R1/right stick) rotates the camera natively, the game
owns a yaw variable we can drive.  Each candidate is held for ~1 s while the
render forward vector (0x53ADA0) and the camera angle block are sampled.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, ROOT / "tools")

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
import pcsx2_input  # noqa: E402


def snap(b):
    fwd = b.read_floats(0x53ADA0, 3)
    ang = b.read_floats(0x3403B0, 4)
    eye = b.read_floats(0x340360, 3)
    return fwd, ang, eye


def main() -> None:
    b = PineBackend()
    b.connect()
    hwnd = pcsx2_input.render_child()
    print("render hwnd", hex(hwnd))
    base = snap(b)
    print("base fwd", [round(v, 4) for v in base[0]], "ang", [round(v, 4) for v in base[1]])
    for btn in ("l2", "r2", "l1", "r1", "triangle", "square"):
        try:
            pcsx2_input.hold({btn: True}, hwnd)
            time.sleep(1.0)
            now = snap(b)
            pcsx2_input.hold({btn: False}, hwnd)
        except Exception as exc:  # noqa: BLE001
            print(btn, "failed:", exc)
            continue
        dfwd = max(abs(now[0][i] - base[0][i]) for i in range(3))
        dang = max(abs(now[1][i] - base[1][i]) for i in range(3))
        deye = max(abs(now[2][i] - base[2][i]) for i in range(3))
        print(f"{btn:9s} dfwd={dfwd:.4f} dang={dang:.4f} deye={deye:.3f} "
              f"fwd={[round(v,3) for v in now[0]]}")
        time.sleep(0.6)
    b.close()


if __name__ == "__main__":
    main()
