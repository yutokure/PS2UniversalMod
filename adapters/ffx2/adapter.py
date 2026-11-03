"""FFX-2 field camera adapter.

The adapter is the only place that knows FFX-2 addresses.  The core engine,
the GUI and the controller talk to it through the small protocol defined at the
bottom (``CameraAdapter``), so porting the mod to another PS2 title means
implementing that protocol and nothing else.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from core.camera_math.orbit import CameraPose, Vec3, fov_deg_to_scale, scale_to_fov_deg

from . import lookat_cave, memory_map as mm


#: largest plausible stock eye-to-party distance in a field scene
FIELD_EYE_RANGE = 400.0
#: largest plausible stock eye-to-look-at distance (long corridors and map
#: edges point the stock camera far away; orbit replaces the aim anyway)
FIELD_POSE_RANGE = 2000.0


class PatchConflict(RuntimeError):
    """A patched address holds a word that is neither its stock nor its applied form.

    Raised before anything is written, so unknown code is never overwritten.
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


class FFX2Adapter:
    name = "FFX2"
    display_name = "Final Fantasy X-2"
    #: GUI hints (shown under the sliders): the sign conventions of this game's values
    LOOK_HEIGHT_POSITIVE_IS = "down"
    PITCH_POSITIVE_IS = "above"
    OFFSET_RANGE = (-80.0, 80.0)
    CAM_EYE_ADDR = mm.CAM_EYE
    #: the renderer builds its view direction as normalize(aim - eye).  With the
    #: runtime-owned main-camera hook the builder reads CAM_AIM_SLOT (a dead slot)
    #: instead of the word the game rewrites every frame, so writes are race free.
    CAM_TARGET_ADDR = mm.CAM_AIM_SLOT
    CAM_PLAYER_ADDR = mm.PLAYER_ANCHOR
    CAM_EYE_BASE_ADDR = mm.CAM_EYE_BASE
    CAM_EYE_OFFSET_ADDR = mm.CAM_EYE_OFFSET
    #: projection centre of the field camera (see memory_map.STOCK_PROJ_CENTRE)
    field_projection_centre = mm.STOCK_PROJ_CENTRE
    #: when True the runtime positions the camera through the game's own
    #: additive eye offset instead of overwriting the eye (race free).
    uses_offset_injection = True

    def __init__(self, backend) -> None:
        self.backend = backend
        self.info = AdapterInfo()
        self._orig_proj_scale: float | None = None
        self._orig_aim: Vec3 | None = None
        self._proj_owned = False
        self._look_height_cache: float | None = None
        self.features = {
            "orbit": True,
            "free_camera": True,
            "fov": True,
            "position_offsets": True,
            "target_offsets": True,
            "per_frame_write": True,
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
    def read_player(self) -> Vec3:
        """Stable orbit anchor, independent of scripted-camera subject height.

        Keep the normal-field +5 Y reference for existing look_height settings.
        The raw actor anchor must remain near zero during loading, otherwise
        that compensation would turn (0,0,0) into a plausible (0,5,0).
        """
        x, y, z, _w = self.backend.read_floats(mm.PLAYER_ANCHOR, 4)
        if max(abs(x), abs(y), abs(z)) < 0.05:
            return Vec3(x, y, z)
        return Vec3(x, y + mm.ORBIT_ANCHOR_Y_OFFSET, z)

    def read_game_pose(self) -> CameraPose:
        """The pose the game's own camera controller produced this frame."""
        ex, ey, ez, _ = self.backend.read_floats(mm.CAM_EYE_BASE, 4)
        tx, ty, tz, _ = self.backend.read_floats(mm.CAM_AIM, 4)
        return CameraPose(eye=Vec3(ex, ey, ez), target=Vec3(tx, ty, tz))

    def read_aim(self) -> Vec3:
        """Look-at point the renderer will use (see memory_map.CAM_AIM)."""
        x, y, z, _ = self.backend.read_floats(mm.CAM_AIM, 4)
        if self._orig_aim is None:
            self._orig_aim = Vec3(x, y, z)
        return Vec3(x, y, z)

    def write_aim(self, target: Vec3) -> None:
        self.backend.write_float_block(self.CAM_TARGET_ADDR, [target.x, target.y, target.z, 0.0])

    def restore_aim(self) -> None:
        """Hand the look-at point back to the game.

        The patched renderer reads CAM_AIM_SLOT, so restoring means copying the
        game's *current* aim (which the engine rewrites every frame and is
        therefore always the stock value) into that slot.
        """
        live = self.backend.read_floats(mm.CAM_AIM, 4)
        self._orig_aim = Vec3(live[0], live[1], live[2])
        self.backend.write_float_block(self.CAM_TARGET_ADDR, live)

    def read_eye_base(self) -> Vec3:
        x, y, z, _ = self.backend.read_floats(mm.CAM_EYE_BASE, 4)
        return Vec3(x, y, z)

    def write_eye_offset(self, offset: Vec3) -> None:
        """Set the additive eye offset the game applies every frame."""
        self.backend.write_float_block(mm.CAM_EYE_OFFSET, [offset.x, offset.y, offset.z])

    def clear_eye_offset(self) -> None:
        self.backend.write_float_block(mm.CAM_EYE_OFFSET, [0.0, 0.0, 0.0])

    def read_camera_forward(self) -> Vec3:
        """Forward axis of the basis the renderer is currently using.

        This is the authoritative view direction: placing the eye at
        ``target - distance * forward`` puts that target exactly at the centre
        of the screen (verified in reports/centering/).
        """
        x, y, z, _ = self.backend.read_floats(mm.CAM_BASIS_FWD, 4)
        n = (x * x + y * y + z * z) ** 0.5
        if n < 1e-6:
            return Vec3(0.0, 0.0, -1.0)
        return Vec3(x / n, y / n, z / n)

    def place_looking_at(self, target: Vec3, distance: float) -> Vec3:
        """Eye position that centres ``target`` at ``distance`` along the
        camera's current view axis."""
        f = self.read_camera_forward()
        return Vec3(target.x - f.x * distance,
                    target.y - f.y * distance,
                    target.z - f.z * distance)

    def read_fov_deg(self) -> float:
        scale = self.backend.read_floats(mm.CAM_PROJ_SCALE, 1)[0]
        return scale_to_fov_deg(scale)

    def read_scene(self) -> SceneState:
        player = self.read_player()
        pose = self.read_game_pose()
        fov = self.read_fov_deg()
        ok = all(abs(v) < 1e6 for v in (*player.as_tuple(), *pose.eye.as_tuple(), *pose.target.as_tuple()))
        ok = ok and pose.distance() > 0.01
        return SceneState(player=player, game_pose=pose, fov_deg=fov,
                          max_dist_game=pose.distance(),
                          valid=ok, reason="" if ok else "camera data not plausible")

    # --- writes --------------------------------------------------------
    def write_pose(self, pose: CameraPose) -> None:
        """One pipelined burst: eye xyz,w then the look-at point xyz,w."""
        e, t = pose.eye, pose.target
        self.backend.write_float_block(mm.CAM_EYE, [e.x, e.y, e.z, 1.0])
        self.backend.write_float_block(mm.CAM_AIM, [t.x, t.y, t.z, 0.0])

    def write_fov_deg(self, deg: float) -> None:
        scale = fov_deg_to_scale(deg)
        if self._orig_proj_scale is None:
            self._orig_proj_scale = self.backend.read_floats(mm.CAM_PROJ_SCALE, 1)[0]
        self.backend.write_float_block(mm.CAM_PROJ_SCALE, [scale])
        self._proj_owned = True

    def restore_fov(self) -> None:
        if self._proj_owned and self._orig_proj_scale is not None:
            self.backend.write_float_block(mm.CAM_PROJ_SCALE, [self._orig_proj_scale])
        self._proj_owned = False

    def capture_original_fov(self) -> float:
        value = self.backend.read_floats(mm.CAM_PROJ_SCALE, 1)[0]
        self._orig_proj_scale = value
        return scale_to_fov_deg(value)

    # --- scene helpers --------------------------------------------------
    def default_look_height(self) -> float:
        """Default offset from read_player()'s calibrated orbit anchor.

        +Y points down.  -6 keeps the normal-field framing (raw actor Y -1),
        regardless of the height chosen by the current scripted camera.
        """
        if self._look_height_cache is None:
            self._look_height_cache = -6.0
        return self._look_height_cache

    def is_field_like(self, scene: SceneState) -> bool:
        """Heuristic guard: refuse to write during obviously non-field states.

        A field camera keeps the eye within a sane radius of the party anchor.
        Battle / event / menu / loading states break that invariant, so the mod
        stays inert instead of dragging a scripted camera off its rails.
        """
        if not scene.valid:
            return False
        p = scene.player.as_tuple()
        if max(abs(v) for v in p) < 0.05:
            return False          # anchor reads (0,0,0) -> loading / not in a field
        d = scene.game_pose.distance()
        if not (1.0 < d < FIELD_POSE_RANGE):
            return False
        # Scripted camera switches (cut-ins, area entries) park the stock eye far
        # behind the party: 170 units was measured in the camera-switch savestate.
        # Orbit positions its own eye from the party anchor, so the stock eye only
        # has to be plausible, not close.  The old 120-unit limit made the mod go
        # silent in exactly those scenes.
        if (scene.game_pose.eye - scene.player).length() > FIELD_EYE_RANGE:
            return False
        return True

    def heartbeat_word(self) -> int:
        """Word the game rewrites each frame; used to phase-lock our writes."""
        return self.backend.read_u32(mm.CAM_EYE)

    def heartbeat_addr(self) -> int:
        return mm.CAM_EYE

    def patch_active(self) -> bool:
        """True when the main-only look-at redirect is complete and the builder is stock."""
        try:
            return (self.backend.read_u32(mm.LOOKAT_CALL) == mm.LOOKAT_CALL_PATCHED
                    and self.backend.read_u32(mm.LOOKAT_CALL + 4) == mm.LOOKAT_CALL_DELAY
                    and self.backend.read_u32(mm.LOOKAT_LOAD_SITE) == mm.LOOKAT_LOAD_STOCK
                    and self._lookat_cave_valid())
        except Exception:  # noqa: BLE001
            return False

    def _lookat_cave_valid(self) -> bool:
        return all(self.backend.read_u32(mm.LOOKAT_CAVE + 4 * i) == word
                   for i, word in enumerate(lookat_cave.cave_words()))

    # --- stock camera hook -------------------------------------------------
    def hook_active(self) -> bool:
        """True when the runtime-owned stock-camera hook is applied to its call sites.

        With the hook the game's own eye routine is driven by the orbit slots;
        without it the runtime falls back to the eye-offset injection.
        """
        try:
            return all(self.backend.read_u32(addr) == word for addr, word in mm.HOOK_CHECK)
        except Exception:  # noqa: BLE001
            return False

    def write_orbit_params(self, centre: Vec3, yaw_deg: float, pitch_deg: float,
                           distance: float) -> None:
        """Publish the orbit to the game's eye routine (see memory_map).

        The stock routine places the eye at ``centre + (sin yaw cos p, -sin p,
        cos yaw cos p) * dist``, so yaw is written as ``ORBIT_YAW_OFFSET - yaw``
        and pitch as its negative.  The walk reference follows the same eye.
        """
        self.backend.write_float_block(mm.ORBIT_CENTRE, [centre.x, centre.y, centre.z, 0.0])
        self.backend.write_float_block(mm.ORBIT_YAW_SLOT, [
            math.radians(mm.ORBIT_YAW_OFFSET_DEG - yaw_deg),
            -math.radians(pitch_deg),
            distance,
        ])

    def read_projection(self) -> tuple[float, float]:
        """(projection scale, projection centre) the renderer uses now."""
        scale = self.backend.read_floats(mm.CAM_PROJ_SCALE, 1)[0]
        centre = self.backend.read_floats(mm.CAM_PROJ_CENTRE, 1)[0]
        return scale, centre

    def write_projection_centre(self, centre: float) -> None:
        self.backend.write_float_block(mm.CAM_PROJ_CENTRE, [centre])

    def write_projection_scale(self, scale: float) -> None:
        self.backend.write_float_block(mm.CAM_PROJ_SCALE, [scale])

    def set_projection_source(self, redirected: bool) -> None:
        """Select the current bank's scale (CAM_PROJ_SCALE for main), or the stock row.

        Writes the one load instruction (memory_map.PROJ_SOURCE_LOAD), not a value.
        The game never rewrites that instruction, so this is not a per-frame race.
        Compare-and-swap: the word is replaced only while it holds the other form.
        """
        want = mm.PROJ_SOURCE_REDIRECT if redirected else mm.PROJ_SOURCE_STOCK
        have = self.backend.read_u32(mm.PROJ_SOURCE_LOAD)
        if have == want:
            return
        if have != (mm.PROJ_SOURCE_STOCK if redirected else mm.PROJ_SOURCE_REDIRECT):
            raise PatchConflict(f"projection source 0x{mm.PROJ_SOURCE_LOAD:08X} holds 0x{have:08X}")
        self.backend.write_u32(mm.PROJ_SOURCE_LOAD, want)

    def set_patch(self, on: bool) -> None:
        """Apply (on) or remove (off) the look-at and stock-hook words.

        Preflight PATCH_WORDS, the shared load and the call delay slot before
        writing.  Enabling also requires an empty or exact owned cave, installed
        before attaching the call.  Known legacy global loads migrate to stock;
        unknown code raises PatchConflict instead of being overwritten.
        """
        # Preflight every site and the whole cave before making any write.
        # A known old global patch is migrated back to stock in either mode.
        legacy = self.backend.read_u32(mm.LOOKAT_LOAD_SITE)
        if legacy not in (mm.LOOKAT_LOAD_STOCK, mm.LOOKAT_LOAD_PATCHED):
            raise PatchConflict(f"legacy look-at 0x{mm.LOOKAT_LOAD_SITE:08X} holds 0x{legacy:08X}")
        if self.backend.read_u32(mm.LOOKAT_CALL + 4) != mm.LOOKAT_CALL_DELAY:
            raise PatchConflict("look-at call delay slot is not stock")
        words = lookat_cave.cave_words()
        have_cave = [self.backend.read_u32(mm.LOOKAT_CAVE + 4 * i) for i in range(len(words))]
        if on and have_cave != words and any(have_cave):
            raise PatchConflict(f"look-at cave 0x{mm.LOOKAT_CAVE:08X} is not free")
        plan = []
        for addr, stock, applied in mm.PATCH_WORDS:
            have = self.backend.read_u32(addr)
            want = applied if on else stock
            if have == want:
                continue
            if have != (stock if on else applied):
                raise PatchConflict(f"0x{addr:08X} holds 0x{have:08X}, neither stock nor patched")
            plan.append((addr, want))
        if on and have_cave != words:
            for i, word in enumerate(words):
                self.backend.write_u32(mm.LOOKAT_CAVE + 4 * i, word)
        if legacy != mm.LOOKAT_LOAD_STOCK:
            self.backend.write_u32(mm.LOOKAT_LOAD_SITE, mm.LOOKAT_LOAD_STOCK)
        for addr, want in plan:
            self.backend.write_u32(addr, want)

    def patch_state(self) -> str:
        """Return applied, stock, partial or unknown for the look-at and stock-hook words."""
        legacy = self.backend.read_u32(mm.LOOKAT_LOAD_SITE)
        if (legacy not in (mm.LOOKAT_LOAD_STOCK, mm.LOOKAT_LOAD_PATCHED)
                or self.backend.read_u32(mm.LOOKAT_CALL + 4) != mm.LOOKAT_CALL_DELAY):
            return "unknown"
        forms = {"applied"} if legacy == mm.LOOKAT_LOAD_PATCHED else set()
        for addr, stock, applied in mm.PATCH_WORDS:
            have = self.backend.read_u32(addr)
            if have == applied:
                forms.add("applied")
            elif have == stock:
                forms.add("stock")
            else:
                return "unknown"
        if forms == {"applied"}:
            return "applied" if legacy == mm.LOOKAT_LOAD_STOCK and self._lookat_cave_valid() else "partial"
        if forms == {"stock"}:
            return "stock"
        return "partial"

    def write_walk_target(self, centre: Vec3) -> None:
        """Aim the stock walk at the orbit centre (see memory_map.WALK_TARGET).

        With the orbit eye behind the centre, target - eye points away from the
        camera for any orbit yaw, which is the direction the stick walks in.
        """
        self.backend.write_float_block(mm.WALK_TARGET, [centre.x, centre.y, centre.z, 0.0])

    def copy_stock_params(self) -> None:
        """Hand the stock blend values to the game's eye routine (no orbit).

        Used whenever the orbit is off: the slots mirror the values the stock
        blend writes each frame, so the stock camera is unchanged.
        """
        try:
            yaw, npitch, dist = self.backend.read_floats(mm.STOCK_YAW_OUT, 3)
            centre_ptr = self.backend.read_u32(mm.STOCK_CENTRE_PTR)
            if centre_ptr == 0:
                return
            centre = self.backend.read_floats(centre_ptr, 4)
            self.backend.write_float_block(mm.ORBIT_YAW_SLOT, [yaw, npitch, dist])
            self.backend.write_float_block(mm.ORBIT_CENTRE, centre)
        except Exception:  # noqa: BLE001
            pass


def probe(backend) -> dict:
    """Standalone health probe used by tools and tests."""
    ad = FFX2Adapter(backend)
    info = ad.identify()
    out = {"info": info.__dict__}
    if info.matched:
        sc = ad.read_scene()
        out["scene"] = {
            "player": sc.player.as_tuple(),
            "eye": sc.game_pose.eye.as_tuple(),
            "target": sc.game_pose.target.as_tuple(),
            "distance": sc.game_pose.distance(),
            "fov_deg": sc.fov_deg,
            "field_like": ad.is_field_like(sc),
            "valid": sc.valid,
        }
    return out
