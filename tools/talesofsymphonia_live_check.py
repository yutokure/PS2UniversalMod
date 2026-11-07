"""Limited Symphonia GUI/runtime check of an ALREADY RUNNING ordinary town/world.

BEFORE running: externally protect the starting state and clone memory cards;
close other PINE clients, resume the VM and keep the player stationary. This tool
never boots a game, accesses states/cards, opens MCP/GDB, or sends game movement.
MainWindow owns the sole PINE connection. Qt/settings are isolated/offscreen and
scripted camera input is host-only. Run separately in each scene to be checked.
Evidence is numeric render-mailbox validation, NOT pixel/rendering validation.
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
        raise ValueError(f"Use a fresh, nonexistent evidence directory outside Git: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="Fresh, nonexistent evidence directory outside Git")
    args = parser.parse_args()  # --help exits before GUI/PINE imports, directories or settings.
    try:
        out = external_directory(args.out)
        out.mkdir(parents=True)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    sys.path.insert(0, str(ROOT))
    old_environment = {key: os.environ.get(key) for key in ("APPDATA", "QT_QPA_PLATFORM")}
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    checks = []
    window = adapter = guard = runtime = backend = transport = None
    epoch = initial_mode = None
    callbacks = {}
    completed = False
    metadata = {"native_coordinates": "X,Y ground / Z up", "canonical_coordinates": "X,-Z,Y (Y down)",
                "stationary_actor_required": True, "state_operations": False,
                "movement_input": False, "pixel_validation": False}

    def check(name, passed, *, fatal=True, **details):
        checks.append(dict(name=name, passed=bool(passed), **details))
        print(("PASS " if passed else "FAIL ") + name + " " + json.dumps(details), flush=True)
        if not passed and fatal:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="symphonia-live-") as home:
        os.environ["APPDATA"] = home
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
            from adapters.talesofsymphonia.adapter import TalesOfSymphoniaAdapter, canonical
            from adapters.talesofsymphonia import caves, memory_map as mm
            from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
            from core.config.settings import AppSettings, SettingsStore
            from core.memory_backend.guard import SAME, GuardedBackend
            from gui.camera_controller import app as gui
            from gui.camera_controller.app import MainWindow, MODE_ORBIT, MODE_ORIGINAL

            # No registry geometry, user presets, physical controller or keyboard.
            original_qsettings = gui.QSettings
            gui.QSettings = lambda *_args: QSettings(str(Path(home) / "geometry.ini"), QSettings.IniFormat)
            settings_store = SettingsStore()
            # MainWindow builds its input combo from the default game's settings
            # before selecting the live adapter; seed that entry too, to prevent
            # even a brief automatic physical-controller/keyboard input pump.
            settings_store.put(AppSettings(game_id="SLPS-25250", input_source="scripted"))
            settings_store.put(AppSettings(game_id=mm.GAME_ID, mode=MODE_ORIGINAL,
                                           distance=1800, look_height=-87, pitch_deg=35,
                                           yaw_deg=180, fov_deg=45, input_source="scripted"))
            app = QApplication.instance() or QApplication([])

            def spin(seconds):
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(.005)

            def same():
                # A reconnect, even into this edition, invalidates this run's evidence.
                return (isinstance(adapter, TalesOfSymphoniaAdapter) and isinstance(guard, GuardedBackend)
                        and backend is guard and runtime is not None and window.adapter is adapter
                        and window.guard is guard and window.runtime is runtime
                        and window.backend is transport and transport.epoch == epoch
                        and guard.expected == (mm.GAME_ID, mm.DISC_CRC) and guard.verify() == SAME
                        and transport.epoch == epoch)

            def require_same():
                if not same():
                    raise RuntimeError("Identity/connection changed or unknown; abandon old addresses without restore")
                if initial_mode is not None and backend.read_u32(mm.MODE) != initial_mode:
                    raise RuntimeError("Scene changed during stationary check; rerun separately in each scene")

            def wait(predicate, seconds=8):
                end = time.monotonic() + seconds
                while True:
                    require_same()
                    if predicate():
                        return
                    if time.monotonic() >= end:
                        raise TimeoutError(f"Runtime did not settle within {seconds}s: {runtime.stats.last_error}")
                    spin(.025)

            def stock():
                return all(caves.read_words(backend, site, len(words)) == words
                           for site, words, _pair, _address, _code in caves.RESOURCES)

            def native_callbacks():
                return all(backend.read_u32(address) == value for address, value in callbacks.items())

            def ack(flags):
                return (backend.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                        and backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_ACK
                        and backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == flags
                        and backend.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) == flags
                        and caves.matches(backend, flags) and native_callbacks())

            def sample():
                # Convert native render diagnostics to canonical coordinates BEFORE
                # subtracting the same owned player, for town and world alike.
                for _ in range(60):
                    require_same()
                    heartbeat = adapter.heartbeat_word()
                    mode, player_address, player = adapter._scene()
                    base = mm.MOD_BLOCK + mm.MB_SNAPSHOT
                    sequence = backend.read_u32(base + mm.SLOT_SEQUENCE)
                    pose = CameraPose(canonical(Vec3(*backend.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_EYE, 3))),
                                      canonical(Vec3(*backend.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_TARGET, 3))))
                    accepted = backend.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED)
                    owned = (backend.read_u32(base + mm.SLOT_PLAYER) == player_address
                             and backend.read_u32(base + mm.SLOT_MODE) == mode
                             and backend.read_u32(base + mm.SLOT_FLAGS) & mm.FLAG_ORBIT)
                    mode_after, player_after, position_after = adapter._scene()
                    stable = (not sequence & 1 and sequence == backend.read_u32(base + mm.SLOT_SEQUENCE)
                              and heartbeat == adapter.heartbeat_word() and mode_after == mode
                              and player_after == player_address and (position_after - player).length() < .01)
                    if (owned and stable and accepted == mode
                            and backend.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) & mm.FLAG_ORBIT
                            and ack(backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS))):
                        return CameraPose(pose.eye - player, pose.target - player)
                    spin(.01)
                raise RuntimeError("No coherent same-player render sample; keep player and scene stationary")

            def pose_error(actual, expected):
                return max((actual.eye - expected.eye).length(), (actual.target - expected.target).length())

            def expected_pose():
                state = runtime.snapshot()
                target = Vec3(state.target_offset[0], state.look_height + state.target_offset[1], state.target_offset[2])
                pose = orbit_pose(target, math.radians(state.yaw_deg), math.radians(state.pitch_deg), state.distance)
                return CameraPose(pose.eye + Vec3(*state.pos_offset), pose.target)

            window = MainWindow()
            window.show()
            adapter, guard, runtime = window.adapter, window.guard, window.runtime
            backend = adapter.backend if adapter is not None else None
            transport = window.backend
            epoch = getattr(transport, "epoch", None)
            require_same()
            scene = adapter.read_scene()
            initial_mode = backend.read_u32(mm.MODE)
            metadata.update(serial=mm.GAME_ID, crc=mm.DISC_CRC, mode=hex(initial_mode),
                            scene="town" if initial_mode == mm.TOWN_MODE else "world", epoch=epoch)
            callbacks = {address: backend.read_u32(address) for address in (mm.BOOT_TOWN_SITE, mm.BOOT_WORLD_SITE)}
            check("ordinary stationary scene accepted", scene.valid and initial_mode in (mm.TOWN_MODE, mm.WORLD_MODE),
                  reason=scene.reason, mode=hex(initial_mode))
            check("verified guarded Original startup with zero writes", adapter.info.matched
                  and runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
                  and len(caves.RESOURCES) == 11 and stock() and transport.stats["writes"] == 0,
                  serial=window.lbl_serial.text(), writes=transport.stats["writes"])
            spin(.2)
            check("Original remains zero-write", transport.stats["writes"] == 0 and stock(), writes=transport.stats["writes"])
            window.grp_offsets.setChecked(True)
            features = adapter.features
            check("GUI capabilities and canonical limits", features.get("free_camera") is False
                  and not features.get("game_time_pause", False) and not window.rb_free.isEnabled()
                  and not window.chk_game_time.isEnabled() and not runtime.settings.pause_game_time
                  and window.chk_fov.isEnabled() and all(control.isEnabled() for control in window.off)
                  and (window.sl_fov.spin.minimum(), window.sl_fov.spin.maximum()) == (20, 110)
                  and (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == (50, 6000)
                  and (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == (-25, 89.5))
            native_fov = adapter.capture_original_fov()
            require_same()
            writes = runtime.stats.total_writes
            window.rb_orbit.click()
            wait(lambda: runtime.stats.mode == MODE_ORBIT and runtime.stats.total_writes > writes
                 and ack(mm.FLAG_ORBIT) and adapter.patch_active() and not runtime.stats.last_error)
            check("GUI Orbit attaches all eleven hooks and returns native callbacks", True,
                  writes=runtime.stats.total_writes, native_fov=native_fov)
            require_same()
            window.sl_dist.spin.setValue(1800)
            window.sl_yaw.spin.setValue(40)
            window.sl_pitch.spin.setValue(35)  # canonical positive puts the eye above the player.
            spin(.4)
            held = sample()
            yaw, pitch = map(math.degrees, held.yaw_pitch())
            check("GUI yaw and positive pitch reach rendered geometry", abs(runtime.settings.yaw_deg - 40) < .01
                  and abs(runtime.settings.pitch_deg - 35) < .01
                  and abs((yaw - 40 + 180) % 360 - 180) < .1 and abs(pitch - 35) < .1
                  and pose_error(held, expected_pose()) < .5, yaw=yaw, pitch=pitch)
            before = runtime.snapshot()
            require_same()
            window.scripted.set(.55, .3)
            try:
                spin(.5)
            finally:
                window.scripted.set(0, 0)
            # The world renderer is slower than the 60-Hz host input pump.
            # Stop input, then wait for the final even bank to reach a guest frame.
            wait(lambda: pose_error(sample(), expected_pose()) < .5)
            after = runtime.snapshot()
            yaw_delta = abs((after.yaw_deg - before.yaw_deg + 180) % 360 - 180)
            error = pose_error(sample(), expected_pose())
            check("scripted camera input updates yaw and pitch", yaw_delta > 2
                  and abs(after.pitch_deg - before.pitch_deg) > 1 and error < .5
                  and not runtime.stats.last_error, yaw_delta=yaw_delta,
                  pitch_delta=after.pitch_deg - before.pitch_deg, relative_pose_error=error)
            require_same()
            window.chk_fov.setChecked(True)
            for fov in (20, 60, 110):
                require_same()
                heartbeat = adapter.heartbeat_word()
                window.sl_fov.spin.setValue(fov)
                wait(lambda: ack(mm.FLAG_ORBIT | mm.FLAG_FOV) and adapter.fov_in_sync(fov)
                     and adapter.heartbeat_word() != heartbeat)
                sx, sy = backend.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_LENS, 2)
                native_sx, native_sy = backend.read_floats(mm.MOD_BLOCK + mm.MB_NATIVE_LENS, 2)
                expected_sx = 1 / math.tan(math.radians(fov) / 2)
                check("accepted projection follows FOV and preserves native aspect", abs(sx - expected_sx) < .001
                      and native_sx > 0 and abs(sy / sx - native_sy / native_sx) < .001,
                      requested=fov, actual=adapter.read_fov_deg(), sx=sx, sy=sy)
            held = sample()
            require_same()
            window.btn_fov_reset.click()
            wait(lambda: not runtime.settings.use_fov and ack(mm.FLAG_ORBIT)
                 and abs(adapter.read_fov_deg() - adapter.capture_original_fov()) < .05)
            error = pose_error(sample(), held)
            check("native FOV reset keeps Orbit geometry", error < .5 and not window.chk_fov.isChecked()
                  and adapter.patch_active(), relative_pose_error=error, native_fov=adapter.capture_original_fov())
            values = [100, 25, -80, -40, 20, 60]
            for control, value in zip(window.off, values):
                require_same()
                control.spin.setValue(value)
            spin(.4)
            error = pose_error(sample(), expected_pose())
            state = runtime.snapshot()
            check("six canonical offsets reach same-player render geometry", state.pos_offset + state.target_offset == values
                  and error < .5 and not runtime.stats.last_error, relative_pose_error=error, offsets=values)
            require_same()
            window.rb_original.click()
            wait(lambda: stock() and runtime.stats.mode == MODE_ORIGINAL and ack(0)
                 and not runtime.stats.last_error)
            check("Original restores all eleven code sites and both native callbacks", len(caves.RESOURCES) == 11
                  and stock() and native_callbacks() and not adapter.patch_active(),
                  callbacks={hex(address): hex(backend.read_u32(address)) for address in callbacks})
            code_owned = all(caves.read_words(backend, address, len(words)) == tuple(words)
                             for address, words in caves.CODE_RESOURCES)
            check("retained detached cave code remains exact", code_owned)
            spin(.15)
            check("native scene and lens resume after detach", adapter.read_scene().valid
                  and abs(adapter.read_fov_deg() - native_fov) < .05 and native_callbacks(),
                  original_fov=native_fov, restored_fov=adapter.read_fov_deg())
            completed = True
        except Exception as exc:
            check("validation aborted", False, fatal=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            try:
                if window is not None:
                    window.scripted.set(0, 0)
                    window.poller.stop()
                    # MainWindow re-verifies once more internally; on any doubt,
                    # abandon instead of restoring into a new game/connection.
                    window._teardown(restore=same())
                    window.close()
            except Exception as exc:
                check("guarded GUI cleanup", False, fatal=False, error=f"{type(exc).__name__}: {exc}")
            if "original_qsettings" in locals():
                gui.QSettings = original_qsettings
            for key, value in old_environment.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            sources = [Path(__file__), *(ROOT / path for path in (
                "adapters/talesofsymphonia/adapter.py", "adapters/talesofsymphonia/caves.py",
                "adapters/talesofsymphonia/memory_map.py", "gui/camera_controller/app.py",
                "core/camera_runtime/engine.py", "core/memory_backend/guard.py"))]
            payload = dict(game="TALESOFSYMPHONIA", completed=completed,
                           passed=completed and all(row["passed"] for row in checks), checks=checks,
                           metadata=metadata, python=sys.version.split()[0],
                           sources={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in sources},
                           scope="Provided stationary town/world only; numeric mailbox checks, no pixel PASS; "
                                 "movement/state reload/menu/event/long-run not tested")
            (out / "checks.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
