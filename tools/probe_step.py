"""Single-shot camera rebuild probe.

Each poke writes 1 to the camera dirty latch 0x340AC9 exactly once, waits for the
game to consume it, and reports the resulting camera state.  This isolates the
dynamics of FUN_001a91a0 from the write-rate race.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

CAM = 0x340350
LATCH = 0x340AC9
POS = CAM + 0x50
EYE = CAM + 0x10
YAW = CAM + 0x60
PITCH = CAM + 0x64
DIST = CAM + 0x68
FWD = 0x53ADA0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=None, help="absolute yaw to write before poking")
    ap.add_argument("--pokes", type=int, default=3)
    ap.add_argument("--settle", type=float, default=0.35)
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    def snap():
        return {
            "yaw": b.read_f32(YAW),
            "pitch": b.read_f32(PITCH),
            "dist": b.read_f32(DIST),
            "pos": vec(POS),
            "eye": vec(EYE),
            "fwd": vec(FWD, 3),
            "latch": b.read_u32(LATCH) & 0xFF,
            "acc": b.read_u32(0x340ACC) & 0xFF,
            "flag_a": b.read_u32(0x340ACA) & 0xFF,
            "flag_b": b.read_u32(0x340ACB) & 0xFF,
        }

    def show(tag, s):
        print(f"{tag:8s} yaw={s['yaw']:+.6f} pitch={s['pitch']:+.6f} dist={s['dist']:7.3f} "
              f"latch={s['latch']} acc={s['acc']} a={s['flag_a']} b={s['flag_b']}")
        print(f"         pos={[round(v, 4) for v in s['pos']]} fwd={[round(v, 4) for v in s['fwd']]}")

    s0 = snap()
    show("initial", s0)
    if args.yaw is not None:
        import struct
        b.write_u32(YAW, struct.unpack("<I", struct.pack("<f", args.yaw))[0])
        s0 = snap()
        show("yaw-set", s0)

    prev = s0
    for i in range(args.pokes):
        b.write_u32(LATCH, 1)
        time.sleep(args.settle)
        cur = snap()
        d = math.dist(prev["pos"], cur["pos"])
        dd = [cur["pos"][j] - prev["pos"][j] for j in range(3)]
        n = math.sqrt(sum(x * x for x in dd)) or 1.0
        u = [round(x / n, 4) for x in dd]
        print(f"poke{i + 1}: moved={d:8.4f} delta={[round(x, 4) for x in dd]} "
              f"unit={u} |dist|={cur['dist']:.4f}")
        show(f"  after", cur)
        prev = cur
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
