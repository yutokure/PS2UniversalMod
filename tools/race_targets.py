"""Compare write targets for the camera override.

The renderer reads 0x340360 (the eye).  The game appears to compute into
0x340370 and copy into 0x340360 near the end of its camera function, so the
two addresses have very different race windows.  This probe writes the same
orbit pose through each candidate target and measures how often the rendered
frame actually shows our camera (leak rate).
"""
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_math.orbit import Vec3, orbit_pose  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "flicker"
OUT.mkdir(parents=True, exist_ok=True)


def probe(backend, adapter, targets, yaw_deg, frames, w, original):
    sc = adapter.read_scene()
    yaw, pitch = sc.game_pose.yaw_pitch()
    pose = orbit_pose(Vec3(sc.player.x, sc.game_pose.target.y, sc.player.z),
                      yaw + math.radians(yaw_deg), pitch, sc.game_pose.distance())
    vals = [pose.eye.x, pose.eye.y, pose.eye.z]
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            for addr in targets:
                backend.write_float_block(addr, vals)

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    time.sleep(0.7)
    shots = []
    for _ in range(frames):
        shots.append(w.grab())
        time.sleep(0.06)
    stop.set()
    th.join(timeout=1)
    scores = [diffscore(original, f)["frac_gt16"] for f in shots]
    leaks = sum(1 for s in scores if s < 0.10)
    return {
        "targets": [hex(t) for t in targets],
        "scores": [round(s, 3) for s in scores],
        "leaks": leaks,
        "win_rate": round(1 - leaks / len(scores), 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=90.0)
    ap.add_argument("--frames", type=int, default=10)
    args = ap.parse_args()
    backend = PineBackend()
    backend.connect()
    ad = FFX2Adapter(backend)
    ad.identify()
    w = Window()
    original = w.grab()
    Image.fromarray(original.astype(np.uint8)).save(OUT / "race_original.png")
    combos = [
        [0x340360],
        [0x340370],
        [0x3403A0],
        [0x340360, 0x340370],
        [0x340360, 0x340370, 0x3403A0],
    ]
    results = []
    for targets in combos:
        r = probe(backend, ad, targets, args.yaw, args.frames, w, original)
        results.append(r)
        print(f"{r['targets']}: win_rate={r['win_rate']} scores={r['scores']}")
        time.sleep(0.4)
    best = max(results, key=lambda r: r["win_rate"])
    print("\nBEST:", best["targets"], best["win_rate"])
    import json
    (OUT / "race_targets.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    backend.close()


if __name__ == "__main__":
    main()
