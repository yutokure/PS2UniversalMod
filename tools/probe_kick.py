"""Force the FFX-2 camera update (LATCH) and see whether yaw drives the eye.

FUN_001a91a0 is the per-frame camera update but it is wrapped in

    if ((&DAT_0033f730)[slot*0x1C0] != 0)          # slot active
      if ((&DAT_00340ac9)[entity*0x1050] != 0)     # <-- dirty latch
        ... rebuild camera ...

so while the player stands still the whole camera block is frozen, which is why
writes to yaw/pitch used to look like no-ops.  This probe pokes the latch.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

CAM = 0x340350
LATCH = 0x340AC9
ACC = 0x340ACC
POS = CAM + 0x50
EYE = CAM + 0x10
GAMEEYE = CAM + 0x20
YAW = CAM + 0x60
PITCH = CAM + 0x64
BASIS_EYE = 0x53ADB0
BASIS_FWD = 0x53ADA0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.6)
    ap.add_argument("--secs", type=float, default=6.0)
    ap.add_argument("--kick", type=int, default=1)
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    def u8(a):
        return b.read_u32(a) & 0xFF

    print(f"running={b.status() == 0}  latch=0x{LATCH:08X}")
    print(f"slot0={u8(0x33F730)} latch={u8(LATCH)} acc=0x{ACC:08X}:{u8(ACC)}")
    y0 = b.read_f32(YAW)
    p0, e0, g0 = vec(POS), vec(EYE), vec(GAMEEYE)
    f0 = vec(BASIS_FWD, 4)
    be0 = vec(BASIS_EYE, 4)
    print(f"before yaw={y0:+.6f} pos={[round(v, 4) for v in p0]}")
    print(f"       eye={[round(v, 4) for v in e0]} fwd={[round(v, 4) for v in f0]}")

    enc = [
        (YAW, struct.unpack("<I", struct.pack("<f", y0 + args.yaw))[0]),
        (LATCH, args.kick),
    ]
    deadline = time.monotonic() + args.secs
    n = 0
    hits = 0
    while time.monotonic() < deadline:
        for a, w in enc:
            b.write_u32(a, w)
        if n % 40 == 0:
            if u8(LATCH) == 0:
                hits += 1
        n += 1

    y1 = b.read_f32(YAW)
    p1, e1, g1 = vec(POS), vec(EYE), vec(GAMEEYE)
    f1 = vec(BASIS_FWD, 4)
    be1 = vec(BASIS_EYE, 4)
    print(f"after  yaw={y1:+.6f} pos={[round(v, 4) for v in p1]}")
    print(f"       eye={[round(v, 4) for v in e1]} fwd={[round(v, 4) for v in f1]}")
    print(f"       basis_eye={[round(v, 4) for v in be1]}")
    print(f"writes={n} ({n / args.secs:.0f}/s)")
    print(f"pos_moved={math.dist(p0, p1):.4f} eye_moved={math.dist(e0, e1):.4f} "
          f"gameeye_moved={math.dist(g0, g1):.4f}")
    dot = sum(a * c for a, c in zip(f0[:3], f1[:3]))
    print(f"fwd_before={[round(v, 4) for v in f0[:3]]}")
    print(f"fwd_after ={[round(v, 4) for v in f1[:3]]}  dot={dot:+.4f}")
    print(f"latch consumed at least {hits} times (0 => latch never observed cleared)")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
