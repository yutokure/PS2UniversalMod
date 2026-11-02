"""The game's own zoom, without the mod (TEST-03): R1 and the right stick, and the stage values.

    python tools/su5_zoom_check.py

Load sstates/suikoden5/base.p2s first.  No hook is installed here: the hooks are removed at the
start, and the readings come from the camera globals and the camera control object (found through
the one-off pointer scan of the live memory image), so this is the unmodified game.
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
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def read(b):
    return {"dist": round(b.read_floats(mm.G_DISTANCE, 1)[0], 1), "pitch": round(b.read_floats(mm.G_PITCH, 1)[0], 1),
            "yaw": round(b.read_floats(mm.G_YAW, 1)[0], 1), "fov": round(b.read_floats(mm.G_FOV, 1)[0], 1),
            "eye": [round(v, 1) for v in b.read_floats(mm.G_EYE, 3)]}


def main() -> int:
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    ad.uninstall_all()
    time.sleep(0.5)
    seq = [read(b)]
    print("start", seq[0])
    for i in range(3):
        pin.hold({"r1": True})
        time.sleep(0.2)
        pin.hold({"r1": False})
        time.sleep(1.2)
        seq.append(read(b))
        print(f"R1 #{i + 1}", seq[-1])
    dists = [s["dist"] for s in seq]
    check("R1 cycles the distance 400 -> 300 -> 200 -> 400", dists == [400.0, 300.0, 200.0, 400.0], str(dists))
    check("zoom changes only the distance (pitch, yaw, FOV constant)",
          len({(s["pitch"], s["yaw"], s["fov"]) for s in seq}) == 1)
    check("the eye moves along the view line (not the aim)",
          seq[1]["eye"] != seq[0]["eye"] and seq[3]["eye"] == seq[0]["eye"])
    # right stick (native): up steps the zoom, edge triggered
    d0 = read(b)["dist"]
    pin._KB.set_analog(pin.render_child(), 0.0, 1.0, "right", pin.CONFIG)
    time.sleep(0.5)
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "right", pin.CONFIG)
    time.sleep(1.2)
    d1 = read(b)["dist"]
    check("the game's own right stick steps the zoom (mod off)", d1 != d0, f"{d0} -> {d1}")
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
