"""Component-by-component probe of the camera state block at 0x3403B0.

0x3403BC moved 19-50 % of the frame with small deltas, so the block clearly
feeds the camera.  This probe walks every component with small (angle-sized)
deltas and stores one frame each, so the effect of each can be classified as
rotate / translate / zoom.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "probe_block"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="0x3403B0")
    ap.add_argument("--deltas", nargs="*", type=float, default=[0.2, 0.5])
    ap.add_argument("--settle", type=float, default=1.0)
    args = ap.parse_args()
    addr = int(args.base, 0)
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur = b.read_floats(addr, 4)
    print("block:", [round(v, 4) for v in cur])
    for idx in range(4):
        for delta in args.deltas:
            val = cur[:]
            val[idx] = cur[idx] + delta
            stop = threading.Event()

            def wr(val=val, stop=stop):
                while not stop.is_set():
                    b.write_float_block(addr, val)

            th = threading.Thread(target=wr, daemon=True)
            th.start()
            time.sleep(args.settle)
            held = b.read_floats(addr, 4)
            shot = w.grab()
            score = diffscore(base, shot)
            stop.set()
            th.join(timeout=1)
            time.sleep(0.35)
            b.write_float_block(addr, cur)
            name = f"i{idx}_d{delta}.png"
            Image.fromarray(shot.astype("uint8")).save(OUT / name)
            print(f"idx {idx} +{delta}: held={[round(v,3) for v in held]} "
                  f"frac={score['frac_gt16']:.3f} -> {name}")
            time.sleep(0.25)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
