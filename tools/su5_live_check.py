"""Live check of the Suikoden V adapter through PINE (PCSX2 running the game).

    python tools/su5_live_check.py [step ...]

Steps: identity, passthrough, orbit, fov, offset, stick, restore.  With no step, all run.
Each step prints readings and a PASS/FAIL line; nothing is written outside the mod block,
the two hook sites and the cave area, and ``restore`` removes every hook.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.suikoden5 import caves, memory_map as mm  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_math.orbit import Vec3  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
    return ok


def glob(b):
    return {
        "focus": [round(v, 2) for v in b.read_floats(mm.G_FOCUS, 3)],
        "eye": [round(v, 2) for v in b.read_floats(mm.G_EYE, 3)],
        "pitch": round(b.read_floats(mm.G_PITCH, 1)[0], 2),
        "yaw": round(b.read_floats(mm.G_YAW, 1)[0], 2),
        "dist": round(b.read_floats(mm.G_DISTANCE, 1)[0], 2),
        "fov": round(b.read_floats(mm.G_FOV, 1)[0], 2),
    }


def eye_offset_dir(g):
    fx, fy, fz = g["focus"]
    ex, ey, ez = g["eye"]
    return math.degrees(math.atan2(ex - fx, ez - fz)), math.degrees(
        math.atan2(ey - fy, math.hypot(ex - fx, ez - fz))), math.dist((fx, fy, fz), (ex, ey, ez))


def main(steps: list[str]) -> int:
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    want = steps or ["identity", "passthrough", "orbit", "fov", "offset", "stick", "restore"]

    if "identity" in want:
        print("identity")
        info = ad.identify()
        check("serial/crc", info.matched, f"{info.game_id}/{info.crc}")

    if "passthrough" in want:
        print("passthrough (cave installed, no flags: the game must be unchanged)")
        before = glob(b)
        ad.uninstall_all()
        caves.install_camera(b)
        time.sleep(0.3)
        hb0 = b.read_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT)
        time.sleep(0.3)
        hb1 = b.read_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT)
        after = glob(b)
        check("heartbeat advances", hb1 > hb0, f"{hb0}->{hb1}")
        check("ctl pointer captured", b.read_u32(mm.MOD_BLOCK + mm.MB_CTL_PTR) != 0,
              hex(b.read_u32(mm.MOD_BLOCK + mm.MB_CTL_PTR)))
        same = all(abs(before[k] - after[k]) < 0.01 for k in ("pitch", "yaw", "dist", "fov"))
        check("globals unchanged by the idle cave", same, f"{before} -> {after}")

    if "orbit" in want:
        print("orbit")
        native = ad.read_native()
        anchor = ad.read_player()
        for yaw_e, pitch_e, dist in ((64.0, 13.0, 400.0), (0.0, 30.0, 300.0), (150.0, 55.0, 250.0)):
            ad.write_orbit_params(anchor, yaw_e, pitch_e, dist)
            time.sleep(0.25)
            g = glob(b)
            yaw_o, pit_o, d_o = eye_offset_dir(g)
            ok = (abs(((yaw_o - yaw_e + 180) % 360) - 180) < 0.5 and abs(pit_o - pitch_e) < 0.5
                  and abs(d_o - dist) < 1.0)
            check(f"orbit yaw={yaw_e} pitch={pitch_e} dist={dist}", ok,
                  f"eye dir yaw={yaw_o:.1f} pitch={pit_o:.1f} d={d_o:.1f}")
        ad.write_orbit_params(anchor, native["yaw"] + 180 - 360, native["pitch"], native["distance"])
        time.sleep(0.25)
        g = glob(b)
        check("stock values reproduce the stock camera",
              abs(g["pitch"] - native["pitch"]) < 0.01 and abs(g["dist"] - native["distance"]) < 0.01,
              str(g))

    if "fov" in want:
        print("fov")
        stock = ad.capture_original_fov()
        for fov in (40.0, 70.0, 20.0):
            ad.write_fov_deg(fov)
            time.sleep(0.25)
            check(f"fov {fov}", abs(ad.read_fov_deg() - fov) < 0.1, f"read {ad.read_fov_deg():.2f}")
        ad.restore_fov()
        time.sleep(0.25)
        check("fov restored", abs(ad.read_fov_deg() - stock) < 0.1, f"{ad.read_fov_deg():.2f} vs {stock:.2f}")

    if "offset" in want:
        print("offset (focus moves)")
        anchor = ad.read_player()
        f0 = b.read_floats(mm.G_FOCUS, 3)
        ad.write_orbit_params(Vec3(anchor.x + 30, anchor.y, anchor.z + 20), 64.0, 13.0, 400.0)
        time.sleep(0.25)
        f1 = b.read_floats(mm.G_FOCUS, 3)
        check("focus x/z +30/+20", abs(f1[0] - f0[0] - 30) < 0.1 and abs(f1[2] - f0[2] - 20) < 0.1,
              f"{[round(v,2) for v in f0]} -> {[round(v,2) for v in f1]}")
        ad.write_orbit_params(Vec3(anchor.x, anchor.y - 10, anchor.z), 64.0, 13.0, 400.0)
        time.sleep(0.25)
        f2 = b.read_floats(mm.G_FOCUS, 3)
        check("engine -10 in Y-down = +10 up", abs(f2[1] - f0[1] - 10) < 0.1, f"{f0[1]:.2f} -> {f2[1]:.2f}")

    if "stick" in want:
        print("stick block flag")
        ad.set_stick_block(True)
        check("zoom hook patched", caves.zoom_site_state(b) == "patched")
        check("flag set", bool(caves.read_flags(b) & mm.FLAG_BLOCK_RSTICK))
        ad.set_stick_block(False)
        check("zoom hook restored", caves.zoom_site_state(b) == "original")

    if "restore" in want:
        print("restore")
        ad.uninstall_all()
        check("camera site original", caves.camera_site_state(b) == "original")
        check("zoom site original", caves.zoom_site_state(b) == "original")
        time.sleep(0.3)
        g = glob(b)
        native_ok = abs(g["pitch"] - mm.STOCK_PITCH) < 30
        check("camera runs on game values", native_ok, str(g))

    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
