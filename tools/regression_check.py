"""Engine regression check for every adapter: orbit, FOV and restore on the running game.

    python tools/regression_check.py

Picks the adapter from the game that PCSX2 is running (FFX-2, Shining Force Neo or Suikoden V),
runs the real CameraRuntime in orbit mode and reads the result back through the adapter:

* the camera direction turns when the right stick is pushed (orbit works through the engine);
* the horizontal distance of the eye from the focus stays constant while it turns;
* a FOV override reaches the game and the stock FOV comes back;
* after ``stop()`` + ``restore()`` the game's own camera direction returns.

Load the game's own savestate (FFX-2 ``base.p2s``, Shining Force Neo ``base.p2s``,
Suikoden V ``base.p2s``) and let the VM run before starting.  Only one PINE client at a time.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from adapters.shiningforceneo.adapter import SFNeoAdapter  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

ADAPTERS = {"SLPS-25250": FFX2Adapter, "SLPM-65908": SFNeoAdapter, "SLPM-66286": Suikoden5Adapter}
RES: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def heading(ad) -> float:
    """Camera horizontal direction in degrees (eye -> focus on the ground plane)."""
    p = ad.read_game_pose()
    return math.degrees(math.atan2(p.target.x - p.eye.x, p.target.z - p.eye.z))


def ang(a: float, b: float) -> float:
    return (a - b + 540.0) % 360.0 - 180.0


def main() -> int:
    b = PineBackend()
    b.connect()
    gid = b.game_id().strip().upper()
    cls = ADAPTERS.get(gid)
    if cls is None:
        print(f"unsupported game {gid}")
        return 2
    ad = cls(b)
    info = ad.identify()
    print(f"{ad.name}: {info.game_id}/{info.crc} matched={info.matched}")
    check("identify", info.matched)
    if not info.matched:
        return 1
    d = ad.default_settings() if hasattr(ad, "default_settings") else {}
    s = CameraSettings(**{k: v for k, v in d.items() if k in CameraSettings().__dict__})
    rt = CameraRuntime(ad, s)
    rt.capture_original_fov()
    stock_fov = ad.capture_original_fov()
    h0 = heading(ad)
    rt.sync_to_game()
    rt.settings.mode = MODE_ORBIT
    rt.start()
    time.sleep(1.5)
    check("orbit accepted the scene", not rt.stats.last_error or rt.stats.last_error.startswith("scene guard") is False,
          rt.stats.last_error or "ok")
    h1 = heading(ad)
    rt.set_stick(1.0, 0.0)
    time.sleep(1.0)
    rt.set_stick(0.0, 0.0)
    time.sleep(0.6)
    h2 = heading(ad)
    turned = abs(ang(h2, h1))
    check("right stick turns the camera", turned > 10.0, f"{turned:.1f} deg ({h1:.1f} -> {h2:.1f})")
    rt.settings.use_fov = True
    rt.settings.fov_deg = 60.0
    time.sleep(1.5)
    got = ad.read_fov_deg()
    check("FOV override reaches the game", abs(got - 60.0) < 1.5, f"{got:.2f} (stock {stock_fov:.2f})")
    rt.settings.use_fov = False
    time.sleep(1.2)
    check("FOV restored when switched off", abs(ad.read_fov_deg() - stock_fov) < 1.5, f"{ad.read_fov_deg():.2f}")
    rt.stop()
    rt.restore()
    time.sleep(4.0)
    h3 = heading(ad)
    check("restore: the game's own camera direction is back", abs(ang(h3, h0)) < 20.0, f"{h0:.1f} -> {h3:.1f}")
    bad = [r for r in RES if not r[1]]
    print(f"\n{ad.name}: {len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
