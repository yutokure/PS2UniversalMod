"""DQ5 GUI/runtime validation on an already-running protected ordinary field.

One guarded PINE client owned by MainWindow; no GDB, game boot, savestate or
memory-card edits. Use isolated cards and protect the starting state first.
Evidence must be outside the repository. --move checks four short camera-relative direction pairs (use an open area).
--reload-handshake waits for an external stock-state load and resume.
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
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tools'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase,QFont
from adapters.dragonquest5.adapter import DragonQuest5Adapter
from adapters.dragonquest5 import memory_map as mm,caves
from core.camera_math.orbit import Vec3,orbit_pose
from core.memory_backend.guard import SAME
from gui.camera_controller.app import MainWindow,MODE_ORIGINAL
import pcsx2_input as pin
from pcsx2_mcp.window_capture import capture_window


def evidence_directory(value):
    path = value.resolve()
    if path==ROOT or path.is_relative_to(ROOT): raise ValueError('Evidence must be outside the repository')
    if path.exists() and (not path.is_dir() or any(path.iterdir())): raise ValueError(f'Use a new/empty directory: {path}')
    return path


def angle_error(a,b): return abs((a-b+180)%360-180)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--move',action='store_true')
    parser.add_argument('--reload-handshake',type=Path)
    args=parser.parse_args()
    try:
        out=evidence_directory(args.out)
        handshake=evidence_directory(args.reload_handshake) if args.reload_handshake else None
        if handshake==out: raise ValueError('Use distinct evidence and handshake directories')
    except ValueError as exc: parser.error(str(exc))
    out.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    # Offscreen Qt may have no platform fonts. Load an existing system font only.
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'meiryo.ttc'
    if font.exists():
        QFontDatabase.addApplicationFont(str(font));app.setFont(QFont('Meiryo',9))
    checks=[];window=adapter=runtime=backend=guard=hwnd=None;completed=False
    old_appdata=os.environ.get('APPDATA')
    def spin(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end: app.processEvents();time.sleep(.005)
    def check(name,passed,**data):
        checks.append(dict(name=name,passed=bool(passed),**data))
        print(('PASS ' if passed else 'FAIL ')+name+' '+json.dumps(data),flush=True)
    def same():
        return window is not None and window.adapter is adapter and window.guard is guard and guard is not None and guard.verify()==SAME
    def require_same():
        if not same(): raise RuntimeError('Identity/connection changed; no old-game restoration')
    def words(address,count): return [backend.read_u32(address+i*4) for i in range(count)]
    def hooks(on):return all(tuple(words(a,2))==(hook if on else stock) for a,stock,hook,_,_ in caves.RESOURCES)
    def shot(name):
        require_same();capture_window(hwnd,out/(name+'.png'));spin(.1);capture_window(hwnd,out/(name+'.png'))
    def reset():
        if window is not None and window.scripted is not None:window.scripted.set(0,0)
        if hwnd is not None:pin._KB.reset(hwnd)
    def stick(x,y,which):require_same();pin._KB.set_analog(hwnd,x,y,which,pin.CONFIG)
    def pose(yaw,pitch,distance):
        require_same();window.sl_yaw.spin.setValue(yaw);window.sl_pitch.spin.setValue(pitch);window.sl_dist.spin.setValue(distance);spin(.65)
    def sample():
        p=adapter.read_game_pose();y,pitch=p.yaw_pitch()
        return p,math.degrees(y),-math.degrees(pitch)
    with tempfile.TemporaryDirectory(prefix='dq5-live-') as home:
        os.environ['APPDATA']=home
        try:
            window=MainWindow();window.show();spin(.8)
            if not isinstance(window.adapter,DragonQuest5Adapter):raise RuntimeError('Requires Japanese SLPM-65555/B64E9939')
            adapter,guard,runtime=window.adapter,window.guard,window.runtime;backend=adapter.backend
            require_same();hwnd=pin.render_child();reset();window.cmb_input.setCurrentText('scripted')
            window.grp_offsets.setChecked(True)
            check('Original startup, exact guarded identity and GUI features',runtime.settings.mode==MODE_ORIGINAL and guard.expected==(mm.GAME_ID,mm.DISC_CRC) and hooks(False) and not window.rb_free.isEnabled() and window.rb_orbit.isEnabled() and window.chk_fov.isEnabled() and all(c.isEnabled() for c in window.off),mode=runtime.settings.mode,identity=guard.expected,stock_hooks=hooks(False),offsets_enabled=[c.isEnabled() for c in window.off])
            scene=adapter.read_scene()
            if not scene.valid:raise RuntimeError(scene.reason)
            native_yaw=backend.read_u32(mm.CAM_YAW);native_lens=backend.read_u32(mm.CAM_FOV)
            native_eye=backend.read_floats(mm.CAM_EYE,3);native_target=backend.read_floats(mm.CAM_TARGET,3)
            shot('stock');window.btn_enable.click();spin(.9)
            check('GUI enable installs render input and movement hooks',adapter.patch_active() and hooks(True) and not runtime.stats.last_error,error=runtime.stats.last_error)
            for yaw,pitch,distance in [(-147.73,25,150),(-57.73,55,180),(40,89.5,150),(40,-25,130)]:
                pose(yaw,pitch,distance);p,y,pi=sample()
                check(f'Orbit {yaw}/{pitch}/{distance}',angle_error(y,yaw)<.1 and abs(pi-pitch)<.1 and abs(p.distance()-distance)<.02 and not runtime.stats.last_error,yaw=y,pitch=pi,distance=p.distance(),error=runtime.stats.last_error)
                shot(f'orbit_{yaw}_{pitch}')
            pose(-57.73,45,157)
            window.sl_look.spin.setValue(12)
            offsets=(2,-1,3,-2,1,-3)
            window.grp_offsets.setChecked(True)
            for c,v in zip(window.off,offsets):c.spin.setValue(v)
            spin(.7);p=adapter.read_game_pose();player=adapter.read_player()
            expected=orbit_pose(player+Vec3(-2,13,-3),math.radians(runtime.settings.yaw_deg),math.radians(runtime.settings.pitch_deg),runtime.settings.distance)
            e=(p.eye-expected.eye-Vec3(2,-1,3)).length();t=(p.target-expected.target).length()
            check('six independent offsets and Y-up height',e<.02 and t<.02,eye_error=e,target_error=t)
            for c in window.off:c.spin.setValue(0)
            window.sl_look.spin.setValue(10)
            for fov in [30,55,80]:
                window.chk_fov.setChecked(True);window.sl_fov.spin.setValue(fov);spin(.75)
                check(f'FOV {fov} actual projection with native lens retained',abs(adapter.read_fov_deg()-fov)<.05 and backend.read_u32(mm.CAM_FOV)==native_lens,actual=adapter.read_fov_deg())
                shot(f'fov{fov}')
            window.chk_fov.setChecked(False);spin(.6)
            check('FOV release keeps Orbit and restores native projection',adapter.patch_active() and abs(adapter.read_fov_deg()-adapter.capture_original_fov())<.05,actual=adapter.read_fov_deg())
            pose(-57.73,45,157);before=runtime.settings.yaw_deg
            window.scripted.set(.7,.5);spin(.3);window.scripted.set(0,0);spin(.4)
            p,y,pi=sample();held=runtime.settings.yaw_deg;held_pitch=-runtime.settings.pitch_deg;spin(.35);_,y2,pi2=sample()
            check('right input integrates yaw and pitch then holds',angle_error(before,held)>1 and angle_error(y,held)<.15 and abs(pi-held_pitch)<.15 and angle_error(y2,y)<.1 and abs(pi2-pi)<.1,before=before,yaw=y,pitch=pi)
            pose(-57.73,45,157)
            pad=backend.read_u32(mm.PAD_PROCESSED_PTR)
            yaw0=backend.read_u32(mm.CAM_YAW)
            try:
                stick(1,0,'right');spin(.3)
                received=backend.read_u32(pad+mm.PAD_RIGHT_X) if pad else 0
                yaw1=backend.read_u32(mm.CAM_YAW)
            finally:reset()
            spin(.25)
            check('real game right RX is received but native yaw is suppressed',received!=0 and yaw1==yaw0 and hooks(True),processed_rx=received,native_yaw_before=yaw0,native_yaw_after=yaw1)
            check('native rig eye target yaw and lens remain unchanged',backend.read_floats(mm.CAM_EYE,3)==native_eye and backend.read_floats(mm.CAM_TARGET,3)==native_target and backend.read_u32(mm.CAM_YAW)==native_yaw and backend.read_u32(mm.CAM_FOV)==native_lens)
            if args.move:
                # Opposite pairs limit drift; terrain collision can still invalidate
                # a direction measurement. Do not equate blocked displacement to
                # the velocity/facing consumer test or claim all scenes are covered.
                for yaw in (0,90,180,-90):
                    pose(yaw,45,157)
                    for label,x,y in (('forward',0,1),('back',0,-1)):
                        runtime.freeze(True);spin(.1)
                        try:
                            before=adapter.read_player();p0=adapter.read_game_pose();h0=adapter.heartbeat_word()
                            stamp0=[backend.read_u32(mm.MOD_BLOCK+off) for off in (mm.MB_SLOT,mm.SLOTS[0],mm.SLOTS[1])]
                            forward=p0.target-p0.eye;norm=math.hypot(forward.x,forward.z)
                            fx,fz=forward.x/norm,forward.z/norm
                            expected=(x*fz+y*fx,-x*fx+y*fz)
                            try:
                                stick(x,y,'left');spin(.2)
                                actor=backend.read_u32(mm.PLAYER_PTR)
                                velocity=backend.read_floats(actor+0x110,3)
                                heading=backend.read_f32(mm.PLAYER_MANAGER+0x6EAC)
                            finally:reset()
                            spin(.3);after=adapter.read_player();p1=adapter.read_game_pose()
                            delta=after-before;move=math.hypot(delta.x,delta.z)
                            error=((p1.target-after)-(p0.target-before)).length()
                            dot=(delta.x*expected[0]+delta.z*expected[1])/move if move>.05 else -1
                            speed=math.hypot(velocity[0],velocity[2])
                            vdot=(velocity[0]*expected[0]+velocity[2]*expected[1])/speed if speed>.05 else -1
                            hdot=-math.sin(heading)*expected[0]-math.cos(heading)*expected[1]
                            stamp1=[backend.read_u32(mm.MOD_BLOCK+off) for off in (mm.MB_SLOT,mm.SLOTS[0],mm.SLOTS[1])]
                            check(f'Orbit-relative {yaw} {label}, native velocity/facing and guest follow',dot>.98 and vdot>.999 and hdot>.999 and error<.05 and stamp0==stamp1 and adapter.heartbeat_word()>h0,movement=move,direction_dot=dot,velocity_dot=vdot,heading_dot=hdot,relative_target_error=error)
                        finally:runtime.freeze(False)
            if handshake:
                pose(40,65,170);window.chk_fov.setChecked(True);window.sl_fov.spin.setValue(55);spin(.7)
                handshake.mkdir(parents=True,exist_ok=True)
                (handshake/'ready.json').write_text(json.dumps(dict(serial=mm.GAME_ID,crc=mm.DISC_CRC,yaw=40,pitch=65,distance=170,fov=55)))
                print('READY for external stock state load/resume: '+str(handshake),flush=True)
                end=time.monotonic()+180
                while not (handshake/'continue.txt').exists():
                    if time.monotonic()>end:raise TimeoutError('Stock reload handshake expired')
                    spin(.1);require_same()
                spin(2);p,y,pi=sample()
                check('stock state reload automatically reapplies cached Orbit and FOV',hooks(True) and angle_error(y,40)<.1 and abs(pi-65)<.1 and abs(p.distance()-170)<.02 and abs(adapter.read_fov_deg()-55)<.05 and not runtime.stats.last_error,yaw=y,pitch=pi,fov=adapter.read_fov_deg(),error=runtime.stats.last_error)
                shot('reload_reapplied')
            window.btn_restore.click();spin(.8)
            check('Original restores all hooks input and native camera projection',runtime.settings.mode==MODE_ORIGINAL and hooks(False) and backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)==0 and abs(adapter.read_fov_deg()-adapter.capture_original_fov())<.05,error=runtime.stats.last_error)
            yaw0=backend.read_u32(mm.CAM_YAW)
            try:stick(1,0,'right');spin(.3)
            finally:reset()
            spin(.25)
            check('native right-stick horizontal camera works again after restore',backend.read_u32(mm.CAM_YAW)!=yaw0,before=yaw0,after=backend.read_u32(mm.CAM_YAW))
            shot('restored');window.grab().save(str(out/'gui.png'));completed=True
        except Exception as exc:
            check('live check aborted',False,error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
        finally:
            try:reset()
            except Exception as exc:check('input cleanup',False,error=str(exc))
            try:
                if same():
                    runtime.freeze(False);runtime.stop();runtime.restore();spin(.1)
                    check('guarded final cleanup',hooks(False) and backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)==0)
            except Exception as exc:check('restore cleanup',False,error=str(exc))
            try:
                if window is not None:window.close();spin(.2)
            finally:
                if old_appdata is None:os.environ.pop('APPDATA',None)
                else:os.environ['APPDATA']=old_appdata
                (out/'checks.json').write_text(json.dumps(dict(game='DRAGONQUEST5',completed=completed,passed=completed and all(c['passed'] for c in checks),checks=checks,scope='Limited ordinary field; no menu/battle/long-run guarantee'),indent=2),encoding='utf-8')
    return 0 if completed and all(c['passed'] for c in checks) else 1


if __name__=='__main__':raise SystemExit(main())
