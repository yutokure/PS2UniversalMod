"""Right-stick yaw/pitch Orbit for Japanese PS2 Dragon Quest V.

Native camera state runs unchanged; the render transaction consumes relative
parameters and adds the current owned player node on the guest.
"""
from __future__ import annotations
import math
import threading
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm, caves


class DragonQuest5Adapter:
    name = 'DRAGONQUEST5'
    display_name = 'Dragon Quest V'
    display_name_key = 'game.dragonquest5'
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = -1.0
    PITCH_POSITIVE_IS = 'above'
    LOOK_HEIGHT_POSITIVE_IS = 'up'
    PITCH_RANGE = (-89.5, 25.0)
    DISTANCE_RANGE = (20.0, 600.0)
    LOOK_HEIGHT_RANGE = (-50.0, 80.0)
    OFFSET_RANGE = (-200.0, 200.0)
    field_projection_centre = 0.0
    patch_recheck_s = 1.0
    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAM_EYE
    CAM_TARGET_ADDR = mm.CAM_TARGET

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True, per_frame_write=False)
        self._lock = threading.RLock()
        self._orbit = False
        self._fov = None
        self._last_orbit = None

    def identify(self):
        try:
            gid, crc, title = self.backend.game_id().strip(), self.backend.crc().strip(), self.backend.title().strip()
            matched = (gid.upper(), crc.upper()) == (mm.GAME_ID, mm.DISC_CRC)
            self.info = AdapterInfo(gid, crc, title, matched, '' if matched else f'expected {mm.GAME_ID}/{mm.DISC_CRC}')
        except Exception as exc:
            self.info = AdapterInfo(reason=f'PINE error: {exc}')
        return self.info

    @staticmethod
    def _pointer(value):
        return value >= 0x100000 and value + 0x200 < 0x2000000 and value % 16 == 0

    def _field(self):
        b = self.backend
        for address, word in mm.EXACT_GUARDS:
            if b.read_u32(address) != word:
                raise caves.PatchConflict('DQ5 ordinary party-follow camera is unavailable or suspended')
        for address in mm.ZERO_HALF_GUARDS:
            word = b.read_u32(address & ~3) >> ((address & 3)*8)
            if word & 65535: raise caves.PatchConflict('DQ5 event/menu camera is suspended')
        actor = b.read_u32(mm.PLAYER_PTR)
        if not self._pointer(actor): raise caves.PatchConflict('invalid DQ5 player owner')
        node = b.read_u32(actor + mm.PLAYER_NODE)
        if not self._pointer(node): raise caves.PatchConflict('invalid DQ5 player node')
        player = Vec3(*b.read_floats(node + mm.NODE_POSITION, 3))
        pose = self._native_pose()
        values = (*player.as_tuple(), *pose.eye.as_tuple(), *pose.target.as_tuple())
        if not all(math.isfinite(x) and abs(x)<100000 for x in values) or not 1 < pose.distance() < 2000:
            raise caves.PatchConflict('invalid DQ5 field geometry')
        lens = b.read_f32(mm.CAM_FOV)
        if not math.isfinite(lens) or not .01 < lens < 3.13: raise caves.PatchConflict('invalid DQ5 lens')
        return node, player

    def _native_pose(self):
        return CameraPose(Vec3(*self.backend.read_floats(mm.CAM_EYE, 3)),
                          Vec3(*self.backend.read_floats(mm.CAM_TARGET, 3)))

    def read_player(self): return self._field()[1]

    def read_game_pose(self):
        b = self.backend
        if (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT
                and b.read_u32(mm.MOD_BLOCK+mm.MB_APPLIED)&mm.FLAG_ORBIT):
            return CameraPose(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_EYE, 3)),
                              Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_TARGET, 3)))
        return self._native_pose()

    @staticmethod
    def _horizontal_fov(rad):
        return math.degrees(2*math.atan(math.tan(rad/2)/mm.PROJECTION_X_FACTOR))

    @staticmethod
    def _native_fov(deg):
        return 2*math.atan(mm.PROJECTION_X_FACTOR*math.tan(math.radians(deg)/2))

    def read_fov_scale(self):
        # Actual rendered cos(half-angle)/sin(half-angle), plus X post-scale.
        b = self.backend
        sine = b.read_f32(mm.CAM_PROJECTION+0x2C)
        return mm.PROJECTION_X_FACTOR*b.read_f32(mm.CAM_PROJECTION)/sine if abs(sine)>1e-9 else 0.0

    def read_fov_deg(self):
        scale = self.read_fov_scale()
        return math.degrees(2*math.atan(1/scale)) if math.isfinite(scale) and scale>0 else 0.0

    def capture_original_fov(self): return self._horizontal_fov(self.backend.read_f32(mm.CAM_FOV))

    def read_scene(self):
        try:
            player = self._field()[1]; pose = self.read_game_pose(); fov = self.read_fov_deg()
            values = (*pose.eye.as_tuple(), *pose.target.as_tuple())
            valid = (all(math.isfinite(x) and abs(x)<100000 for x in values)
                     and 1 < pose.distance() < 2000 and math.isfinite(fov) and 1 < fov < 179)
            return SceneState(player, pose, fov, pose.distance(), valid,
                              '' if valid else 'invalid DQ5 rendered camera or projection')
        except caves.PatchConflict as exc:
            return SceneState(Vec3(0,0,0), CameraPose(Vec3(0,0,0),Vec3(0,0,1)),0,0,False,str(exc))

    def is_field_like(self, scene): return scene.valid

    @staticmethod
    def _world(pose):
        forward = pose.target-pose.eye
        forward = forward.scaled(1/forward.length())
        right = Vec3(forward.z, 0, -forward.x)
        if right.length()<1e-7: raise ValueError('DQ5 vertical view is singular')
        right = right.scaled(1/right.length())
        up = Vec3(forward.y*right.z-forward.z*right.y,
                  forward.z*right.x-forward.x*right.z,
                  forward.x*right.y-forward.y*right.x)
        return (*right.as_tuple(),0,*up.as_tuple(),0,*forward.as_tuple(),0,*pose.eye.as_tuple(),1)

    def _publish(self):
        node, player = self._field()
        b = self.backend
        relative = self._last_orbit
        if relative is None:
            pose = self._native_pose(); relative = CameraPose(pose.eye-player,pose.target-player)
        world = self._world(relative)  # Validate singular geometry before the first write.
        caves.prepare(b)
        slot = (b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1
        address = mm.MOD_BLOCK+mm.SLOTS[slot]
        sequence = (b.read_u32(address+mm.SLOT_SEQUENCE)+2)&0xFFFFFFFE
        flags = (mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0)
        b.write_u32(address+mm.SLOT_SEQUENCE,sequence|1)
        b.write_float_block(address+mm.SLOT_WORLD,world)
        b.write_float_block(address+mm.SLOT_TARGET,(*relative.target.as_tuple(),1))
        # Reuse the game's native Y-rotation and actor-facing calculations.
        # Native yaw describes forward, while the GUI yaw describes eye position.
        forward = relative.target-relative.eye
        b.write_float_block(address+mm.SLOT_YAW,[math.atan2(forward.x,forward.z)])
        b.write_float_block(address+mm.SLOT_FOV,[self._native_fov(self._fov) if self._fov is not None else 0])
        b.write_u32(address+mm.SLOT_NODE,node); b.write_u32(address+mm.SLOT_FLAGS,flags)
        b.write_u32(address+mm.SLOT_SEQUENCE,sequence)
        b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT,slot)
        caves.install(b)
        b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags)

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *, pos_offset=None, target_offset=None):
        pos = pos_offset or Vec3(0,0,0)
        target = target_offset if target_offset is not None else centre-self.read_player()
        if not all(math.isfinite(x) for x in (*centre.as_tuple(),*pos.as_tuple(),*target.as_tuple(),yaw_deg,pitch_deg,distance)):
            raise ValueError('non-finite DQ5 Orbit parameter')
        pitch = max(self.PITCH_RANGE[0],min(self.PITCH_RANGE[1],pitch_deg))
        distance = max(self.DISTANCE_RANGE[0],min(self.DISTANCE_RANGE[1],distance))
        pose = orbit_pose(target,math.radians(yaw_deg),math.radians(pitch),distance)
        with self._lock:
            self._last_orbit = CameraPose(pose.eye+pos,pose.target); self._orbit = True; self._publish()

    def set_patch(self,on):
        with self._lock:
            self._orbit = bool(on)
            if on: self._publish()
            else: self._release()

    def _release(self):
        b = self.backend
        caves.preflight(b)
        if b.read_u32(mm.MOD_BLOCK)==mm.MAGIC:
            flags = (mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0)
            b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags)
        if self._orbit or self._fov is not None:
            try: self._field()
            except caves.PatchConflict: return
            self._publish()
        else: caves.uninstall(b)

    def patch_state(self):
        state = caves.site_state(self.backend)
        if state == 'applied' and self.backend.read_u32(mm.MOD_BLOCK)==mm.MAGIC:
            return ('applied' if caves.all_applied(self.backend)
                    and self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT else 'stock')
        return state
    def patch_active(self): return self.patch_state()=='applied'
    hook_active = patch_active

    def write_fov_deg(self,deg):
        if not math.isfinite(deg): raise ValueError('non-finite DQ5 FOV')
        with self._lock:
            self._fov = max(20.0,min(110.0,deg)); self._publish()
    def restore_fov(self):
        with self._lock: self._fov = None; self._release()
    def fov_in_sync(self,deg):
        return (self._fov is not None and abs(self._fov-deg)<.01
                and caves.all_applied(self.backend)
                and self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_FOV
                and abs(self.read_fov_deg()-deg)<.05)
    def center_on_target(self,distance,look_height):
        player = self.read_player(); yaw,pitch = self._native_pose().yaw_pitch()
        target = Vec3(0,look_height,0); centre = player+target
        self.write_orbit_params(centre,math.degrees(yaw),math.degrees(pitch),distance,target_offset=target)
        return orbit_pose(centre,yaw,pitch,distance)
    def read_aim(self): return self.read_game_pose().target
    def read_eye_base(self): return self._native_pose().eye
    def read_camera_forward(self):
        pose = self.read_game_pose(); forward = pose.target-pose.eye
        return forward.scaled(1/forward.length())
    def place_looking_at(self,target,distance): return target-self.read_camera_forward().scaled(distance)
    def write_pose(self,pose):
        yaw,pitch = pose.yaw_pitch()
        self.write_orbit_params(pose.target,math.degrees(yaw),math.degrees(pitch),pose.distance())
    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE,look_height=10.0,pitch_deg=-32.0,yaw_deg=-147.73,
                    fov_deg=self._horizontal_fov(mm.STOCK_FOV_RAD))
    def default_look_height(self): return 10.0
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
    def copy_stock_params(self): pass
    def set_stick_block(self,on): pass  # Scoped pad hook belongs to the Orbit flag.
