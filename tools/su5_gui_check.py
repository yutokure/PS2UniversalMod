"""Drive the real camera-controller GUI (offscreen) against PCSX2 running Suikoden V.

    python tools/su5_gui_check.py [--shot PATH]

The GUI is created exactly as ``run_gui.py`` does, and the widgets are driven through the same
signals a user triggers (buttons, spin boxes, check boxes).  Every result is read back from the
game's memory, so a number that only changes in the window does not pass.  The GUI's own
settings file is used and updated (per game id; other games are untouched).  Input is the
GUI's "scripted" source so a physical pad cannot interfere.
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.suikoden5 import caves, memory_map as mm  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from gui.camera_controller.app import MainWindow  # noqa: E402

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def spin(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def g(b):
    return {"f": b.read_floats(mm.G_FOCUS, 3), "e": b.read_floats(mm.G_EYE, 3),
            "pitch": b.read_floats(mm.G_PITCH, 1)[0], "yaw": b.read_floats(mm.G_YAW, 1)[0],
            "dist": b.read_floats(mm.G_DISTANCE, 1)[0], "fov": b.read_floats(mm.G_FOV, 1)[0]}


def main() -> int:
    shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
    app = QApplication(sys.argv[:1])
    win = MainWindow()
    win.show()
    spin(app, 1.5)
    ok_conn = isinstance(win.adapter, Suikoden5Adapter) and win.runtime is not None
    check("GUI connected and picked the Suikoden V adapter", ok_conn,
          f"{win.lbl_serial.text()} / {win.lbl_adapter.text()}")
    if not ok_conn:
        return 1
    b = win.backend
    check("game id / CRC shown", "SLPM-66286" in win.lbl_serial.text() and "7380" in win.lbl_serial.text().lower())
    check("native zoom group is shown for this game", win.grp_zoom.isVisibleTo(win))
    win.cmb_input.setCurrentText("scripted")
    spin(app, 0.3)
    native = g(b)

    # --- Camera mode: Orbit -------------------------------------------------
    win.btn_enable.click()
    spin(app, 1.2)
    check("Orbit: patch applied and runtime running", win.adapter.patch_state() == "applied" and win.runtime.running,
          win.lbl_runtime.text())
    check("Orbit: first frame keeps the stock framing (no snap)",
          abs(g(b)["pitch"] - native["pitch"]) < 1.0 and abs(g(b)["dist"] - native["dist"]) < 1.0,
          f"pitch {g(b)['pitch']:.1f} dist {g(b)['dist']:.1f}")

    # --- rotation sliders ---------------------------------------------------
    win.sl_yaw.spin.setValue(10.0)
    win.sl_pitch.spin.setValue(30.0)
    spin(app, 0.6)
    gg = g(b)
    d = (gg["yaw"] - ((10.0 - 180.0) % 360.0) + 540) % 360 - 180
    check("GUI yaw 10 / pitch 30 reach the game", abs(d) < 0.6 and abs(gg["pitch"] - 30.0) < 0.6,
          f"game yaw {gg['yaw']:.1f} pitch {gg['pitch']:.1f}")

    # --- position: distance, look height, camera and target offsets ------------
    win.sl_dist.spin.setValue(300.0)
    spin(app, 0.5)
    check("GUI distance 300", abs(g(b)["dist"] - 300.0) < 0.6, f"{g(b)['dist']:.1f}")
    f0 = g(b)["f"]
    win.sl_look.spin.setValue(20.0)             # engine +Y is down: the focus drops by 20
    spin(app, 0.5)
    f1 = g(b)["f"]
    check("GUI look height moves the focus vertically", abs((f1[1] - f0[1]) + 20.0) < 0.6, f"{f0[1]:.1f} -> {f1[1]:.1f}")
    win.sl_look.spin.setValue(0.0)
    spin(app, 0.4)
    f2 = g(b)["f"]
    win.off[0].spin.setValue(25.0)              # camera X
    win.off[2].spin.setValue(-15.0)             # camera Z
    spin(app, 0.5)
    f3 = g(b)["f"]
    check("GUI camera X/Z offsets move the rig", abs(f3[0] - f2[0] - 25.0) < 0.6 and abs(f3[2] - f2[2] + 15.0) < 0.6,
          f"({f2[0]:.1f},{f2[2]:.1f}) -> ({f3[0]:.1f},{f3[2]:.1f})")
    win.off[1].spin.setValue(10.0)              # camera Y (engine: down)
    spin(app, 0.5)
    f4 = g(b)["f"]
    check("GUI camera Y offset moves the rig vertically", abs((f4[1] - f3[1]) + 10.0) < 0.6, f"{f3[1]:.1f} -> {f4[1]:.1f}")
    win.off[3].spin.setValue(12.0)              # target X
    spin(app, 0.5)
    f5 = g(b)["f"]
    check("GUI target X offset moves the aim point", abs(f5[0] - f4[0] - 12.0) < 0.6, f"{f4[0]:.1f} -> {f5[0]:.1f}")
    for i in range(6):
        win.off[i].spin.setValue(0.0)
    spin(app, 0.5)
    check("offsets reset to zero return the focus", abs(g(b)["f"][0] - native["f"][0]) < 3.0 and
          abs(g(b)["f"][2] - native["f"][2]) < 3.0, f"{g(b)['f']}")

    # --- lens ---------------------------------------------------------------------
    win.chk_fov.setChecked(True)
    win.sl_fov.spin.setValue(60.0)
    spin(app, 1.0)
    check("GUI FOV 60 changes the game's projection", abs(g(b)["fov"] - 60.0) < 0.3, f"{g(b)['fov']:.2f}")
    # what the game's own FUN_00236F60 hands to the viewport object: sin(fov/2) (its formula)
    vp = b.read_floats(0xB3F790 + 0x68, 1)[0]
    check("viewport extent follows the game's formula sin(fov/2)", abs(vp - math.sin(math.radians(30.0))) < 0.01, f"{vp:.4f}")
    win.btn_fov_reset.click()
    spin(app, 1.0)
    check("FOV reset returns the game value", abs(g(b)["fov"] - native["fov"]) < 0.3, f"{g(b)['fov']:.2f}")

    # --- native zoom ----------------------------------------------------------------
    stage = win.adapter.read_zoom_stage()
    check("native zoom stage is read", stage in (0, 1, 2), win.lbl_zoom_now.text())
    win.btn_zoom_stage[2].click()
    spin(app, 0.6)
    check("zoom stage 3 button sets the orbit distance 200", abs(g(b)["dist"] - 200.0) < 0.6, f"{g(b)['dist']:.1f}")
    win.btn_zoom_stage[0].click()
    spin(app, 0.5)
    check("zoom stage 1 button sets 400", abs(g(b)["dist"] - 400.0) < 0.6, f"{g(b)['dist']:.1f}")

    # --- right stick (GUI scripted source) ----------------------------------------------
    y0 = g(b)["yaw"]
    win.scripted.set(1.0, 0.0)
    spin(app, 0.8)
    win.scripted.set(0.0, 0.0)
    spin(app, 0.3)
    dy = (g(b)["yaw"] - y0 + 540) % 360 - 180
    check("right stick input rotates the camera through the GUI", abs(dy) > 15, f"{dy:+.1f} deg")
    if shot:
        win.grab().save(shot)

    # --- settings persistence ----------------------------------------------------------------
    win._persist()
    st = win.store.get("SLPM-66286")
    check("settings saved under the game id", st.game_id == "SLPM-66286" and st.mode == "orbit", f"mode={st.mode}")

    # --- Original -----------------------------------------------------------------------------
    win.btn_disable.click()
    spin(app, 1.2)
    after = g(b)
    check("Original: hooks removed", caves.camera_site_state(b) == "original" and caves.zoom_site_state(b) == "original")
    check("Original: the game's own camera values are back",
          abs(after["pitch"] - native["pitch"]) < 1.5 and abs(after["yaw"] - native["yaw"]) < 1.5
          and abs(after["fov"] - native["fov"]) < 0.3, f"{after['pitch']:.1f}/{after['yaw']:.1f}/{after['fov']:.1f}")
    win.close()
    spin(app, 0.3)
    check("closing the GUI leaves the game unpatched", caves.camera_site_state(b) == "original")
    bad = [r for r in RES if not r[1]]
    print(f"\n{len(RES) - len(bad)}/{len(RES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
