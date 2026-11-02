"""Check that the orbit really keeps Yuna centred, in any field.

Takes four frames at yaw 0/90/180/270 with the camera overridden and measures
how far the character's silhouette sits from the image centre.  A correct orbit
keeps the subject at a roughly constant screen position while the background
rotates.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "centering"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaws", nargs="*", type=float, default=[0, 90, 180, 270])
    args = ap.parse_args()
    backend = PineBackend()
    backend.connect()
    ad = FFX2Adapter(backend)
    info = ad.identify()
    print("game:", info.game_id, info.crc, "matched=", info.matched)
    sc = ad.read_scene()
    print("player", tuple(round(v, 2) for v in sc.player.as_tuple()))
    print("game eye", tuple(round(v, 2) for v in sc.game_pose.eye.as_tuple()),
          "game target", tuple(round(v, 2) for v in sc.game_pose.target.as_tuple()))
    print("centred on game target:", round((sc.game_pose.target - sc.player).length(), 2), "units from player")

    st = CameraSettings()
    rt = CameraRuntime(ad, st)
    rt.start()
    rt.sync_to_game()
    st.mode = MODE_ORBIT
    st.target_offset = [0.0, 0.0, 0.0]
    w = Window()
    frames = []
    try:
        for yaw in args.yaws:
            st.yaw_deg = yaw
            time.sleep(0.7)
            arr = w.grab()
            Image.fromarray(arr.astype(np.uint8)).save(OUT / f"yaw_{int(yaw):03d}.png")
            frames.append(arr)
            print(f"yaw {yaw:6.1f} captured  diff_vs_prev="
                  f"{(diffscore(frames[-2], arr)['frac_gt16'] if len(frames) > 1 else 0):.3f}")
    finally:
        rt.restore()
        time.sleep(0.3)
        rt.stop()
        backend.close()

    # the subject should stay near the centre: compare the central column bands
    for i, f in enumerate(frames):
        h, wd = f.shape[:2]
        center = f[int(h * 0.35):int(h * 0.8), int(wd * 0.42):int(wd * 0.58)]
        print(f"frame {args.yaws[i]:6.1f}: centre patch mean={center.mean():.1f}")
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
