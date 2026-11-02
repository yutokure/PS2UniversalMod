"""Probe the spherical orbit camera driven by FUN_0011c3d8.

Decompiled update (per frame):

    DAT_00480ec4 += (DAT_00480ec8 - DAT_00480ec4) * 0.125      # distance smoothing
    DAT_003312d0 += DAT_003312e0                               # centre x (+pan)
    DAT_003312d8 += DAT_003312e8                               # centre z (+pan)
    DAT_003312d4  = DAT_003312d4 - 10 + DAT_0032caa4 + DAT_003312e4
    DAT_003312f0  = clamp(DAT_003312f0, gp8360, gp8364)        # pitch, clamped
    cos/sin(DAT_003312f0), cos/sin(DAT_003312f4)               # pitch, yaw
    DAT_003312c0 = d0 + cosd*cosy * -dist
    DAT_003312c4 = d4 + cosd*siny * -dist        (+ -10 + DAT_0032caa4)
    DAT_003312c8 = d8 + sind     * -dist

0x3312C0 holds exactly the live eye, so this is the real camera solve.
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

EYE = 0x3312C0          # computed eye (x, y, z)
CTR = 0x3312D0          # centre      (x, y, z)
PAN = 0x3312E0          # centre pan  (x, y, z)
PITCH = 0x3312F0
YAW = 0x3312F4
DIST = 0x480EC4
DIST_TGT = 0x480EC8
HEIGHT = 0x32CAA4
CAM_EYE = 0x340360
CAM_POS = 0x3403A0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0, help="radians added to 0x3312F4")
    ap.add_argument("--pitch", type=float, default=0.0, help="radians added to 0x3312F0")
    ap.add_argument("--dist", type=float, default=None, help="absolute distance")
    ap.add_argument("--secs", type=float, default=0.0)
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    def dump():
        print(f"  eye    0x3312C0 {[round(v, 5) for v in vec(EYE)]}")
        print(f"  centre 0x3312D0 {[round(v, 5) for v in vec(CTR)]}")
        print(f"  pan    0x3312E0 {[round(v, 5) for v in vec(PAN)]}")
        print(f"  pitch  0x3312F0 {b.read_f32(PITCH):+.6f} rad ({math.degrees(b.read_f32(PITCH)):+.2f} deg)")
        print(f"  yaw    0x3312F4 {b.read_f32(YAW):+.6f} rad ({math.degrees(b.read_f32(YAW)):+.2f} deg)")
        print(f"  dist   0x480EC4 {b.read_f32(DIST):.4f}  target {b.read_f32(DIST_TGT):.4f}")
        print(f"  height 0x32CAA4 {b.read_f32(HEIGHT):+.5f}")
        print(f"  cam eye 0x340360 {[round(v, 5) for v in vec(CAM_EYE)]}")
        print(f"  cam pos 0x3403A0 {[round(v, 5) for v in vec(CAM_POS)]}")

    print(f"running={b.status() == 0}")
    print("before:")
    dump()
    if args.dump:
        b.close()
        return 0

    yaw0 = b.read_f32(YAW)
    pitch0 = b.read_f32(PITCH)
    tgt = {
        YAW: yaw0 + args.yaw,
        PITCH: pitch0 + args.pitch,
    }
    if args.dist is not None:
        tgt[DIST] = args.dist
        tgt[DIST_TGT] = args.dist
    for a, v in tgt.items():
        print(f"  write 0x{a:08X} <- {v:+.6f}")

    enc = [(a, struct.unpack("<I", struct.pack("<f", v))[0]) for a, v in tgt.items()]
    n = 0
    if args.secs <= 0:
        for a, w in enc:
            b.write_u32(a, w)
        n = 1
    else:
        deadline = time.monotonic() + args.secs
        while time.monotonic() < deadline:
            for a, w in enc:
                b.write_u32(a, w)
            n += 1

    print(f"after ({n} sweeps):")
    dump()
    moved = math.dist(vec(CAM_EYE), vec(EYE))
    print(f"|cam_eye - orbit_eye| = {moved:.5f}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
