"""Hold a camera parameter override for a fixed time (used with MCP screenshots).

    python tools/hold.py --yaw 0.6 --secs 25
    python tools/hold.py --pitch 0.3 --secs 25
    python tools/hold.py --field 0x3403B0 --delta 0.6 --secs 25

The process keeps re-writing the value at ~600 Hz so a game-side rewrite cannot
win the race.  It prints what it wrote and the resulting camera vector so the
console output is itself evidence.
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
YAW = CAM + 0x60
PITCH = CAM + 0x64
DIST = CAM + 0x68
POS = CAM + 0x50
EYE = CAM + 0x10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--field", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--delta", type=float, default=0.0)
    ap.add_argument("--value", type=float, default=None)
    ap.add_argument("--secs", type=float, default=20.0)
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    p0 = vec(POS)
    e0 = vec(EYE)
    y0 = b.read_f32(YAW)
    print(f"status=0x{b.status():X}  running={b.status() == 0}")
    print(f"before yaw={y0:+.5f} pitch={b.read_f32(PITCH):+.5f} dist={b.read_f32(DIST):.4f}")
    print(f"before pos={[round(v, 4) for v in p0]} eye={[round(v, 4) for v in e0]}")

    tgt = {YAW: y0 + args.yaw, PITCH: b.read_f32(PITCH) + args.pitch}
    if args.field:
        cur = b.read_f32(args.field)
        tgt[args.field] = (args.value if args.value is not None else cur + args.delta)
    for a, v in tgt.items():
        print(f"write 0x{a:08X} <- {v:+.5f}")

    enc = [(a, struct.unpack("<I", struct.pack("<f", v))[0]) for a, v in tgt.items()]
    deadline = time.monotonic() + args.secs
    n = 0
    try:
        while time.monotonic() < deadline:
            for a, w in enc:
                b.write_u32(a, w)
            n += 1
    except KeyboardInterrupt:
        pass

    y1 = b.read_f32(YAW)
    p1 = vec(POS)
    e1 = vec(EYE)
    d = math.dist(p0, p1) if len(p0) == len(p1) else float("nan")
    print(f"after  yaw={y1:+.5f} pitch={b.read_f32(PITCH):+.5f} dist={b.read_f32(DIST):.4f}")
    print(f"after  pos={[round(v, 4) for v in p1]} eye={[round(v, 4) for v in e1]}")
    print(f"writes={n} ({n / args.secs:.0f}/s)  pos_moved={d:.4f}")
    if args.field:
        print(f"field 0x{args.field:08X} final={b.read_f32(args.field):+.5f}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
