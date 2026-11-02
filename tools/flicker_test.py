"""Flicker test: does every rendered frame show our camera, or does the game's
own camera leak through on some frames?

Procedure
  1. mod off  -> capture the *game* camera as the reference "original" frame
  2. mod on   -> capture N consecutive frames at ~60 ms
  3. each frame is classified: close to "original" == leak (flicker),
     far from "original" == our camera

A deterministic override must produce zero leaked frames.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "flicker"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=90.0)
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--shot-frac", type=float, default=0.10)
    ap.add_argument("--leak-frac", type=float, default=0.06)
    args = ap.parse_args()

    backend = PineBackend()
    backend.connect()
    ad = FFX2Adapter(backend)
    ad.identify()
    w = Window()

    st = CameraSettings()
    rt = CameraRuntime(ad, st)
    rt.start()
    time.sleep(0.4)
    original = w.grab()
    Image.fromarray(original.astype(np.uint8)).save(OUT / "flicker_original.png")

    rt.sync_to_game()
    st.mode = MODE_ORBIT
    st.yaw_deg += args.yaw
    st.target_offset = [0.0, 0.0, 0.0]
    time.sleep(0.8)

    frames = []
    for _ in range(args.frames):
        frames.append(w.grab())
        time.sleep(0.06)

    leaks = 0
    rows = []
    for i, f in enumerate(frames):
        s = diffscore(original, f)
        leaked = s["frac_gt16"] < args.leak_frac
        leaks += int(leaked)
        rows.append({"frame": i, "frac_gt16": round(s["frac_gt16"], 4), "leak": leaked})
        print(f"  frame {i:02d}: frac_gt16={s['frac_gt16']:.3f} "
              f"{'LEAK (game camera)' if leaked else 'ok (mod camera)'}")

    # how stable are the modded frames relative to each other?
    pair = [diffscore(frames[0], f)["frac_gt16"] for f in frames[1:]]
    print(f"\nwrites/s: {rt.stats.writes_per_sec:.0f}")
    print(f"leaked frames: {leaks}/{len(frames)}")
    print(f"mod-frame self-variance max: {max(pair):.4f}")

    rt.restore()
    time.sleep(0.3)
    rt.stop()
    backend.close()

    verdict = leaks == 0
    print("FLICKER TEST:", "PASS" if verdict else f"FAIL ({leaks} leaks)")
    import json
    (OUT / "flicker_result.json").write_text(json.dumps(
        {"frames": rows, "leaks": leaks, "writes_per_sec": rt.stats.writes_per_sec,
         "pass": verdict}, indent=1), encoding="utf-8")
    raise SystemExit(0 if verdict else 1)


if __name__ == "__main__":
    main()
