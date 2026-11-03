"""Druaga GUI/runtime integration checks against an already running field.

No second PINE client may run concurrently. Uses isolated settings, restores the
native camera and releases injected input in finally. Evidence is outside Git.
Optional --reload-handshake DIR waits for a stock savestate reload by the existing
MCP connection, then checks automatic reapplication. Does not write card files
itself; gameplay may autosave, so use backed-up/isolated test cards.
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

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication
from adapters.nightmaredruaga.adapter import DruagaAdapter
from adapters.nightmaredruaga import caves, memory_map as mm
from gui.camera_controller.app import MainWindow
from core.camera_math.orbit import Vec3
import pcsx2_input as pin
from pcsx2_mcp.window_capture import capture_window


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--reload-handshake',type=Path)
    ap.add_argument('--dungeon-direction',choices=('up','down','left','right'),default='left',
                    help='Choose a passable Dungeon D-pad neighbor; tool does not navigate maps')
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    if args.reload_handshake and args.reload_handshake.exists() and any(args.reload_handshake.iterdir()):
        raise SystemExit('Use a new/empty handshake directory')
    results=[]; app=QApplication([])
    def spin(sec):
        end=time.monotonic()+sec
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    def check(name,ok,**data):
        results.append(dict(name=name,passed=bool(ok),**data))
        print(('PASS ' if ok else 'FAIL ')+name+' '+json.dumps(data),flush=True)
    def stick(x=0,y=0,which='right'):
        pin._KB.set_analog(pin.render_child(),x,y,which,pin.CONFIG)
    def shot(name):
        path=args.out/(name+'.png')
        capture_window(pin.render_child(),path); spin(.1); capture_window(pin.render_child(),path)
    with tempfile.TemporaryDirectory(prefix='druaga-gui-') as home:
        old=os.environ.get('APPDATA'); os.environ['APPDATA']=home
        w=MainWindow()
        try:
            w.show(); spin(.7)
            check('GUI identifies exact edition with guard',isinstance(w.adapter,DruagaAdapter)
                  and w.guard.writes_allowed and 'B476ED7A' in w.lbl_serial.text().upper())
            if not isinstance(w.adapter,DruagaAdapter): raise RuntimeError('Druaga not connected')
            a,b=w.adapter,w.backend
            w.grp_offsets.setChecked(True)
            check('starts Original and independent offsets enabled',w.rb_original.isChecked()
                  and not w.rb_free.isEnabled() and all(x.isEnabled() for x in w.off),
                  mode=w.runtime.settings.mode,offsets=[x.isEnabled() for x in w.off])
            w.cmb_input.setCurrentText('scripted')
            stock=a.read_scene()
            shot('stock')
            w.btn_enable.click(); spin(.8)
            check('GUI enable safely centres camera',a.patch_active() and not w.runtime.stats.last_error,
                  error=w.runtime.stats.last_error)
            for yaw,pitch,d in ((90,35,22),(-90,55,16),(0,89.5,24),(170,-10,20)):
                w.sl_yaw.spin.setValue(yaw);w.sl_pitch.spin.setValue(pitch);w.sl_dist.spin.setValue(d)
                spin(.45);p=a.read_game_pose();y,pt=map(math.degrees,p.yaw_pitch())
                check(f'orbit yaw{yaw} pitch{pitch} distance{d}',abs((y-yaw+180)%360-180)<.03
                      and abs(pt+pitch)<.03 and abs(p.distance()-d)<.002,
                      yaw=y,pitch=pt,distance=p.distance(),error=w.runtime.stats.last_error)
                shot(f'orbit_{yaw}_{pitch}')
            # Independent eye and target offsets: changing eye must not translate target.
            w.sl_yaw.spin.setValue(90);w.sl_pitch.spin.setValue(35);w.sl_dist.spin.setValue(22)
            w.sl_look.spin.setValue(1.5)
            w.off[0].spin.setValue(2);w.off[1].spin.setValue(1);w.off[2].spin.setValue(-1)
            w.off[3].spin.setValue(-1);w.off[4].spin.setValue(.5);w.off[5].spin.setValue(1)
            spin(.6);p=a.read_game_pose();player=a.read_player()
            from core.camera_math.orbit import orbit_pose
            wanted=orbit_pose(player+Vec3(-1,2,1),math.radians(90),math.radians(-35),22)
            check('six offsets and look height reach actual matrix',
                  (p.target-wanted.target).length()<.001 and (p.eye-(wanted.eye+Vec3(2,1,-1))).length()<.001,
                  eye=p.eye.as_tuple(),target=p.target.as_tuple(),player=player.as_tuple())
            shot('offsets')
            for sl in w.off:sl.spin.setValue(0)
            w.sl_look.spin.setValue(0);spin(.3)
            for deg in (40,60,90):
                w.chk_fov.setChecked(True);w.sl_fov.spin.setValue(deg);spin(.65)
                check(f'FOV {deg} changes rendered projection',abs(a.read_fov_deg()-deg)<.03,measured=a.read_fov_deg())
                shot(f'fov{deg}')
            # Movement must follow every guest frame even with fixed host parameters.
            before=a.read_player();delta_before=a.read_game_pose().eye-before
            dungeon=a._dungeon(*a._camera())
            # Dungeon uses D-pad for tile movement; its left analog operates the
            # item shortcut UI. Do not call that native control scheme a MOD fault.
            if dungeon:
                pin.hold({args.dungeon_direction:True})
                try:spin(.4)
                finally:pin.hold({args.dungeon_direction:False})
            else:
                stick(1,0,'left');spin(.4);stick(0,0,'left')
            spin(.4)
            after=a.read_player();delta_after=a.read_game_pose().eye-after
            check('native movement retained and Orbit follows actor', (after-before).length()>.05
                  and (delta_after-delta_before).length()<.002,
                  before=before.as_tuple(),after=after.as_tuple(),relative_error=(delta_after-delta_before).length())
            shot('walk')
            stick(1,0);spin(.25)
            raw=b.read_u32(mm.PAD_RAW_AXES);processed=b.read_u32(mm.PAD_RIGHT_X)
            check('right action blocked without destroying raw input',raw&255>240 and processed==0
                  and caves.read_words(b,mm.PAD_AXIS_HOOK,2)==caves.PAD_HOOK
                  and all(b.read_u32(addr)==neutral for (addr,_),neutral in zip(mm.PAD_ACTION_LOADS,mm.PAD_NEUTRAL_WORDS)),
                  raw=hex(raw),processed=hex(processed))
            stick();spin(.2)
            # Feed the selected source (the 120 Hz pump owns runtime.set_stick).
            w.scripted.set(.7,.3);spin(.25);w.scripted.set(0,0);spin(.3)
            check('runtime right-axis rotates camera',abs(w.runtime.settings.yaw_deg-90)>1,
                  yaw=w.runtime.settings.yaw_deg)
            w.sl_yaw.spin.setValue(90);w.sl_pitch.spin.setValue(35);w.sl_dist.spin.setValue(22)
            if args.reload_handshake:
                d=args.reload_handshake;d.mkdir(parents=True,exist_ok=True)
                (d/'ready.json').write_text(json.dumps(dict(yaw=90,pitch=-35,distance=22,fov=90)))
                print('READY for stock state reload',flush=True)
                deadline=time.monotonic()+180
                while not (d/'continue.txt').exists() and time.monotonic()<deadline:spin(.1)
                if not (d/'continue.txt').exists():raise TimeoutError('reload handshake expired')
                spin(2.0);p=a.read_game_pose();y,pt=map(math.degrees,p.yaw_pitch())
                check('stock state reload automatically reapplies camera movement FOV and pad',
                      abs(y-90)<.03 and abs(pt+35)<.03 and abs(p.distance()-22)<.002
                      and caves.movement_state(b)=='applied'
                      and abs(a.read_fov_deg()-90)<.03
                      and caves.read_words(b,mm.PAD_AXIS_HOOK,2)==caves.PAD_HOOK
                  and all(b.read_u32(addr)==neutral for (addr,_),neutral in zip(mm.PAD_ACTION_LOADS,mm.PAD_NEUTRAL_WORDS)),
                      yaw=y,pitch=pt,distance=p.distance(),fov=a.read_fov_deg(),error=w.runtime.stats.last_error)
            w.btn_restore.click();spin(.8)
            p=a.read_game_pose();cam=a._camera()[1]
            native_eye=Vec3(*b.read_floats(cam+(0x250 if a._dungeon(*a._camera()) else mm.CAM_NATIVE_EYE),3))
            native_fov=a.capture_original_fov()  # reload may select a different class/scene
            check('Original restores native matrix FOV and every instruction',
                  caves.site_state(b)=='stock' and caves.movement_state(b)=='stock'
                   and (p.eye-native_eye).length()<.001
                  and abs(a.read_fov_deg()-native_fov)<.03
                  and caves.read_words(b,mm.PAD_AXIS_HOOK,2)==mm.PAD_AXIS_STOCK
                   and all(b.read_u32(addr)==word for addr,word in mm.PAD_ACTION_LOADS),
                  fov=a.read_fov_deg(),error=w.runtime.stats.last_error)
            shot('restored');w.grab().save(str(args.out/'gui.png'))
        finally:
            try:stick();stick(0,0,'left')
            finally:
                w.close();spin(.2)
                if old is None:os.environ.pop('APPDATA',None)
                else:os.environ['APPDATA']=old
                (args.out/'checks.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return 0 if all(x['passed'] for x in results) else 1

if __name__=='__main__':raise SystemExit(main())
