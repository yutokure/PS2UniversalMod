"""Live Exa GUI checks with isolated settings and optional stock-state reload.

Run with PCSX2 already in an Exa field, and no other PINE client. Evidence
(including screenshots) goes outside Git. --reload-handshake DIR lets a separate
MCP client load a stock state while this GUI stays alive: wait for ready.json,
load the state/resume the VM, then create continue.txt in that directory.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication
from adapters.shiningforceexa.adapter import SFExaAdapter
from adapters.shiningforceexa import memory_map as mm
from gui.camera_controller.app import MainWindow
import pcsx2_input as pin
from pcsx2_mcp.window_capture import capture_window


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--reload-handshake', type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.reload_handshake and args.reload_handshake.exists():
        if any(args.reload_handshake.iterdir()):
            raise SystemExit('use an empty/new reload-handshake directory')
    results = []
    def check(name, ok, **data):
        results.append(dict(name=name, passed=bool(ok), **data))
        print(('PASS ' if ok else 'FAIL ') + name + ' ' + json.dumps(data), flush=True)
    app = QApplication([])
    def spin(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(.01)
    def stick(x=0, y=0, which='right'):
        pin._KB.set_analog(pin.render_child(), x, y, which, pin.CONFIG)
    def shot(name):
        # Two captures avoid a stale covered-window frame (known lab limitation).
        path = args.out / (name + '.png')
        capture_window(pin.render_child(), path)
        spin(.1)
        capture_window(pin.render_child(), path)
    with tempfile.TemporaryDirectory(prefix='sfexa-gui-') as isolated:
        old_appdata = os.environ.get('APPDATA')
        os.environ['APPDATA'] = isolated
        win = MainWindow()
        try:
            win.show()
            spin(.6)
            check('GUI identifies Exa with guarded backend', isinstance(win.adapter, SFExaAdapter)
                  and win.guard.writes_allowed and '8B383FDF' in win.lbl_serial.text().upper())
            if not isinstance(win.adapter, SFExaAdapter):
                raise RuntimeError('Exa not connected')
            ad, b = win.adapter, win.backend
            check('unsupported Free and offsets disabled', not win.rb_free.isEnabled()
                  and all(not w.isEnabled() for w in win.off))
            win.cmb_input.setCurrentText('scripted')
            original_fov = ad.read_fov_deg()
            win.btn_enable.click()
            spin(.7)
            check('GUI enable uses native centring', ad.patch_active() and not win.runtime.stats.last_error,
                  error=win.runtime.stats.last_error)
            win.sl_yaw.spin.setValue(180)
            win.sl_pitch.spin.setValue(30)
            win.sl_dist.spin.setValue(1200)
            win.sl_look.spin.setValue(50)
            spin(.6)
            p = ad.read_game_pose()
            yaw, pitch = map(math.degrees, p.yaw_pitch())
            check('GUI controls reach native camera fields', abs(abs(yaw) - 180) < .05
                  and abs(pitch + 30) < .05 and abs(p.distance() - 1200) < .2
                  and abs(ad.read_height() - 300) < .01, yaw=yaw, pitch=pitch, distance=p.distance())
            shot('yaw180')
            win.sl_yaw.spin.setValue(90)
            spin(.5)
            shot('yaw90')
            # Real emulator pad input: raw right deflects, processed right stays centred.
            stick(1, 0)
            spin(.3)
            raw = b.read_u32(mm.PAD_RX_SOURCES[0])
            proc = b.read_u32(mm.PAD_PROCESSED)
            check('right stick masking retains raw input', raw & 255 > 240 and proc & 65535 == 0x7f7f,
                  raw=hex(raw), processed=hex(proc))
            shot('masked_right')
            stick()
            # Left input remains available, including a short real walk.
            before = ad.read_player()
            stick(.7, 0, 'left')
            spin(.3)
            proc = b.read_u32(mm.PAD_PROCESSED)
            stick(0, 0, 'left')
            spin(.3)
            after = ad.read_player()
            check('left stick survives and character moves', (proc >> 16) & 255 != 127
                  and (after - before).length() > 5, processed=hex(proc), before=before.as_tuple(), after=after.as_tuple())
            win.chk_fov.setChecked(True)
            win.sl_fov.spin.setValue(80)
            spin(.8)
            check('GUI FOV changes actual projection', abs(ad.read_fov_deg() - 80) < .06,
                  measured=ad.read_fov_deg())
            shot('fov80')
            win.sl_pitch.spin.setValue(89.5)
            spin(.5)
            measured = math.degrees(ad.read_game_pose().yaw_pitch()[1])
            check('GUI overhead limit', abs(measured + 89.5) < .03, measured=measured)
            shot('overhead')
            win.sl_pitch.spin.setValue(30)
            spin(.4)
            if args.reload_handshake:
                d = args.reload_handshake
                d.mkdir(parents=True, exist_ok=True)
                (d / 'ready.json').write_text(json.dumps(dict(yaw=90, pitch=-30, distance=1200, fov=80)))
                print('READY for external stock-state reload', flush=True)
                deadline = time.monotonic() + 90
                while not (d / 'continue.txt').exists() and time.monotonic() < deadline:
                    spin(.1)
                if not (d / 'continue.txt').exists():
                    raise TimeoutError('stock-state reload handshake timed out')
                spin(1.8)
                y, p = map(math.degrees, ad.read_game_pose().yaw_pitch())
                check('stock state reload reapplies control and pad patch', abs(y - 90) < .06
                      and abs(p + 30) < .06 and abs(ad.read_fov_deg() - 80) < .06
                      and b.read_u32(mm.PAD_RX_LOAD) == mm.PAD_NEUTRAL_WORD
                      and b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_NEUTRAL_WORD,
                      yaw=y, pitch=p, fov=ad.read_fov_deg(), error=win.runtime.stats.last_error)
            win.btn_restore.click()
            spin(.8)
            stick(1, 0)
            spin(.3)
            proc = b.read_u32(mm.PAD_PROCESSED)
            check('Original returns right stick and both instructions', proc & 255 > 240
                  and b.read_u32(mm.PAD_RX_LOAD) == mm.PAD_RX_WORD
                  and b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_RY_WORD, processed=hex(proc))
            stick()
            check('Original returns projection and smoothing', ad.patch_state() == 'stock'
                  and abs(ad.read_fov_deg() - original_fov) < .1, fov=ad.read_fov_deg(), gate=ad.patch_state())
            win.grab().save(str(args.out / 'gui.png'))
        finally:
            try:
                stick()
                stick(0, 0, 'left')
            except Exception as exc:
                print(f'input cleanup: {exc}', file=sys.stderr)
            win.close()
            spin(.2)
            if old_appdata is None:
                os.environ.pop('APPDATA', None)
            else:
                os.environ['APPDATA'] = old_appdata
            (args.out / 'gui_checks.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
