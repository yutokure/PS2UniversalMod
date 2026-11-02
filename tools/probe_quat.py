"""Test 0x3403D0 as a quaternion rotation post-offset.

0x3403DC (the w component of the vec4 at 0x3403D0) is extremely sensitive: even
+0.05 scrambles most of the frame, which is exactly what a near-degenerate
quaternion does.  This writes proper rotations and checks whether the view
rotates cleanly.

    q = (axis * sin(theta/2), cos(theta/2))
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

OUT = ROOT / "reports" / "quat"
OUT.mkdir(parents=True, exist_ok=True)
BASE = 0x3403D0


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    cur = b.read_floats(BASE, 4)
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    print("block 0x3403D0:", [round(v, 5) for v in cur])
    print("block 0x3403E0:", [round(v, 3) for v in b.read_floats(0x3403E0, 4)])
    trials = [
        ("yaw30", (0.0, math.sin(math.radians(15)), 0.0, math.cos(math.radians(15)))),
        ("yaw90", (0.0, math.sin(math.radians(45)), 0.0, math.cos(math.radians(45)))),
        ("pitch20", (math.sin(math.radians(10)), 0.0, 0.0, math.cos(math.radians(10)))),
        ("identity", (0.0, 0.0, 0.0, 1.0)),
    ]
    for name, q in trials:
        stop = threading.Event()

        def wr(q=q, stop=stop):
            while not stop.is_set():
                b.write_float_block(BASE, q)

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(1.0)
        held = b.read_floats(BASE, 4)
        shot = w.grab()
        score = diffscore(base, shot)
        stop.set()
        th.join(timeout=1)
        time.sleep(0.35)
        b.write_float_block(BASE, cur)
        Image.fromarray(shot.astype("uint8")).save(OUT / f"{name}.png")
        print(f"{name}: held={[round(v,4) for v in held]} frac={score['frac_gt16']:.3f}")
        time.sleep(0.3)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
