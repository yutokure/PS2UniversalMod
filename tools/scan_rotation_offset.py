"""Scan for a *rotation* post-offset analogous to the eye offset at 0x3403E0.

The eye offset proves the camera pipeline has an "extra transform" stage that
the game applies after its own camera maths and never rewrites.  If a rotation
offset exists next to it, writing it would rotate the view deterministically.

Each float in the window is nudged and the rendered frame is compared.
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

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="0x3403C0")
    ap.add_argument("--end", default="0x340480")
    ap.add_argument("--delta", type=float, default=0.35)
    ap.add_argument("--settle", type=float, default=0.5)
    args = ap.parse_args()
    start, end = int(args.start, 0), int(args.end, 0)
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    print(f"scan {start:#x}..{end:#x} delta={args.delta}")
    hits = []
    for addr in range(start, end, 4):
        cur = b.read_f32(addr)
        if not (abs(cur) < 1e5):
            continue
        val = cur + args.delta
        stop = threading.Event()

        def wr(addr=addr, val=val, stop=stop):
            while not stop.is_set():
                b.write_float_block(addr, [val])

        th = threading.Thread(target=wr, daemon=True)
        th.start()
        time.sleep(args.settle)
        score = diffscore(base, w.grab())
        stop.set()
        th.join(timeout=1)
        b.write_float_block(addr, [cur])
        frac = score["frac_gt16"]
        if frac > 0.05:
            hits.append((addr, cur, frac))
            print(f"  HIT {addr:#08x} cur={cur:+.4f} frac={frac:.3f}")
        time.sleep(0.12)
    print(f"\n{len(hits)} hits")
    for a, v, f in hits:
        print(f"  {a:#08x} value={v:+.4f} frac={f:.3f}")
    b.close()


if __name__ == "__main__":
    main()
