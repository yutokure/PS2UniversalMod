"""Vectorised search for the EE-side render-camera packet.

Finds every 16-byte-aligned location that holds the render eye, and checks
whether the 0x00..0x40 bytes before it hold the live camera forward vector
(i.e. the scratchpad layout direction@+0, eye@+0x10 that VU1 receives).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\PS2CameraLab\work\sstates_extracted")
STATES = ["base", "base_only_wait", "base_left_moved",
          "base_chara_little_moved_and_cam_big_moved"]
EYE = 0x340360
FWD = 0x53ADA0
TOL = 1e-3


def main() -> None:
    for name in STATES:
        f = np.fromfile(ROOT / name / "eeMemory.bin", dtype=np.uint8).view("<f4")
        eye = np.array([float(f[EYE // 4 + i]) for i in range(3)])
        fwd = np.array([float(f[FWD // 4 + i]) for i in range(3)])
        fwd = fwd / np.linalg.norm(fwd)
        print(f"\n=== {name} === eye={eye.round(3)} fwd={fwd.round(4)}")

        m = (np.abs(f[:-3] - eye[0]) < TOL) & (np.abs(f[1:-2] - eye[1]) < TOL) & (np.abs(f[2:-1] - eye[2]) < TOL)
        eye_hits = np.flatnonzero(m) * 4
        print(f"eye copies: {len(eye_hits)} -> {[hex(int(h)) for h in eye_hits[:16]]}")

        fwd_hits = []
        for back in (0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64):
            for h in eye_hits:
                a = int(h) - back
                if a < 0:
                    continue
                v = f[a // 4: a // 4 + 3]
                if np.all(np.abs(v - fwd) < 2e-3):
                    fwd_hits.append((a, int(h), back))
        for a, h, back in fwd_hits:
            print(f"  *** fwd @ {a:#09x}  eye @ {h:#09x}  (delta -0x{back:x})")

        # also: any place holding fwd immediately followed 0x10 later by eye
        mf = (np.abs(f[:-3] - fwd[0]) < 2e-3) & (np.abs(f[1:-2] - fwd[1]) < 2e-3) & (np.abs(f[2:-1] - fwd[2]) < 2e-3)
        fwd_all = np.flatnonzero(mf) * 4
        print(f"fwd copies: {[hex(int(h)) for h in fwd_all[:16]]}")


if __name__ == "__main__":
    main()
