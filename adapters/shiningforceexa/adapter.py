"""Exa camera control through the game's own parameters, without code caves.

The Neo-like layout was verified, not inherited: Exa has a different actor
layout, defaults and input routine. All writes go through the supplied backend.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from core.camera_math.orbit import (
    CameraPose, Vec3, FOV_SCALE_REF, FOV_MIN_DEG, FOV_MAX_DEG, orbit_pose,
)
from . import memory_map as mm

DISTANCE_RANGE = (300.0, 6000.0)
LOOK_HEIGHT_RANGE = (-400.0, 400.0)
FIELD_DISTANCE_RANGE = (100.0, 10000.0)


class PatchConflict(RuntimeError):
    """Unknown instructions, gate or active camera: do not force an overwrite."""


@dataclass
class AdapterInfo:
    game_id: str = ""
    crc: str = ""
    title: str = ""
    matched: bool = False
    reason: str = ""


@dataclass
class SceneState:
    player: Vec3
    game_pose: CameraPose
    fov_deg: float
    max_dist_game: float
    valid: bool = True
    reason: str = ""


def fov_from_scale(sx: float) -> float:
    return 2 * math.degrees(math.atan(1 / sx)) if math.isfinite(sx) and sx > 1e-9 else 0.0


class SFExaAdapter:
    name = "SFEXA"
    display_name = "Shining Force Exa"
    LOOK_HEIGHT_POSITIVE_IS = "up"
    PITCH_POSITIVE_IS = "above"
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = -1.0
    PITCH_RANGE = (-89.5, 25.0)
    DISTANCE_RANGE = DISTANCE_RANGE
    LOOK_HEIGHT_RANGE = LOOK_HEIGHT_RANGE
    OFFSET_RANGE = (-80.0, 80.0)
    accepts_look_height = True
    uses_offset_injection = False
    field_projection_centre = 0.0
    CAM_EYE_ADDR = CAM_EYE_BASE_ADDR = mm.CAM_EYE
    CAM_TARGET_ADDR = CAM_PLAYER_ADDR = mm.CAM_FOCUS
    # Not used: the runtime skips offset publication for this adapter.
    CAM_EYE_OFFSET_ADDR = mm.CAM_EYE

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=False, target_offsets=False, per_frame_write=False)
        self._orbit_on = False
        self._fov_on = False
        self._saved: dict[int, int] = {}
        self._written: dict[int, int] = {}
        self._saved_fov: int | None = None
        self._written_fov: int | None = None
        self._last_orbit: tuple | None = None
        self._needs_orbit_republish = False

    def identify(self) -> AdapterInfo:
        try:
            gid, crc, title = self.backend.game_id().strip(), self.backend.crc().strip(), self.backend.title().strip()
            ok = (gid.upper(), crc.upper()) == (mm.GAME_ID, mm.DISC_CRC)
            self.info = AdapterInfo(gid, crc, title, ok, "" if ok else f"expected {mm.GAME_ID}/{mm.DISC_CRC}")
        except Exception as exc:
            self.info = AdapterInfo(reason=f"PINE error: {exc}")
        return self.info

    def _camera_ok(self) -> bool:
        return self.backend.read_u32(mm.CAM_ACTIVE_PTR) == mm.CAM_STRUCT

    def _require_camera(self):
        if not self._camera_ok():
            raise PatchConflict("active Exa camera allocation changed")

    def read_player(self) -> Vec3:
        actor = self.backend.read_u32(mm.PARTY_ACTOR_PTR)
        if actor < 0x100000 or actor + mm.PARTY_POS_OFFSET + 12 > 0x2000000 or actor & 0xF:
            return Vec3(0, 0, 0)
        return Vec3(*self.backend.read_floats(actor + mm.PARTY_POS_OFFSET, 3))

    def read_game_pose(self) -> CameraPose:
        return CameraPose(Vec3(*self.backend.read_floats(mm.CAM_EYE, 3)),
                          Vec3(*self.backend.read_floats(mm.CAM_FOCUS, 3)))

    def read_height(self):
        return self.backend.read_floats(mm.CAM_HEIGHT, 1)[0]

    def read_aim(self):
        return self.read_game_pose().target

    def read_eye_base(self):
        return self.read_game_pose().eye

    def read_camera_forward(self):
        p = self.read_game_pose()
        v = p.target - p.eye
        return v.scaled(1 / v.length()) if v.length() > 1e-6 else Vec3(0, 0, -1)

    def place_looking_at(self, target, distance):
        return target - self.read_camera_forward().scaled(distance)

    def read_fov_scale(self):
        vp = self.backend.read_floats(mm.CAM_VP, 12)
        return math.sqrt(sum(vp[i] ** 2 for i in (0, 4, 8)))

    def read_fov_deg(self):
        # Actual rendered projection, NOT the control halfword/mirror.
        return fov_from_scale(self.read_fov_scale())

    def read_scene(self):
        player, pose = self.read_player(), self.read_game_pose()
        valid = self._camera_ok()
        valid = valid and self.backend.read_u32(mm.CAM_MODE) in mm.FIELD_CAMERA_MODES
        valid = valid and self.backend.read_u32(mm.CAM_FOCUS_MODE) == mm.PARTY_FOCUS_MODE
        valid = valid and all(math.isfinite(v) and abs(v) < 1e6
                              for v in (*player.as_tuple(), *pose.eye.as_tuple(), *pose.target.as_tuple()))
        # Focus smoothing deliberately lags on stairs. No focus.y == actor.y + height test.
        return SceneState(player, pose, self.read_fov_deg(), pose.distance(), valid,
                          "" if valid else "not the verified Exa party camera")

    def is_field_like(self, scene):
        return (scene.valid and max(abs(v) for v in scene.player.as_tuple()) > .05
                and FIELD_DISTANCE_RANGE[0] < scene.game_pose.distance() < FIELD_DISTANCE_RANGE[1])

    def _gate_byte(self):
        return (self.backend.read_u32(mm.SMOOTH_GATE_WORD) >> mm.SMOOTH_GATE_SHIFT) & 255

    def _save(self):
        if not self._saved:
            self._saved = {a: self.backend.read_u32(a) for a in
                           (mm.CAM_YAW_WORD, mm.CAM_DISTANCE, mm.CAM_HEIGHT)}

    def _put(self, addr, word):
        self.backend.write_u32(addr, word)
        self._written[addr] = word

    def _release_params(self):
        # Do not undo a new scene/state's own parameter reset.
        for addr, original in self._saved.items():
            if addr in self._written and self.backend.read_u32(addr) == self._written[addr]:
                self.backend.write_u32(addr, original)
        self._saved.clear()
        self._written.clear()
        self._last_orbit = None
        self._needs_orbit_republish = False

    def _sync_gate(self):
        self._require_camera()
        have = self._gate_byte()
        if have not in (0, 1):
            raise PatchConflict(f"smoothing gate holds {have}")
        on = self._orbit_on or self._fov_on
        if on and have == mm.SMOOTH_GATE_STOCK:
            # A loaded stock state (or native reset) can be observed by either
            # FOV servicing or Orbit servicing first. Capture its own baseline
            # before disabling the gate, regardless of which owner noticed it.
            self._saved.clear()
            self._written.clear()
            if self._fov_on:
                self._saved_fov = self.backend.read_u32(mm.CAM_FOV_WORD) >> 16
            self._needs_orbit_republish = self._orbit_on and self._last_orbit is not None
        if on:
            self._save()
        elif self._saved:
            self._release_params()
        want = 0 if on else 1
        if have != want:
            w = self.backend.read_u32(mm.SMOOTH_GATE_WORD)
            self.backend.write_u32(mm.SMOOTH_GATE_WORD,
                                   (w & ~(255 << mm.SMOOTH_GATE_SHIFT)) | (want << mm.SMOOTH_GATE_SHIFT))
        return have != want

    def set_patch(self, on):
        # Validate before claiming ownership or capturing data.
        self._require_camera()
        if self._gate_byte() not in (0, 1):
            raise PatchConflict("unknown smoothing gate")
        self._orbit_on = bool(on)
        changed = self._sync_gate()
        overwritten = any(self.backend.read_u32(a) != w for a, w in self._written.items())
        if on and (changed or overwritten or self._needs_orbit_republish) and self._last_orbit is not None:
            self.write_orbit_params(*self._last_orbit[:4], look_height=self._last_orbit[4])
            self._needs_orbit_republish = False

    def patch_state(self):
        return {0: "applied", 1: "stock"}.get(self._gate_byte(), "unknown")

    def patch_active(self):
        return self._camera_ok() and self._gate_byte() == 0

    hook_active = patch_active

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *, look_height=None):
        self._require_camera()
        if look_height is None:
            look_height = centre.y - self.read_player().y
        values = (yaw_deg, pitch_deg, distance, look_height)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("non-finite Exa camera parameter")
        self._save()
        yaw = round(((yaw_deg - mm.YAW_FIELD_OFFSET_DEG + 180) % 360 - 180) * mm.ANGLE_UNITS_PER_DEG) & 65535
        pitch = round(pitch_deg * mm.ANGLE_UNITS_PER_DEG) & 65535
        self._put(mm.CAM_YAW_WORD, yaw | (pitch << 16))
        for addr, value in ((mm.CAM_DISTANCE, distance), (mm.CAM_HEIGHT, mm.STOCK_HEIGHT + look_height)):
            self._put(addr, struct.unpack('<I', struct.pack('<f', value))[0])
        self._last_orbit = (centre, yaw_deg, pitch_deg, distance, look_height)

    def center_on_target(self, distance, look_height):
        """Native centring boundary used by the runtime; never writes the eye output."""
        scene = self.read_scene()
        if not self.is_field_like(scene):
            raise PatchConflict("not the verified Exa party camera")
        yaw, pitch = scene.game_pose.yaw_pitch()
        self.set_patch(True)
        self.write_orbit_params(scene.player, math.degrees(yaw), math.degrees(pitch),
                                distance, look_height=look_height)
        target = Vec3(scene.player.x, scene.player.y + mm.STOCK_HEIGHT + look_height, scene.player.z)
        return orbit_pose(target, yaw, pitch, distance)

    def write_pose(self, pose):
        y, p = pose.yaw_pitch()
        self.write_orbit_params(Vec3(pose.target.x, pose.target.y - mm.STOCK_HEIGHT, pose.target.z),
                                math.degrees(y), math.degrees(p), pose.distance())

    def write_fov_deg(self, deg):
        self._require_camera()
        if not math.isfinite(deg):
            raise ValueError("non-finite FOV")
        aspect = self.backend.read_floats(mm.CAM_ASPECT, 1)[0]
        if not math.isfinite(aspect) or not .5 < aspect < 3:
            raise PatchConflict("invalid projection aspect")
        deg = min(max(deg, FOV_MIN_DEG), FOV_MAX_DEG)
        vfov = 2 * math.atan(math.tan(math.radians(deg) / 2) / aspect)
        units = round(math.degrees(vfov) * mm.ANGLE_UNITS_PER_DEG)
        gate = self._gate_byte()
        if gate not in (0, 1):
            raise PatchConflict("unknown smoothing gate")
        if self._saved_fov is None:
            self._saved_fov = self.backend.read_u32(mm.CAM_FOV_WORD) >> 16
        self._fov_on = True
        self._sync_gate()
        word = self.backend.read_u32(mm.CAM_FOV_WORD)
        self.backend.write_u32(mm.CAM_FOV_WORD, (word & 65535) | (units << 16))
        self._written_fov = units

    def restore_fov(self):
        if self._saved_fov is not None:
            self._require_camera()
            word = self.backend.read_u32(mm.CAM_FOV_WORD)
            if word >> 16 == self._written_fov:
                self.backend.write_u32(mm.CAM_FOV_WORD, (word & 65535) | (self._saved_fov << 16))
            self._saved_fov = self._written_fov = None
        if self._fov_on:
            self._fov_on = False
            self._sync_gate()

    def capture_original_fov(self):
        if self._saved_fov is None:
            return self.read_fov_deg()
        aspect = self.backend.read_floats(mm.CAM_ASPECT, 1)[0]
        v = math.radians(self._saved_fov / mm.ANGLE_UNITS_PER_DEG)
        return math.degrees(2 * math.atan(aspect * math.tan(v / 2)))

    def fov_in_sync(self, deg):
        return abs(self.read_fov_deg() - deg) < .05

    def set_stick_block(self, on):
        pairs = ((mm.PAD_RX_LOAD, mm.PAD_RX_WORD), (mm.PAD_RY_LOAD, mm.PAD_RY_WORD))
        # Check ALL sites before ANY write. Mixed known stock/ours is recoverable.
        have = [self.backend.read_u32(a) for a, _ in pairs]
        if any(w not in (stock, mm.PAD_NEUTRAL_WORD) for w, (_, stock) in zip(have, pairs)):
            raise PatchConflict("unknown Exa right-stick load instruction")
        for w, (addr, stock) in zip(have, pairs):
            want = mm.PAD_NEUTRAL_WORD if on else stock
            if w != want:
                self.backend.write_u32(addr, want)

    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE_GAME, look_height=0.0, fov_deg=fov_from_scale(mm.STOCK_PROJ_SX))

    def default_look_height(self):
        return 0.0

    def heartbeat_addr(self):
        return mm.CAM_EYE

    def heartbeat_word(self):
        return self.backend.read_u32(mm.CAM_EYE)

    def read_projection(self):
        return FOV_SCALE_REF, 0.0

    # No offset-injection or projection-redirection writes in Exa.
    def write_eye_offset(self, offset): pass
    def clear_eye_offset(self): pass
    def write_aim(self, target): pass
    def write_projection_centre(self, centre): pass
    def write_projection_scale(self, scale): pass
    def set_projection_source(self, redirected): pass
    def restore_aim(self): pass
    def write_walk_target(self, centre): pass
    def copy_stock_params(self): pass


def probe(backend):
    ad = SFExaAdapter(backend)
    out = dict(info=ad.identify().__dict__)
    if ad.info.matched:
        s = ad.read_scene()
        out['scene'] = dict(player=s.player.as_tuple(), eye=s.game_pose.eye.as_tuple(),
                            target=s.game_pose.target.as_tuple(), distance=s.game_pose.distance(),
                            height=ad.read_height(), fov_deg=ad.read_fov_deg(),
                            field_like=ad.is_field_like(s), gate=ad.patch_state())
    return out
