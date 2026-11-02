"""Yuna-centred orbit camera for Final Fantasy X-2 (PS2, SLPS-25250).

How the engine aims the field camera (measured, not guessed)
------------------------------------------------------------
FUN_001b07a0 is a look-at matrix builder called every frame:

    FUN_001b07a0(out = 0x33F620, eye = 0x340360, target = 0x33FC10,
                 up = 0x33FBC0, roll = f12)

    0x33FBC0 = (0.0, -1.0, 0.0)          up reference (+Y is down in FFX-2)
    forward  = normalize(*0x33FC10 - *0x340360)

which was verified numerically to 5 decimals against the live render basis at
0x53ADA0.  The player anchor is the camera target at 0x340380, so

    eye = player - forward * distance

is a genuine orbit whose pivot is the character and whose look-at point is the
character.  Both writes are plain float stores, so the orbit costs two PINE
writes per frame and is race free as long as it is refreshed.

    python tools/orbit_cam.py --aim                      # look at Yuna, keep eye
    python tools/orbit_cam.py --yaw 30 --secs 20         # orbit 30 deg
    python tools/orbit_cam.py --yaw 30 --pitch -10 --dist 45 --secs 20
    python tools/orbit_cam.py --status
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

EYE = 0x340360          # render eye            (engine: eye = gameeye + offset)
GAMEEYE = 0x340370      # +0x20
PLAYER = 0x340380       # +0x30 player anchor / look-at source
POS = 0x3403A0          # +0x50 smoothed position
ANG = 0x3403B0          # +0x60 yaw, +0x64 -pitch, +0x68 distance, +0x6c dolly
OFFSET = 0x3403E0       # +0x90 additive eye offset
AIM = 0x33FC10          # look-at point consumed by FUN_001b07a0
UPREF = 0x33FBC0        # (0, -1, 0)
BASIS_FWD = 0x53ADA0
BASIS_LOOK = 0x53ADD0


def pack(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(v)))[0]


def forward(yaw: float, pitch: float):
    cp = math.cos(pitch)
    return [cp * math.cos(yaw), math.sin(pitch), cp * math.sin(yaw)]


def yaw_pitch_of(fwd):
    pitch = math.asin(max(-1.0, min(1.0, fwd[1])))
    yaw = math.atan2(fwd[2], fwd[0])
    return yaw, pitch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0, help="degrees, added to the live yaw")
    ap.add_argument("--pitch", type=float, default=0.0, help="degrees, added to the live pitch")
    ap.add_argument("--dist", type=float, default=None, help="absolute orbit distance")
    ap.add_argument("--height", type=float, default=0.0, help="look-at height above the anchor")
    ap.add_argument("--target", type=str, default=None, help="X,Y,Z look-at override")
    ap.add_argument("--eye", type=str, default=None, help="X,Y,Z eye override (free camera)")
    ap.add_argument("--aim", action="store_true", help="keep the eye, aim at the character")
    ap.add_argument("--secs", type=float, default=0.0, help="hold time; 0 writes once")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    eye = vec(EYE)
    player = vec(PLAYER)
    aim = vec(AIM)
    fwd = vec(BASIS_FWD)
    d_eye = math.dist(eye, player)
    d_aim = math.dist(eye, aim)
    print(f"running={b.status() == 0}")
    print(f"eye    {[round(v, 4) for v in eye]}")
    print(f"player {[round(v, 4) for v in player]}   (|eye-player| = {d_eye:.3f})")
    print(f"aim    {[round(v, 4) for v in aim]}   (|eye-aim| = {d_aim:.3f})")
    print(f"fwd    {[round(v, 4) for v in fwd]}  check={[round(v, 4) for v in
          ([(aim[i] - eye[i]) / d_aim for i in range(3)] if d_aim else [0, 0, 0])]}")
    y0, p0 = yaw_pitch_of(fwd)
    print(f"yaw={math.degrees(y0):+.3f} deg  pitch={math.degrees(p0):+.3f} deg")
    if args.status:
        b.close()
        return 0

    if args.target:
        target = [float(x) for x in args.target.split(",")]
    else:
        target = [player[0], player[1] + args.height, player[2]]

    if args.eye:
        eye = [float(x) for x in args.eye.split(",")]
        new_eye = eye
    elif args.aim:
        new_eye = eye
    else:
        yaw = y0 + math.radians(args.yaw)
        pitch = p0 + math.radians(args.pitch)
        dist = args.dist if args.dist is not None else d_eye
        f = forward(yaw, pitch)
        new_eye = [target[i] - f[i] * dist for i in range(3)]

    print(f"target {[round(v, 4) for v in target]}")
    print(f"new eye{[round(v, 4) for v in new_eye]}")
    d_new = math.dist(new_eye, target)
    print(f"orbit distance {d_new:.4f}")

    flat_aim = [pack(v) for v in target + [0.0]]
    flat_eye = [pack(v) for v in new_eye + [0.0]]
    n = 0
    if args.secs <= 0:
        for i, w in enumerate(flat_aim):
            b.write_u32(AIM + 4 * i, w)
        for a in (EYE, GAMEEYE, POS):
            for i, w in enumerate(flat_eye):
                b.write_u32(a + 4 * i, w)
        n = 1
    else:
        deadline = time.monotonic() + args.secs
        while time.monotonic() < deadline:
            for i, w in enumerate(flat_aim):
                b.write_u32(AIM + 4 * i, w)
            for a in (EYE, GAMEEYE, POS):
                for i, w in enumerate(flat_eye):
                    b.write_u32(a + 4 * i, w)
            n += 1

    aim_now = vec(AIM)
    eye_now = vec(EYE)
    fwd_now = vec(BASIS_FWD)
    print(f"writes={n} ({n / args.secs:.0f}/s)" if args.secs else f"writes={n}")
    print(f"aim_now {[round(v, 4) for v in aim_now]}  held="
          f"{all(abs(aim_now[i] - target[i]) < 1e-3 for i in range(3))}")
    print(f"eye_now {[round(v, 4) for v in eye_now]}  held="
          f"{all(abs(eye_now[i] - new_eye[i]) < 1e-3 for i in range(3))}")
    print(f"fwd_now {[round(v, 4) for v in fwd_now]}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
