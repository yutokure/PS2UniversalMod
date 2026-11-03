"""Measure camera-relative movement in an already-running verified field.

One PINE client only. Load a protected stock state before each case externally;
this tool never loads/saves states or touches memory cards. Use isolated test
cards because gameplay itself can autosave. It sends short real keyboard input,
compares the player displacement with the *actual* eye-target horizontal bearing,
and restores all owned patches/input in finally. A blocked tile is a failed
measurement, not proof that the movement conversion is wrong.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapters.nightmaredruaga.adapter import DruagaAdapter
from adapters.radiatastories.adapter import RadiataStoriesAdapter
from core.camera_math.orbit import Vec3
from core.memory_backend.guard import GuardedBackend
from core.memory_backend.pine_backend import PineBackend
import pcsx2_input as pin


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', choices=('druaga', 'radiata'), required=True)
    ap.add_argument('--yaw', type=float, required=True)
    ap.add_argument('--direction', choices=('up', 'down', 'left', 'right'), default='up')
    ap.add_argument('--duration', type=float, default=.2)
    ap.add_argument('--position-offset', nargs=3, type=float, default=(0, 0, 0))
    ap.add_argument('--target-offset', nargs=3, type=float, default=(0, 0, 0))
    ap.add_argument('--stock', action='store_true', help='Measure native controls without enabling Orbit')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if not .05 <= args.duration <= .6:
        ap.error('duration must be 0.05..0.6 seconds (short protected movement only)')
    raw = PineBackend()
    guard = GuardedBackend(raw)
    adapter = (DruagaAdapter if args.game == 'druaga' else RadiataStoriesAdapter)(guard)
    report = dict(game=args.game, yaw=args.yaw, direction=args.direction, stock=args.stock)
    hwnd = None
    bound = False
    try:
        identity = adapter.identify()
        if not identity.matched:
            raise RuntimeError(identity.reason)
        guard.bind(identity.game_id, identity.crc)
        bound = True
        scene = adapter.read_scene()
        if not adapter.is_field_like(scene):
            raise RuntimeError(scene.reason)
        hwnd = pin.render_child()
        pin._KB.reset(hwnd)
        dungeon = args.game == 'druaga' and adapter._dungeon(*adapter._camera())
        if not args.stock:
            adapter.set_patch(True)
            adapter.set_stick_block(True)
            adapter.write_orbit_params(scene.player, args.yaw,
                                       -35 if args.game == 'druaga' else 20,
                                       16 if args.game == 'druaga' else 1500,
                                       pos_offset=Vec3(*args.position_offset),
                                       target_offset=Vec3(*args.target_offset))
            time.sleep(.25)
        before = adapter.read_player()
        pose = adapter.read_game_pose()
        fx, fz = pose.target.x-pose.eye.x, pose.target.z-pose.eye.z
        length = math.hypot(fx, fz)
        if length < 1e-6:
            raise RuntimeError('vertical/degenerate actual camera bearing')
        fx, fz = fx/length, fz/length
        # Both verified engines use (Fz, -Fx) for horizontal screen right.
        rx, rz = fz, -fx
        ex, ez = {'up': (fx, fz), 'down': (-fx, -fz),
                  'right': (rx, rz), 'left': (-rx, -rz)}[args.direction]
        if dungeon:
            # Native tile movement has eight legal bearings, not an analog continuum.
            # Match the native +22.5-degree half-open sector boundaries.
            angle = math.floor((math.atan2(ex, ez)+math.pi/8)/(math.pi/4))*(math.pi/4)
            ex, ez = math.sin(angle), math.cos(angle)
            pin.hold({args.direction: True}, hwnd)
        else:
            # BackgroundKeyboard uses positive Y for the Up binding.
            x, y = {'up': (0, 1), 'down': (0, -1),
                    'left': (-1, 0), 'right': (1, 0)}[args.direction]
            pin._KB.set_analog(hwnd, x, y, 'left', pin.CONFIG)
        try:
            time.sleep(args.duration)
        finally:
            pin._KB.reset(hwnd)
        time.sleep(.4 if dungeon else .15)
        after = adapter.read_player()
        dx, dz = after.x-before.x, after.z-before.z
        moved = math.hypot(dx, dz)
        alignment = (dx*ex+dz*ez)/moved if moved > 1e-6 else None
        relative_error = ((adapter.read_game_pose().eye-after)-(pose.eye-before)).length()
        report.update(identity=identity.__dict__, dungeon=bool(dungeon),
                      before=before.as_tuple(), after=after.as_tuple(),
                      eye=pose.eye.as_tuple(), target=pose.target.as_tuple(),
                      expected_xz=(ex, ez), displacement_xz=(dx, dz),
                      moved=moved, alignment=alignment, relative_eye_error=relative_error,
                      passed=moved > .02 and alignment is not None and alignment > .95)
    finally:
        try:
            if hwnd is not None:
                pin._KB.reset(hwnd)
            # Never restore through a stale or different-game lease.
            if bound and guard.verify() == 'same':
                adapter.set_stick_block(False)
                adapter.set_patch(False)
                adapter.restore_fov()
                if args.game == 'druaga':
                    from adapters.nightmaredruaga import caves
                    report['restored'] = (caves.site_state(guard) == 'stock'
                                          and caves.movement_state(guard) == 'stock')
                else:
                    from adapters.radiatastories import caves
                    report['restored'] = caves.site_state(guard) == 'stock'
        finally:
            raw.close()
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report.get('passed') and report.get('restored') else 1


if __name__ == '__main__':
    raise SystemExit(main())
