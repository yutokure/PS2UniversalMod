"""Race-free Yuna-centred orbit: write once, let the game reproduce it.

With the .pnach retargeting the look-at load to 0x33FC40 both camera words we
care about become ours for good:

    eye  : the game computes  0x340360 = 0x340370 + 0x3403E0  every frame, and
           it never writes 0x3403E0 itself  ->  one offset write is enough.
    aim  : the patched FUN_001b07a0 reads 0x33FC40 instead of 0x33FC10, and the
           game never touches 0x33FC40      ->  one write is enough.

Nothing is rewritten per frame, so there is no race and therefore no flicker.

    python tools/orbit_final.py --yaw 40 --secs 20
    python tools/orbit_final.py --restore
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

EYE = 0x340360
BASE = 0x340370
PLAYER = 0x340380
POS = 0x3403A0
OFFSET = 0x3403E0
AIM_ORIG = 0x33FC10
AIM_NEW = 0x33FC40
FWD = 0x53ADA0
STATE = Path(__file__).resolve().parents[1] / "work" / "orbit_final_state.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=None)
    ap.add_argument("--dist", type=float, default=None)
    ap.add_argument("--height", type=float, default=-6.0)
    ap.add_argument("--secs", type=float, default=0.0)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    if args.restore:
        if STATE.exists():
            st = json.loads(STATE.read_text())
            b.write_float_block(OFFSET, st["offset"])
            b.write_float_block(AIM_NEW, st["aim"])
            print("restored offset/aim from state")
        else:
            b.write_float_block(OFFSET, [0.0, 0.0, 0.0])
            b.write_float_block(AIM_NEW, vec(AIM_ORIG))
            print("restored offset=0, aim=original")
        b.close()
        return 0

    base = vec(BASE)
    eye = vec(EYE)
    player = vec(PLAYER)
    fwd = vec(FWD)
    d_eye = math.dist(eye, player)
    pitch0 = math.asin(max(-1.0, min(1.0, fwd[1])))
    yaw0 = math.atan2(fwd[2], fwd[0])
    print(f"base  {[round(v, 4) for v in base]}")
    print(f"eye   {[round(v, 4) for v in eye]}")
    print(f"player{[round(v, 4) for v in player]}  |eye-player|={d_eye:.4f}")
    print(f"yaw={math.degrees(yaw0):+.3f} pitch={math.degrees(pitch0):+.3f}")

    yaw = yaw0 + math.radians(args.yaw)
    pitch = pitch0 if args.pitch is None else math.radians(args.pitch)
    dist = args.dist if args.dist is not None else d_eye
    aim = [player[0], player[1] + args.height, player[2]]
    cp = math.cos(pitch)
    f = [cp * math.cos(yaw), math.sin(pitch), cp * math.sin(yaw)]
    new_eye = [aim[i] - f[i] * dist for i in range(3)]
    off = [new_eye[i] - base[i] for i in range(3)]

    print(f"aim   {[round(v, 4) for v in aim]}  (0x{AIM_NEW:08X})")
    print(f"eye'  {[round(v, 4) for v in new_eye]}  offset={[round(v, 4) for v in off]}")

    b.write_float_block(OFFSET, off)
    b.write_float_block(AIM_NEW, aim)
    if not STATE.exists():
        STATE.write_text(json.dumps({"offset": [0.0] * 3, "aim": vec(AIM_ORIG)}, indent=1))

    print("written once - now idle (no further writes)")
    n = int(args.secs / 0.5) if args.secs else 2
    for _ in range(n):
        time.sleep(0.5)
        print(f"  eye={[round(v, 4) for v in vec(EYE)]} "
              f"aim_new={[round(v, 4) for v in vec(AIM_NEW)]} "
              f"fwd={[round(v, 4) for v in vec(FWD)]}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
