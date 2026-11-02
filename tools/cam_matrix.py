"""Drive the FFX-2 view matrix at 0x33F620 directly.

Layout recovered by measurement (2026-10-31):

    0x53AD80  right     \
    0x53AD90  up         |  the orthonormal camera basis, one row each
    0x53ADA0  forward   /

    0x33F620  M[0] = (right.x, up.x, fwd.x, 0)
    0x33F630  M[1] = (right.y, up.y, fwd.y, 0)
    0x33F640  M[2] = (right.z, up.z, fwd.z, 0)
    0x33F650  T    = -(M . eye), 1.0            <- verified to 7 decimals

So the engine builds a world->view matrix from the camera basis and the eye each
time the camera updates.  If the renderer consumes this matrix we can rotate the
view freely regardless of what the game's own camera logic wants.

    python tools/cam_matrix.py --status
    python tools/cam_matrix.py --yaw 20 --secs 25
    python tools/cam_matrix.py --pitch 12 --secs 25
    python tools/cam_matrix.py --restore
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

RIGHT = 0x53AD80
UP = 0x53AD90
FWD = 0x53ADA0
BEYE = 0x53ADB0
MAT = 0x33F620
EYE = 0x340360
GAMEEYE = 0x340370
POS50 = 0x3403A0
STATE = Path(__file__).resolve().parents[1] / "work" / "cam_matrix_state.json"


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(v):
    n = math.sqrt(dot(v, v))
    return [x / n for x in v]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def rot_axis(axis, ang):
    """Rodrigues rotation matrix (3x3) about a unit axis."""
    x, y, z = norm(axis)
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return [
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ]


def apply(R, v):
    return [dot(R[i], v) for i in range(3)]


def read_basis(b):
    return [read_vec(b, a) for a in (RIGHT, UP, FWD)]


def read_vec(b, a):
    return [b.read_f32(a + 4 * i) for i in range(3)]


def build_matrix(basis, eye):
    right, up, fwd = basis
    rows = []
    for i in range(3):
        rows.append([right[i], up[i], fwd[i], 0.0])
    rows.append([-dot(right, eye), -dot(up, eye), -dot(fwd, eye), 1.0])
    return rows


def write_matrix(b, rows):
    flat = [x for r in rows for x in r]
    b.write_float_block(MAT, flat)
    return flat


def report(tag, basis, eye):
    right, up, fwd = basis
    print(f"{tag}: fwd={[round(v, 5) for v in fwd]} eye={[round(v, 5) for v in eye]}")
    print(f"       up={[round(v, 5) for v in up]} right={[round(v, 5) for v in right]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0, help="degrees about world +Y")
    ap.add_argument("--pitch", type=float, default=0.0, help="degrees about camera right axis")
    ap.add_argument("--roll", type=float, default=0.0, help="degrees about camera forward")
    ap.add_argument("--eye", type=str, default=None, help="X,Y,Z to place the eye first")
    ap.add_argument("--secs", type=float, default=0.0, help="hold time (0 = single write)")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    b = PineBackend()
    b.connect()

    if args.restore:
        if not STATE.exists():
            print("no saved state")
            return 1
        st = json.loads(STATE.read_text())
        eye = st["eye"]
        b.write_float_block(EYE, eye + [0.0])
        b.write_float_block(POS50, eye + [0.0])
        b.write_float_block(GAMEEYE, eye + [0.0])
        write_matrix(b, build_matrix(st["basis"], eye))
        report("restored", st["basis"], eye)
        b.close()
        return 0

    basis = read_basis(b)
    eye = read_vec(b, EYE)
    report("current", basis, eye)
    if args.status:
        print("matrix rows:")
        for i in range(4):
            print("  ", [round(b.read_f32(MAT + 16 * i + 4 * j), 6) for j in range(4)])
        b.close()
        return 0

    if not STATE.exists():
        STATE.write_text(json.dumps({"basis": basis, "eye": eye}, indent=1))
        print(f"saved pre-state -> {STATE}")

    if args.eye:
        eye = [float(x) for x in args.eye.split(",")]
        b.write_float_block(EYE, eye + [0.0])
        b.write_float_block(POS50, eye + [0.0])
        b.write_float_block(GAMEEYE, eye + [0.0])
        print(f"eye set to {[round(v, 5) for v in eye]}")

    basis = read_basis(b)
    rot = []
    if args.yaw:
        rot.append(rot_axis([0.0, 1.0, 0.0], math.radians(args.yaw)))
    if args.pitch:
        rot.append(rot_axis(basis[0], math.radians(args.pitch)))
    if args.roll:
        rot.append(rot_axis(basis[2], math.radians(args.roll)))
    new = basis
    for R in rot:
        new = [apply(R, v) for v in new]
    new = [norm(v) for v in new]

    rows = build_matrix(new, eye)
    report("target", new, eye)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, dot(basis[2], new[2])))))
    print(f"forward rotated {angle:.3f} deg")

    flat = [struct.unpack("<I", struct.pack("<f", x))[0] for r in rows for x in r]
    n = 0
    if args.secs <= 0:
        write_matrix(b, rows)
        n = 1
    else:
        deadline = time.monotonic() + args.secs
        while time.monotonic() < deadline:
            for i, w in enumerate(flat):
                b.write_u32(MAT + 4 * i, w)
            n += 1

    back = [round(b.read_f32(MAT + 4 * i), 5) for i in range(16)]
    print(f"writes={n}  matrix_now={back}")
    want = [round(x, 5) for x in flat_to_float(flat)]
    print(f"matrix_want={want}")
    print(f"write_held={'YES' if back == want else 'NO'}")
    b.close()
    return 0


def flat_to_float(bits):
    return [struct.unpack("<f", struct.pack("<I", w))[0] for w in bits]


if __name__ == "__main__":
    raise SystemExit(main())
