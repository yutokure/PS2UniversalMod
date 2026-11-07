"""Limited Innocent Life GUI/runtime checks against an already-running field.

Protect the starting state and use cloned memory cards first. This tool never
boots games, loads/saves states, edits cards or opens GDB. MainWindow owns the
only PINE client. --move injects short forward/backward walks at four yaws;
terrain can block/slide a walk, which is reported rather than called success.
--reload-handshake waits for an external same-edition stock-state load/resume.
Evidence must be outside the repository. Always releases input and restores via
the verified identity guard; a changed/unknown game is abandoned without writes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication
from adapters.innocentlife.adapter import InnocentLifeAdapter
from adapters.innocentlife import caves, memory_map as mm
from core.memory_backend.guard import SAME
from gui.camera_controller.app import MainWindow, MODE_ORBIT, MODE_ORIGINAL
import pcsx2_input as pin
from pcsx2_mcp.window_capture import capture_window


def angle_error(a, b):
    return abs((a - b + 180) % 360 - 180)


def external_directory(value):
    path = value.resolve()
    if path == ROOT or path.is_relative_to(ROOT):
        raise ValueError("Evidence/handshake directories must be outside the repository")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Use a new/empty directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--move", action="store_true")
    parser.add_argument("--reload-handshake", type=Path)
    args = parser.parse_args()
    try:
        out = external_directory(args.out)
        handshake = external_directory(args.reload_handshake) if args.reload_handshake else None
        if out == handshake:
            raise ValueError("Use distinct evidence and handshake directories")
    except ValueError as exc:
        parser.error(str(exc))
    app = QApplication.instance() or QApplication([])
    checks = []
    measurements = []
    window = adapter = guard = runtime = backend = hwnd = None
    completed = False
    old_appdata = os.environ.get("APPDATA")

    def spin(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def check(name, passed, **details):
        checks.append(dict(name=name, passed=bool(passed), **details))
        print(("PASS " if passed else "FAIL ") + name + " " + json.dumps(details), flush=True)

    def same():
        return (guard is not None and window.guard is guard and window.adapter is adapter
                and window.runtime is runtime and guard.verify() == SAME)

    def require_same():
        if not same():
            raise RuntimeError("Game identity/connection changed; no restoration into old addresses")

    def reset():
        if window is not None:
            window.scripted.set(0, 0)
        if hwnd is not None:
            pin._KB.reset(hwnd)

    def stick(x=0, y=0, which="left"):
        require_same()
        pin._KB.set_analog(hwnd, x, y, which, pin.CONFIG)

    def clock():
        return tuple(backend.read_u32(a) for a in (mm.CLOCK_HOURS, mm.CLOCK_MINUTES, mm.CLOCK_SECONDS))

    def shot(name):
        require_same()
        capture_window(hwnd, out / (name + ".png"))
        spin(.08)
        capture_window(hwnd, out / (name + ".png"))

    def pose(yaw, pitch=35, distance=90):
        require_same()
        window.sl_yaw.spin.setValue(yaw)
        window.sl_pitch.spin.setValue(pitch)
        window.sl_dist.spin.setValue(distance)
        spin(.35)
        actual = adapter.read_game_pose()
        view = np.array(backend.read_floats(mm.VIEW, 16)).reshape(4, 4)
        view_eye = -view[3, :3] @ np.linalg.inv(view[:3, :3])
        eye_error = float(np.linalg.norm(view_eye - np.array(actual.eye.as_tuple())))
        actual_yaw, actual_pitch = map(math.degrees, actual.yaw_pitch())
        check("render view matches requested Orbit", angle_error(actual_yaw, yaw) < .1
              and abs(actual_pitch - pitch) < .1 and eye_error < .02,
              requested_yaw=yaw, yaw=actual_yaw, pitch=actual_pitch,
              view_eye_error=eye_error, runtime_error=runtime.stats.last_error)
        return actual

    with tempfile.TemporaryDirectory(prefix="innocentlife-live-") as home:
        os.environ["APPDATA"] = home
        try:
            window = MainWindow()
            window.show()
            spin(.7)
            if not isinstance(window.adapter, InnocentLifeAdapter) or window.runtime is None:
                raise RuntimeError("Requires SLPS-25763 / 9AC21F92 in an ordinary field")
            adapter, guard, runtime = window.adapter, window.guard, window.runtime
            backend = adapter.backend
            hwnd = pin.render_child()
            window.cmb_input.setCurrentText("scripted")
            window.grp_offsets.setChecked(True)
            require_same()
            check("exact guarded edition and safe startup", guard.expected == (mm.GAME_ID, mm.DISC_CRC)
                  and runtime.settings.mode == MODE_ORIGINAL and not runtime.settings.pause_game_time
                  and caves.site_state(backend) == "stock", serial=window.lbl_serial.text())
            check("GUI exposes supported features only", window.chk_game_time.isEnabled()
                  and not window.rb_free.isEnabled() and window.chk_fov.isEnabled()
                  and all(control.isEnabled() for control in window.off),
                  free_reason=window.rb_free.toolTip(), fov_reason=window.chk_fov.toolTip())
            scene = adapter.read_scene()
            check("ordinary field accepted", scene.valid, reason=scene.reason)
            if not scene.valid:
                raise RuntimeError(scene.reason)
            start_clock = clock()
            spin(.65)
            check("native clock advances before pause", clock() != start_clock,
                  before=start_clock, after=clock())
            window.chk_game_time.setChecked(True)
            spin(.65)
            frozen = clock()
            frame0 = backend.read_u32(0x1BE7CC)  # local measured main-loop counter
            spin(1.2)
            frame1 = backend.read_u32(0x1BE7CC)
            check("Original clock-only pause keeps VM running", clock() == frozen
                  and frame1 > frame0 and adapter.time_paused()
                  and runtime.settings.mode == MODE_ORIGINAL,
                  clock=frozen, frames=frame1-frame0, clock_error=runtime.stats.game_time_error)
            shot("clock_only")
            native = tuple(backend.read_u32(mm.CAMERA+i*4) for i in range(7))
            window._on_mode(MODE_ORBIT)
            spin(.65)
            for yaw in (0, 90, 180, -90):
                pose(yaw)
                shot(f"orbit_{yaw}")
            check("native rig and clock preserved while rotating", native == tuple(
                backend.read_u32(mm.CAMERA+i*4) for i in range(7)) and clock() == frozen,
                clock=clock())
            pose(180)
            native_focal = backend.read_u32(mm.CAM_FOCAL)
            native_fov = adapter.capture_original_fov()
            native_projection = tuple(backend.read_floats(mm.PROJECTION, 16))
            check("native calibrated horizontal FOV", abs(adapter.read_fov_deg()-native_fov) < .05,
                  native_fov=native_fov, projection_x=native_projection[0])
            window.chk_fov.setChecked(True)
            for fov in (20, 40, 60, 100, 110):
                window.sl_fov.spin.setValue(fov)
                spin(.65)
                projection = backend.read_floats(mm.PROJECTION, 16)
                expected_x = mm.SCREEN_HALF_WIDTH / math.tan(math.radians(fov)/2)
                x_factor = backend.read_f32(mm.PROJECTION_X_FACTOR)
                y_factor = backend.read_f32(mm.PROJECTION_Y_FACTOR)
                clip_x = backend.read_f32(0x207DA0)
                check("FOV changes native render and clipping projection", abs(adapter.read_fov_deg()-fov) < .05
                      and abs(projection[0]-expected_x) < .01
                      and abs(projection[5]-expected_x*y_factor/x_factor) < .01
                      and abs(clip_x-expected_x/mm.SCREEN_HALF_WIDTH) < .001
                      and backend.read_u32(mm.CAM_FOCAL) == native_focal
                      and adapter.fov_in_sync(fov), requested=fov, actual=adapter.read_fov_deg(),
                      projection_x=projection[0], projection_y=projection[5], clip_x=clip_x,
                      native_preserved=backend.read_u32(mm.CAM_FOCAL) == native_focal,
                      error=runtime.stats.last_error)
                shot(f"fov_{fov}")
            window.btn_fov_reset.click()
            spin(.65)
            restored_projection = tuple(backend.read_floats(mm.PROJECTION, 16))
            check("FOV reset returns entire native projection", restored_projection == native_projection
                  and not runtime.settings.use_fov and not window.chk_fov.isChecked(),
                  actual=adapter.read_fov_deg(), native=native_fov)
            shot("fov_reset")
            pose(40, 70, 120)
            shot("pitch70")
            window.off[0].spin.setValue(12)
            window.off[4].spin.setValue(-3)
            spin(.35)
            p = adapter.read_game_pose()
            forward = p.target - p.eye
            bank = mm.MOD_BLOCK + mm.SLOTS[backend.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1]
            bank_yaw = backend.read_f32(bank+mm.SLOT_YAW)
            check("independent offsets update actual movement view yaw",
                  angle_error(math.degrees(bank_yaw), math.degrees(math.atan2(forward.x, forward.z))) < .1,
                  yaw=math.degrees(bank_yaw))
            for control in window.off:
                control.spin.setValue(0)
            pose(0)
            old_yaw = runtime.settings.yaw_deg
            window.scripted.set(.6, 0)
            spin(.2)
            window.scripted.set(0, 0)
            spin(.2)
            check("right-stick input rotates and retains angle", angle_error(runtime.settings.yaw_deg, old_yaw) > 3,
                  before=old_yaw, after=runtime.settings.yaw_deg)
            if args.move:
                for yaw in (0, 90, 180, -90):
                    p = pose(yaw)
                    forward = p.target-p.eye
                    expected = np.array([forward.x, forward.z])
                    expected /= np.linalg.norm(expected)
                    for direction, sy in (("forward", 1), ("backward", -1)):
                        a = adapter.read_player()
                        try:
                            stick(0, sy)
                            # Native turn smoothing can consume the first 180-degree
                            # turn without translation; allow it to settle before
                            # judging displacement rather than patching native speed.
                            spin(.5)
                        finally:
                            reset()
                        spin(.12)
                        z = adapter.read_player()
                        displacement = np.array([z.x-a.x, z.z-a.z])
                        length = float(np.linalg.norm(displacement))
                        wanted = expected * sy
                        alignment = float(displacement @ wanted / length) if length > .01 else 0
                        heading = math.degrees(backend.read_f32(mm.PLAYER+0x14))
                        target_heading = math.degrees(math.atan2(wanted[0], wanted[1]))
                        facing_error = angle_error(heading, target_heading)
                        entry = dict(yaw=yaw, direction=direction, start=a.as_tuple(), end=z.as_tuple(),
                                     distance=length, alignment=alignment, facing_error=facing_error)
                        measurements.append(entry)
                        check("walk displacement and facing follow Orbit", length > 1 and alignment > .85
                              and facing_error < 15, **entry)
                        check("clock stays paused during movement", clock() == frozen, clock=clock())
            pose(40, 65, 110)
            window.sl_fov.spin.setValue(60)
            window.chk_fov.setChecked(True)
            spin(.65)
            if handshake:
                (handshake / "ready.txt").write_text("Load same-edition stock state and resume, then create continue.txt", encoding="utf-8")
                print("READY " + str(handshake), flush=True)
                end = time.monotonic()+900
                while not (handshake/"continue.txt").exists():
                    if time.monotonic() > end:
                        raise TimeoutError("Stock-state reload handshake expired")
                    spin(.1)
                    require_same()
                spin(2)
                check("stock state load reapplies Orbit, FOV and clock", adapter.patch_active()
                      and adapter.time_paused() and adapter.fov_in_sync(60)
                      and not runtime.stats.game_time_error and not runtime.stats.last_error,
                      clock=clock(), error=runtime.stats.last_error)
                pose(40, 65, 110)
                frozen = clock()
                spin(.5)
                check("reapplied clock stays fixed", clock() == frozen, clock=clock())
            window._on_mode(MODE_ORIGINAL)
            spin(.5)
            check("Original restores camera while preserving clock opt-in",
                  not adapter.patch_active() and adapter.time_paused()
                  and abs(adapter.read_fov_deg()-adapter.capture_original_fov()) < .05
                  and runtime.settings.pause_game_time and window.chk_game_time.isChecked(),
                  fov=adapter.read_fov_deg(), native_fov=adapter.capture_original_fov())
            window.btn_restore.click()
            spin(.8)
            check("disable-all restores every instruction and clears clock",
                  caves.matches(backend, 0) and not runtime.settings.pause_game_time
                  and not window.chk_game_time.isChecked(), error=runtime.stats.last_error,
                  clock_error=runtime.stats.game_time_error)
            c0 = clock()
            spin(.5)
            check("clock resumes without catch-up", clock() != c0,
                  before=c0, after=clock())
            shot("restored")
            window.grab().save(str(out/"gui.png"))
            completed = True
        except Exception as exc:
            check("live check aborted", False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        finally:
            try:
                reset()
            except Exception as exc:
                check("input cleanup", False, error=str(exc))
            try:
                if same():
                    runtime.freeze(False)
                    runtime.stop()
                    runtime.restore()
                    check("guarded final cleanup", caves.matches(backend, 0),
                          error=runtime.stats.last_error, clock_error=runtime.stats.game_time_error)
            except Exception as exc:
                check("restore cleanup", False, error=str(exc))
            try:
                if window is not None:
                    window.close()
                    spin(.15)
            finally:
                if old_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_appdata
                payload = dict(game="INNOCENTLIFE", completed=completed,
                               passed=completed and all(item["passed"] for item in checks),
                               checks=checks, movement=measurements,
                               scope="Limited provided outdoor field; no all-menu/event/map/long-run guarantee")
                (out/"checks.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if completed and all(item["passed"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
