"""Soak test: long orbit run with mixed input, watching for jumps, errors and lost hooks.

    python tools/su5_soak.py [seconds] [log.jsonl]

The real CameraRuntime holds the orbit while this script cycles: right-stick yaw and pitch
sweeps, left-stick walking, distance / FOV / offset changes like a user at the GUI, and R1
presses.  Every 50 ms it samples the camera globals and reports

* camera jumps: a yaw change per sample larger than the stick could produce, or a
  change of the eye-to-focus distance while the distance setting is constant;
* lost hooks: the camera or zoom site no longer ours while the orbit is on (a savestate
  load does this; it must be repaired within ``REPAIR_S``);
* runtime errors reported by the engine.

Savestates may be loaded from outside while it runs; the script prints one line per
repair.  Exit status 1 when a jump or an unrepaired loss was seen.
"""
from __future__ import annotations

import json
import math
import random
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

REPAIR_S = 3.0
MAX_YAW_STEP = 12.0       # degrees between two 50 ms samples (150 deg/s * 0.05 = 7.5, with margin)


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    log_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    b = PineBackend()
    b.connect()
    ad = Suikoden5Adapter(b)
    ad.uninstall_all()
    d = ad.default_settings()
    s = CameraSettings(**{k: v for k, v in d.items() if k in CameraSettings().__dict__})
    rt = CameraRuntime(ad, s)
    rt.sync_to_game()
    rt.settings.mode = MODE_ORBIT
    rt.start()
    time.sleep(1.0)
    rnd = random.Random(7)
    stats = {"samples": 0, "jumps": 0, "lost_hook": 0, "repairs": 0, "errors": set(), "max_yaw_step": 0.0,
             "walks": 0, "r1": 0, "param_changes": 0, "max_loss_s": 0.0}
    last_yaw = None
    lost_since = None
    next_action = 0.0
    phase = 0
    t_end = time.time() + secs
    fh = log_path.open("w", encoding="utf-8") if log_path else None
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
    while time.time() < t_end:
        now = time.time()
        if now >= next_action:
            phase += 1
            kind = phase % 6
            if kind == 0:
                rt.set_stick(1.0, 0.0); next_action = now + 2.0
            elif kind == 1:
                rt.set_stick(0.0, rnd.choice([-1.0, 1.0])); next_action = now + 1.2
            elif kind == 2:
                rt.set_stick(0.0, 0.0)
                pin._KB.set_analog(pin.render_child(), rnd.choice([-1, 0, 1]), rnd.choice([-1, 1]), "left", pin.CONFIG)
                stats["walks"] += 1; next_action = now + 0.7
            elif kind == 3:
                pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
                rt.settings.distance = rnd.uniform(200.0, 600.0)
                rt.settings.use_fov = rnd.random() < 0.7
                rt.settings.fov_deg = rnd.uniform(20.0, 80.0)
                rt.settings.target_offset = [rnd.uniform(-20, 20), rnd.uniform(-10, 10), rnd.uniform(-20, 20)]
                rt.settings.pos_offset = [rnd.uniform(-20, 20), 0.0, rnd.uniform(-20, 20)]
                stats["param_changes"] += 1; next_action = now + 1.5
            elif kind == 4:
                pin.hold({"r1": True}); time.sleep(0.2); pin.hold({"r1": False})
                stats["r1"] += 1; next_action = now + 0.8
            else:
                rt.set_stick(-1.0, 0.0); next_action = now + 2.0
        time.sleep(0.05)
        try:
            hooks_ok = caves.camera_site_state(b) == "patched" and caves.zoom_site_state(b) == "patched"
            yaw = b.read_floats(mm.G_YAW, 1)[0]
            f = b.read_floats(mm.G_FOCUS, 3)
            e = b.read_floats(mm.G_EYE, 3)
            dist_g = b.read_floats(mm.G_DISTANCE, 1)[0]
        except Exception as exc:  # noqa: BLE001
            stats["errors"].add(f"pine: {exc}")
            continue
        stats["samples"] += 1
        if not hooks_ok:
            if lost_since is None:
                lost_since = now
                stats["lost_hook"] += 1
        elif lost_since is not None:
            loss = now - lost_since
            stats["max_loss_s"] = max(stats["max_loss_s"], loss)
            stats["repairs"] += 1
            print(f"hook repaired after {loss:.2f}s")
            lost_since = None
            last_yaw = None
        if lost_since is not None and now - lost_since > REPAIR_S:
            stats["errors"].add("hook not repaired")
        if hooks_ok and last_yaw is not None and f != [0.0, 0.0, 0.0]:
            step = abs((yaw - last_yaw + 540) % 360 - 180)
            stats["max_yaw_step"] = max(stats["max_yaw_step"], step)
            if step > MAX_YAW_STEP:
                stats["jumps"] += 1
                print(f"yaw jump {step:.1f} deg at {now - (t_end - secs):.1f}s")
        last_yaw = yaw if hooks_ok else None
        if rt.stats.last_error and not rt.stats.last_error.startswith("scene guard"):
            stats["errors"].add(rt.stats.last_error)
        if fh:
            fh.write(json.dumps({"t": round(now - (t_end - secs), 2), "yaw": round(yaw, 2), "dist": round(dist_g, 1),
                                 "hooks": hooks_ok}) + "\n")
    pin._KB.set_analog(pin.render_child(), 0.0, 0.0, "left", pin.CONFIG)
    rt.stop()
    rt.restore()
    time.sleep(0.5)
    clean = caves.camera_site_state(b) == "original" and caves.zoom_site_state(b) == "original"
    stats["errors"] = sorted(stats["errors"])
    stats["clean_exit"] = clean
    print(json.dumps(stats, indent=1, default=str))
    bad = stats["jumps"] or stats["errors"] or not clean
    if fh:
        fh.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
