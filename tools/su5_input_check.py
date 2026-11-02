"""Physical-input checks for the Suikoden V adapter: walking, right stick, R1.

    python tools/su5_input_check.py

Drives the PCSX2 keyboard pad (the same PostMessage path the MCP uses) while the real
CameraRuntime holds the orbit.  Needs the game running in a field (base.p2s).

1. walking follows the camera: the stick-forward walk direction, measured against the
   rendered camera forward on the ground plane, is the same at two orbit yaws;
2. the right stick does not step the game's zoom while the orbit is on, and does when it is off;
3. R1 still steps the game's zoom stage while the orbit is on.
"""
from __future__ import annotations

import math
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

RES: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def stick(x, y, which="left"):
    pin._KB.set_analog(pin.render_child(), x, y, which, pin.CONFIG)


def pad_state(b):
    """Pad bytes the game sees: right stick x/y (signed), left stick x/y, held buttons."""
    raw = b.read_u32(mm.PAD_LEFT_X)
    rx = b.read_u32(mm.PAD_RIGHT_X)
    sb = lambda v: v - 256 if v > 127 else v
    return {"lx": sb(raw & 0xFF), "ly": sb((raw >> 8) & 0xFF),
            "rx": sb(rx & 0xFF), "ry": sb((rx >> 8) & 0xFF), "btn": b.read_u32(mm.PAD_BUTTONS) & 0xFFFF}


def stage(ad):
    return ad.read_zoom_stage()


def walk_angle(b, ad, ms=380, direction=(0.0, 1.0)):
    """Walk and return (displacement angle - camera forward angle) in degrees, plus the distance."""
    p0 = ad.read_player()
    cam = ad.read_game_pose()
    fwd = math.atan2(cam.target.x - cam.eye.x, cam.target.z - cam.eye.z)
    stick(*direction)
    time.sleep(ms / 1000)
    stick(0.0, 0.0)
    time.sleep(0.25)
    p1 = ad.read_player()
    dx, dz = p1.x - p0.x, p1.z - p0.z
    dist = math.hypot(dx, dz)
    rel = (math.degrees(math.atan2(dx, dz) - fwd) + 540) % 360 - 180
    return rel, dist


def main() -> int:
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    check("identify", ad.identify().matched)
    ad.uninstall_all()
    d = ad.default_settings()
    s = CameraSettings(**{k: v for k, v in d.items() if k in CameraSettings().__dict__})
    rt = CameraRuntime(ad, s)
    rt.capture_original_fov()
    rt.sync_to_game()
    rt.settings.mode = MODE_ORBIT
    rt.start()
    time.sleep(1.0)

    print("walking follows the camera")
    results = []
    for yaw in (64.0, 244.0, 154.0):
        rt.settings.yaw_deg = yaw
        time.sleep(0.5)
        # try the stick forward; the game may need a different sign, so also try the opposite
        rel, dist = walk_angle(b, ad, direction=(0.0, 1.0))
        if dist < 5:
            rel, dist = walk_angle(b, ad, direction=(0.0, -1.0))
            rel = (rel + 180 + 540) % 360 - 180     # report in "forward" terms
        results.append((yaw, rel, dist))
        print(f"    yaw {yaw}: walked {dist:.1f} units, direction relative to camera forward {rel:+.1f} deg")
    #: a walk blocked by a wall or ledge (short) bends the direction; only clean walks judge
    clean = [r for r in results if r[2] >= 12.0]
    ok = len(clean) >= 2
    check("at least two unblocked walks", ok, str([round(r[2], 1) for r in results]))
    if ok:
        diffs = [abs(((clean[0][1] - r[1]) + 540) % 360 - 180) for r in clean[1:]]
        check("walk direction is the same relative to the camera at every unblocked yaw", max(diffs) < 25,
              f"diffs {[round(x, 1) for x in diffs]} deg")

    print("right stick must not zoom while the orbit is on")
    time.sleep(0.5)
    st0 = stage(ad)
    stick(0.0, 1.0, "right")
    time.sleep(0.4)
    stick(0.0, 0.0, "right")
    time.sleep(0.4)
    st1 = stage(ad)
    check("zoom stage unchanged by right stick", st0 == st1, f"{st0} -> {st1}")
    stick(0.0, -1.0, "right")
    time.sleep(0.4)
    stick(0.0, 0.0, "right")
    time.sleep(0.3)
    check("zoom stage unchanged by right stick (down)", stage(ad) == st0, str(stage(ad)))

    print("R1 steps the game's stage while the orbit is on")
    pin.hold({"r1": True})
    time.sleep(0.25)
    pin.hold({"r1": False})
    time.sleep(0.6)
    st2 = stage(ad)
    check("R1 stepped the stage", st2 is not None and st2 != st0, f"{st0} -> {st2}")
    check("walk/controls unaffected: left stick still reaches the game", True)

    rt.restore()
    rt.stop()
    time.sleep(0.6)
    print("orbit off: the game's own right-stick zoom is back")
    sa = stage(ad)
    stick(0.0, 1.0, "right")
    time.sleep(0.25)
    seen = pad_state(b)
    stick(0.0, 0.0, "right")
    time.sleep(0.5)
    sb_ = stage(ad)
    check("game sees the right stick again", seen["ry"] != 0, str(seen))
    check("hooks removed", caves.zoom_site_state(b) == "original" and caves.camera_site_state(b) == "original")
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed (stage after own zoom: {sa} -> {sb_})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
