"""Japanese Magna Carta: field Orbit/FOV and independent gameplay switches."""
from __future__ import annotations
import math
import threading
import time
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from . import memory_map as mm, caves

class MagnaCartaAdapter:
    name = 'MAGNACARTA'
    display_name = 'Magna Carta'
    display_name_key = 'game.magnacarta'
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_RANGE = (-25.0, 89.5)
    DISTANCE_RANGE = (150.0, 6000.0)
    LOOK_HEIGHT_RANGE = (-500.0, 500.0)
    OFFSET_RANGE = (-2000.0, 2000.0)
    FOV_RANGE = (20.0, 110.0)
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = 1.0
    PITCH_POSITIVE_IS = 'above'
    LOOK_HEIGHT_POSITIVE_IS = 'down'
    field_projection_centre = 0.0
    patch_recheck_s = 1.0
    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAMERA_EYE
    CAM_TARGET_ADDR = mm.MOD_BLOCK + mm.MB_RENDER_TARGET

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True,
                             per_frame_write=False, wide_view_running=True,
                             no_encounters=True)
        self._lock = threading.RLock()
        self._orbit = self._wide = self._no_encounters = False
        self._relative = orbit_pose(Vec3(0,-100,0),0,math.radians(15),1500)
        self._fov = None
        self._audit_at = 0.0
        self._epoch = None

    def identify(self):
        try:
            gid=self.backend.game_id().strip(); crc=self.backend.crc().strip()
            title=self.backend.title().strip()
            matched=(gid.upper(),crc.upper())==(mm.GAME_ID,mm.DISC_CRC)
            self.info=AdapterInfo(gid,crc,title,matched,'' if matched else f'expected {mm.GAME_ID}/{mm.DISC_CRC}')
        except Exception as exc:
            self.info=AdapterInfo(reason=f'PINE error: {exc}')
        return self.info

    @staticmethod
    def _ptr(value): return 0x100000 <= value < 0x1FFF000 and value % 16 == 0
    @staticmethod
    def _valid(v): return all(math.isfinite(x) and abs(x)<1000000 for x in v.as_tuple())
    @staticmethod
    def _canonical(values): return Vec3(values[0],-values[2],values[1])
    @staticmethod
    def _native(v): return (v.x,v.z,-v.y)

    def _field_view(self):
        b=self.backend
        def ptr(address):
            value=b.read_u32(address)
            if not self._ptr(value): raise caves.PatchConflict('Magna Carta field/script object unavailable')
            return value
        # The last pawn alias can belong to an AI. Resolve the local PC from
        # the registered manager's current world, without pinning a heap address.
        owner=ptr(mm.FIELD_OWNER_GLOBAL); magi=ptr(owner+mm.OWNER_MAGI)
        if b.read_u32(magi+mm.MAGI_OWNER)!=owner:
            raise caves.PatchConflict('Magna Carta field/script ownership mismatch')
        state=ptr(owner+mm.STATE_POINTER); mode=(b.read_u32(state+0x90)>>8)&255
        script=ptr(ptr(magi+0x0C)+0x18)
        if (mode,b.read_u32(script+0x20)) not in mm.FIELD_SCENES:
            raise caves.PatchConflict('Magna Carta active script/mode is not a supported field')
        level=ptr(magi+mm.ACTOR_LEVEL); game=ptr(level+mm.LEVEL_GAME)
        pc=ptr(game+mm.GAME_LOCAL_PC); viewport=ptr(pc+mm.PC_PLAYER); actor=ptr(pc+mm.PC_PAWN)
        if (b.read_u32(viewport+mm.VIEWPORT_ACTOR)!=pc or b.read_u32(actor+mm.PLAYER_CONTROLLER)!=pc
                or b.read_u32(actor+mm.PLAYER_MAGI)!=magi):
            raise caves.PatchConflict('Magna Carta local player/script ownership mismatch')
        player=self._canonical(b.read_floats(actor+mm.PLAYER_POSITION,3))
        if not self._valid(player): raise caves.PatchConflict('invalid Magna Carta player position')
        return actor,player,pc

    def _field(self): return self._field_view()[:2]

    def read_player(self):
        with self._lock: return self._field()[1]

    def _native_pose(self,player=None):
        b=self.backend
        eye=self._canonical(b.read_floats(mm.CAMERA_EYE,3))
        # In native view matrix, column2 = forward (X,Y,Z), Z-up. This
        # diagnostic reconstructs a target without touching the game camera.
        matrix=b.read_floats(mm.VIEW_MATRIX,16)
        forward=Vec3(matrix[2],-matrix[10],matrix[6])
        if player is None: player=self._field()[1]
        distance=max(1,(player-eye).length())
        if not self._valid(eye) or not self._valid(forward): raise caves.PatchConflict('invalid Magna Carta camera')
        return CameraPose(eye,eye+forward.scaled(distance))

    def _accepted(self,actor):
        b=self.backend
        return (b.read_u32(mm.MOD_BLOCK)==mm.MAGIC and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT
                and b.read_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED)==actor)

    def _pose(self,player,accepted):
        b=self.backend
        if accepted:
            return CameraPose(self._canonical(b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_EYE,3)),
                              self._canonical(b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_TARGET,3)))
        return self._native_pose(player)

    def read_game_pose(self):
        with self._lock:
            actor,player=self._field()
            return self._pose(player,self._accepted(actor))

    def read_scene(self):
        with self._lock:
            try:
                actor,player,pc=self._field_view(); accepted=self._accepted(actor)
                pose=self._pose(player,accepted)
                valid=self._valid(pose.eye) and self._valid(pose.target) and 1<pose.distance()<20000
                return SceneState(player,pose,self._fov_value(pc,accepted),pose.distance(),valid,'' if valid else 'invalid Magna Carta camera geometry')
            except caves.PatchConflict as exc:
                return SceneState(Vec3(0,0,0),CameraPose(Vec3(0,0,0),Vec3(0,0,1)),0,0,False,str(exc))
    def is_field_like(self,scene): return scene.valid
    def heartbeat_addr(self): return mm.MOD_BLOCK+mm.MB_HEARTBEAT
    def _flags(self):
        return (1 if self._orbit else 0)|(2 if self._orbit and self._fov is not None else 0)|(4 if self._wide else 0)|(8 if self._no_encounters else 0)

    def _inspect(self,full=False):
        epoch=getattr(self.backend,'epoch',None)
        now=time.monotonic()
        if full or epoch!=self._epoch or now>=self._audit_at or not caves.ready(self.backend):
            p=caves.preflight(self.backend); self._epoch=epoch; self._audit_at=now+1.0; return p
        return None

    @staticmethod
    def _rotation(relative):
        forward=relative.target-relative.eye
        horizontal=math.hypot(forward.x,forward.z)
        if not all(math.isfinite(x) for x in (*relative.eye.as_tuple(),*relative.target.as_tuple())) or horizontal<1e-4:
            raise ValueError('invalid/singular Magna Carta Orbit view')
        # Native Unreal rotator: yaw about Z, zero +X, pitch positive up.
        yaw=round(math.atan2(forward.z,forward.x)*65536/(2*math.pi)) & 65535
        pitch=round(math.atan2(-forward.y,horizontal)*65536/(2*math.pi)) & 65535
        return pitch,yaw

    @staticmethod
    def _movement_yaw(yaw):
        # Native sin/cos uses a 4-turn-unit lookup; ProcessAnalog then derives
        # heading with acos(-y/length). Near exact axes, rounding can exceed its
        # domain and produce a huge heading/no movement. Keep only that consumer
        # at least 8 turn units (0.044 degrees) from a quadrant boundary.
        phase = yaw & 0x3FFF
        if phase < 8:
            return (yaw + 8 - phase) & 0xFFFF
        if phase > 0x4000 - 8:
            return yaw - (phase - (0x4000 - 8))
        return yaw

    def _publish(self,p=None):
        b=self.backend; actor,_=self._field(); pitch,yaw=self._rotation(self._relative)
        if p is not None: caves.prepare(b,p)
        slot=(b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1
        address=mm.MOD_BLOCK+mm.SLOTS[slot]
        seq=(b.read_u32(address)+2)&0xFFFFFFFE
        b.write_u32(address,seq|1)
        b.write_u32(address+mm.SLOT_FLAGS,self._flags()); b.write_u32(address+mm.SLOT_PLAYER,actor)
        b.write_float_block(address+mm.SLOT_EYE,(*self._native(self._relative.eye),0))
        b.write_float_block(address+mm.SLOT_TARGET,(*self._native(self._relative.target),0))
        b.write_u32(address+mm.SLOT_PITCH,pitch); b.write_u32(address+mm.SLOT_ROT_YAW,yaw)
        # ProcessAnalog's pad-up direction uses the actual view forward yaw.
        # An extra half-turn here reverses every movement direction, not rendering.
        b.write_u32(address+mm.SLOT_YAW,self._movement_yaw(yaw)); b.write_float_block(address+mm.SLOT_FOV,(self._fov or 55.0,))
        b.write_u32(address,seq); b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT,slot)

    def _sync(self,*,publish=False,full=False):
        p=self._inspect(full)
        if publish and self._orbit:
            self._publish(p)
            # Prepared resources no longer empty. Don't re-prepare reachable cave.
            if p: p=caves.Inspection((),False,p.state)
        flags=self._flags()
        if p is not None or self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)!=flags:
            caves.sync(self.backend,flags,p)

    def write_orbit_params(self,centre,yaw_deg,pitch_deg,distance,*,pos_offset=None,target_offset=None):
        with self._lock:
            self._field()
            vals=(*centre.as_tuple(),yaw_deg,pitch_deg,distance)
            if not all(math.isfinite(x) for x in vals): raise ValueError('nonfinite Magna Carta Orbit parameters')
            target=target_offset if target_offset is not None else centre-self.read_player()
            pos=pos_offset if pos_offset is not None else Vec3(0,0,0)
            pose=orbit_pose(target,math.radians(yaw_deg),math.radians(max(-25,min(89.5,pitch_deg))),max(150,min(6000,distance)))
            relative=CameraPose(pose.eye+pos,pose.target); self._rotation(relative)
            self._relative=relative; self._orbit=True; self._sync(publish=True)

    def set_patch(self,on):
        with self._lock:
            if on: self._field()
            self._orbit=bool(on); self._sync(publish=bool(on),full=True)
    def patch_state(self):
        with self._lock:
            state=caves.site_state(self.backend)
            if state=='unknown': return state
            return 'applied' if state=='applied' and self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&1 else 'stock'
    def patch_active(self): return self.patch_state()=='applied'
    hook_active=patch_active
    def set_wide_view_running(self,on):
        with self._lock:
            self._wide=bool(on); self._sync(full=True)
    def set_no_encounters(self,on):
        with self._lock:
            self._no_encounters=bool(on); self._sync(full=True)
    def _toggle_active(self,flag):
        return caves.ready(self.backend) and bool(self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&flag)
    def wide_view_running(self):
        with self._lock: return self._toggle_active(mm.FLAG_WIDE)
    def no_encounters(self):
        with self._lock: return self._toggle_active(mm.FLAG_NO_ENCOUNTERS)

    def _fov_value(self,pc,accepted):
        if accepted:
            fov=self.backend.read_f32(mm.MOD_BLOCK+mm.MB_RENDER_FOV)
            if math.isfinite(fov) and 5<fov<170: return fov
        fov=self.backend.read_f32(pc+0x1F4)
        return fov if math.isfinite(fov) and 5<fov<170 else 55.0
    def read_fov_deg(self):
        with self._lock:
            try: actor,_,pc=self._field_view()
            except caves.PatchConflict: return 55.0
            return self._fov_value(pc,self._accepted(actor))
    def read_fov_scale(self): return 320.0/math.tan(math.radians(self.read_fov_deg())/2)
    def capture_original_fov(self):
        with self._lock:
            try: _,_,pc=self._field_view()
            except caves.PatchConflict: return 55.0
            return self._fov_value(pc,False)
    def write_fov_deg(self,deg):
        with self._lock:
            if not math.isfinite(deg): raise ValueError('nonfinite Magna Carta FOV')
            self._fov=max(20,min(110,deg))
            if self._orbit: self._sync(publish=True)
    def restore_fov(self):
        with self._lock:
            self._fov=None
            if self._orbit: self._sync(publish=True)
    def fov_in_sync(self,deg): return abs(self.read_fov_deg()-max(20,min(110,deg)))<.1
    def restore(self):
        """Camera only; runtime independently releases gameplay switches."""
        with self._lock:
            self._orbit=False; self._fov=None; self._sync(full=True)
    def load_stock_hook(self,on): self.set_patch(on)
    def copy_stock_params(self):
        with self._lock:
            try: self._field()
            except caves.PatchConflict:
                p=self._inspect(full=True)
                if p is not None and not p.init:
                    self.backend.write_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED,0)
    def center_on_target(self,distance,look_height):
        with self._lock:
            pose=self._native_pose(); yaw,pitch=pose.yaw_pitch()
            target=self.read_player()+Vec3(0,look_height,0)
            self.write_orbit_params(target,math.degrees(yaw),math.degrees(pitch),distance,
                                    target_offset=Vec3(0,look_height,0))
            return orbit_pose(target,yaw,pitch,max(150,min(6000,distance)))
    def default_look_height(self): return -100.0
    def read_aim(self): return self.read_game_pose().target
    def read_eye_base(self): return self._native_pose().eye
    def heartbeat_word(self): return self.backend.read_u32(self.heartbeat_addr())
    def read_projection(self): return 619.0,0.0
    def write_projection_centre(self,centre): pass
    def write_projection_scale(self,scale): pass
    def set_projection_source(self,redirected): pass
    def write_eye_offset(self,offset): pass
    def clear_eye_offset(self): pass
    def write_aim(self,target): pass
    def restore_aim(self): pass
    def write_walk_target(self,centre): pass
    def set_stick_block(self,on): pass  # No native right-camera consumer found.
    def write_pose(self,pose): raise NotImplementedError('Magna Carta Free Camera is not supported')
    def default_settings(self):
        return dict(yaw_deg=0.0,pitch_deg=15.0,distance=1500.0,look_height=-100.0,
                    fov_deg=55.0,use_fov=False)
