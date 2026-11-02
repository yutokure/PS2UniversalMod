"""Probe 0x3403B0..0x3403BC: the camera state block.

An earlier visual sweep showed 0x3403BC alone moved 55 % of the frame, far more
than any other non-eye value.  If that is the camera's yaw/pitch the view can be
rotated through it.
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

from PIL import Image  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "probe_3bc"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur = b.read_floats(0x3403B0, 4)
    print("0x3403B0 block:", [round(v, 4) for v in cur])
    for delta in (0.3, 1.0, 3.0):
        val = cur[:]
        val[3] = cur[3] + delta
        stop = threading.Event()

        def wr(val=val, stop=stop):
            while not stop.is_set():
                b.write_float_block(0x3403B0, val)

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(1.2)
        held = b.read_floats(0x3403B0, 4)
        shot = w.grab()
        score = diffscore(base, shot)
        stop.set()
        th.join(timeout=1)
        time.sleep(0.4)
        b.write_float_block(0x3403B0, cur)
        Image.fromarray(shot.astype("uint8")).save(OUT / f"d{delta}.png")
        print(f"delta +{delta}: held={[round(v,3) for v in held]} frac={score['frac_gt16']:.3f}")
        time.sleep(0.3)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
