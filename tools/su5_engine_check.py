"""Drive the Suikoden V adapter through the real CameraRuntime (no GUI) and check numbers.

    python tools/su5_engine_check.py [--shots DIR]

Needs PCSX2 running Suikoden V in a field (e.g. sstates/suikoden5/base.p2s loaded and the VM
running).  The right stick is fed with ``runtime.set_stick``; the physical stick path is
covered by tools/su5_input_check.py.  Reads only the camera globals and the mod block.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.suikoden5 import caves, memory_map as mm  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

RES: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def g(b):
    f = b.read_floats(mm.G_FOCUS, 3)
    e = b.read_floats(mm.G_EYE, 3)
    return {"f": f, "e": e, "pitch": b.read_floats(mm.G_PITCH, 1)[0], "yaw": b.read_floats(mm.G_YAW, 1)[0],
            "dist": b.read_floats(mm.G_DISTANCE, 1)[0], "fov": b.read_floats(mm.G_FOV, 1)[0]}


def main() -> int:
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    info = ad.identify()
    check("identify", info.matched, f"{info.game_id}/{info.crc}")
    ad.uninstall_all()
    time.sleep(0.2)
    native0 = g(b)
    d = ad.default_settings()
    s = CameraSettings(**{k: v for k, v in d.items() if k in CameraSettings().__dict__})
    rt = CameraRuntime(ad, s)
    rt.capture_original_fov()
    check("sync_to_game", rt.sync_to_game(), f"yaw={rt.settings.yaw_deg:.1f} pitch={rt.settings.pitch_deg:.1f} "
                                           f"dist={rt.settings.distance:.1f}")
    rt.settings.mode = MODE_ORBIT
    rt.start()
    time.sleep(1.0)
    check("patch applied", ad.patch_state() == "applied", ad.patch_state())
    check("right stick blocked", bool(caves.read_flags(b) & mm.FLAG_BLOCK_RSTICK) and
          caves.zoom_site_state(b) == "patched")
    g0 = g(b)
    check("scene accepted", not rt.stats.last_error, rt.stats.last_error or "ok")

    # horizontal rotation: right stick right for 1 s
    yaw_before = g0["yaw"]
    rt.set_stick(1.0, 0.0)
    time.sleep(1.0)
    rt.set_stick(0.0, 0.0)
    time.sleep(0.3)
    g1 = g(b)
    dyaw = (g1["yaw"] - yaw_before + 540) % 360 - 180
    check("right stick rotates yaw", abs(dyaw) > 20, f"yaw {yaw_before:.1f} -> {g1['yaw']:.1f} ({dyaw:+.1f} deg)")
    off = math.hypot(g1["e"][0] - g1["f"][0], g1["e"][2] - g1["f"][2])
    check("eye orbits the focus at constant distance",
          abs(math.dist(g1["e"], g1["f"]) - g1["dist"]) < 1.0, f"d={math.dist(g1['e'], g1['f']):.1f} horiz={off:.1f}")
    check("focus unchanged by rotation", math.dist(g0["f"], g1["f"]) < 0.5)

    # vertical rotation
    p_before = g1["pitch"]
    rt.set_stick(0.0, 1.0)
    time.sleep(0.8)
    rt.set_stick(0.0, 0.0)
    time.sleep(0.3)
    g2 = g(b)
    check("right stick pitches", abs(g2["pitch"] - p_before) > 5, f"pitch {p_before:.1f} -> {g2['pitch']:.1f}")

    # hold: no drift without input
    time.sleep(0.8)
    g3 = g(b)
    check("camera holds when the stick is released", abs(g3["yaw"] - g2["yaw"]) < 0.01 and abs(g3["pitch"] - g2["pitch"]) < 0.01)

    # GUI-style settings
    rt.settings.distance = 250.0
    time.sleep(0.4)
    check("distance 250", abs(g(b)["dist"] - 250.0) < 0.5, f"{g(b)['dist']:.1f}")
    rt.settings.use_fov = True
    rt.settings.fov_deg = 50.0
    time.sleep(0.8)
    check("fov 50", abs(g(b)["fov"] - 50.0) < 0.2, f"{g(b)['fov']:.2f}")
    rt.settings.target_offset = [20.0, 0.0, 0.0]
    time.sleep(0.4)
    gt = g(b)
    check("target offset x moves the focus", abs(gt["f"][0] - g0["f"][0] - 20.0) < 0.5,
          f"{g0['f'][0]:.1f} -> {gt['f'][0]:.1f}")
    rt.settings.target_offset = [0.0, 0.0, 0.0]
    rt.settings.use_fov = False
    time.sleep(0.8)

    # restore
    rt.restore()
    rt.stop()
    time.sleep(0.5)
    g4 = g(b)
    check("restore: hooks removed", caves.camera_site_state(b) == "original" and caves.zoom_site_state(b) == "original")
    check("restore: flags cleared", caves.read_flags(b) == 0 if caves.block_valid(b) else True)
    nat = (g4["pitch"], g4["yaw"], g4["dist"])
    check("restore: the game's own camera values are back",
          all(abs(g4[k] - native0[k]) < 1.0 for k in ("yaw", "pitch", "dist")) and abs(g4["fov"] - native0["fov"]) < 0.2,
          f"{nat} fov={g4['fov']:.1f} (before the mod: {native0['pitch']}, {native0['yaw']}, {native0['dist']})")
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
