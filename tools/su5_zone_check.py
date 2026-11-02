"""Area camera check: the mod keeps control while the game's own camera zone changes.

    python tools/su5_zone_check.py

Load sstates/suikoden5/base.p2s (running), then this walks the character forward onto the
slope.  Without the mod the game's own pitch rises from 13 to 40 degrees on the way (that
is the S4 state of the savestate set).  With the orbit on, the rendered pitch, yaw and
distance must stay at the orbit values while the game's goal values (read back from the
mod block) still change, and the camera must follow the character.  Afterwards the orbit is
turned off and the game's own pitch must be back.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcsx2_input as pin  # noqa: E402
from adapters.suikoden5 import memory_map as mm  # noqa: E402
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
    rt.settings.pitch_deg = 25.0
    rt.settings.yaw_deg = 100.0
    rt.settings.distance = 330.0
    rt.start()
    time.sleep(1.0)
    p0 = ad.read_player()
    seen_pitch, seen_native, rendered = [], [], []
    pin._KB.set_analog(pin.render_child(), 0.0, 1.0, "left", pin.CONFIG)
    t0 = time.time()
    while time.time() - t0 < 3.2:
        rendered.append((b.read_floats(mm.G_PITCH, 1)[0], b.read_floats(mm.G_YAW, 1)[0],
                         b.read_floats(mm.G_DISTANCE, 1)[0]))
        seen_native.append(ad.read_native()["pitch"])
        time.sleep(0.1)
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
    time.sleep(0.3)
    p1 = ad.read_player()
    moved = ((p1.x - p0.x) ** 2 + (p1.z - p0.z) ** 2 + (p1.y - p0.y) ** 2) ** 0.5
    check("character moved", moved > 10, f"{moved:.1f} units")
    check("native (game) pitch changed during the walk", max(seen_native) - min(seen_native) > 10,
          f"{min(seen_native):.1f}..{max(seen_native):.1f}")
    check("rendered pitch held at the orbit value",
          all(abs(r[0] - 25.0) < 0.01 for r in rendered), f"{min(r[0] for r in rendered):.2f}..{max(r[0] for r in rendered):.2f}")
    check("rendered yaw held", all(abs(r[1] - ((100.0 - 180.0) % 360.0)) < 0.01 for r in rendered))
    check("rendered distance held", all(abs(r[2] - 330.0) < 0.01 for r in rendered))
    f = b.read_floats(mm.G_FOCUS, 3)
    e = b.read_floats(mm.G_EYE, 3)
    check("camera followed the character (focus tracks it)",
          abs(f[0] - (p1.x)) < 25 and abs(f[2] - p1.z) < 25, f"focus {f[0]:.1f},{f[2]:.1f} player {p1.x:.1f},{p1.z:.1f}")
    # eye and focus are two PINE reads, not one atomic snapshot: take a few and accept any
    ok = 0
    for _ in range(6):
        e = b.read_floats(mm.G_EYE, 3)
        f = b.read_floats(mm.G_FOCUS, 3)
        ok += abs(((e[0] - f[0]) ** 2 + (e[1] - f[1]) ** 2 + (e[2] - f[2]) ** 2) ** 0.5 - 330.0) < 1.0
        time.sleep(0.05)
    check("no jump: eye-focus distance constant", ok >= 4, f"{ok}/6 samples")
    rt.restore()
    rt.stop()
    time.sleep(1.5)
    native_pitch = b.read_floats(mm.G_PITCH, 1)[0]
    native_yaw = b.read_floats(mm.G_YAW, 1)[0]
    from adapters.suikoden5 import caves
    check("orbit off: hooks removed", caves.camera_site_state(b) == "original")
    check("orbit off: the rendered camera is the game's own again (not the orbit values)",
          abs(native_pitch - 25.0) > 0.01 or abs(native_yaw - 280.0) > 0.01,
          f"pitch {native_pitch:.1f} yaw {native_yaw:.1f} (the walk may also have crossed into another map)")
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
