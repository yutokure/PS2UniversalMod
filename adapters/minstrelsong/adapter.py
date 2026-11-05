"""Ordinary field Orbit, native compass and movement, Japanese Minstrel Song."""
from __future__ import annotations
import math
import threading
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm, caves


class MinstrelSongAdapter:
    name = 'MINSTRELSONG'
    display_name = 'Romancing SaGa -Minstrel Song-'
    display_name_key = 'game.minstrelsong'
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = 1.0
    PITCH_POSITIVE_IS = 'above'
    LOOK_HEIGHT_POSITIVE_IS = 'down'
    PITCH_RANGE = (-25.0, 89.5)
    DISTANCE_RANGE = (1.0, 80.0)
    LOOK_HEIGHT_RANGE = (-10.0, 10.0)
    OFFSET_RANGE = (-30.0, 30.0)
    field_projection_centre = 0.0
    patch_recheck_s = 1.0

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True, per_frame_write=False)
        self._lock = threading.RLock()
        self._orbit = False
        self._fov = None
        self._last_orbit = None
        self._prepared = False

    def identify(self):
        try:
            gid, crc, title = self.backend.game_id().strip(), self.backend.crc().strip(), self.backend.title().strip()
            matched = (gid.upper(), crc.upper()) == (mm.GAME_ID, mm.DISC_CRC)
            self.info = AdapterInfo(gid, crc, title, matched, '' if matched else f'expected {mm.GAME_ID}/{mm.DISC_CRC}')
        except Exception as exc:
            self.info = AdapterInfo(reason=f'PINE error: {exc}')
        return self.info

    def _field(self):
        b = self.backend
        for address, value in (*mm.EXACT_GUARDS, *((p, 0) for p in mm.ZERO_GUARDS)):
            if b.read_u32(address) != value:
                raise caves.PatchConflict('Minstrel Song ordinary field follow is suspended or unavailable')
        player = Vec3(*b.read_floats(mm.PLAYER, 3))
        pose = self._native_pose()
        values = (*player.as_tuple(), *pose.eye.as_tuple(), *pose.target.as_tuple())
        if not all(math.isfinite(v) and abs(v) < 100000 for v in values) or not .01 < pose.distance() < 1000:
            raise caves.PatchConflict('invalid Minstrel Song field geometry')
        focal = b.read_f32(mm.CAM_NATIVE_FOCAL)
        if not math.isfinite(focal) or not 10 < focal < 10000:
            raise caves.PatchConflict('invalid Minstrel Song native lens')
        return player

    @staticmethod
    def _focal(deg):
        return mm.HALF_WIDTH / math.tan(math.radians(deg)/2)

    @staticmethod
    def _fov_deg(focal):
        return math.degrees(2*math.atan(mm.HALF_WIDTH/focal)) if math.isfinite(focal) and focal > 0 else 0.0

    def _native_pose(self):
        return CameraPose(Vec3(*self.backend.read_floats(mm.CAM_EYE, 3)),
                          Vec3(*self.backend.read_floats(mm.CAM_TARGET, 3)))

    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAM_EYE
    CAM_TARGET_ADDR = mm.CAM_TARGET

    def read_player(self):
        return self._field()

    def read_game_pose(self):
        b = self.backend
        if (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS) & mm.FLAG_ORBIT
                and b.read_u32(mm.MOD_BLOCK+mm.MB_APPLIED) & mm.FLAG_ORBIT):
            return CameraPose(Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_EYE, 3)),
                              Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_TARGET, 3)))
        return self._native_pose()

    def read_fov_scale(self):
        return self.backend.read_f32(mm.PROJECTION)/mm.HALF_WIDTH

    def read_fov_deg(self):
        return self._fov_deg(self.backend.read_f32(mm.PROJECTION))

    def capture_original_fov(self):
        return self._fov_deg(self.backend.read_f32(mm.CAM_NATIVE_FOCAL))

    def read_scene(self):
        try:
            player = self._field()
            pose = self.read_game_pose()
            valid = (all(math.isfinite(v) and abs(v) < 100000 for v in (*pose.eye.as_tuple(), *pose.target.as_tuple()))
                     and .01 < pose.distance() < 1000 and 1 < self.read_fov_deg() < 179)
            return SceneState(player, pose, self.read_fov_deg(), pose.distance(), valid,
                              '' if valid else 'invalid Minstrel Song rendered camera')
        except caves.PatchConflict as exc:
            return SceneState(Vec3(0, 0, 0), CameraPose(Vec3(0, 0, 0), Vec3(0, 0, 1)), 0, 0, False, str(exc))

    def is_field_like(self, scene):
        return scene.valid

    def _publish(self):
        player = self._field()
        b = self.backend
        # Validate every owned instruction before any parameter publication too;
        # an intact hook/magic alone does not prove its cave is still ours.
        caves.prepare(b)
        self._prepared = True
        needs_install = any(b.read_u32(address) == stock[0] for address, stock, _, _, _ in caves.RESOURCES)
        relative = self._last_orbit
        if relative is None:
            pose = self._native_pose()
            relative = CameraPose(pose.eye-player, pose.target-player)
        slot = (b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1
        address = mm.MOD_BLOCK+mm.SLOTS[slot]
        sequence = (b.read_u32(address+mm.SLOT_SEQUENCE)+2)&0xFFFFFFFE
        flags = (mm.FLAG_ORBIT if self._orbit else 0) | (mm.FLAG_FOV if self._fov is not None else 0)
        b.write_u32(address+mm.SLOT_SEQUENCE, sequence|1)
        b.write_float_block(address+mm.SLOT_EYE, (*relative.eye.as_tuple(), 1))
        b.write_float_block(address+mm.SLOT_TARGET, (*relative.target.as_tuple(), 1))
        b.write_float_block(address+mm.SLOT_FOCAL, [self._focal(self._fov) if self._fov is not None else 0])
        b.write_u32(address+mm.SLOT_FLAGS, flags)
        b.write_u32(address+mm.SLOT_SEQUENCE, sequence)
        b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT, slot)
        b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS, flags)
        if needs_install: caves.install(b)

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *, pos_offset=None, target_offset=None):
        pos = pos_offset or Vec3(0, 0, 0)
        target = target_offset if target_offset is not None else centre-self.read_player()
        if not all(math.isfinite(v) for v in (*centre.as_tuple(), *pos.as_tuple(), *target.as_tuple(), yaw_deg, pitch_deg, distance)):
            raise ValueError('non-finite Minstrel Song Orbit parameter')
        pitch_deg = max(self.PITCH_RANGE[0], min(self.PITCH_RANGE[1], pitch_deg))
        distance = max(self.DISTANCE_RANGE[0], min(self.DISTANCE_RANGE[1], distance))
        pose = orbit_pose(target, math.radians(yaw_deg), math.radians(pitch_deg), distance)
        with self._lock:
            self._last_orbit = CameraPose(pose.eye+pos, pose.target)
            self._orbit = True
            self._publish()

    def set_patch(self, on):
        with self._lock:
            self._orbit = bool(on)
            if on:
                caves.preflight(self.backend)
                self._publish()
            else:
                self._release()

    def _release(self):
        b = self.backend
        caves.preflight(b)
        flags = (mm.FLAG_ORBIT if self._orbit else 0) | (mm.FLAG_FOV if self._fov is not None else 0)
        if b.read_u32(mm.MOD_BLOCK) == mm.MAGIC:
            b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS, flags)
            if self._fov is None: caves.restore_projection(b)
        if flags:
            try: self._field()
            except caves.PatchConflict: return
            self._publish()
        else:
            caves.uninstall(b)

    def patch_state(self):
        state = caves.site_state(self.backend)
        if state == 'applied' and self.backend.read_u32(mm.MOD_BLOCK) == mm.MAGIC:
            return 'applied' if self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT else 'stock'
        return state

    def patch_active(self): return self.patch_state() == 'applied'
    hook_active = patch_active

    def write_fov_deg(self, deg):
        if not math.isfinite(deg): raise ValueError('non-finite Minstrel Song FOV')
        with self._lock:
            self._fov = max(20.0, min(110.0, deg)); self._publish()

    def restore_fov(self):
        with self._lock:
            self._fov = None; self._release()

    def fov_in_sync(self, deg):
        return (self._fov is not None and abs(self._fov-deg)<.01
                and caves.site_state(self.backend) == 'applied' and abs(self.read_fov_deg()-deg)<.05)

    def center_on_target(self, distance, look_height):
        self._field()
        yaw, pitch = self._native_pose().yaw_pitch()
        aim = self.read_player()+Vec3(0, look_height, 0)
        self.write_orbit_params(aim, math.degrees(yaw), math.degrees(pitch), distance,
                                target_offset=Vec3(0, look_height, 0))
        return orbit_pose(aim, yaw, pitch, distance)

    def read_aim(self): return self.read_game_pose().target
    def read_eye_base(self): return self._native_pose().eye
    def read_camera_forward(self):
        p = self.read_game_pose(); v = p.target-p.eye
        return v.scaled(1/v.length())
    def place_looking_at(self, target, distance): return target-self.read_camera_forward().scaled(distance)
    def write_pose(self, pose):
        y, p = pose.yaw_pitch()
        self.write_orbit_params(pose.target, math.degrees(y), math.degrees(p), pose.distance())
    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE, look_height=-1.5, pitch_deg=18.0, yaw_deg=-165.0,
                    fov_deg=self._fov_deg(mm.STOCK_FOCAL))
    def default_look_height(self): return -1.5
    def heartbeat_addr(self): return mm.MOD_BLOCK+mm.MB_HEARTBEAT
    def heartbeat_word(self): return self.backend.read_u32(self.heartbeat_addr())
    def read_projection(self): return FOV_SCALE_REF, 0.0
    def write_projection_centre(self, centre): pass
    def write_projection_scale(self, scale): pass
    def set_projection_source(self, redirected): pass
    def write_eye_offset(self, offset): pass
    def clear_eye_offset(self): pass
    def write_aim(self, target): pass
    def restore_aim(self): pass
    def write_walk_target(self, centre): pass
    def copy_stock_params(self): pass
    def set_stick_block(self, on): pass  # No native right-stick camera control to suppress.
