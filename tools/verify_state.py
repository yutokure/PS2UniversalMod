"""Compare live EE memory against an extracted savestate at the camera/player
anchors.  Used to prove savestate restore is faithful (E2E-02).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

EXTRACT = Path(r"C:\PS2CameraLab\work\sstates_extracted")
WATCH = {
    "player_anchor": 0x3312D0,
    "cam_eye": 0x340360,
    "cam_target": 0x340380,
    "cam_state": 0x3403B0,
    "proj_scale": 0x340B00,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="extracted state directory name")
    ap.add_argument("--tol", type=float, default=1e-3)
    args = ap.parse_args()
    ram = np.fromfile(EXTRACT / args.state / "eeMemory.bin", dtype=np.uint8)
    b = PineBackend()
    b.connect()
    report = {"state": args.state, "checks": {}, "all_match": True}
    try:
        for name, addr in WATCH.items():
            want = np.frombuffer(ram[addr:addr + 16].tobytes(), dtype="<f4").tolist()
            got = b.read_floats(addr, 4)
            ok = all(abs(w - g) <= args.tol for w, g in zip(want, got))
            report["checks"][name] = {"addr": hex(addr), "expected": want, "live": got, "match": ok}
            report["all_match"] &= ok
            print(f"{'OK ' if ok else 'DIFF'} {name:15s} {hex(addr)}  live={[round(v,4) for v in got]}")
    finally:
        b.close()
    print("ALL MATCH" if report["all_match"] else "MISMATCH")
    print(json.dumps(report, indent=1)[:1200])


if __name__ == "__main__":
    main()
