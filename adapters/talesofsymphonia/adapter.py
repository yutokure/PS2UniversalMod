"""Ordinary town/dungeon and walking world-map Orbit for Japanese Symphonia.

Native Z-up is translated at this adapter boundary only. All runtime/GUI vectors
use X,-Z,Y (Y-down); injected native copies use X,Y,Z. Original rigs are untouched.
"""
from __future__ import annotations
import math
import threading
import time
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm, caves


def canonical(v): return Vec3(v.x,-v.z,v.y)
def native(v): return Vec3(v.x,v.z,-v.y)

class TalesOfSymphoniaAdapter:
    name='TALESOFSYMPHONIA'
    display_name='Tales of Symphonia'
    display_name_key='game.talesofsymphonia'
    uses_offset_injection=False
    accepts_orbit_offsets=True
    PITCH_DISPLAY_SIGN=PITCH_INPUT_SIGN=1.0
    PITCH_POSITIVE_IS='above'
    LOOK_HEIGHT_POSITIVE_IS='down'
    PITCH_RANGE=(-25.0,89.5)
    DISTANCE_RANGE=(50.0,6000.0)
    LOOK_HEIGHT_RANGE=(-1000.0,1000.0)
    OFFSET_RANGE=(-3000.0,3000.0)
    FOV_RANGE=(20.0,110.0)
    field_projection_centre=0.0
    patch_recheck_s=1.0
    CAM_EYE_ADDR=CAM_EYE_BASE_ADDR=mm.CAM_EYE
    CAM_TARGET_ADDR=mm.TOWN_TARGET

    def __init__(self,backend):
        self.backend=backend
        self.info=AdapterInfo()
        self.features=dict(orbit=True,free_camera=False,fov=True,position_offsets=True,
                           target_offsets=True,per_frame_write=False)
        self._lock=threading.RLock()
        self._orbit=False
        self._fov=None
        self._relative=None
        self._prepared_backend=None
        self._prepared_epoch=None
        self._audit_at=0.0

    def identify(self):
        try:
            gid,crc,title=(self.backend.game_id().strip(),self.backend.crc().strip(),self.backend.title().strip())
            matched=(gid.upper(),crc.upper())==(mm.GAME_ID,mm.DISC_CRC)
            self.info=AdapterInfo(gid,crc,title,matched,'' if matched else f'expected {mm.GAME_ID}/{mm.DISC_CRC}')
        except Exception as exc: self.info=AdapterInfo(reason=f'PINE error: {exc}')
        return self.info

    def _byte(self,address): return self.backend.read_u32(address)&255
    @staticmethod
    def _valid(v): return all(math.isfinite(x) and abs(x)<200000 for x in v.as_tuple())

    def _scene(self):
        b=self.backend; mode=b.read_u32(mm.MODE)
        if b.read_u32(mm.SUBMODE)!=0: raise caves.PatchConflict('Symphonia menu/event camera is suspended')
        if mode==mm.TOWN_MODE:
            if self._byte(mm.TOWN_SCRIPT_CAMERA) or self._byte(mm.TOWN_ALT_CAMERA) or b.read_u32(mm.TOWN_ACTOR)!=0x13BA20:
                raise caves.PatchConflict('Symphonia scripted/non-player town camera is unavailable')
            player=mm.TOWN_PLAYER
        elif mode==mm.WORLD_MODE:
            root=b.read_u32(mm.WORLD_ROOT)
            if root&15 or not 0x100000<=root<0x1600000:
                raise caves.PatchConflict('invalid Symphonia world owner')
            if b.read_u32(root)!=1 or b.read_u32(root+mm.WORLD_FLAGS)&mm.WORLD_REJECT_MASK or any(self._byte(root+off) for off in mm.WORLD_BUSY_BYTES):
                raise caves.PatchConflict('Symphonia special world/vehicle camera is unavailable')
            player=root+mm.WORLD_POSITION
        else: raise caves.PatchConflict('Symphonia ordinary town/world scene is unavailable')
        pos=canonical(Vec3(*b.read_floats(player,3)))
        if not self._valid(pos): raise caves.PatchConflict('invalid Symphonia player position')
        return mode,player,pos

    def read_player(self):
        with self._lock: return self._scene()[2]

    def _native_pose(self):
        mode,_,player=self._scene(); b=self.backend
        if mode==mm.TOWN_MODE:
            eye=canonical(Vec3(*b.read_floats(mm.TOWN_EYE,3)))
            target=canonical(Vec3(*b.read_floats(mm.TOWN_TARGET,3)))
        elif b.read_u32(mm.MOD_BLOCK)==mm.MAGIC and b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED)==mode:
            eye=canonical(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_NATIVE_EYE,3)))
            target=canonical(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_NATIVE_TARGET,3)))
        else:
            world=b.read_floats(mm.CAMERA_WORLD,16)
            eye=canonical(Vec3(*world[12:15]))
            backward=canonical(Vec3(*world[8:11]))
            target=eye-backward.scaled((eye-player).length())
        pose=CameraPose(eye,target)
        if not self._valid(eye) or not self._valid(target) or not 1<pose.distance()<30000:
            raise caves.PatchConflict('invalid Symphonia camera geometry')
        return pose

    def read_game_pose(self):
        with self._lock:
            mode,_,_=self._scene(); b=self.backend
            if b.read_u32(mm.MOD_BLOCK)==mm.MAGIC and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&1 and b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED)==mode:
                return CameraPose(canonical(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_EYE,3))),
                                  canonical(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_TARGET,3))))
            return self._native_pose()

    def read_scene(self):
        with self._lock:
            try:
                _,_,player=self._scene(); pose=self.read_game_pose(); fov=self.read_fov_deg()
                valid=self._valid(pose.eye) and self._valid(pose.target) and 1<pose.distance()<30000 and 1<fov<179
                return SceneState(player,pose,fov,pose.distance(),valid,'' if valid else 'invalid Symphonia rendered camera')
            except caves.PatchConflict as exc:
                return SceneState(Vec3(0,0,0),CameraPose(Vec3(0,0,0),Vec3(0,0,1)),0,0,False,str(exc))
    def is_field_like(self,scene): return scene.valid

    @staticmethod
    def _degrees(sx): return math.degrees(2*math.atan(1/sx)) if math.isfinite(sx) and sx>0 else 0.0
    def _stock_sx(self):
        b=self.backend
        if b.read_u32(mm.MODE)==mm.WORLD_MODE:
            units=mm.WORLD_VFOV_UNITS[bool(b.read_u32(mm.WORLD_MAP_ID)&65535)]
            return 1/(math.tan(units*math.pi/65536)*mm.WORLD_ASPECT)
        # Ordinary town lens is the selected rig's vertical degree parameter.
        index=self._byte(mm.TOWN_CAMERA_INDEX)
        if index>=8: raise caves.PatchConflict('invalid Symphonia town lens owner')
        vertical=b.read_f32(mm.TOWN_CAMERA_BASE+index*0x94+0x58)
        if not math.isfinite(vertical) or not 1<vertical<170:
            raise caves.PatchConflict('invalid Symphonia native town lens')
        # Native builder truncates half the 16-bit-turn angle before sin/cos.
        half_units=int(vertical*65536/360)//2
        return 1/(math.tan(half_units*2*math.pi/65536)*(4/3))
    def read_fov_scale(self):
        return (1/math.tan(math.radians(self.read_fov_deg())/2))*FOV_SCALE_REF
    def read_fov_deg(self):
        # The shared global projection is reset for HUD late in a world frame.
        # Diagnostics are from the real accepted 3D arguments, never HUD mirrors.
        b=self.backend
        if b.read_u32(mm.MOD_BLOCK)==mm.MAGIC and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&1:
            sx=b.read_f32(mm.MOD_BLOCK+mm.MB_RENDER_LENS)
            if math.isfinite(sx) and sx>0: return self._degrees(sx)
        return self._degrees(self._stock_sx())
    def capture_original_fov(self):
        return self._degrees(self._stock_sx())

    def _inspection(self,force=False):
        b=self.backend; epoch=getattr(b,'epoch',None)
        cached=self._prepared_backend is b and self._prepared_epoch==epoch
        try:
            if cached and not force and time.monotonic()<self._audit_at and caves.ready(b):
                return caves.Inspection('applied',(),False)
            self._prepared_backend=None
            p=caves.preflight(b)
            self._prepared_backend=b; self._prepared_epoch=epoch; self._audit_at=time.monotonic()+1.0
            return p
        except Exception:
            self._prepared_backend=None
            raise

    def _publish(self,*,audit=False):
        mode,player,anchor=self._scene()
        relative=self._relative
        if relative is None:
            p=self._native_pose(); relative=CameraPose(p.eye-anchor,p.target-anchor)
        eye,target=native(relative.eye),native(relative.target); forward=target-eye
        if not self._valid(eye) or not self._valid(target) or math.hypot(forward.x,forward.y)<1e-5 or not 1<forward.length()<30000:
            raise ValueError('invalid/singular Symphonia Orbit geometry')
        yaw=math.atan2(forward.x,forward.y)%(2*math.pi)
        flags=mm.FLAG_ORBIT | (mm.FLAG_FOV if self._fov is not None else 0)
        b=self.backend; p=self._inspection(force=audit); p=caves.prepare(b,p)
        slot=(b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1; address=mm.MOD_BLOCK+mm.SLOTS[slot]
        seq=(b.read_u32(address)+2)&0xFFFFFFFE
        b.write_u32(address,seq|1)
        b.write_u32(address+mm.SLOT_FLAGS,flags); b.write_u32(address+mm.SLOT_MODE,mode); b.write_u32(address+mm.SLOT_PLAYER,player)
        b.write_float_block(address+mm.SLOT_EYE,(*eye.as_tuple(),1))
        b.write_float_block(address+mm.SLOT_TARGET,(*target.as_tuple(),1))
        b.write_float_block(address+mm.SLOT_FORWARD,(forward.x,forward.y,yaw,1/math.tan(math.radians(self._fov)/2) if self._fov is not None else 0))
        b.write_u32(address,seq); b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT,slot)
        caves.sync(b,flags,p)

    def write_orbit_params(self,centre,yaw_deg,pitch_deg,distance,*,pos_offset=None,target_offset=None):
        with self._lock:
            pos=pos_offset or Vec3(0,0,0)
            target=target_offset if target_offset is not None else centre-self.read_player()
            if not all(math.isfinite(x) for x in (*centre.as_tuple(),*pos.as_tuple(),*target.as_tuple(),yaw_deg,pitch_deg,distance)):
                raise ValueError('non-finite Symphonia Orbit parameter')
            pitch=max(self.PITCH_RANGE[0],min(self.PITCH_RANGE[1],pitch_deg))
            distance=max(self.DISTANCE_RANGE[0],min(self.DISTANCE_RANGE[1],distance))
            pose=orbit_pose(target,math.radians(yaw_deg),math.radians(pitch),distance)
            self._relative=CameraPose(pose.eye+pos,pose.target); self._orbit=True; self._publish()

    def set_patch(self,on):
        with self._lock:
            if on:
                self._orbit=True; self._publish(audit=True)
            else:
                self._prepared_backend=None
                self._orbit=False; caves.sync(self.backend,0)
    def patch_state(self):
        with self._lock:
            state=caves.site_state(self.backend)
            if state!='applied': return state
            return 'applied' if self.backend.read_u32(mm.MOD_BLOCK)==mm.MAGIC and self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&1 else 'stock'
    def patch_active(self): return self.patch_state()=='applied'
    hook_active=patch_active
    def copy_stock_params(self):
        # Scene rejection must drop accepted consumers while keeping lifecycle
        # available. Never publish a new camera into an unsupported scene.
        with self._lock:
            try: self._scene()
            except caves.PatchConflict:
                p=caves.preflight(self.backend)
                if not p.init: self.backend.write_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED,0)
    def write_fov_deg(self,deg):
        if not math.isfinite(deg): raise ValueError('non-finite Symphonia FOV')
        with self._lock:
            self._fov=max(self.FOV_RANGE[0],min(self.FOV_RANGE[1],deg))
            if self._orbit: self._publish()
    def restore_fov(self):
        with self._lock:
            self._fov=None
            if self._orbit: self._publish()
    def fov_in_sync(self,deg):
        with self._lock:
            return self._orbit and self._fov is not None and abs(self._fov-deg)<.01 and self.patch_active() and abs(self.read_fov_deg()-deg)<.08
    def center_on_target(self,distance,look_height):
        with self._lock:
            pose=self._native_pose(); y,p=pose.yaw_pitch(); aim=self.read_player()+Vec3(0,look_height,0)
            self.write_orbit_params(aim,math.degrees(y),math.degrees(p),distance,target_offset=Vec3(0,look_height,0))
            return orbit_pose(aim,y,p,distance)
    def default_settings(self):
        return dict(distance=1800.0,look_height=-87.0,pitch_deg=35.0,yaw_deg=180.0,fov_deg=45.0)
    def default_look_height(self): return -87.0
    def read_aim(self): return self.read_game_pose().target
    def read_eye_base(self): return self._native_pose().eye
    def read_camera_forward(self):
        p=self.read_game_pose(); v=p.target-p.eye; return v.scaled(1/v.length())
    def place_looking_at(self,target,distance): return target-self.read_camera_forward().scaled(distance)
    def write_pose(self,pose):
        y,p=pose.yaw_pitch(); self.write_orbit_params(pose.target,math.degrees(y),math.degrees(p),pose.distance())
    def heartbeat_addr(self): return mm.MOD_BLOCK+mm.MB_HEARTBEAT
    def heartbeat_word(self): return self.backend.read_u32(self.heartbeat_addr())
    def read_projection(self): return FOV_SCALE_REF,0.0
    def write_projection_centre(self,centre): pass
    def write_projection_scale(self,scale): pass
    def set_projection_source(self,redirected): pass
    def write_eye_offset(self,offset): pass
    def clear_eye_offset(self): pass
    def write_aim(self,target): pass
    def restore_aim(self): pass
    def write_walk_target(self,centre): pass
    def set_stick_block(self,on): pass  # Dedicated field RX call is scoped by guest guards.
