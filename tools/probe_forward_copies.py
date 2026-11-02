"""Test whether the forward-vector copies outside 0x53ADA0 drive the render."""
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


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    ref = b.read_floats(0x53ADA0, 4)
    print("reference forward", [round(v, 3) for v in ref[:3]])
    for addr in (0x1165384, 0x116A890):
        cur = b.read_floats(addr, 3)
        print(hex(addr), "now", [round(v, 3) for v in cur])
        a = math.radians(50)
        ca, sa = math.cos(a), math.sin(a)
        v = cur[:3]
        nv = [v[0] * ca - v[2] * sa, v[1], v[0] * sa + v[2] * ca]
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
        time.sleep(0.4)
        b.write_float_block(addr, cur)
        print(f"  held {[round(x, 3) for x in held[:3]]} delta={score['frac_gt16']:.3f}")
        time.sleep(0.3)
    b.close()


if __name__ == "__main__":
    main()
