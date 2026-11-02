"""Stability test for the yaw field at 0x3403B0.

A held yaw offset produced a clearly rotated frame once, so the field really is
the camera yaw.  This holds a fixed offset for several seconds and captures a
series of frames: if the rotation is stable every frame shows it, if it is a
race the frames alternate between rotated and original.
"""
from __future__ import annotations

import argparse
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

OUT = ROOT / "reports" / "yaw_stability"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", type=float, default=0.6)
    ap.add_argument("--pitch-delta", type=float, default=0.0)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--interval", type=float, default=0.35)
    args = ap.parse_args()
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur = b.read_floats(0x3403B0, 4)
    val = cur[:]
    val[0] = cur[0] + args.delta
    val[1] = cur[1] + args.pitch_delta
    print("base block", [round(v, 4) for v in cur], "->", [round(v, 4) for v in val])
    stop = threading.Event()

    def wr():
        while not stop.is_set():
            b.write_float_block(0x3403B0, val)

    th = threading.Thread(target=wr, daemon=True)
    th.start()
    scores = []
    try:
        time.sleep(0.8)
        for i in range(args.frames):
            shot = w.grab()
            s = diffscore(base, shot)
            scores.append(s["frac_gt16"])
            Image.fromarray(shot.astype("uint8")).save(OUT / f"f{i}.png")
            print(f"  frame {i}: frac={s['frac_gt16']:.3f} yaw_now={round(b.read_floats(0x3403B0,1)[0],4)}")
            time.sleep(args.interval)
    finally:
        stop.set()
        th.join(timeout=1)
        time.sleep(0.4)
        b.write_float_block(0x3403B0, cur)
        b.close()
    rotated = sum(1 for s in scores if s > 0.15)
    print(f"rotated frames: {rotated}/{len(scores)}")
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
