"""Grandia II JP Orbit/FOV adapter; native camera sources stay game-owned.

The render transaction consumes player-relative eye/target values and restores
native NJ outputs at its tail. Read rendered diagnostics from the MOD mailbox,
not those restored outputs. Original-mode FOV-only and Free Camera are unsupported.
"""
from __future__ import annotations

import math
import threading

from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm, caves


class Grandia2Adapter:
    name = "GRANDIA2"
    display_name = "Grandia II"
    display_name_key = "game.grandia2"
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = -1.0
    PITCH_POSITIVE_IS = "above"
    LOOK_HEIGHT_POSITIVE_IS = "up"
    PITCH_RANGE = (-89.5, 25.0)
    DISTANCE_RANGE = (100.0, 10000.0)
    LOOK_HEIGHT_RANGE = (-1000.0, 1000.0)
    OFFSET_RANGE = (-3000.0, 3000.0)
    # Wider views can exceed the native renderer's packet-buffer budget.
    FOV_RANGE = (20.0, 60.0)
    field_projection_centre = 0.0
    patch_recheck_s = 1.0
    # Read-only native sources. All publication writes go to MOD banks instead.
    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAM_EYE
    CAM_TARGET_ADDR = mm.CAM_TARGET

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True,
                             per_frame_write=False)
        self._lock = threading.RLock()
        self._orbit = False
        self._fov = None
        self._last_orbit = None
        # Never share audit authorization across adapter/backend instances or
        # transport reconnects. The GuardedBackend still protects every write.
        self._prepared_backend = None
        self._prepared_epoch = None

    def identify(self):
        with self._lock:
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
    def _pointer(value, size=4):
        return 0x100000 <= value and value + size <= 0x2000000 and value % 4 == 0

    @staticmethod
    def _valid_vector(vector):
        return all(math.isfinite(value) and abs(value) < 1000000
                   for value in vector.as_tuple())

    @classmethod
    def _valid_pose(cls, pose):
        return (cls._valid_vector(pose.eye) and cls._valid_vector(pose.target)
                and 1.0 < pose.distance() < 100000.0)

    @staticmethod
    def _check_focal(focal):
        if not math.isfinite(focal) or not 1.0 < focal < 1000000.0:
            raise caves.PatchConflict("invalid Grandia II focal length")
        return focal

    def _projection(self):
        b = self.backend
        width = b.read_f32(mm.SCREEN_WIDTH)
        aspect = b.read_f32(mm.ASPECT_X)
        if not (math.isfinite(width) and 16.0 <= width <= 4096.0
                and math.isfinite(aspect) and 0.1 < aspect < 4.0):
            raise caves.PatchConflict("invalid Grandia II projection dimensions")
        return width, aspect

    def _native_pose(self):
        b = self.backend
        return CameraPose(Vec3(*b.read_floats(mm.CAM_EYE, 3)),
                          Vec3(*b.read_floats(mm.CAM_TARGET, 3)))

    def _field(self):
        b = self.backend
        for address, value in mm.EXACT_GUARDS:
            if b.read_u32(address) != value:
                raise caves.PatchConflict("Grandia II field camera is suspended or unavailable")
        # Both outdoor follow (8) and indoor fixed (0) cameras are supported.
        # No unproven actor-active mask or follow-only predicate is imposed.
        if (b.read_u32(mm.CAMERA) & 0xFFFF) not in (0, 8):
            raise caves.PatchConflict("Grandia II native camera mode is unavailable")
        owner = b.read_u32(mm.PLAYER_PTR)
        if not self._pointer(owner, mm.ACTOR_NODE + 4):
            raise caves.PatchConflict("invalid Grandia II player owner")
        node = b.read_u32(owner + mm.ACTOR_NODE)
        if not self._pointer(node, mm.NODE_POSITION + 12):
            raise caves.PatchConflict("invalid Grandia II player node")
        player = Vec3(*b.read_floats(node + mm.NODE_POSITION, 3))
        if not self._valid_vector(player) or not self._valid_pose(self._native_pose()):
            raise caves.PatchConflict("invalid Grandia II native field geometry")
        self._check_focal(b.read_f32(mm.FIELD_FOCAL))
        self._projection()
        return owner, node, player

    def read_player(self):
        with self._lock:
            return self._field()[2]

    def _render_applied(self):
        b = self.backend
        return (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                and b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) & mm.FLAG_ORBIT != 0)

    def read_game_pose(self):
        with self._lock:
            b = self.backend
            if self._render_applied():
                return CameraPose(Vec3(*b.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_EYE, 3)),
                                  Vec3(*b.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_TARGET, 3)))
            return self._native_pose()

    def read_scene(self):
        with self._lock:
            try:
                player = self._field()[2]
                pose = self.read_game_pose()
                fov = self.read_fov_deg()
                valid = self._valid_pose(pose) and math.isfinite(fov) and 1.0 < fov < 179.0
                return SceneState(player, pose, fov, pose.distance(), valid,
                                  "" if valid else "invalid Grandia II rendered camera or projection")
            except caves.PatchConflict as exc:
                return SceneState(Vec3(0, 0, 0), CameraPose(Vec3(0, 0, 0), Vec3(0, 0, 1)),
                                  0, 0, False, str(exc))

    def is_field_like(self, scene):
        return scene.valid

    @classmethod
    def _view_parameters(cls, relative):
        if not cls._valid_pose(relative):
            raise ValueError("non-finite or out-of-range Grandia II Orbit geometry")
        forward = relative.target - relative.eye
        if math.hypot(forward.x, forward.z) < 1e-5:
            raise ValueError("Grandia II vertical view is singular")
        forward = forward.scaled(1.0 / forward.length())
        off = relative.eye - relative.target
        # Native yaw is an eye-direction integer, not a float or forward angle.
        yaw = round(math.atan2(off.x, off.z) * 65536.0 / (2.0 * math.pi))
        yaw = ((yaw + 32768) & 0xFFFF) - 32768
        return forward, yaw

    def _relative_pose(self, player):
        if self._last_orbit is not None:
            return self._last_orbit
        pose = self._native_pose()
        return CameraPose(pose.eye - player, pose.target - player)

    def _native_focal(self, degrees):
        width, aspect = self._projection()
        return self._check_focal(width / (2.0 * math.tan(math.radians(degrees) / 2.0) * aspect))

    def _ensure_prepared(self, *, audit=False):
        b = self.backend
        epoch = getattr(b, "epoch", None)
        cached = self._prepared_backend is b and self._prepared_epoch == epoch
        try:
            if cached and not audit and caves.ready(b):
                return
            self._prepared_backend = None
            self._prepared_epoch = None
            caves.prepare(b)
        except Exception:
            self._prepared_backend = None
            self._prepared_epoch = None
            raise
        self._prepared_backend = b
        self._prepared_epoch = epoch

    def _publish(self, *, audit=False):
        owner, node, player = self._field()
        relative = self._relative_pose(player)
        forward, yaw = self._view_parameters(relative)
        focal = (self._native_focal(self._fov) if self._fov is not None
                 else self._check_focal(self.backend.read_f32(mm.FIELD_FOCAL)))
        flags = mm.FLAG_ORBIT | (mm.FLAG_FOV if self._fov is not None else 0)
        b = self.backend
        # Live site pairs/control ownership are checked before EVERY bank write.
        # Full cave-body audits run on first use, reconnect/state loss and each
        # periodic set_patch(True). Cave-body-only changes are not instant checks.
        self._ensure_prepared(audit=audit)
        # Initial activation may use a native fallback rather than a runtime
        # Orbit request. Preserve that relative view for FOV reset and reapply.
        self._last_orbit = relative
        slot = (b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1) ^ 1
        address = mm.MOD_BLOCK + mm.SLOTS[slot]
        sequence = (b.read_u32(address + mm.SLOT_SEQUENCE) + 2) & 0xFFFFFFFE
        b.write_u32(address + mm.SLOT_SEQUENCE, sequence | 1)
        b.write_float_block(address + mm.SLOT_EYE, (*relative.eye.as_tuple(), 1.0))
        b.write_float_block(address + mm.SLOT_TARGET, (*relative.target.as_tuple(), 1.0))
        b.write_float_block(address + mm.SLOT_FORWARD, forward.as_tuple())
        b.write_u32(address + mm.SLOT_YAW, yaw & 0xFFFFFFFF)
        b.write_float_block(address + mm.SLOT_FOCAL, (focal,))
        b.write_u32(address + mm.SLOT_PLAYER, owner)
        b.write_u32(address + mm.SLOT_NODE, node)
        b.write_u32(address + mm.SLOT_FLAGS, flags)
        b.write_u32(address + mm.SLOT_SEQUENCE, sequence)
        b.write_u32(mm.MOD_BLOCK + mm.MB_SLOT, slot)
        # Desired lifecycle flags are ORBIT only. FOV is a bank-local choice;
        # synchronize owns MB_FLAGS and the install/removal acknowledgement.
        caves.synchronize(b, mm.FLAG_ORBIT)

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *,
                           pos_offset=None, target_offset=None):
        with self._lock:
            pos = pos_offset if pos_offset is not None else Vec3(0, 0, 0)
            # Explicit offsets use the runtime's SAME actor sample, avoiding
            # subtraction of a later actor position while the player is moving.
            target = target_offset if target_offset is not None else centre - self.read_player()
            values = (*centre.as_tuple(), *pos.as_tuple(), *target.as_tuple(),
                      yaw_deg, pitch_deg, distance)
            if not all(math.isfinite(value) for value in values):
                raise ValueError("non-finite Grandia II Orbit parameter")
            pitch = max(self.PITCH_RANGE[0], min(self.PITCH_RANGE[1], pitch_deg))
            distance = max(self.DISTANCE_RANGE[0], min(self.DISTANCE_RANGE[1], distance))
            pose = orbit_pose(target, math.radians(yaw_deg), math.radians(pitch), distance)
            relative = CameraPose(pose.eye + pos, pose.target)
            self._view_parameters(relative)
            self._last_orbit = relative
            self._orbit = True
            self._publish()

    def set_patch(self, on):
        with self._lock:
            self._orbit = bool(on)
            if on:
                # Full audit + republish even with an unchanged runtime pose key.
                # Cave-body conflict detection occurs at the next runtime audit
                # (normally 1s plus scheduling/transport latency), not instantly.
                self._publish(audit=True)
            else:
                self._prepared_backend = None
                self._prepared_epoch = None
                caves.synchronize(self.backend, 0)

    def patch_state(self):
        with self._lock:
            b = self.backend
            state = caves.site_state(b)
            if state != "applied":
                return state
            # Mixed but owned instruction pairs are a recoverable stock state,
            # not a fully acknowledged installation or an unknown-code conflict.
            all_applied = all(caves.read_words(b, address, len(hook)) == hook
                              for address, _stock, hook in caves.SITES)
            return ("applied" if all_applied and b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == mm.FLAG_ORBIT else "stock")

    def patch_active(self):
        return self.patch_state() == "applied"

    hook_active = patch_active

    def restore(self):
        with self._lock:
            self._prepared_backend = None
            self._prepared_epoch = None
            self._orbit = False
            self._fov = None
            # Removal performs one full preflight, even after a cached hot path.
            caves.synchronize(self.backend, 0)

    def read_fov_scale(self):
        with self._lock:
            b = self.backend
            # NJ outputs are restored every render tail. The mailbox captures
            # the focal actually used, whether native or overridden by the bank.
            address = mm.MOD_BLOCK + mm.MB_RENDER_FOCAL if self._render_applied() else mm.NJ_FOCAL
            focal = self._check_focal(b.read_f32(address))
            return focal * self._projection()[1]

    def read_fov_deg(self):
        with self._lock:
            width, _ = self._projection()
            return math.degrees(2.0 * math.atan(width / (2.0 * self.read_fov_scale())))

    def capture_original_fov(self):
        with self._lock:
            self._field()
            width, aspect = self._projection()
            b = self.backend
            # During the render transaction FIELD_FOCAL is temporarily replaced.
            # Its saved native value, not the override, is the Original baseline.
            pending = (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
                       and b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) != 0)
            address = mm.MOD_BLOCK + mm.MB_NATIVE_FOCAL if pending else mm.FIELD_FOCAL
            focal = self._check_focal(b.read_f32(address))
            return math.degrees(2.0 * math.atan(width / (2.0 * focal * aspect)))

    def write_fov_deg(self, degrees):
        if not math.isfinite(degrees):
            raise ValueError("non-finite Grandia II FOV")
        with self._lock:
            self._field()
            degrees = max(self.FOV_RANGE[0], min(self.FOV_RANGE[1], degrees))
            self._native_focal(degrees)
            self._fov = degrees
            # Store the request, but never install camera/movement for FOV-only.
            if self._orbit:
                self._publish()
            else:
                caves.preflight(self.backend)

    def fov_in_sync(self, degrees):
        with self._lock:
            if not math.isfinite(degrees):
                return False
            degrees = max(self.FOV_RANGE[0], min(self.FOV_RANGE[1], degrees))
            b = self.backend
            return (self._orbit and self._fov is not None and abs(self._fov - degrees) < .01
                    and self.patch_active() and self._render_applied()
                    and b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) & mm.FLAG_FOV != 0
                    and abs(self.read_fov_deg() - degrees) < .05)

    def restore_fov(self):
        with self._lock:
            self._fov = None
            if self._orbit:
                # Keep exactly the same relative eye/target. The next render
                # selects its current native focal, not a stale saved lens value.
                self._publish()
            else:
                caves.preflight(self.backend)

    def center_on_target(self, distance, look_height):
        with self._lock:
            player = self._field()[2]
            yaw, pitch = self._native_pose().yaw_pitch()
            target = Vec3(0, look_height, 0)
            self.write_orbit_params(player + target, math.degrees(yaw), math.degrees(pitch),
                                    distance, target_offset=target)
            relative = self._last_orbit
            return CameraPose(player + relative.eye, player + relative.target)

    def read_aim(self):
        return self.read_game_pose().target

    def read_eye_base(self):
        with self._lock:
            return self._native_pose().eye

    def read_camera_forward(self):
        with self._lock:
            pose = self.read_game_pose()
            forward = pose.target - pose.eye
            if not self._valid_pose(pose):
                raise caves.PatchConflict("invalid Grandia II camera direction")
            return forward.scaled(1.0 / forward.length())

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
        with self._lock:
            return self.backend.read_u32(self.heartbeat_addr())

    # Compatibility hooks intentionally do not modify native camera, projection,
    # right-stick inputs, or game time. Free Camera is not advertised.
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
