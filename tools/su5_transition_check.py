"""Map-change check: the orbit survives a field -> field transition.

    python tools/su5_transition_check.py

Load sstates/suikoden5/base.p2s (running).  The character is walked forward until the map
exit loads the next field (the game's camera update stops during the load).  The runtime
keeps running the whole time.  After the load the orbit values must be applied again in the
new map, the camera must follow the character there, and the right stick must still be
blocked.  Afterwards the orbit is switched off and the game's own camera comes back.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcsx2_input as pin  # noqa: E402
from adapters.suikoden5 import caves, memory_map as mm  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    ad.uninstall_all()
    d = ad.default_settings()
    s = CameraSettings(**{k: v for k, v in d.items() if k in CameraSettings().__dict__})
    rt = CameraRuntime(ad, s)
    rt.sync_to_game()
    rt.settings.mode = MODE_ORBIT
    rt.settings.pitch_deg, rt.settings.yaw_deg, rt.settings.distance = 25.0, 100.0, 330.0
    rt.start()
    time.sleep(1.0)
    native_before = ad.read_native()
    pin._KB.set_analog(pin.render_child(), 0.0, 1.0, "left", pin.CONFIG)
    t0 = time.time()
    stalled_at = None
    last = ad.heartbeat_word()
    while time.time() - t0 < 12.0:
        time.sleep(0.15)
        hb = ad.heartbeat_word()
        if hb == last and stalled_at is None and time.time() - t0 > 1.0:
            stalled_at = time.time()
        if hb != last:
            if stalled_at is not None:
                break
            last = hb
        if stalled_at and time.time() - stalled_at > 8.0:
            break
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
    check("the map change stopped the camera update (loading)", stalled_at is not None)
    # wait for the new map: heartbeat resumes
    resumed = False
    t1 = time.time()
    while time.time() - t1 < 40.0:
        a = ad.heartbeat_word()
        time.sleep(0.4)
        if ad.heartbeat_word() != a and b.read_floats(mm.G_FOCUS, 3) != [0.0, 0.0, 0.0]:
            resumed = True
            break
    check("camera update resumed in the new map", resumed, f"after {time.time() - t1:.1f}s")
    time.sleep(1.5)
    pitch = b.read_floats(mm.G_PITCH, 1)[0]
    dist = b.read_floats(mm.G_DISTANCE, 1)[0]
    yaw = b.read_floats(mm.G_YAW, 1)[0]
    check("orbit values applied again in the new map", abs(pitch - 25.0) < 0.01 and abs(dist - 330.0) < 0.01
          and abs(yaw - 280.0) < 0.01, f"pitch {pitch:.2f} dist {dist:.1f} yaw {yaw:.1f}")
    native_after = ad.read_native()
    check("the new map's own camera values are different (so the orbit really overrides)",
          abs(native_after["yaw"] - native_before["yaw"]) > 1 or abs(native_after["pitch"] - native_before["pitch"]) > 1,
          f"{native_before} -> {native_after}")
    p0 = ad.read_player()
    pin._KB.set_analog(pin.render_child(), 0.0, 1.0, "left", pin.CONFIG)
    time.sleep(0.6)
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
    time.sleep(0.3)
    p1 = ad.read_player()
    check("character walks and the camera follows in the new map",
          abs(p1.x - p0.x) + abs(p1.z - p0.z) > 3 and abs(b.read_floats(mm.G_FOCUS, 3)[0] - p1.x) < 25,
          f"moved {abs(p1.x - p0.x) + abs(p1.z - p0.z):.1f}")
    check("right stick still blocked", bool(caves.read_flags(b) & mm.FLAG_BLOCK_RSTICK)
          and caves.zoom_site_state(b) == "patched")
    check("no runtime error", not rt.stats.last_error, rt.stats.last_error or "")
    rt.stop()
    rt.restore()
    time.sleep(0.8)
    check("restored: hooks removed", caves.camera_site_state(b) == "original" and caves.zoom_site_state(b) == "original")
    check("restored: the game's own camera runs", abs(b.read_floats(mm.G_PITCH, 1)[0] - 25.0) > 0.01
          or abs(b.read_floats(mm.G_YAW, 1)[0] - 280.0) > 0.01)
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
