"""Suikoden V field-camera adapter.

The adapter is the only place that knows Suikoden V addresses.  It speaks the same protocol
as the FFX-2 and Shining Force Neo adapters, so the camera engine and the GUI work unchanged.

How it controls the camera (see ``memory_map.py`` and ``caves.py``): the game's field camera
update stores the focus, distance, pitch and yaw into globals and sets the FOV every frame.
A code cave at that stretch takes those four values, and a world offset of the focus, from a
mod block when the matching flag is set.  The host writes the block only when a value
changes; the game does the rest, so the camera moves in the same frame and the walk code,
which reads the yaw global, follows the camera.

Coordinates: the engine's camera model is FFX-2's (+Y down, positive pitch above the
target, eye = target + (sin yaw cos pitch, -sin pitch, cos yaw cos pitch) * d).  Suikoden V
has +Y up, so the adapter negates Y when it reports positions and un-negates it when it
writes, and maps yaw by ``game_yaw = engine_yaw - 180`` (pitch is the same angle).
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from core.camera_math.orbit import (
    FOV_MAX_DEG,
    FOV_MIN_DEG,
    FOV_SCALE_REF,
    CameraPose,
    Vec3,
)

from . import caves
from . import memory_map as mm

#: distance range that counts as a field camera and the slider range of the GUI
FIELD_DISTANCE_RANGE = (5.0, 5000.0)
DISTANCE_RANGE = (50.0, 1500.0)
LOOK_HEIGHT_RANGE = (-200.0, 200.0)
#: the camera update runs every frame in the field; no heartbeat for this long = not a field
HEARTBEAT_TIMEOUT_S = 0.75

#: scratch slots the engine's offset path writes to (the game never reads them)
SCRATCH_EYE = mm.MOD_BLOCK + 0x50
SCRATCH_EYE_OFFSET = mm.MOD_BLOCK + 0x60
SCRATCH_AIM = mm.MOD_BLOCK + 0x70


@dataclass
class AdapterInfo:
    game_id: str = ""
    crc: str = ""
    title: str = ""
    matched: bool = False
    reason: str = ""


@dataclass
class SceneState:
    """Per-frame snapshot of what the game currently has."""
    player: Vec3
    game_pose: CameraPose
    fov_deg: float
    max_dist_game: float
    valid: bool = True
    reason: str = ""


def _wrap_deg(deg: float) -> float:
    return deg % 360.0


def fov_from_scale(sx: float) -> float:
    if sx <= 1e-9:
        return 0.0
    return 2.0 * math.degrees(math.atan(1.0 / sx))


class Suikoden5Adapter:
    name = "SUIKODEN5"
    display_name = "Suikoden V"
    CAM_EYE_ADDR = SCRATCH_EYE
    CAM_TARGET_ADDR = SCRATCH_AIM
    CAM_EYE_OFFSET_ADDR = SCRATCH_EYE_OFFSET
    CAM_PLAYER_ADDR = mm.G_FOCUS
    CAM_EYE_BASE_ADDR = mm.G_EYE
    #: the camera is placed by the game from yaw/pitch/distance; no eye offset injection
    uses_offset_injection = False
    #: the engine passes the GUI camera-position offsets to write_orbit_params
    accepts_pos_offset = True
    field_projection_centre = 0.0
    DISTANCE_RANGE = DISTANCE_RANGE
    LOOK_HEIGHT_RANGE = LOOK_HEIGHT_RANGE
    #: the native zoom is three stages (R1, or the right stick)
    ZOOM_STAGES = len(mm.ZOOM_DISTANCES)

    def __init__(self, backend) -> None:
        self.backend = backend
        self.info = AdapterInfo()
        self._lock = threading.RLock()
        self._hb_seen: int | None = None
        self._hb_time = 0.0
        self.features = {
            "orbit": True,
            "free_camera": False,
            "fov": True,
            "position_offsets": True,
            "target_offsets": True,
            "per_frame_write": False,
            "native_zoom": True,
        }

    # --- identity ------------------------------------------------------
    def identify(self) -> AdapterInfo:
        try:
            gid = self.backend.game_id().strip()
            crc = self.backend.crc().strip()
            title = self.backend.title().strip()
        except Exception as exc:  # noqa: BLE001
            self.info = AdapterInfo(matched=False, reason=f"PINE error: {exc}")
            return self.info
        ok = gid.upper() == mm.GAME_ID.upper() and crc.upper() == mm.DISC_CRC.upper()
        self.info = AdapterInfo(game_id=gid, crc=crc, title=title, matched=ok,
                                reason="" if ok else f"expected {mm.GAME_ID}/{mm.DISC_CRC}")
        return self.info

    # --- helpers ---------------------------------------------------------
    def _mb(self, off: int) -> int:
        return mm.MOD_BLOCK + off

    def _cave_live(self) -> bool:
        """True once the camera cave has run at least once (the block holds our data)."""
        try:
            return (caves.block_valid(self.backend)
                    and self.backend.read_u32(self._mb(mm.MB_HEARTBEAT)) != 0
                    and caves.camera_site_state(self.backend) == "patched")
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _flip(x: float, y: float, z: float) -> Vec3:
        return Vec3(x, -y, z)

    # --- reads -------------------------------------------------------------
    def read_player(self) -> Vec3:
        """Party anchor in the engine frame: the focus before the mod offset."""
        if self._cave_live():
            x, y, z = self.backend.read_floats(self._mb(mm.MB_NATIVE_FOCUS), 3)
        else:
            x, y, z = self.backend.read_floats(mm.G_FOCUS, 3)
        return self._flip(x, y, z)

    def read_game_pose(self) -> CameraPose:
        ex, ey, ez = self.backend.read_floats(mm.G_EYE, 3)
        tx, ty, tz = self.backend.read_floats(mm.G_FOCUS, 3)
        return CameraPose(eye=self._flip(ex, ey, ez), target=self._flip(tx, ty, tz))

    def read_aim(self) -> Vec3:
        x, y, z = self.backend.read_floats(mm.G_FOCUS, 3)
        return self._flip(x, y, z)

    def read_eye_base(self) -> Vec3:
        x, y, z = self.backend.read_floats(mm.G_EYE, 3)
        return self._flip(x, y, z)

    def read_camera_forward(self) -> Vec3:
        pose = self.read_game_pose()
        f = pose.target - pose.eye
        n = f.length()
        if n < 1e-6:
            return Vec3(0.0, 0.0, -1.0)
        return f.scaled(1.0 / n)

    def place_looking_at(self, target: Vec3, distance: float) -> Vec3:
        f = self.read_camera_forward()
        return Vec3(target.x - f.x * distance, target.y - f.y * distance,
                    target.z - f.z * distance)

    def read_fov_deg(self) -> float:
        """Horizontal field of view the frame is drawn with (includes any override)."""
        return self.backend.read_floats(mm.G_FOV, 1)[0]

    def read_fov_scale(self) -> float:
        fov = self.read_fov_deg()
        if fov <= 1e-6 or fov >= 179.0:
            return 0.0
        return 1.0 / math.tan(math.radians(fov) / 2.0)

    def read_native(self) -> dict:
        """The game's own goal values (what the camera would use without the mod)."""
        d, p, y, f = (self.backend.read_floats(self._mb(o), 1)[0] for o in (
            mm.MB_NATIVE_DISTANCE, mm.MB_NATIVE_PITCH, mm.MB_NATIVE_YAW, mm.MB_NATIVE_FOV))
        return {"distance": d, "pitch": p, "yaw": y, "fov": f}

    def read_scene(self) -> SceneState:
        player = self.read_player()
        pose = self.read_game_pose()
        ok = all(abs(v) < 1e6 for v in (*player.as_tuple(), *pose.eye.as_tuple(),
                                        *pose.target.as_tuple()))
        ok = ok and pose.distance() > 0.01
        return SceneState(player=player, game_pose=pose, fov_deg=self.read_fov_deg(),
                          max_dist_game=pose.distance(), valid=ok,
                          reason="" if ok else "camera data not plausible")

    def is_field_like(self, scene: SceneState) -> bool:
        """Refuse to write unless the field camera update is running."""
        if not scene.valid:
            return False
        if max(abs(v) for v in scene.player.as_tuple()) < 0.05:
            return False          # focus reads (0,0,0): loading / not in a field
        d = scene.game_pose.distance()
        if not (FIELD_DISTANCE_RANGE[0] < d < FIELD_DISTANCE_RANGE[1]):
            return False
        return self._heartbeat_alive()

    def _heartbeat_alive(self) -> bool:
        """The camera update runs each frame in a field; events and menus stop it."""
        try:
            if not self._cave_live():
                return True       # nothing to judge by before the cave has run once
            hb = self.backend.read_u32(self._mb(mm.MB_HEARTBEAT))
        except Exception:  # noqa: BLE001
            return False
        now = time.monotonic()
        if self._hb_seen is None or hb != self._hb_seen:
            self._hb_seen, self._hb_time = hb, now
            return True
        return (now - self._hb_time) < HEARTBEAT_TIMEOUT_S

    def heartbeat_word(self) -> int:
        return self.backend.read_u32(self._mb(mm.MB_HEARTBEAT))

    def heartbeat_addr(self) -> int:
        return self._mb(mm.MB_HEARTBEAT)

    # --- writes --------------------------------------------------------------
    def write_eye_offset(self, offset: Vec3) -> None:
        self.backend.write_float_block(self.CAM_EYE_OFFSET_ADDR, [offset.x, offset.y, offset.z, 0.0])

    def clear_eye_offset(self) -> None:
        self.backend.write_float_block(self.CAM_EYE_OFFSET_ADDR, [0.0, 0.0, 0.0, 0.0])

    def write_aim(self, target: Vec3) -> None:
        self.backend.write_float_block(self.CAM_TARGET_ADDR, [target.x, target.y, target.z, 0.0])

    def restore_aim(self) -> None:
        return None

    def write_orbit_params(self, centre: Vec3, yaw_deg: float, pitch_deg: float,
                           distance: float, pos_offset: Vec3 | None = None) -> None:
        """Publish the orbit to the game's camera.

        ``centre`` is the engine's orbit centre (anchor + look height + target offset, in the
        engine's +Y-down frame); the world offset the cave adds to the focus is the
        difference to the anchor, with Y flipped back.  ``pos_offset`` (the GUI camera X/Y/Z)
        moves the whole rig the same way: the camera keeps its direction and slides.
        """
        anchor = self.read_player()
        dx, dy, dz = centre.x - anchor.x, centre.y - anchor.y, centre.z - anchor.z
        if pos_offset is not None:
            dx, dy, dz = dx + pos_offset.x, dy + pos_offset.y, dz + pos_offset.z
        b = self.backend
        with self._lock:
            b.write_floats(self._mb(mm.MB_DISTANCE), [float(distance)])
            b.write_floats(self._mb(mm.MB_PITCH), [float(pitch_deg)])
            b.write_floats(self._mb(mm.MB_YAW), [_wrap_deg(yaw_deg - 180.0)])
            b.write_floats(self._mb(mm.MB_OFF_X), [dx, -dy, dz])
            caves.write_flags(b, caves.read_flags(b) | mm.FLAGS_ORBIT)

    def write_pose(self, pose: CameraPose) -> None:
        yaw, pitch = pose.yaw_pitch()
        t = pose.target
        self.write_orbit_params(t, math.degrees(yaw), math.degrees(pitch), pose.distance())

    def write_walk_target(self, centre: Vec3) -> None:
        """The walk code reads the camera yaw global itself; nothing to aim here."""
        return None

    def copy_stock_params(self) -> None:
        return None

    # --- field of view ----------------------------------------------------------
    def capture_original_fov(self) -> float:
        """The stock field of view in degrees (the game's own goal value)."""
        if self._cave_live():
            return self.read_native()["fov"]
        return self.read_fov_deg()

    def write_fov_deg(self, deg: float) -> None:
        deg = min(max(deg, FOV_MIN_DEG), FOV_MAX_DEG)
        caves.install_camera(self.backend)
        with self._lock:
            self.backend.write_floats(self._mb(mm.MB_FOV), [float(deg)])
            caves.write_flags(self.backend, caves.read_flags(self.backend) | mm.FLAG_FOV)

    def restore_fov(self) -> None:
        if not caves.block_valid(self.backend):
            return
        with self._lock:
            caves.write_flags(self.backend, caves.read_flags(self.backend) & ~mm.FLAG_FOV)
            self._release_camera_hook_if_idle()

    def _release_camera_hook_if_idle(self) -> None:
        """Take the camera hook out once no override flag needs it (stock code runs again)."""
        if caves.read_flags(self.backend) & (mm.FLAGS_ORBIT | mm.FLAG_FOV) == 0:
            caves.uninstall_camera(self.backend)

    def fov_in_sync(self, deg: float) -> bool:
        return abs(self.read_fov_deg() - deg) <= 0.05

    # --- right stick ---------------------------------------------------------------
    def set_stick_block(self, on: bool) -> None:
        """Hold the right stick at centre for the game's zoom input (orbit on) or release it."""
        if on:
            caves.install_zoom(self.backend)
            with self._lock:
                caves.write_flags(self.backend,
                                  caves.read_flags(self.backend) | mm.FLAG_BLOCK_RSTICK)
        else:
            if caves.block_valid(self.backend):
                with self._lock:
                    caves.write_flags(self.backend,
                                      caves.read_flags(self.backend) & ~mm.FLAG_BLOCK_RSTICK)
            caves.uninstall_zoom(self.backend)

    # --- native zoom ------------------------------------------------------------------
    def _ctl(self) -> int | None:
        if not caves.block_valid(self.backend):
            return None
        ptr = self.backend.read_u32(self._mb(mm.MB_CTL_PTR))
        return ptr or None

    def read_zoom_stage(self) -> int | None:
        """The game's own zoom stage (0..2), or None before the cave has seen the camera."""
        ctl = self._ctl()
        if ctl is None:
            return None
        stage = self.backend.read_u32(ctl + mm.CTL_ZOOM_STAGE) & 0xFFFF
        return stage if stage < self.ZOOM_STAGES else None

    @staticmethod
    def stage_distance(stage: int) -> float:
        return mm.ZOOM_DISTANCES[max(0, min(stage, len(mm.ZOOM_DISTANCES) - 1))]

    def set_zoom_stage(self, stage: int) -> float | None:
        """Set the game's stage counter so the next R1 steps on from ``stage``.

        Returns the distance of that stage (the caller applies it to the orbit).  The game's
        own zoom animation is not triggered here; the stage short is only kept in step.
        """
        ctl = self._ctl()
        stage = max(0, min(int(stage), len(mm.ZOOM_DISTANCES) - 1))
        if ctl is None:
            return None
        addr = ctl + mm.CTL_ZOOM_STAGE
        word = self.backend.read_u32(addr)
        self.backend.write_u32(addr, (word & 0xFFFF0000) | stage)
        return self.stage_distance(stage)

    def native_distance(self) -> float | None:
        if not self._cave_live():
            return None
        return self.read_native()["distance"]

    # --- projection (FFX-2 scale; unused here) ------------------------------------------
    def read_projection(self) -> tuple[float, float]:
        return FOV_SCALE_REF, 0.0

    def write_projection_centre(self, centre: float) -> None:
        return None

    def write_projection_scale(self, scale: float) -> None:
        return None

    def set_projection_source(self, redirected: bool) -> None:
        return None

    # --- settings and scene helpers --------------------------------------------------------
    def default_settings(self) -> dict:
        return {
            "distance": mm.STOCK_DISTANCE,
            "yaw_deg": _wrap_signed(mm.STOCK_YAW + 180.0),
            "pitch_deg": mm.STOCK_PITCH,
            "look_height": 0.0,
            "fov_deg": mm.STOCK_FOV,
            "pitch_min_deg": -5.0,
            "pitch_max_deg": 85.0,
        }

    def default_look_height(self) -> float:
        return 0.0

    # --- patch (the cave) ------------------------------------------------------------------
    def set_patch(self, on: bool) -> None:
        """Install the camera cave and set the orbit flags (on), or clear them (off)."""
        if on:
            caves.install_camera(self.backend)
            with self._lock:
                caves.write_flags(self.backend, caves.read_flags(self.backend) | mm.FLAGS_ORBIT)
        else:
            if caves.block_valid(self.backend):
                with self._lock:
                    caves.write_flags(self.backend,
                                      caves.read_flags(self.backend) & ~mm.FLAGS_ORBIT)
                    self._release_camera_hook_if_idle()

    def patch_state(self) -> str:
        """applied, stock or unknown for the camera hook."""
        try:
            state = caves.camera_site_state(self.backend)
            if state == "unknown":
                return "unknown"
            if state == "original":
                return "stock"
            flags = caves.read_flags(self.backend) if caves.block_valid(self.backend) else 0
            return "applied" if flags & mm.FLAGS_ORBIT == mm.FLAGS_ORBIT else "stock"
        except Exception:  # noqa: BLE001
            return "unknown"

    def patch_active(self) -> bool:
        return self.patch_state() == "applied"

    def hook_active(self) -> bool:
        return self.patch_active()

    def uninstall_all(self) -> None:
        """Take every hook out: the game runs its own code again (used on exit and in tests)."""
        if caves.block_valid(self.backend):
            caves.write_flags(self.backend, 0)
        caves.uninstall_zoom(self.backend)
        caves.uninstall_camera(self.backend)


def _wrap_signed(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def probe(backend) -> dict:
    """Standalone health probe used by tools and tests."""
    ad = Suikoden5Adapter(backend)
    info = ad.identify()
    out = {"info": info.__dict__}
    if info.matched:
        sc = ad.read_scene()
        out["scene"] = {
            "player": sc.player.as_tuple(),
            "eye": sc.game_pose.eye.as_tuple(),
            "target": sc.game_pose.target.as_tuple(),
            "distance": sc.game_pose.distance(),
            "fov_deg": ad.read_fov_deg(),
            "field_like": ad.is_field_like(sc),
            "valid": sc.valid,
            "patch": ad.patch_state(),
        }
    return out
