"""Probe a candidate camera-control vector: perturb each component and score
the rendered response."""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default="0x53A990")
    ap.add_argument("--deltas", nargs="*", type=float, default=[0.5, 2.0, 10.0])
    ap.add_argument("--settle", type=float, default=0.9)
    args = ap.parse_args()
    addr = int(args.addr, 0)
    b = PineBackend()
    b.connect()
    w = Window()
    orig = list(b.read_floats(addr, 4))
    base = w.grab()
    print("orig", [round(v, 3) for v in orig])
    for idx in range(3):
        delta = args.deltas[idx]
        stop = threading.Event()
        val = orig[:]
        val[idx] = orig[idx] + delta

        def wr(stop=stop, val=val):
            while not stop.is_set():
                b.write_float_block(addr, val)

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(args.settle)
        score = diffscore(base, w.grab())
        held = [round(v, 3) for v in b.read_floats(addr, 4)]
        stop.set()
        th.join(timeout=1)
        time.sleep(0.35)
        print(f"component {idx} +{delta}: frac={score['frac_gt16']:.3f} held={held}")
    b.write_float_block(addr, orig)
    print("restored", [round(v, 3) for v in b.read_floats(addr, 4)])
    b.close()


if __name__ == "__main__":
    main()
