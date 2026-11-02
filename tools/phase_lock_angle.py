"""Phase-locked angle override.

Continuous writes lose because they can land after the camera code has already
consumed the angle.  This variant polls the angle word and writes our value the
moment the game refreshes it, so the write always lands *after* the game's
store and hopefully *before* the read that builds the view direction.

    idle: 1 read per poll (~60 us)
    event: 1 extra write
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

OUT = ROOT / "reports" / "phase_lock"
OUT.mkdir(parents=True, exist_ok=True)
YAW = 0x3403B0


def run(backend, target_bits, stop, counter):
    b = backend
    polls = writes = 0
    while not stop.is_set():
        try:
            v = b.read_u32(YAW)
        except Exception:  # noqa: BLE001
            time.sleep(0.01)
            continue
        polls += 1
        if v != target_bits:
            b.write_u32(YAW, target_bits)
            writes += 1
    counter["polls"] = polls
    counter["writes"] = writes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delta", type=float, default=0.6)
    ap.add_argument("--pitch-delta", type=float, default=0.0)
    ap.add_argument("--frames", type=int, default=8)
    args = ap.parse_args()
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur = b.read_floats(YAW, 4)
    val = cur[:]
    val[0] = cur[0] + args.delta
    val[1] = cur[1] + args.pitch_delta
    print("base", [round(v, 4) for v in cur], "->", [round(v, 4) for v in val])
    stop = threading.Event()
    counter: dict = {}
    import struct
    target_bits = struct.unpack("<I", struct.pack("<f", val[0]))[0]
    th = threading.Thread(target=run, args=(b, target_bits, stop, counter), daemon=True)
    th.start()
    scores = []
    try:
        time.sleep(0.8)
        for i in range(args.frames):
            shot = w.grab()
            s = diffscore(base, shot)
            scores.append(round(s["frac_gt16"], 3))
            Image.fromarray(shot.astype("uint8")).save(OUT / f"f{i}.png")
            print(f"  frame {i}: frac={s['frac_gt16']:.3f} yaw={round(b.read_floats(YAW,1)[0],4)}")
            time.sleep(0.3)
    finally:
        stop.set()
        th.join(timeout=2)
        time.sleep(0.3)
        b.write_float_block(YAW, cur)
        b.close()
    print("counter", counter)
    rot = sum(1 for s in scores if s > 0.15)
    print(f"rotated {rot}/{len(scores)}")
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
