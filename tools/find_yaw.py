"""Locate the yaw field next to the known pitch field (0x3403B4).

0x3403B4 holds -pitch in radians and matches the live forward vector exactly,
so the yaw must be stored the same way in the same block.  This scans a window
around it for a float equal to any plausible yaw encoding of the live forward.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

START = 0x340300
END = 0x340500


def main() -> None:
    b = PineBackend()
    b.connect()
    fwd = b.read_floats(0x53ADA0, 3)
    n = math.sqrt(sum(v * v for v in fwd))
    fx, fy, fz = (v / n for v in fwd)
    pitch = math.asin(fy)
    yaw_a = math.atan2(fx, fz)
    yaw_b = math.atan2(-fz, fx)
    yaw_c = math.atan2(fz, -fx)
    print(f"fwd=({fx:.6f},{fy:.6f},{fz:.6f}) pitch={pitch:.6f} "
          f"yaw[atan2(x,z)]={yaw_a:.6f} yaw[atan2(-z,x)]={yaw_b:.6f} yaw[atan2(z,-x)]={yaw_c:.6f}")

    vals = {off: b.read_f32(off) for off in range(START, END, 4)}
    targets = {
        "pitch": [-pitch, pitch],
        "yaw_a": [yaw_a, -yaw_a],
        "yaw_b": [yaw_b, -yaw_b],
        "yaw_c": [yaw_c, -yaw_c],
    }
    for name, (t1, t2) in targets.items():
        for t in (t1, t2):
            hits = [off for off, v in vals.items() if abs(v - t) < 2e-4]
            if hits:
                print(f"  {name} {t:+.6f}: {[hex(h) for h in hits]}")
    print("\nblock around 0x3403B0:")
    for off in range(0x340390, 0x340410, 0x10):
        print(f"  {off:#08x}", [round(vals.get(off + 4 * k, 0.0), 4) for k in range(4)])
    b.close()


if __name__ == "__main__":
    main()
