"""Minstrel Song GUI/runtime checks on an already-running verified ordinary field.

One PINE client: MainWindow owns the only connection. Uses temporary APPDATA and
an offscreen GUI, writes evidence outside the repository, and releases injected
input/restores through the identity guard in finally. Never boots games, navigates
menus, loads/saves states or edits memory cards. Gameplay itself can autosave: use
isolated/backed-up cards and protect the starting VM state before running.

--move injects ONE short left-stick Up input (0.23 seconds). A wall, blocked route
or unchanged actor heading is reported, not reinterpreted as camera success.
--reload-handshake waits for an EXTERNAL same-edition stock state load/resume;
this script never opens a second PINE or a GDB/MCP connection. Special menus and
all other scenes remain outside the verified scope.
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
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402
from adapters.minstrelsong.adapter import MinstrelSongAdapter  # noqa: E402
from adapters.minstrelsong import caves, memory_map as mm  # noqa: E402
from core.camera_math.orbit import Vec3, orbit_pose  # noqa: E402
from core.memory_backend.guard import SAME  # noqa: E402
from gui.camera_controller.app import MainWindow, MODE_ORIGINAL  # noqa: E402
import pcsx2_input as pin  # noqa: E402
from pcsx2_mcp.window_capture import capture_window  # noqa: E402


def angle_error(a, b):
    """Unsigned wrapped error in degrees (camera/actor memory contains radians)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def evidence_directory(value):
    path = value.resolve()
    if path == ROOT or path.is_relative_to(ROOT):
        raise ValueError('Evidence and handshake directories must be outside the repository')
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f'Use a new/empty directory: {path}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New/empty evidence directory outside Git')
    parser.add_argument('--move', action='store_true', help='One 0.23 second left-stick Up walk; protect cards/state first')
    parser.add_argument('--reload-handshake', type=Path, help='New/empty external stock-state reload handshake directory')
    args = parser.parse_args()
    try:
        out = evidence_directory(args.out)
        handshake = evidence_directory(args.reload_handshake) if args.reload_handshake else None
        if handshake == out:
            raise ValueError('Use distinct evidence and handshake directories')
    except ValueError as exc:
        parser.error(str(exc))
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    results = []
    screenshots = []
    window = adapter = guard = runtime = backend = hwnd = None
    completed = False
    old_appdata = os.environ.get('APPDATA')

    def spin(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.005)

    def check(name, passed, **data):
        item = dict(name=name, passed=bool(passed), **data)
        results.append(item)
        print(('PASS ' if passed else 'FAIL ') + name + ' ' + json.dumps(data), flush=True)
        return bool(passed)

    def same_game():
        return (guard is not None and window is not None and window.guard is guard
                and window.adapter is adapter and window.runtime is runtime
                and guard.verify() == SAME)

    def require_same_game():
        if not same_game():
            raise RuntimeError('Game identity/connection changed; stop without restoring old-game addresses')

    def reset_input():
        if window is not None and window.scripted is not None:
            window.scripted.set(0, 0)
        if hwnd is not None:
            pin._KB.reset(hwnd)

    def stick(x=0, y=0, which='left'):
        require_same_game()
        pin._KB.set_analog(hwnd, x, y, which, pin.CONFIG)

    def shot(name):
        require_same_game()
        path = out / (name + '.png')
        # Existing window-capture path can return a stale first frame. Capture
        # twice; these are window images, not guaranteed native GS dimensions.
        capture_window(hwnd, path)
        spin(.1)
        capture_window(hwnd, path)
        screenshots.append(path.name)

    def hook_words():
        return {f'{address:08X}': [f'{word:08X}' for word in caves.read_words(backend, address, 2)]
                for address, _, _, _, _ in caves.RESOURCES}

    def all_hooks(applied):
        return all(caves.read_words(backend, address, 2) == (hook if applied else stock)
                   for address, stock, hook, _, _ in caves.RESOURCES)

    def yaw_state():
        pose = adapter.read_game_pose()
        yaw, pitch = map(math.degrees, pose.yaw_pitch())
        return pose, yaw, pitch, math.degrees(backend.read_f32(mm.CAM_YAW))

    def set_pose(yaw, pitch, distance):
        require_same_game()
        window.sl_yaw.spin.setValue(yaw)
        window.sl_pitch.spin.setValue(pitch)
        window.sl_dist.spin.setValue(distance)
        spin(.6)

    with tempfile.TemporaryDirectory(prefix='minstrelsong-live-') as home:
        os.environ['APPDATA'] = home
        try:
            window = MainWindow()
            window.show()
            spin(.7)
            identified = (isinstance(window.adapter, MinstrelSongAdapter)
                          and window.runtime is not None and window.guard is not None
                          and window.guard.writes_allowed
                          and window.guard.expected == (mm.GAME_ID, mm.DISC_CRC))
            check('exact Minstrel Song edition identified with guarded writes', identified,
                  serial=window.lbl_serial.text(), adapter=window.lbl_adapter.text())
            if not identified:
                raise RuntimeError('Requires SLPM-65920 / 2B9AF3C5 in a verified ordinary field')
            adapter, guard, runtime = window.adapter, window.guard, window.runtime
            backend = adapter.backend  # The same guarded MainWindow connection, never another PINE client.
            require_same_game()
            window.grp_offsets.setChecked(True)
            window.cmb_input.setCurrentText('scripted')
            check('Original startup and supported GUI features',
                  runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
                  and not window.rb_free.isEnabled() and bool(window.rb_free.toolTip())
                  and window.rb_orbit.isEnabled() and window.chk_fov.isEnabled()
                  and all(control.isEnabled() for control in window.off),
                  mode=runtime.settings.mode, free_reason=window.rb_free.toolTip())
            scene = adapter.read_scene()
            check('verified ordinary field accepted', scene.valid, reason=scene.reason)
            if not scene.valid:
                raise RuntimeError(scene.reason)
            check('starts with every hook stock', all_hooks(False), hooks=hook_words())
            if not all_hooks(False):
                raise RuntimeError('Start from stock hooks; do not use a state with an active previous MOD')
            hwnd = pin.render_child()
            reset_input()
            shot('stock')
            window.btn_enable.click()
            spin(.8)
            check('GUI enable centres and installs every owned hook',
                  adapter.patch_active() and all_hooks(True) and not runtime.stats.last_error,
                  hooks=hook_words(), error=runtime.stats.last_error)
            for yaw, pitch, distance in ((150, 22, 6), (-165, 22, 10),
                                          (150, 60, 10), (-165, 60, 6)):
                set_pose(yaw, pitch, distance)
                pose, actual_yaw, actual_pitch, compass_yaw = yaw_state()
                check(f'Orbit {yaw}/{pitch}/{distance} and native compass yaw',
                      angle_error(actual_yaw, yaw) < .1 and abs(actual_pitch - pitch) < .1
                      and abs(pose.distance() - distance) < .015
                      and angle_error(compass_yaw, actual_yaw) < .1 and not runtime.stats.last_error,
                      yaw=actual_yaw, pitch=actual_pitch, distance=pose.distance(),
                      compass_yaw=compass_yaw, actor_heading=math.degrees(backend.read_f32(mm.PLAYER_HEADING)),
                      error=runtime.stats.last_error)
                shot(f'orbit_{yaw}_{pitch}_{distance}')

            set_pose(-165, 22, 10)
            window.sl_look.spin.setValue(-1.3)
            offsets = (.2, -.1, .15, -.15, .1, .2)
            for control, value in zip(window.off, offsets):
                control.spin.setValue(value)
            spin(.6)
            pose, actual_yaw, _, compass_yaw = yaw_state()
            player = adapter.read_player()
            wanted = orbit_pose(player + Vec3(-.15, -1.2, .2), math.radians(-165), math.radians(22), 10)
            eye_error = (pose.eye - wanted.eye - Vec3(.2, -.1, .15)).length()
            target_error = (pose.target - wanted.target).length()
            check('six independent small offsets and height reach guest render arguments',
                  eye_error < .02 and target_error < .02 and angle_error(compass_yaw, actual_yaw) < .1,
                  eye=pose.eye.as_tuple(), target=pose.target.as_tuple(), player=player.as_tuple(),
                  eye_error=eye_error, target_error=target_error,
                  compass_yaw=compass_yaw, actual_offset_yaw=actual_yaw)
            shot('offsets')
            for control in window.off:
                control.spin.setValue(0)
            window.sl_look.spin.setValue(-1.5)
            spin(.4)

            for deg in (40, 65, 85):
                window.chk_fov.setChecked(True)
                window.sl_fov.spin.setValue(deg)
                spin(.7)
                require_same_game()
                actual_fov = adapter.read_fov_deg()
                focal, focal_y = backend.read_f32(mm.PROJECTION), backend.read_f32(mm.PROJECTION_Y)
                check(f'FOV {deg} reaches actual native projection',
                      abs(actual_fov - deg) < .05
                      and abs(focal_y / focal - mm.PROJECTION_Y_RATIO) < .001,
                      measured=actual_fov, focal=focal, focal_y=focal_y,
                      native_fov=adapter.capture_original_fov(), error=runtime.stats.last_error)
                shot(f'fov{deg}')
            window.chk_fov.setChecked(False)
            spin(.7)
            check('FOV release preserves Orbit and restores current native lens',
                  adapter.patch_active() and abs(adapter.read_fov_deg() - adapter.capture_original_fov()) < .05,
                  actual=adapter.read_fov_deg(), native=adapter.capture_original_fov())

            set_pose(-165, 22, 10)
            yaw_before = runtime.settings.yaw_deg
            window.scripted.set(.7, .2)
            try:
                spin(.25)
            finally:
                window.scripted.set(0, 0)
            spin(.35)
            pose, actual_yaw, actual_pitch, compass_yaw = yaw_state()
            held_yaw = runtime.settings.yaw_deg
            spin(.35)
            _, final_yaw, _, final_compass = yaw_state()
            check('scripted right input rotates then holds actual Orbit and compass',
                  angle_error(held_yaw, yaw_before) > 1
                  and angle_error(actual_yaw, held_yaw) < .1
                  and angle_error(final_yaw, actual_yaw) < .1
                  and angle_error(final_compass, final_yaw) < .1,
                  before=yaw_before, requested=held_yaw, actual=actual_yaw,
                  held_actual=final_yaw, pitch=actual_pitch, compass=compass_yaw)
            shot('scripted_right_held')

            # Scripted source is zero: this keyboard right-axis injection reaches
            # the game, not the MOD input pump. No pad addresses are guessed here.
            set_pose(-165, 22, 10)
            _, right_yaw, _, right_compass = yaw_state()
            heading_before = backend.read_f32(mm.PLAYER_HEADING)
            try:
                stick(1, 0, 'right')
                spin(.16)
            finally:
                reset_input()
            spin(.25)
            _, after_right_yaw, _, after_right_compass = yaw_state()
            check('native right-axis is unassigned with no right-stick blocking patch',
                  angle_error(after_right_yaw, right_yaw) < .1
                  and angle_error(after_right_compass, right_compass) < .1
                  and angle_error(math.degrees(backend.read_f32(mm.PLAYER_HEADING)), math.degrees(heading_before)) < .1
                  and all_hooks(True) and not runtime.stats.last_error,
                  before_yaw=right_yaw, after_yaw=after_right_yaw,
                  scope='keyboard right-axis delivery and camera/actor response; raw pad bytes not located/read',
                  error=runtime.stats.last_error)

            if args.move:
                set_pose(150, 22, 10)
                # Let any in-flight host tick finish before sampling. Compare the
                # publication stamps as well as the freeze flag, not just assume
                # that guest-only actor following happened.
                runtime.freeze(True)
                try:
                    spin(.08)
                    before = adapter.read_player()
                    before_pose, _, _, before_compass = yaw_state()
                    before_heading = math.degrees(backend.read_f32(mm.PLAYER_HEADING))
                    forward = before_pose.target - before_pose.eye
                    horizontal = math.hypot(forward.x, forward.z)
                    if horizontal < 1e-6:
                        raise RuntimeError('No horizontal movement basis for this rendered pose')
                    expected_x, expected_z = forward.x / horizontal, forward.z / horizontal
                    eye_relative = before_pose.eye - before
                    target_relative = before_pose.target - before
                    heartbeat_before = backend.read_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT)
                    publication_before = [backend.read_u32(mm.MOD_BLOCK + offset) for offset in
                                          (mm.MB_SLOT, mm.MB_FLAGS,
                                           mm.SLOTS[0] + mm.SLOT_SEQUENCE, mm.SLOTS[1] + mm.SLOT_SEQUENCE)]
                    stick(0, 1, 'left')  # Verified BackgroundKeyboard Y+ is Up; Y- is Down.
                    try:
                        spin(.23)
                    finally:
                        reset_input()
                    spin(.25)
                    require_same_game()
                    after = adapter.read_player()
                    after_pose, _, _, after_compass = yaw_state()
                    after_heading = math.degrees(backend.read_f32(mm.PLAYER_HEADING))
                    heartbeat_after = backend.read_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT)
                    publication_after = [backend.read_u32(mm.MOD_BLOCK + offset) for offset in
                                         (mm.MB_SLOT, mm.MB_FLAGS,
                                          mm.SLOTS[0] + mm.SLOT_SEQUENCE, mm.SLOTS[1] + mm.SLOT_SEQUENCE)]
                finally:
                    try:
                        reset_input()
                    finally:
                        runtime.freeze(False)
                displacement = after - before
                moved = math.hypot(displacement.x, displacement.z)
                alignment = ((displacement.x * expected_x + displacement.z * expected_z) / moved
                             if moved > 1e-6 else None)
                eye_follow_error = ((after_pose.eye - after) - eye_relative).length()
                target_follow_error = ((after_pose.target - after) - target_relative).length()
                check('one short native Up walk follows rendered horizontal bearing',
                      moved > .02 and alignment is not None and alignment > .95,
                      duration_s=.23, keyboard_y=1, expected_xz=(expected_x, expected_z),
                      displacement_xz=(displacement.x, displacement.z), moved=moved, alignment=alignment,
                      caveat='A wall/route/turning constraint is a failed measurement, not proof of a camera defect')
                check('guest follows actor while host camera publication is frozen',
                      moved > .02 and eye_follow_error < .025 and target_follow_error < .025
                      and heartbeat_after != heartbeat_before and publication_after == publication_before,
                      before=before.as_tuple(), after=after.as_tuple(), eye_error=eye_follow_error,
                      target_error=target_follow_error, heartbeat=(heartbeat_before, heartbeat_after),
                      publication_before=publication_before, publication_after=publication_after)
                heading_changed = angle_error(after_heading, before_heading)
                check('actor heading changes independently while rendered compass yaw stays held',
                      heading_changed > .5 and angle_error(after_compass, before_compass) < .1,
                      heading_before=before_heading, heading_after=after_heading,
                      heading_change=heading_changed, camera_before=before_compass, camera_after=after_compass,
                      caveat='An unchanged actor heading does not demonstrate this independence condition')
                shot('walk')

            if handshake:
                set_pose(150, 22, 10)
                window.chk_fov.setChecked(True)
                window.sl_fov.spin.setValue(40)
                spin(.6)
                handshake.mkdir(parents=True, exist_ok=True)
                payload = dict(serial=mm.GAME_ID, crc=mm.DISC_CRC, yaw=150, pitch=22,
                               distance=10, fov=40,
                               instruction='Externally load a protected same-edition stock state, resume VM, then create continue.txt')
                (handshake / 'ready.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
                print('READY for external stock state load/resume: ' + str(handshake), flush=True)
                deadline = time.monotonic() + 180
                while not (handshake / 'continue.txt').exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError('Stock reload handshake expired')
                    spin(.1)
                    require_same_game()
                spin(2)
                pose, actual_yaw, actual_pitch, compass_yaw = yaw_state()
                check('stock reload automatically reapplies every hook Orbit FOV and compass',
                      all_hooks(True) and angle_error(actual_yaw, 150) < .1
                      and abs(actual_pitch - 22) < .1 and abs(pose.distance() - 10) < .015
                      and abs(adapter.read_fov_deg() - 40) < .05
                      and angle_error(compass_yaw, actual_yaw) < .1 and not runtime.stats.last_error,
                      yaw=actual_yaw, pitch=actual_pitch, distance=pose.distance(),
                      compass_yaw=compass_yaw, fov=adapter.read_fov_deg(),
                      hooks=hook_words(), error=runtime.stats.last_error)
                shot('stock_reload_reapplied')

            require_same_game()
            window.btn_restore.click()
            spin(.8)
            native_pose = adapter._native_pose()
            pose = adapter.read_game_pose()
            actual_fov, native_fov = adapter.read_fov_deg(), adapter.capture_original_fov()
            native_yaw = math.degrees(native_pose.yaw_pitch()[0])
            compass_yaw = math.degrees(backend.read_f32(mm.CAM_YAW))
            check('Original restores every hook native camera lens and compass',
                  runtime.settings.mode == MODE_ORIGINAL and all_hooks(False)
                  and backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
                  and (pose.eye - native_pose.eye).length() < .02
                  and (pose.target - native_pose.target).length() < .02
                  and abs(actual_fov - native_fov) < .05
                  and angle_error(compass_yaw, native_yaw) < .1 and not runtime.stats.last_error,
                  hooks=hook_words(), actual_fov=actual_fov, native_fov=native_fov,
                  native_yaw=native_yaw, compass_yaw=compass_yaw, error=runtime.stats.last_error)
            shot('restored')
            if not window.grab().save(str(out / 'gui.png')):
                raise RuntimeError('Could not save GUI screenshot')
            screenshots.append('gui.png')
            completed = True
        except Exception as exc:
            check('live check aborted', False, error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        finally:
            # Each cleanup stage is independent so an input or capture failure
            # cannot skip the guarded camera teardown or the report write.
            try:
                reset_input()
            except Exception as exc:
                check('input reset cleanup', False, error=str(exc))
            try:
                if same_game():
                    runtime.freeze(False)
                    runtime.stop()
                    runtime.restore()
                    spin(.15)
                    check('finally restores all owned hooks and flags',
                          all_hooks(False) and backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0,
                          hooks=hook_words(), error=runtime.stats.last_error)
                elif guard is not None:
                    check('cleanup skips old-game writes after identity loss', True,
                          scope='No restore attempted; MainWindow teardown abandons the runtime')
            except Exception as exc:
                check('guarded restore cleanup', False, error=f'{type(exc).__name__}: {exc}')
            try:
                if window is not None:
                    window.close()
                    spin(.2)
            except Exception as exc:
                check('GUI teardown cleanup', False, error=str(exc))
            finally:
                if old_appdata is None:
                    os.environ.pop('APPDATA', None)
                else:
                    os.environ['APPDATA'] = old_appdata
                report = dict(game='MINSTRELSONG', serial=mm.GAME_ID, crc=mm.DISC_CRC,
                              completed=completed, move_requested=args.move,
                              reload_requested=handshake is not None,
                              passed=completed and all(item['passed'] for item in results),
                              scope='Limited ordinary field GUI/guest readbacks; screenshots require visual review; no menu coverage',
                              screenshots=screenshots, checks=results)
                (out / 'checks.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if completed and all(item['passed'] for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
