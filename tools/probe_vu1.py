"""Try to rotate the view by writing the camera packet where VU1 actually reads it.

The EE copy at 0x53ADA0 is only transferred to VU1 when the game's camera
controller rebuilds the packet, so while the player stands still the packet in
VU1 memory is authoritative.  The scratchpad mirror we measured is
(direction @ +0x00, eye @ +0x10), so the same layout is tried at
0x70000000 (EE scratchpad) and 0x70004000 (VU1 data memory window).
"""
from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

CANDIDATES = [0x70000060, 0x70004060, 0x70004000, 0x70000040]


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    ref = b.read_floats(0x53ADA0, 4)
    print("reference fwd", [round(v, 3) for v in ref[:3]])
    for addr in CANDIDATES:
        try:
            cur = b.read_floats(addr, 3)
        except Exception as exc:  # noqa: BLE001
            print(hex(addr), "read failed:", exc)
            continue
        d = diffscore(base, w.grab())
        print(hex(addr), "now", [round(v, 4) for v in cur], "| baseline delta", round(d["frac_gt16"], 3))
        if not any(abs(v) > 1e-6 for v in cur):
            continue
        a = math.radians(50)
        ca, sa = math.cos(a), math.sin(a)
        nv = [cur[0] * ca - cur[2] * sa, cur[1], cur[0] * sa + cur[2] * ca]
        stop = threading.Event()

        def wr(addr=addr, nv=nv, stop=stop):
            while not stop.is_set():
                b.write_float_block(addr, nv)

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(1.2)
        held = b.read_floats(addr, 3)
        score = diffscore(base, w.grab())
        stop.set()
        th.join(timeout=1)
        time.sleep(0.3)
        print(f"  held {[round(x, 3) for x in held]} delta={score['frac_gt16']:.3f}")
        try:
            b.write_float_block(addr, cur)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    b.close()


if __name__ == "__main__":
    main()
