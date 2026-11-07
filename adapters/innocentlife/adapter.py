"""Japanese Innocent Life Orbit/FOV, native camera-relative movement and clock pause.

The game owns its camera rig, player movement, collisions and clock baseline.
Orbit publishes relative parameters, not camera output writes. The clock option
only zeroes elapsed seconds; scripted setters (for example sleep) remain native.
"""
from __future__ import annotations

import math
import threading

from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm, caves


class InnocentLifeAdapter:
    name = "INNOCENTLIFE"
    display_name = "Innocent Life: A Futuristic Harvest Moon"
    display_name_key = "game.innocentlife"
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = 1.0
    PITCH_POSITIVE_IS = "above"
    LOOK_HEIGHT_POSITIVE_IS = "down"
    PITCH_RANGE = (-25.0, 89.5)
    DISTANCE_RANGE = (10.0, 600.0)
    LOOK_HEIGHT_RANGE = (-100.0, 100.0)
    OFFSET_RANGE = (-200.0, 200.0)
    field_projection_centre = 0.0
    patch_recheck_s = 1.0
    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAM_EYE
    # Diagnostic rendered target, never a direct native write destination.
    CAM_TARGET_ADDR = mm.MOD_BLOCK + mm.MB_RENDER_TARGET

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True,
                             per_frame_write=False, game_time_pause=True)
        self._lock = threading.RLock()
        self._orbit = False
        self._time = False
        self._last_orbit = None
        self._fov = None

    def identify(self):
        try:
            gid = self.backend.game_id().strip()
            crc = self.backend.crc().strip()
            title = self.backend.title().strip()
            matched = (gid.upper(), crc.upper()) == (mm.GAME_ID, mm.DISC_CRC)
            self.info = AdapterInfo(gid, crc, title, matched,
                                    "" if matched else f"expected {mm.GAME_ID}/{mm.DISC_CRC}")
        except Exception as exc:
            self.info = AdapterInfo(reason=f"PINE error: {exc}")
        return self.info

    @staticmethod
    def _valid_vector(vector):
        return all(math.isfinite(value) and abs(value) < 100000 for value in vector.as_tuple())

    def _native_player(self):
        return Vec3(*self.backend.read_floats(mm.PLAYER, 3))

    def _native_pose(self):
        """Reconstruct target using native rotation and distance to follow anchor."""
        b = self.backend
        eye = Vec3(*b.read_floats(mm.CAM_EYE, 3))
        pitch, yaw = b.read_f32(mm.CAM_PITCH), b.read_f32(mm.CAM_YAW)
        anchor = self._native_player() + Vec3(0, mm.STOCK_LOOK_HEIGHT, 0)
        if not (self._valid_vector(eye) and self._valid_vector(anchor)
                and math.isfinite(pitch) and math.isfinite(yaw)
                and abs(pitch) < 100 and abs(yaw) < 100000):
            raise caves.PatchConflict("invalid Innocent Life native camera geometry")
        distance = (anchor - eye).length()
        if not 0.01 < distance < 2000:
            raise caves.PatchConflict("invalid Innocent Life follow distance")
        forward = Vec3(math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                       math.cos(yaw) * math.cos(pitch))
        return CameraPose(eye, eye + forward.scaled(distance))

    def _field(self):
        b = self.backend
        for address, value in mm.EXACT_GUARDS:
            if b.read_u32(address) != value:
                raise caves.PatchConflict("Innocent Life ordinary player-follow camera is suspended or unavailable")
        if not b.read_u32(mm.FIELD_OWNER):
            raise caves.PatchConflict("Innocent Life field/input owner is unavailable")
        if (b.read_u32(mm.NATIVE_FLAGS) & mm.NATIVE_REJECT_MASK
                or b.read_u32(mm.INPUT_GUARD_BYTE) & mm.INPUT_REJECT_MASK):
            raise caves.PatchConflict("Innocent Life native field/input predicate rejects this scene")
        player = self._native_player()
        if not self._valid_vector(player):
            raise caves.PatchConflict("invalid Innocent Life player position")
        self._native_pose()
        focal = b.read_f32(mm.CAM_FOCAL)
        if not math.isfinite(focal) or not 10 < focal < 10000:
            raise caves.PatchConflict("invalid Innocent Life native focal length")
        return player

    def read_player(self):
        with self._lock:
            return self._field()

    def read_game_pose(self):
        with self._lock:
            b = self.backend
            if (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) & mm.FLAG_ORBIT
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) & mm.FLAG_ORBIT):
                return CameraPose(Vec3(*b.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_EYE, 3)),
                                  Vec3(*b.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_TARGET, 3)))
            return self._native_pose()

    def read_scene(self):
        with self._lock:
            try:
                player = self._field()
                pose = self.read_game_pose()
                valid = (self._valid_vector(pose.eye) and self._valid_vector(pose.target)
                         and 0.01 < pose.distance() < 2000)
                return SceneState(player, pose, self.read_fov_deg(), pose.distance(), valid,
                                  "" if valid else "invalid Innocent Life rendered camera")
            except caves.PatchConflict as exc:
                return SceneState(Vec3(0, 0, 0), CameraPose(Vec3(0, 0, 0), Vec3(0, 0, 1)),
                                  0, 0, False, str(exc))

    def is_field_like(self, scene):
        return scene.valid

    @staticmethod
    def _angles(relative):
        values = (*relative.eye.as_tuple(), *relative.target.as_tuple())
        if not all(math.isfinite(value) and abs(value) < 100000 for value in values):
            raise ValueError("non-finite or out-of-range Innocent Life Orbit geometry")
        forward = relative.target - relative.eye
        horizontal = math.hypot(forward.x, forward.z)
        if horizontal < 1e-5 or not 0.01 < forward.length() < 2000:
            raise ValueError("Innocent Life Orbit view is singular or out of range")
        return -math.atan2(forward.y, horizontal), math.atan2(forward.x, forward.z)

    def _relative_pose(self):
        if self._last_orbit is not None:
            return self._last_orbit
        # Known defaults are always finite and do not need a scene read for the
        # independent clock-only lane (including a state reload in a menu).
        return orbit_pose(Vec3(0, mm.STOCK_LOOK_HEIGHT, 0),
                          math.radians(mm.STOCK_YAW_DEG), math.radians(mm.STOCK_PITCH_DEG),
                          mm.STOCK_DISTANCE)

    def _flags(self):
        return (mm.FLAG_ORBIT if self._orbit else 0) | (mm.FLAG_TIME if self._time else 0)

    def _publish_bank(self, flags, inspection):
        relative = self._relative_pose()
        pitch, yaw = self._angles(relative)  # Reject bad geometry BEFORE any write.
        use_fov = bool(flags & mm.FLAG_ORBIT) and self._fov is not None
        focal = self._native_focal(self._fov) if use_fov else 0.0
        bank_flags = flags | (mm.FLAG_FOV if use_fov else 0)
        b = self.backend
        inspection = caves._prepare_checked(b, inspection)
        slot = (b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1) ^ 1
        address = mm.MOD_BLOCK + mm.SLOTS[slot]
        sequence = (b.read_u32(address + mm.SLOT_SEQUENCE) + 2) & 0xFFFFFFFE
        b.write_u32(address + mm.SLOT_SEQUENCE, sequence | 1)
        b.write_float_block(address + mm.SLOT_EYE, (*relative.eye.as_tuple(), 1))
        b.write_float_block(address + mm.SLOT_TARGET, (*relative.target.as_tuple(), 1))
        b.write_float_block(address + mm.SLOT_PITCH, (pitch, yaw))
        b.write_float_block(address + mm.SLOT_FOCAL, (focal,))
        b.write_u32(address + mm.SLOT_PLAYER, mm.PLAYER)
        b.write_u32(address + mm.SLOT_FLAGS, bank_flags)
        b.write_u32(address + mm.SLOT_SEQUENCE, sequence)
        b.write_u32(mm.MOD_BLOCK + mm.MB_SLOT, slot)
        return inspection

    def _synchronize(self, inspection, *, publish=False):
        # The caller inspected every resource before this transaction's first
        # write. Reuse only that local immutable result under the SAME RLock;
        # the next adapter call always performs a new complete inspection.
        flags = self._flags()
        if flags and (publish or inspection.needs_magic or inspection.empty_caves):
            inspection = self._publish_bank(flags, inspection)
        caves._sync_checked(self.backend, flags, inspection)

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *,
                           pos_offset=None, target_offset=None):
        with self._lock:
            pos = pos_offset if pos_offset is not None else Vec3(0, 0, 0)
            # Explicit target offsets already use the SAME runtime anchor sample.
            target = target_offset if target_offset is not None else centre - self.read_player()
            values = (*centre.as_tuple(), *pos.as_tuple(), *target.as_tuple(),
                      yaw_deg, pitch_deg, distance)
            if not all(math.isfinite(value) for value in values):
                raise ValueError("non-finite Innocent Life Orbit parameter")
            pitch = max(self.PITCH_RANGE[0], min(self.PITCH_RANGE[1], pitch_deg))
            distance = max(self.DISTANCE_RANGE[0], min(self.DISTANCE_RANGE[1], distance))
            pose = orbit_pose(target, math.radians(yaw_deg), math.radians(pitch), distance)
            relative = CameraPose(pose.eye + pos, pose.target)
            self._angles(relative)
            self._field()
            inspection = caves.preflight(self.backend)
            self._last_orbit = relative
            self._orbit = True
            self._synchronize(inspection, publish=True)

    def set_patch(self, on):
        with self._lock:
            if on:
                self._field()
            inspection = caves.preflight(self.backend)
            self._orbit = bool(on)
            # Re-publish on periodic runtime checks so stock state loads recover
            # the last requested offsets even if its runtime pose key is unchanged.
            self._synchronize(inspection, publish=bool(on))

    def patch_state(self):
        with self._lock:
            b = self.backend
            state = caves.site_state(b)
            if state == "unknown":
                return state
            if (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) & mm.FLAG_ORBIT
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) & mm.FLAG_ORBIT
                    and caves.read_words(b, mm.RENDER_HOOK, 2) == caves.RENDER_PAIR
                    and caves.read_words(b, mm.MOVE_HOOK, 2) == caves.MOVE_PAIR):
                return "applied"
            return "stock"

    def patch_active(self):
        return self.patch_state() == "applied"

    hook_active = patch_active

    def set_time_paused(self, on):
        """Pause per-frame elapsed game seconds, not scripted setters or the VM."""
        with self._lock:
            inspection = caves.preflight(self.backend)
            self._time = bool(on)
            self._synchronize(inspection)

    def time_paused(self):
        """Observed native instruction state, never merely the host's desire."""
        with self._lock:
            caves.preflight(self.backend)
            return self.backend.read_u32(mm.CLOCK_HOOK) == mm.CLOCK_PAUSED

    def read_game_time(self):
        with self._lock:
            hours, minutes, seconds = (self.backend.read_u32(address) for address in
                                       (mm.CLOCK_HOURS, mm.CLOCK_MINUTES, mm.CLOCK_SECONDS))
            if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
                raise caves.PatchConflict("invalid Innocent Life clock values")
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def restore(self):
        """Explicit complete release; normal runtime also releases lanes separately."""
        with self._lock:
            inspection = caves.preflight(self.backend)
            self._orbit = self._time = False
            self._fov = None
            self._synchronize(inspection)

    def center_on_target(self, distance, look_height):
        with self._lock:
            player = self._field()
            yaw, pitch = self._native_pose().yaw_pitch()
            target = Vec3(0, look_height, 0)
            self.write_orbit_params(player + target, math.degrees(yaw), math.degrees(pitch),
                                    distance, target_offset=target)
            relative = self._relative_pose()
            return CameraPose(player + relative.eye, player + relative.target)

    def read_aim(self):
        return self.read_game_pose().target

    def read_eye_base(self):
        return self._native_pose().eye

    def read_camera_forward(self):
        pose = self.read_game_pose()
        forward = pose.target - pose.eye
        return forward.scaled(1 / forward.length())

    def place_looking_at(self, target, distance):
        return target - self.read_camera_forward().scaled(distance)

    def write_pose(self, pose):
        yaw, pitch = pose.yaw_pitch()
        self.write_orbit_params(pose.target, math.degrees(yaw), math.degrees(pitch), pose.distance())

    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE, look_height=mm.STOCK_LOOK_HEIGHT,
                    pitch_deg=mm.STOCK_PITCH_DEG, yaw_deg=mm.STOCK_YAW_DEG,
                    fov_deg=mm.STOCK_FOV_DEG)

    def default_look_height(self):
        return mm.STOCK_LOOK_HEIGHT

    def heartbeat_addr(self):
        return mm.MOD_BLOCK + mm.MB_HEARTBEAT

    def heartbeat_word(self):
        return self.backend.read_u32(self.heartbeat_addr())

    @staticmethod
    def _fov_from_scale(scale):
        return (math.degrees(2 * math.atan(mm.SCREEN_HALF_WIDTH / scale))
                if math.isfinite(scale) and scale > 0 else 0.0)

    def _x_factor(self):
        factor = self.backend.read_f32(mm.PROJECTION_X_FACTOR)
        if not math.isfinite(factor) or not 0.1 < factor < 4:
            raise caves.PatchConflict("invalid Innocent Life projection X factor")
        return factor

    def _native_focal(self, deg):
        return mm.SCREEN_HALF_WIDTH / (self._x_factor() * math.tan(math.radians(deg) / 2))

    def read_fov_scale(self):
        # Real screen-space projection output; never a requested-value mirror.
        return self.backend.read_f32(mm.PROJECTION)

    def read_fov_deg(self):
        with self._lock:
            return self._fov_from_scale(self.read_fov_scale())

    def capture_original_fov(self):
        with self._lock:
            self._field()
            return self._fov_from_scale(self.backend.read_f32(mm.CAM_FOCAL) * self._x_factor())

    def write_fov_deg(self, deg):
        if not math.isfinite(deg):
            raise ValueError("non-finite Innocent Life FOV")
        with self._lock:
            self._field()
            deg = max(20.0, min(110.0, deg))
            self._native_focal(deg)  # Validate projection BEFORE preparation writes.
            inspection = caves.preflight(self.backend)
            self._fov = deg
            # FOV accompanies Orbit, never enables camera/movement on its own.
            self._synchronize(inspection, publish=True)

    def fov_in_sync(self, deg):
        with self._lock:
            if not math.isfinite(deg):
                return False
            deg = max(20.0, min(110.0, deg))
            b = self.backend
            return (self._orbit and self._fov is not None and abs(self._fov - deg) < .01
                    and self.patch_active()
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) & mm.FLAG_FOV != 0
                    and abs(self.read_fov_deg() - deg) < .05)

    def restore_fov(self):
        with self._lock:
            inspection = caves.preflight(self.backend)
            self._fov = None
            # Next render copies the then-current native focal, including script
            # changes made during Orbit. No stale saved native value is written.
            self._synchronize(inspection, publish=True)

    # Compatibility hooks are intentionally inert: no native camera/projection
    # writes and no right-stick patch (the original has no camera right-stick).
    def read_projection(self):
        return FOV_SCALE_REF, 0.0

    def write_projection_centre(self, centre):
        pass

    def write_projection_scale(self, scale):
        pass

    def set_projection_source(self, redirected):
        pass

    def write_eye_offset(self, offset):
        pass

    def clear_eye_offset(self):
        pass

    def write_aim(self, target):
        pass

    def restore_aim(self):
        pass

    def write_walk_target(self, centre):
        pass

    def copy_stock_params(self):
        pass

    def set_stick_block(self, on):
        pass
