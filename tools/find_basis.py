"""Find the render camera's orientation store.

The eye at 0x340360 translates the camera but does not re-aim it: the look
direction comes from a separate basis the game builds when its own camera
updates.  This tool derives the expected forward/up vectors from the measured
eye and target and searches every savestate for matching unit vectors.
"""
from __future__ import annotations

import _paths  # noqa: F401  (repo + lab paths)

import argparse
import json
import math
from pathlib import Path

import numpy as np

ROOT = _paths.WORK / "sstates_extracted"
STATES = ["base", "base_only_wait", "base_left_moved",
          "base_chara_little_moved_and_cam_big_moved"]
EYE = 0x340360
TARGET = 0x340380


def load(name: str) -> np.ndarray:
    raw = np.fromfile(ROOT / name / "eeMemory.bin", dtype=np.uint8)
    return raw.view("<f4")


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=2e-3)
    args = ap.parse_args()
    rows = {}
    for name in STATES:
        f = load(name)
        eye = [float(f[EYE // 4 + i]) for i in range(3)]
        tgt = [float(f[TARGET // 4 + i]) for i in range(3)]
        d = [tgt[i] - eye[i] for i in range(3)]
        fwd = unit(d)
        # camera basis: forward f, right r = normalize(cross(f, up_world)),
        # up u = cross(r, f); up_world = (0,1,0) because +Y is down in memory
        r = unit([fwd[1] * 0 - fwd[2] * 1, fwd[2] * 0 - fwd[0] * 0, fwd[0] * 1 - fwd[1] * 0])
        u = [r[1] * fwd[2] - r[2] * fwd[1], r[2] * fwd[0] - r[0] * fwd[2], r[0] * fwd[1] - r[1] * fwd[0]]
        rows[name] = {"eye": eye, "target": tgt, "fwd": fwd, "right": r, "up": u}
        print(f"{name:44s} fwd={[round(x,4) for x in fwd]} right={[round(x,4) for x in r]} "
              f"up={[round(x,4) for x in u]}")

    # search for the forward vector in every state
    for name in STATES:
        f = load(name)
        fwd = rows[name]["fwd"]
        for label, vec in (("fwd", fwd), ("-fwd", [-x for x in fwd]),
                           ("right", rows[name]["right"]), ("up", rows[name]["up"])):
            hits = []
            for i in range(f.size - 4):
                if (abs(float(f[i]) - vec[0]) <= args.tol
                        and abs(float(f[i + 1]) - vec[1]) <= args.tol
                        and abs(float(f[i + 2]) - vec[2]) <= args.tol):
                    hits.append(i * 4)
            if hits:
                print(f"  {name[:22]:22s} {label:6s} {len(hits)} hits: "
                      f"{[hex(h) for h in hits[:8]]}")
    (_paths.REPO / "reports" / "camera_basis.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
