"""End-to-end smoke test of the camera runtime against the live emulator.

    python tools/runtime_check.py --yaw-offset 55 --seconds 3

Captures the window before and during the override and reports the visual
delta plus the runtime statistics, then restores the original camera.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT, MODE_FREE  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402
import numpy as np  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw-offset", type=float, default=55.0)
    ap.add_argument("--pitch", type=float, default=None)
    ap.add_argument("--distance", type=float, default=None)
    ap.add_argument("--fov", type=float, default=None)
    ap.add_argument("--seconds", type=float, default=2.5)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--shots", default=str(ROOT / "reports" / "shots"))
    args = ap.parse_args()

    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    backend = PineBackend()
    backend.connect()
    ad = FFX2Adapter(backend)
    info = ad.identify()
    print("identity:", info.game_id, info.crc, "matched=", info.matched, repr(info.title))
    if not info.matched:
        print("ABORT: adapter does not match the running game")
        return

    scene = ad.read_scene()
    print(f"player={tuple(round(v,3) for v in scene.player.as_tuple())}")
    print(f"eye={tuple(round(v,3) for v in scene.game_pose.eye.as_tuple())} "
          f"target={tuple(round(v,3) for v in scene.game_pose.target.as_tuple())} d={scene.game_pose.distance():.2f}")
    print(f"fov={scene.fov_deg:.2f} deg  field_like={ad.is_field_like(scene)}")

    w = Window()
    base = w.grab()

    st = CameraSettings()
    rt = CameraRuntime(ad, st)
    rt.capture_original_fov()
    base_yaw, base_pitch = scene.game_pose.yaw_pitch()
    st.mode = MODE_ORBIT
    st.yaw_deg = __import__("math").degrees(base_yaw) + args.yaw_offset
    st.pitch_deg = __import__("math").degrees(base_pitch) if args.pitch is None else args.pitch
    st.distance = scene.game_pose.distance() if args.distance is None else args.distance
    st.target_offset = [0.0, 0.0, 0.0]
    if args.fov:
        st.use_fov = True
        st.fov_deg = args.fov
    rt.start()
    frames = []
    try:
        time.sleep(0.6)
        for i in range(args.frames):
            time.sleep(max(0.02, args.seconds / args.frames))
            frames.append((diffscore(base, w.grab()), w.grab()))
    finally:
        rt.restore()
        time.sleep(0.4)
        rt.stop()
        backend.close()

    scores = [f[0] for f in frames]
    print("runtime stats:", json.dumps({k: v for k, v in rt.stats.__dict__.items()
                                        if k not in ("applied_pose", "game_pose")}, indent=1, default=str))
    print("frame deltas vs baseline:")
    for i, s in enumerate(scores):
        print(f"  frame{i}: frac_gt16={s['frac_gt16']:.3f} mean={s['mean']:.2f} p99={s['p99']:.1f}")
    if frames:
        best = max(scores, key=lambda s: s["frac_gt16"])
        print("BEST:", best)
        # record an image pair for the report
        from PIL import Image
        arr = frames[int(np.argmax([s['frac_gt16'] for s in scores]))][1].astype(np.uint8)
        Image.fromarray(arr).save(shots / "runtime_check_after.png")
        Image.fromarray(base.astype(np.uint8)).save(shots / "runtime_check_before.png")
        print("saved shots to", shots)


if __name__ == "__main__":
    main()
