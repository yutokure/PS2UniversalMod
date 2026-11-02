"""Shining Force Neo field-camera adapter.

The adapter is the only place that knows Shining Force Neo addresses.  It speaks the
same protocol as the FFX-2 adapter, so the camera engine and the GUI work unchanged.

Unlike FFX-2, the game here has no per-frame eye slot to inject into.  Its own
controller (FUN_001D6160) builds the eye and the focus from a yaw, a pitch, a distance
and a focus height every frame.  So the orbit writes those four fields
(write_orbit_params), and the smoothing gate (set_patch) keeps the game from pulling the
yaw back.  The field of view is a scale on the view-projection, applied by a code cave
at the game's VP load (fov_cave.py).  Engine writes to the eye offset and aim points go
to mod scratch slots the game never reads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.camera_math.orbit import (
    FOV_MAX_DEG,
    FOV_MIN_DEG,
    FOV_SCALE_REF,
    CameraPose,
    Vec3,
)

from . import fov_cave
from . import pad_cave
from . import memory_map as mm


#: distance range that counts as a field camera.  The stock field distance is 2000 and
#: the scripted gate camera uses 1300.  The orbit writes its own distance, so the guard
#: only rejects loading screens and other broken states, not the orbit's own value.
FIELD_DISTANCE_RANGE = (100.0, 10000.0)
#: slider ranges the GUI uses for this game (FFX-2 keeps its own)
DISTANCE_RANGE = (300.0, 6000.0)
LOOK_HEIGHT_RANGE = (-400.0, 400.0)


class PatchConflict(RuntimeError):
    """A patched byte holds a value that is neither its stock nor its applied form.

    Raised before anything is written, so unknown state is never overwritten.
    """


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
    return (deg + 180.0) % 360.0 - 180.0


def fov_from_scale(sx: float) -> float:
    """Horizontal field of view in degrees for a projection x-scale (1 / tan(fov/2))."""
    if sx <= 1e-9:
        return 0.0
    return 2.0 * math.degrees(math.atan(1.0 / sx))


class SFNeoAdapter:
    name = "SFNEO"
    display_name = "Shining Force Neo"
    #: the engine's offset path writes here; the game never reads these slots
    CAM_EYE_ADDR = mm.SCRATCH_EYE
    CAM_TARGET_ADDR = mm.SCRATCH_AIM
    CAM_EYE_OFFSET_ADDR = mm.SCRATCH_EYE_OFFSET
    CAM_PLAYER_ADDR = mm.CAM_FOCUS
    CAM_EYE_BASE_ADDR = mm.CAM_EYE
    #: the game places the eye itself from yaw/pitch/distance; no offset injection
    uses_offset_injection = False
    #: the projection is not the FFX-2 scale; read_projection reports the neutral value
    field_projection_centre = 0.0
    DISTANCE_RANGE = DISTANCE_RANGE
    LOOK_HEIGHT_RANGE = LOOK_HEIGHT_RANGE

    def __init__(self, backend) -> None:
        self.backend = backend
        self.info = AdapterInfo()
        self.features = {
            "orbit": True,
            "free_camera": False,
            "fov": True,
            "position_offsets": False,
            "target_offsets": False,
            "per_frame_write": False,
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

    # --- reads ---------------------------------------------------------
    def read_height(self) -> float:
        """Focus height above the party point (stock 100)."""
        return self.backend.read_floats(mm.CAM_HEIGHT, 1)[0]

    def read_player(self) -> Vec3:
        """Party anchor: the party point the controller builds the focus from.

        It is read from the actor, not from the focus minus the height: the orbit changes
        the height, and the focus only follows it on the next frame, so a focus-based
        anchor would move with the orbit's own writes.
        """
        x, y, z = self.backend.read_floats(mm.PARTY_POS, 3)
        return Vec3(x, y, z)

    def read_game_pose(self) -> CameraPose:
        """The pose the game's own controller produced this frame."""
        ex, ey, ez, _ = self.backend.read_floats(mm.CAM_EYE, 4)
        tx, ty, tz, _ = self.backend.read_floats(mm.CAM_FOCUS, 4)
        return CameraPose(eye=Vec3(ex, ey, ez), target=Vec3(tx, ty, tz))

    def read_aim(self) -> Vec3:
        x, y, z, _ = self.backend.read_floats(mm.CAM_FOCUS, 4)
        return Vec3(x, y, z)

    def read_eye_base(self) -> Vec3:
        x, y, z, _ = self.backend.read_floats(mm.CAM_EYE, 4)
        return Vec3(x, y, z)

    def read_camera_forward(self) -> Vec3:
        """Unit view direction: from the eye towards the focus."""
        pose = self.read_game_pose()
        f = pose.target - pose.eye
        n = f.length()
        if n < 1e-6:
            return Vec3(0.0, 0.0, -1.0)
        return f.scaled(1.0 / n)

    def place_looking_at(self, target: Vec3, distance: float) -> Vec3:
        f = self.read_camera_forward()
        return Vec3(target.x - f.x * distance,
                    target.y - f.y * distance,
                    target.z - f.z * distance)

    def read_fov_scale(self) -> float:
        """The x projection scale now in the VP: the norm of column 0 (sx)."""
        vp = self.backend.read_floats(mm.CAM_VP, 16)
        return math.sqrt(vp[0] * vp[0] + vp[4] * vp[4] + vp[8] * vp[8])

    def read_fov_deg(self) -> float:
        """Horizontal field of view the frame is drawn with (includes any FOV override)."""
        return fov_from_scale(self.read_fov_scale())

    def read_scene(self) -> SceneState:
        player = self.read_player()
        pose = self.read_game_pose()
        ok = all(abs(v) < 1e6 for v in (*player.as_tuple(), *pose.eye.as_tuple(), *pose.target.as_tuple()))
        ok = ok and pose.distance() > 0.01
        # the focus must be the party point plus the height; otherwise the controller is
        # not in its field state (loading, events) and nothing should be written
        if ok:
            ok = abs(pose.target.y - (player.y + self.read_height())) < 1.0
        return SceneState(player=player, game_pose=pose, fov_deg=0.0,
                          max_dist_game=pose.distance(),
                          valid=ok, reason="" if ok else "camera data not plausible")

    # --- writes --------------------------------------------------------
    def write_eye_offset(self, offset: Vec3) -> None:
        """Scratch only: this game takes the eye from yaw/pitch/distance."""
        self.backend.write_float_block(self.CAM_EYE_OFFSET_ADDR, [offset.x, offset.y, offset.z, 0.0])

    def clear_eye_offset(self) -> None:
        self.backend.write_float_block(self.CAM_EYE_OFFSET_ADDR, [0.0, 0.0, 0.0, 0.0])

    def write_aim(self, target: Vec3) -> None:
        """Scratch only: the focus is the game's own point and is not moved here."""
        self.backend.write_float_block(self.CAM_TARGET_ADDR, [target.x, target.y, target.z, 0.0])

    def restore_aim(self) -> None:
        return None

    def write_orbit_params(self, centre: Vec3, yaw_deg: float, pitch_deg: float,
                           distance: float) -> None:
        """Publish the orbit to the game's camera controller.

        ``yaw_deg`` and ``pitch_deg`` are the eye angles the engine uses (the eye offset
        is ``distance * (sin yaw cos pitch, -sin pitch, cos yaw cos pitch)`` about the
        focus).  The yaw field holds ``yaw - 180`` and the controller adds 180 back.

        ``centre`` is the engine's orbit centre: the party anchor plus the look height.
        The game's focus is the anchor plus the focus height, so the height field is set to
        ``STOCK_HEIGHT + (centre.y - anchor.y)``: a look height of 0 is the stock framing.
        """
        anchor = self.read_player()
        height = mm.STOCK_HEIGHT + (centre.y - anchor.y)
        field_yaw = _wrap_deg(yaw_deg - mm.YAW_FIELD_OFFSET_DEG)
        yaw_u16 = int(round(field_yaw * mm.ANGLE_UNITS_PER_DEG)) & 0xFFFF
        pitch_u16 = int(round(pitch_deg * mm.ANGLE_UNITS_PER_DEG)) & 0xFFFF
        self.backend.write_u32(mm.CAM_YAW_WORD, yaw_u16 | (pitch_u16 << 16))
        self.backend.write_float_block(mm.CAM_DISTANCE, [distance])
        self.backend.write_float_block(mm.CAM_HEIGHT, [height])

    def write_pose(self, pose: CameraPose) -> None:
        """Express a pose as yaw, pitch, distance and focus height and publish it.

        ``pose.target`` is the focus the game should use, so the orbit centre is the
        focus minus the stock height.
        """
        yaw, pitch = pose.yaw_pitch()
        t = pose.target
        centre = Vec3(t.x, t.y - mm.STOCK_HEIGHT, t.z)
        self.write_orbit_params(centre, math.degrees(yaw), math.degrees(pitch), pose.distance())

    def write_walk_target(self, centre: Vec3) -> None:
        """The game's walk direction follows its own eye; nothing to aim here."""
        return None

    def copy_stock_params(self) -> None:
        """Nothing to mirror: with the gate back on, the game's own smoothing takes over."""
        return None

    # --- field of view ---------------------------------------------------
    def _stock_sx(self) -> float:
        """The unscaled x projection scale: the VP norm with the cave's ratio taken out."""
        sx = self.read_fov_scale()
        if fov_cave.call_site_state(self.backend) == "patched":
            flag, ratio = fov_cave.read_ratio(self.backend)
            if flag and ratio > 1e-9:
                return sx / ratio
        return sx

    def write_fov_deg(self, deg: float) -> None:
        """Set the horizontal field of view by scaling the projection in the VP load.

        The ratio is taken against the unscaled scale, so changing the FOV again does not
        compound.  The cave is installed on first use.
        """
        deg = min(max(deg, FOV_MIN_DEG), FOV_MAX_DEG)
        target_sx = 1.0 / math.tan(math.radians(deg) / 2.0)
        stock = self._stock_sx()
        fov_cave.install(self.backend)
        fov_cave.set_ratio(self.backend, target_sx / stock, on=True)

    def restore_fov(self) -> None:
        """Stock field of view: clear the flag, then give the game its own VP call back."""
        if fov_cave.call_site_state(self.backend) != "patched":
            return
        fov_cave.set_ratio(self.backend, 1.0, on=False)
        fov_cave.uninstall_call_site(self.backend)

    def capture_original_fov(self) -> float:
        """The stock field of view in degrees (the unscaled projection)."""
        return fov_from_scale(self._stock_sx())

    def fov_in_sync(self, deg: float) -> bool:
        """True when the frame is already drawn at ``deg`` (checked by the engine)."""
        return abs(self.read_fov_deg() - deg) <= 0.05

    # --- right stick ----------------------------------------------------------
    def set_stick_block(self, on: bool) -> None:
        """Hold the game's right stick at centre (orbit on) or give it back (off).

        The right stick is the menu's cursor input in this game.  The orbit reads the
        stick on the PC side, so the game's copy of it is held at centre while the orbit
        runs.  The left stick and the buttons are not touched.
        """
        if on:
            pad_cave.install(self.backend)
            pad_cave.set_flag(self.backend, True)
        else:
            pad_cave.set_flag(self.backend, False)
            pad_cave.uninstall_call_site(self.backend)

    # --- projection (the FFX-2 scale; not used by this game) -------------------
    def read_projection(self) -> tuple[float, float]:
        """Reported at the neutral FFX-2 values so the engine leaves the projection alone."""
        return FOV_SCALE_REF, 0.0

    def write_projection_centre(self, centre: float) -> None:
        return None

    def write_projection_scale(self, scale: float) -> None:
        return None

    def set_projection_source(self, redirected: bool) -> None:
        return None

    # --- settings and scene helpers -------------------------------------------
    def default_settings(self) -> dict:
        """Starting GUI values for this game (the stock framing)."""
        return {
            "distance": mm.STOCK_DISTANCE_GAME,
            "look_height": 0.0,
            "fov_deg": fov_from_scale(mm.STOCK_PROJ_SX),
        }

    def default_look_height(self) -> float:
        return 0.0

    def is_field_like(self, scene: SceneState) -> bool:
        """Refuse to write unless the camera looks like the field camera."""
        if not scene.valid:
            return False
        p = scene.player.as_tuple()
        if max(abs(v) for v in p) < 0.05:
            return False          # anchor reads (0,0,0): loading / not in a field
        d = scene.game_pose.distance()
        return FIELD_DISTANCE_RANGE[0] < d < FIELD_DISTANCE_RANGE[1]

    def heartbeat_word(self) -> int:
        """Word the game rewrites each frame; the engine uses it to phase-lock."""
        return self.backend.read_u32(mm.CAM_EYE)

    def heartbeat_addr(self) -> int:
        return mm.CAM_EYE

    # --- smoothing gate (the patch) -------------------------------------
    def _gate_byte(self) -> int:
        word = self.backend.read_u32(mm.SMOOTH_GATE_WORD)
        return (word >> mm.SMOOTH_GATE_SHIFT) & 0xFF

    def set_patch(self, on: bool) -> None:
        """Clear (on) or restore (off) the smoothing gate byte.

        Compare-and-swap on the one byte: it is changed only while it holds the other
        form, so an unexpected value raises PatchConflict instead of being overwritten.
        """
        want = mm.SMOOTH_GATE_APPLIED if on else mm.SMOOTH_GATE_STOCK
        have = self._gate_byte()
        if have == want:
            return
        if have not in (mm.SMOOTH_GATE_STOCK, mm.SMOOTH_GATE_APPLIED):
            raise PatchConflict(f"smoothing gate 0x{mm.SMOOTH_GATE:08X} holds {have}")
        word = self.backend.read_u32(mm.SMOOTH_GATE_WORD)
        mask = 0xFF << mm.SMOOTH_GATE_SHIFT
        word = (word & ~mask) | (want << mm.SMOOTH_GATE_SHIFT)
        self.backend.write_u32(mm.SMOOTH_GATE_WORD, word)

    def patch_state(self) -> str:
        """applied, stock or unknown for the smoothing gate."""
        have = self._gate_byte()
        if have == mm.SMOOTH_GATE_APPLIED:
            return "applied"
        if have == mm.SMOOTH_GATE_STOCK:
            return "stock"
        return "unknown"

    def patch_active(self) -> bool:
        """True when the orbit holds the smoothing gate (the GUI's patch row)."""
        try:
            return self._gate_byte() == mm.SMOOTH_GATE_APPLIED
        except Exception:  # noqa: BLE001
            return False

    def hook_active(self) -> bool:
        return self.patch_active()


def probe(backend) -> dict:
    """Standalone health probe used by tools and tests."""
    ad = SFNeoAdapter(backend)
    info = ad.identify()
    out = {"info": info.__dict__}
    if info.matched:
        sc = ad.read_scene()
        out["scene"] = {
            "player": sc.player.as_tuple(),
            "eye": sc.game_pose.eye.as_tuple(),
            "target": sc.game_pose.target.as_tuple(),
            "distance": sc.game_pose.distance(),
            "height": ad.read_height(),
            "fov_deg": ad.read_fov_deg(),
            "field_like": ad.is_field_like(sc),
            "valid": sc.valid,
            "gate": ad.patch_state(),
        }
    return out
