"""Radiata Stories live GUI/runtime checks; only use a verified running field.

One PINE client. Uses temporary settings, writes evidence outside the repository,
releases injected controls and restores native camera hooks in finally. Does not
load/save states, write cards or navigate scenes. --move performs a short left
stick input; gameplay itself can autosave. Back up cards before live experiments.
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
from adapters.radiatastories.adapter import RadiataStoriesAdapter
from adapters.radiatastories import caves, memory_map as mm
from core.camera_math.orbit import Vec3, orbit_pose
from gui.camera_controller.app import MainWindow
import pcsx2_input as pin
from pcsx2_mcp.window_capture import capture_window


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--move',action='store_true')
    ap.add_argument('--reload-handshake',type=Path)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if args.reload_handshake and args.reload_handshake.exists() and any(args.reload_handshake.iterdir()):
        raise SystemExit('Use a new/empty reload handshake directory')
    app=QApplication([]);results=[]
    def spin(sec):
        end=time.monotonic()+sec
        while time.monotonic()<end:app.processEvents();time.sleep(.005)
    def check(name,ok,**data):
        results.append(dict(name=name,passed=bool(ok),**data))
        print(('PASS ' if ok else 'FAIL ')+name+' '+json.dumps(data),flush=True)
    def shot(name):
        path=args.out/(name+'.png')
        capture_window(pin.render_child(),path);spin(.1);capture_window(pin.render_child(),path)
    def stick(x=0,y=0,which='left'):
        pin._KB.set_analog(pin.render_child(),x,y,which,pin.CONFIG)
    with tempfile.TemporaryDirectory(prefix='radiata-live-') as home:
        old=os.environ.get('APPDATA');os.environ['APPDATA']=home
        w=MainWindow()
        try:
            w.show();spin(.7)
            check('exact edition identified with guarded writes',isinstance(w.adapter,RadiataStoriesAdapter)
                  and w.guard.writes_allowed and 'AC73005E' in w.lbl_serial.text().upper())
            if not isinstance(w.adapter,RadiataStoriesAdapter):raise RuntimeError('not a supported Radiata field')
            a,b=w.adapter,w.backend
            w.grp_offsets.setChecked(True);w.cmb_input.setCurrentText('scripted')
            check('Original startup and supported GUI features',w.rb_original.isChecked() and not w.rb_free.isEnabled()
                  and all(x.isEnabled() for x in w.off),mode=w.runtime.settings.mode)
            stock=a.read_scene();check('verified field accepted',stock.valid,reason=stock.reason)
            if not stock.valid:raise RuntimeError(stock.reason)
            shot('stock')
            w.btn_enable.click();spin(.7)
            check('enable centres without runtime error',a.patch_active() and not w.runtime.stats.last_error,
                  error=w.runtime.stats.last_error)
            for yaw,pitch,d in ((140,20,1500),(-140,35,1800),(180,75,1000),(175,15,1500)):
                w.sl_yaw.spin.setValue(yaw);w.sl_pitch.spin.setValue(pitch);w.sl_dist.spin.setValue(d)
                spin(.5);p=a.read_game_pose();y,pt=map(math.degrees,p.yaw_pitch())
                check(f'orbit {yaw}/{pitch}/{d}',abs((y-yaw+180)%360-180)<.05 and abs(pt-pitch)<.05 and abs(p.distance()-d)<.01,
                      yaw=y,pitch=pt,distance=p.distance(),error=w.runtime.stats.last_error)
                shot(f'orbit_{yaw}_{pitch}')
            w.sl_yaw.spin.setValue(170);w.sl_pitch.spin.setValue(25);w.sl_dist.spin.setValue(1500)
            w.sl_look.spin.setValue(-80)
            for control,value in zip(w.off,(30,-20,15,-25,10,20)):control.spin.setValue(value)
            spin(.5);p=a.read_game_pose();player=a.read_player()
            wanted=orbit_pose(player+Vec3(-25,-70,20),math.radians(170),math.radians(25),1500)
            check('six independent offsets reach real render matrix',(p.target-wanted.target).length()<.01
                  and (p.eye-wanted.eye-Vec3(30,-20,15)).length()<.01,
                  eye=p.eye.as_tuple(),target=p.target.as_tuple(),player=player.as_tuple())
            shot('offsets')
            for control in w.off:control.spin.setValue(0)
            w.sl_look.spin.setValue(-90);spin(.3)
            for deg in (25,40,65):
                w.chk_fov.setChecked(True);w.sl_fov.spin.setValue(deg);spin(.6)
                check(f'FOV {deg} reaches actual projection',abs(a.read_fov_deg()-deg)<.03,
                      measured=a.read_fov_deg(),native=a.capture_original_fov())
                shot(f'fov{deg}')
            w.chk_fov.setChecked(False);spin(.6)
            check('FOV release keeps Orbit and restores native lens',a.patch_active() and abs(a.read_fov_deg()-a.capture_original_fov())<.03)
            yaw0=w.runtime.settings.yaw_deg
            # Same source-pump integration used by the GUI's physical right stick.
            w.scripted.set(.7,.2);spin(.3);w.scripted.set(0,0);spin(.3)
            p=a.read_game_pose();y,pt=map(math.degrees,p.yaw_pitch())
            check('right-axis input changes held Orbit',abs(w.runtime.settings.yaw_deg-yaw0)>1
                  and abs((y-w.runtime.settings.yaw_deg+180)%360-180)<.1,
                  before=yaw0,after=w.runtime.settings.yaw_deg,actual=y)
            # Guest keeps following when host parameters are no longer republished.
            if args.move:
                before=a.read_player();rel=a.read_game_pose().eye-before
                stick(.5,0);spin(.28);stick();spin(.4)
                after=a.read_player();newrel=a.read_game_pose().eye-after
                check('native walk and guest per-frame actor follow',(after-before).length()>1 and (newrel-rel).length()<.05,
                      before=before.as_tuple(),after=after.as_tuple(),relative_error=(newrel-rel).length())
                shot('walk')
            if args.reload_handshake:
                w.chk_fov.setChecked(True);w.sl_fov.spin.setValue(40)
                w.sl_yaw.spin.setValue(150);w.sl_pitch.spin.setValue(25);w.sl_dist.spin.setValue(1500);spin(.4)
                d=args.reload_handshake;d.mkdir(parents=True,exist_ok=True)
                (d/'ready.json').write_text(json.dumps(dict(yaw=150,pitch=25,distance=1500,fov=40)))
                print('READY for stock savestate reload',flush=True)
                deadline=time.monotonic()+180
                while not (d/'continue.txt').exists() and time.monotonic()<deadline:spin(.1)
                if not (d/'continue.txt').exists():raise TimeoutError('reload handshake expired')
                spin(2);p=a.read_game_pose();y,pt=map(math.degrees,p.yaw_pitch())
                check('stock reload automatically reapplies Orbit and FOV',abs(y-150)<.05 and abs(pt-25)<.05
                      and abs(p.distance()-1500)<.01 and abs(a.read_fov_deg()-40)<.03,
                      yaw=y,pitch=pt,distance=p.distance(),fov=a.read_fov_deg(),error=w.runtime.stats.last_error)
            w.btn_restore.click();spin(.7)
            cam,target=a._camera();p=a.read_game_pose();native=a._native_pose(cam,target)
            check('Original restores all hooks and live native camera/lens',caves.site_state(b)=='stock'
                  and (p.eye-native.eye).length()<.01 and abs(a.read_fov_deg()-a.capture_original_fov())<.03,
                  state=caves.site_state(b),fov=a.read_fov_deg(),error=w.runtime.stats.last_error)
            check('no pending render transaction',b.read_u32(mm.MOD_BLOCK+mm.MB_PENDING)==0)
            shot('restored');w.grab().save(str(args.out/'gui.png'))
        finally:
            stick();stick(0,0,'right')
            w.close();spin(.2)
            if old is None:os.environ.pop('APPDATA',None)
            else:os.environ['APPDATA']=old
            (args.out/'checks.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1

if __name__=='__main__':raise SystemExit(main())
