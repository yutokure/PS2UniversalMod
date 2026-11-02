"""Drive the shipped CameraRuntime in orbit mode against the live game.

Unlike tools/orbit_cam.py (a raw probe) this exercises exactly the code path the
GUI uses: FFX2Adapter + CameraRuntime + the per-frame hot loop in engine.py.

    python tools/orbit_live.py --yaw 0   --secs 12
    python tools/orbit_live.py --yaw 40  --secs 12
    python tools/orbit_live.py --pitch 10 --dist 55 --secs 12
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=None)
    ap.add_argument("--dist", type=float, default=None)
    ap.add_argument("--secs", type=float, default=12.0)
    args = ap.parse_args()

    backend = PineBackend()
    backend.connect()
    adapter = FFX2Adapter(backend)
    info = adapter.identify()
    print(f"identify matched={info.matched} {info.game_id}/{info.crc} :: {info.title}")
    if not info.matched:
        return 2
    scene = adapter.read_scene()
    print(f"player={[round(v, 4) for v in scene.player.as_tuple()]}")
    print(f"eye   ={[round(v, 4) for v in scene.game_pose.eye.as_tuple()]}")
    print(f"aim   ={[round(v, 4) for v in scene.game_pose.target.as_tuple()]}")
    print(f"field_like={adapter.is_field_like(scene)}  fov={scene.fov_deg:.2f}")

    rt = CameraRuntime(adapter, CameraSettings())
    rt.start()
    try:
        rt.sync_to_game()
        s = rt.settings
        s.yaw_deg += args.yaw
        if args.pitch is not None:
            s.pitch_deg = args.pitch
        if args.dist is not None:
            s.distance = args.dist
        print(f"orbit yaw={s.yaw_deg:.3f} pitch={s.pitch_deg:.3f} dist={s.distance:.3f} "
              f"look_height={s.look_height}")
        with rt._lock:  # noqa: SLF001 - deliberate: switch mode atomically
            s.mode = MODE_ORBIT
        deadline = time.monotonic() + args.secs
        while time.monotonic() < deadline:
            time.sleep(0.5)
            st = rt.stats
            if st.last_error:
                print("  error:", st.last_error)
            if st.applied_pose:
                e, t = st.applied_pose
                print(f"  applied eye={[round(v, 3) for v in e]} aim={[round(v, 3) for v in t]} "
                      f"wps={st.writes_per_sec:.0f}")
        print(f"writes/sec={rt.stats.writes_per_sec:.0f} last_error={rt.stats.last_error!r}")
    finally:
        rt.restore()
        rt.stop()
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
