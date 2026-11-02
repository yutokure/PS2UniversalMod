"""Locate the EE-side packet that carries the render camera to VU1.

The VU1 scratchpad mirrors the camera in a very specific layout (direction at
+0x00, eye at +0x10).  The EE source of that DMA must therefore contain the
same two vectors 0x10 apart.  Searching for that pattern finds the buffer the
renderer actually reads -- which is where a code hook or a write must land.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\PS2CameraLab\work\sstates_extracted")
STATES = ["base", "base_only_wait", "base_left_moved",
          "base_chara_little_moved_and_cam_big_moved"]
EYE = 0x340360
FWD = 0x53ADA0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=1e-3)
    ap.add_argument("--look", type=int, default=0x02000000)
    args = ap.parse_args()
    for name in STATES:
        f = np.fromfile(ROOT / name / "eeMemory.bin", dtype=np.uint8).view("<f4")
        fwd = [float(f[FWD // 4 + i]) for i in range(3)]
        eye = [float(f[EYE // 4 + i]) for i in range(3)]
        n = math.sqrt(sum(x * x for x in fwd))
        fwd = [x / n for x in fwd]
        print(f"\n=== {name} === fwd={[round(v,4) for v in fwd]} eye={[round(v,3) for v in eye]}")
        hits = []
        for i in range(f.size - 8):
            for j in range(0, args.look, 4):
                if j % 4:
                    break
                if (abs(float(f[i]) - eye[0]) <= args.tol
                        and abs(float(f[i + 1]) - eye[1]) <= args.tol
                        and abs(float(f[i + 2]) - eye[2]) <= args.tol):
                    hits.append(i * 4)
                    break
        print(f"eye copies: {len(hits)}")
        for h in hits[:20]:
            pre = [float(f[h // 4 - 4 + k]) for k in range(3)] if h >= 16 else None
            print(f"  {h:#09x}  prev16={[round(v,4) for v in pre] if pre else '-'}")
        # look for direction within 0x40 before each eye copy
        for h in hits[:20]:
            for back in (4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64):
                a = h - back
                if a < 0:
                    continue
                v = [float(f[a // 4 + k]) for k in range(3)]
                if all(abs(v[k] - fwd[k]) <= 2e-3 for k in range(3)):
                    print(f"  *** MATCH eye {h:#09x} with fwd at {a:#09x} (delta -{back:#x})")
                    break


if __name__ == "__main__":
    main()
