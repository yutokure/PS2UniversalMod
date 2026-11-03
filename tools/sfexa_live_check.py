"""Exercise the Exa adapter on the already running verified Japanese field.

No ISO/state/card is written. Close the GUI first (one PINE client). Numeric
report only; screenshots and state loads are separate MCP/manual operations.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.shiningforceexa.adapter import SFExaAdapter
from adapters.shiningforceexa import memory_map as mm
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
from core.memory_backend.guard import GuardedBackend
from core.memory_backend.pine_backend import PineBackend


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--hold', type=float, default=0, help='seconds to hold final 90-degree view for external screenshots')
    args = ap.parse_args()
    raw = PineBackend()
    raw.connect()
    b = GuardedBackend(raw)
    ad = SFExaAdapter(b)
    info = ad.identify()
    if not info.matched:
        raw.close()
        raise SystemExit(info.reason)
    b.bind(info.game_id, info.crc)
    scene = ad.read_scene()
    if not ad.is_field_like(scene):
        raw.close()
        raise SystemExit('not the verified Exa field camera')
    report = dict(identity=info.__dict__, checks=[])

    def check(name, ok, **data):
        report['checks'].append(dict(name=name, passed=bool(ok), **data))
        print(('PASS ' if ok else 'FAIL ') + name + ' ' + json.dumps(data), flush=True)

    def pose():
        p = ad.read_game_pose()
        y, t = p.yaw_pitch()
        return dict(yaw=math.degrees(y), pitch=math.degrees(t), distance=p.distance(),
                    eye=p.eye.as_tuple(), target=p.target.as_tuple(), player=ad.read_player().as_tuple(),
                    height=ad.read_height(), fov=ad.read_fov_deg())

    rt = None
    stock = pose()
    stock_half = b.read_u32(mm.CAM_FOV_WORD) >> 16
    stock_params = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_DISTANCE, mm.CAM_HEIGHT)}
    try:
        ad.set_patch(True)
        ad.set_stick_block(True)
        ad.write_orbit_params(scene.player, 90, -30, 1200, look_height=50)
        time.sleep(.8)
        p = pose()
        check('native orbit controls', abs(p['yaw'] - 90) < .1 and abs(p['pitch'] + 30) < .1
              and abs(p['distance'] - 1200) < .2 and abs(p['height'] - 300) < .01, **p)
        for hfov in (40, 60, 90):
            ad.write_fov_deg(hfov)
            time.sleep(.4)
            check('rendered projection FOV', abs(ad.read_fov_deg() - hfov) < .06,
                  requested=hfov, measured=ad.read_fov_deg())
        ad.restore_fov()
        time.sleep(.3)
        check('FOV returns without releasing Orbit', abs(ad.read_fov_deg() - stock['fov']) < .06
              and ad.patch_active(), measured=ad.read_fov_deg(), stock=stock['fov'])
        # Run the actual shared runtime and input integrator, not only adapter calls.
        ad.set_stick_block(False)
        ad.set_patch(False)
        time.sleep(.4)
        settings = CameraSettings(**ad.default_settings())
        rt = CameraRuntime(ad, settings)
        rt.sync_to_game()
        rt.settings.mode = MODE_ORBIT
        rt.start()
        time.sleep(.5)
        before = pose()
        rt.set_stick(.7, .4)
        time.sleep(.8)
        rt.set_stick(0, 0)
        time.sleep(.3)
        after = pose()
        turned = abs((after['yaw'] - before['yaw'] + 180) % 360 - 180)
        check('runtime right-stick integration', turned > 20 and after['pitch'] < before['pitch']
              and not rt.stats.last_error, before=before, after=after, error=rt.stats.last_error)
        rt.settings.use_fov = True
        rt.settings.fov_deg = 70
        time.sleep(.8)
        check('runtime FOV reaches projection', abs(ad.read_fov_deg() - 70) < .06,
              measured=ad.read_fov_deg(), error=rt.stats.last_error)
        rt.settings.yaw_deg, rt.settings.pitch_deg = 90, -30
        rt.settings.distance, rt.settings.look_height = 1200, 50
        time.sleep(.4)
        print('HOLD final orbit', flush=True)
        if args.hold:
            time.sleep(args.hold)
    finally:
        if rt:
            rt.stop()
            rt.restore()
        else:
            ad.set_stick_block(False)
            ad.set_patch(False)
            ad.restore_fov()
        time.sleep(.4)
        check('Original restores both input instructions', b.read_u32(mm.PAD_RX_LOAD) == mm.PAD_RX_WORD
              and b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_RY_WORD)
        check('Original releases smoothing and FOV', ad.patch_state() == 'stock'
              and abs(ad.read_fov_deg() - stock['fov']) < .2,
              gate=ad.patch_state(), measured=ad.read_fov_deg(), stock=stock['fov'])
        report['after'] = pose()
        report['stock'] = stock
        report['stock_fov_halfword'] = stock_half
        report['stock_params'] = {hex(a): w for a, w in stock_params.items()}
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
        raw.close()
    return 0 if all(c['passed'] for c in report['checks']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
