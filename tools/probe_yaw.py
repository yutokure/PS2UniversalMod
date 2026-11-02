"""Focused yaw test: hold a yaw offset on 0x3403B0 and watch the frame.

The value at 0x3403B0 matches the live camera yaw exactly (0x3403B4 matches
-pitch and does rotate), so a yaw change must be able to rotate the view too.
This holds several yaw offsets for longer and records one frame each.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

from PIL import Image  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "probe_yaw"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur = b.read_floats(0x3403B0, 4)
    print("block", [round(v, 4) for v in cur])
    for delta in (0.15, 0.4, 0.8, 1.6):
        val = cur[:]
        val[0] = cur[0] + delta
        stop = threading.Event()

        def wr(val=val, stop=stop):
            while not stop.is_set():
                b.write_float_block(0x3403B0, val)

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(1.8)
        fwd = b.read_floats(0x53ADA0, 3)
        held = b.read_floats(0x3403B0, 4)
        shot = w.grab()
        score = diffscore(base, shot)
        stop.set()
        th.join(timeout=1)
        time.sleep(0.4)
        b.write_float_block(0x3403B0, cur)
        Image.fromarray(shot.astype("uint8")).save(OUT / f"yaw{delta}.png")
        print(f"yaw +{delta}: held={round(held[0],4)} fwd={[round(v,3) for v in fwd]} "
              f"frac={score['frac_gt16']:.3f}")
        time.sleep(0.3)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
