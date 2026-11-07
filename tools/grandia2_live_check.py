"""Limited Grandia II GUI/runtime check of an ALREADY RUNNING ordinary field.

BEFORE running: externally protect the starting state and clone memory cards;
close other PINE clients, resume the VM, and keep the player stationary. This
never boots a game, accesses states/cards, opens GDB, or injects native movement.
MainWindow owns the sole PINE connection; Qt and settings are isolated/offscreen.
Optional reload: load/resume a same-edition STOCK state externally after ready.txt,
then create continue.txt. Optional PrintWindow images require human review: no
pixel/framebuffer PASS is inferred. Run separately in each field to be checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def external_directory(path):
    path = path.resolve()
    if path == ROOT or path.is_relative_to(ROOT) or path.exists():
        raise ValueError(f"Use a fresh, nonexistent directory outside Git: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="Fresh evidence directory outside Git")
    parser.add_argument("--reload-handshake", type=Path, help="Fresh external ready.txt/continue.txt directory (900s timeout)")
    parser.add_argument("--capture-window", action="store_true", help="Save optional, unreviewed PCSX2 window PNGs (not pixel validation)")
    parser.add_argument("--pid", type=int, help="Restrict optional capture to this PCSX2 process")
    args = parser.parse_args()  # --help exits before any GUI/PINE imports or side effects.
    try:
        out = external_directory(args.out)
        handshake = external_directory(args.reload_handshake) if args.reload_handshake else None
        if handshake and (out == handshake or out.is_relative_to(handshake) or handshake.is_relative_to(out)):
            raise ValueError("Evidence and handshake directories must be separate, not nested")
        out.mkdir(parents=True)
        if handshake:
            handshake.mkdir(parents=True)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    checks, captures = [], []
    window = adapter = guard = runtime = backend = None
    completed = False
    old_appdata = os.environ.get("APPDATA")

    def check(name, passed, *, fatal=True, **details):
        checks.append(dict(name=name, passed=bool(passed), **details))
        print(("PASS " if passed else "FAIL ") + name + " " + json.dumps(details), flush=True)
        if not passed and fatal:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="grandia2-live-") as home:
        os.environ["APPDATA"] = home
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
            from adapters.grandia2 import Grandia2Adapter, caves, memory_map as mm
            from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
            from core.memory_backend.guard import SAME, GuardedBackend
            from gui.camera_controller.app import MainWindow, MODE_ORBIT, MODE_ORIGINAL
            from gui.camera_controller import app as gui
            gui.QSettings = lambda *_args: QSettings(str(Path(home) / "geometry.ini"), QSettings.IniFormat)  # No registry geometry.
            app = QApplication.instance() or QApplication([])
            def spin(seconds):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(.005)
            def same():
                return (isinstance(adapter, Grandia2Adapter) and isinstance(guard, GuardedBackend)
                        and backend is guard and runtime is not None and window.adapter is adapter and window.guard is guard
                        and window.runtime is runtime and guard.expected == (mm.GAME_ID, mm.DISC_CRC)
                        and guard.verify() == SAME)
            def require_same():
                if not same():
                    raise RuntimeError("Identity/connection changed or unknown; old addresses must not be restored")
            def wait(predicate, seconds=6):
                end = time.monotonic() + seconds
                while True:
                    require_same()
                    if predicate():
                        return
                    if time.monotonic() >= end:
                        raise TimeoutError(f"Runtime did not settle within {seconds}s: {runtime.stats.last_error}")
                    spin(.025)
            def stock():
                return all(caves.read_words(backend, address, len(words)) == words
                           for address, words, _hook in caves.SITES)
            def shot(name):
                if not args.capture_window:
                    return
                require_same()
                import pcsx2_input as pin  # Path/dependency shim only; never render_child().
                from pcsx2_mcp.window_capture import list_windows, capture_window
                pids = pin._pcsx2_pids()
                rows = [w for pid in pids if args.pid is None or pid == args.pid for w in list_windows(pid)
                        if any(t in w["title"].lower() for t in ("grandia", "グランディア", mm.GAME_ID.lower()))
                        and not any(t in w["title"].lower() for t in ("debugger", "console", "log"))]
                if len(rows) != 1:
                    raise RuntimeError("Capture needs one visible, titled Grandia II top-level PCSX2 window; use --pid")
                row = rows[0]  # PID + visible game title; never largest/native-child selection.
                captures.append(dict(name=name, pid=row["pid"], title=row["title"], review="unreviewed",
                                     **capture_window(int(row["hwnd"], 16), out / (name + ".png"))))
            def sample():
                # Coherent render diagnostics and the SAME owned actor/node, not a later unrelated player sample.
                for _ in range(40):
                    require_same()
                    heartbeat = adapter.heartbeat_word()
                    owner, node, player = adapter._field()
                    pose = CameraPose(Vec3(*backend.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_EYE, 3)),
                                      Vec3(*backend.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_TARGET, 3)))
                    owned = (owner == backend.read_u32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_PLAYER)
                             and node == backend.read_u32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_NODE))
                    if (owned and owner == backend.read_u32(mm.PLAYER_PTR)
                            and node == backend.read_u32(owner + mm.ACTOR_NODE)
                            and heartbeat == adapter.heartbeat_word() and adapter._render_applied()
                            and not backend.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)):
                        return CameraPose(pose.eye - player, pose.target - player)
                    spin(.01)
                raise RuntimeError("No coherent same-actor render sample; keep player/field stationary")
            def pose_error(actual, expected):
                return max((actual.eye - expected.eye).length(), (actual.target - expected.target).length())
            def settings():
                state = runtime.snapshot()
                return {k: getattr(state, k) for k in ("mode", "yaw_deg", "pitch_deg", "distance", "look_height",
                                                      "pos_offset", "target_offset", "fov_deg", "use_fov")}

            window = MainWindow()
            window.show()
            adapter, guard, runtime = window.adapter, window.guard, window.runtime
            backend = adapter.backend if adapter is not None else None
            require_same()
            check("verified guarded Original startup", adapter.info.matched and runtime.settings.mode == MODE_ORIGINAL
                  and window.rb_original.isChecked() and stock() and window.backend.stats["writes"] == 0,
                  serial=window.lbl_serial.text(), writes=window.backend.stats["writes"])
            window.cmb_input.setCurrentText("scripted")
            window.grp_offsets.setChecked(True)
            features = adapter.features
            check("supported GUI features and FOV range", features.get("free_camera") is False
                  and not features.get("game_time_pause", False) and not window.rb_free.isEnabled()
                  and not window.chk_game_time.isEnabled() and not runtime.settings.pause_game_time
                  and not window.chk_game_time.isChecked() and window.chk_fov.isEnabled()
                  and all(c.isEnabled() for c in window.off)
                  and Grandia2Adapter.FOV_RANGE == (20, 110)
                  and (window.sl_fov.spin.minimum(), window.sl_fov.spin.maximum()) == (20, 110))
            scene = adapter.read_scene()
            check("ordinary field accepted", scene.valid, reason=scene.reason)
            writes = runtime.stats.total_writes
            require_same()
            window._on_mode(MODE_ORBIT)
            wait(lambda: runtime.stats.mode == MODE_ORBIT and runtime.stats.total_writes > writes
                 and adapter.patch_active() and not runtime.stats.last_error)
            check("Orbit startup audit settled", True, writes=runtime.stats.total_writes)
            require_same()
            window.sl_yaw.spin.setValue(40)
            window.sl_pitch.spin.setValue(35)  # Display-positive above; internal pitch is negative.
            spin(.4)
            held = sample()
            check("GUI spin values reach rendered yaw and pitch", abs(runtime.settings.yaw_deg - 40) < .01
                  and abs(runtime.settings.pitch_deg + 35) < .01
                  and abs(math.degrees(held.yaw_pitch()[0]) - 40) < .1
                  and abs(math.degrees(held.yaw_pitch()[1]) + 35) < .1)
            before = runtime.snapshot()
            require_same()
            window.scripted.set(.55, .3)
            try:
                spin(.5)
            finally:
                window.scripted.set(0, 0)
            spin(.15)
            after = runtime.snapshot()
            yaw_delta = abs((after.yaw_deg - before.yaw_deg + 180) % 360 - 180)
            check("scripted right-stick tick changes yaw and pitch", yaw_delta > 2
                  and abs(after.pitch_deg - before.pitch_deg) > 1 and not runtime.stats.last_error,
                  yaw_delta=yaw_delta, pitch_delta=after.pitch_deg - before.pitch_deg)
            require_same()
            window.chk_fov.setChecked(True)
            for fov in (20, 40, 60, 100, 110):
                require_same()
                heartbeat = adapter.heartbeat_word()
                window.sl_fov.spin.setValue(fov)
                wait(lambda: adapter.fov_in_sync(fov) and adapter.heartbeat_word() != heartbeat)
                focal = backend.read_f32(mm.MOD_BLOCK + mm.MB_RENDER_FOCAL)
                expected = backend.read_f32(mm.SCREEN_WIDTH) / (2 * math.tan(math.radians(fov) / 2)
                                                               * backend.read_f32(mm.ASPECT_X))
                check("render focal follows FOV", abs(focal - expected) < .05,
                      requested=fov, actual=adapter.read_fov_deg(), focal=focal)
                shot(f"fov_{fov}")
            held = sample()
            require_same()
            window.btn_fov_reset.click()
            wait(lambda: not runtime.settings.use_fov and abs(adapter.read_fov_deg() - adapter.capture_original_fov()) < .05)
            error = pose_error(sample(), held)
            check("native FOV reset holds Orbit pose", error < .5 and not window.chk_fov.isChecked()
                  and adapter.patch_active(), relative_pose_error=error, native_fov=adapter.capture_original_fov())
            require_same()
            values = [100, 25, -80, -40, 20, 60]
            for control, value in zip(window.off, values):
                require_same()
                control.spin.setValue(value)  # FloatSlider.set_value deliberately does not emit.
            spin(.4)
            s = runtime.snapshot()
            target = Vec3(s.target_offset[0], s.look_height + s.target_offset[1], s.target_offset[2])
            expected = orbit_pose(target, math.radians(s.yaw_deg), math.radians(s.pitch_deg), s.distance)
            expected.eye = expected.eye + Vec3(*s.pos_offset)
            error = pose_error(sample(), expected)
            check("six GUI offsets reach same-actor rendered geometry", s.pos_offset + s.target_offset == values
                  and error < .5 and not runtime.stats.last_error, relative_pose_error=error, offsets=values)
            shot("offsets")
            if handshake:
                require_same()
                window.sl_fov.spin.setValue(40)
                window.chk_fov.setChecked(True)
                wait(lambda: adapter.fov_in_sync(40))
                retained = settings()
                (handshake / "ready.txt").write_text("Externally load/resume a protected same-edition STOCK field state; then create continue.txt. No tool state/card access.\n", encoding="utf-8")
                print("READY " + str(handshake), flush=True)
                wait(lambda: (handshake / "continue.txt").is_file(), seconds=900)
                heartbeat = adapter.heartbeat_word()
                wait(lambda: adapter.patch_active() and adapter.fov_in_sync(40)
                     and adapter.heartbeat_word() != heartbeat and not runtime.stats.last_error)
                error = pose_error(sample(), expected)
                check("external stock reload reapplies and retains settings", settings() == retained and error < .5,
                      settings=settings(), relative_pose_error=error, reload_confirmation="external operator handshake")
                shot("reload")
            require_same()
            window._on_mode(MODE_ORIGINAL)
            wait(lambda: stock() and runtime.stats.mode == MODE_ORIGINAL and not runtime.stats.last_error)
            check("Original restores all seven stock hooks", len(caves.SITES) == 7
                  and stock() and not adapter.patch_active())
            shot("restored")
            completed = True
        except Exception as exc:
            check("validation aborted", False, fatal=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            try:
                if window is not None:
                    window.scripted.set(0, 0)
                    window.poller.stop()
                    window._teardown(restore=same())  # Re-verifies internally; otherwise abandons without writes.
                    window.close()
            except Exception as exc:
                check("guarded GUI cleanup", False, fatal=False, error=str(exc))
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
            sources = [Path(__file__), *(ROOT / p for p in ("adapters/grandia2/adapter.py", "adapters/grandia2/caves.py",
                       "adapters/grandia2/packets.py", "adapters/grandia2/memory_map.py",
                       "gui/camera_controller/app.py", "core/camera_runtime/engine.py",
                       "core/memory_backend/guard.py"))]
            payload = dict(game="GRANDIA2", completed=completed, passed=completed and all(c["passed"] for c in checks),
                           checks=checks, captures=captures, python=sys.version.split()[0],
                           sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                           scope="Provided stationary field only; numeric render mailbox checks, no pixel PASS; movement/menu/event/long-run not tested")
            (out / "checks.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
