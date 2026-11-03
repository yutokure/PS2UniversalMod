"""Shining Force Neo adapter tests (no emulator required).

The fake backend holds a sparse little-endian memory image.  The base values are the
ones read from the base savestate: yaw field 56438, pitch -5093, distance 2000, focus
height 100, eye (21.05, 271.87, -4352.84), focus (-1331.53, -666.35, -3216.96), and the
view-projection rows from the same savestate.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.shiningforceneo import fov_cave  # noqa: E402
from adapters.shiningforceneo import pad_cave  # noqa: E402
from adapters.shiningforceneo import memory_map as mm  # noqa: E402
from adapters.shiningforceneo.adapter import (  # noqa: E402
    DISTANCE_RANGE,
    LOOK_HEIGHT_RANGE,
    PatchConflict,
    SFNeoAdapter,
    SceneState,
    fov_from_scale,
    probe,
)
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose  # noqa: E402

#: view-projection (row-major) from the base savestate, at CAM_VP
BASE_VP = [
    2.3165, -1.8486, 0.0, -0.6763,
    0.0, 4.5445, 0.0, -0.4691,
    2.7584, 1.5524, 0.0, 0.5679,
    11958.215, 5560.858, 1.0, 2613.949,
]
BASE_FOCUS = (-1331.53, -666.35, -3216.96)
BASE_ANCHOR_Y = -766.35


class FakeBackend:
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        self.mem: dict[int, int] = {}
        self._serial = serial
        self._crc = crc

    # identity
    def game_id(self) -> str:
        return self._serial

    def crc(self) -> str:
        return self._crc

    def title(self) -> str:
        return "SHINING FORCE NEO"

    # memory
    def _bytes(self, addr: int, n: int) -> bytes:
        return bytes(self.mem.get(addr + i, 0) for i in range(n))

    def _put(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def read_u32(self, addr: int) -> int:
        return struct.unpack("<I", self._bytes(addr, 4))[0]

    def write_u32(self, addr: int, value: int) -> None:
        self._put(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def read_floats(self, addr: int, count: int) -> list[float]:
        return list(struct.unpack(f"<{count}f", self._bytes(addr, 4 * count)))

    def write_float_block(self, addr: int, values) -> None:
        self._put(addr, struct.pack(f"<{len(values)}f", *values))

    def set_u16(self, addr: int, value: int) -> None:
        self._put(addr, struct.pack("<H", value))

    def get_u16(self, addr: int) -> int:
        return struct.unpack("<H", self._bytes(addr, 2))[0]


def base_backend() -> FakeBackend:
    b = FakeBackend()
    b.write_float_block(mm.CAM_EYE, [21.05, 271.87, -4352.84, 1.0])
    b.write_float_block(mm.CAM_FOCUS, [*BASE_FOCUS, 1.0])
    b.write_float_block(mm.CAM_DISTANCE, [2000.0])
    b.write_float_block(mm.CAM_HEIGHT, [mm.STOCK_HEIGHT])
    b.write_float_block(mm.PARTY_POS, [BASE_FOCUS[0], BASE_FOCUS[1] - mm.STOCK_HEIGHT, BASE_FOCUS[2]])
    b.set_u16(mm.CAM_YAW, 56438)
    b.set_u16(mm.CAM_PITCH, (-5093) & 0xFFFF)
    b.write_float_block(mm.CAM_VP, BASE_VP)
    b.write_u32(mm.VP_LOAD_CALL, mm.VP_LOAD_WORD)
    b.mem[mm.SMOOTH_GATE] = mm.SMOOTH_GATE_STOCK
    return b


def emulate_vp_load(b: FakeBackend, vp_addr: int = mm.CAM_VP) -> None:
    """What one VP load of the game does once the cave is in place.

    The real frame rebuilds the VP from the view and the projection (here: BASE_VP at
    ``vp_addr``), and the cave scales columns 0 and 1 only for the field camera's matrix
    (``vp_addr == CAM_VP``).  Overlays such as the map load their own matrix and are left
    alone.
    """
    b.write_float_block(vp_addr, BASE_VP)
    if fov_cave.call_site_state(b) != "patched":
        return
    flag, ratio = fov_cave.read_ratio(b)
    if not flag or vp_addr != mm.CAM_VP:
        return
    for off in mm.VP_COLUMN_OFFSETS:
        v = b.read_floats(vp_addr + off, 1)[0]
        b.write_float_block(vp_addr + off, [v * ratio])


def eye_angles(backend) -> tuple[float, float]:
    yaw, pitch = SFNeoAdapter(backend).read_game_pose().yaw_pitch()
    return math.degrees(yaw), math.degrees(pitch)


def game_eye(focus: Vec3, yaw_u16: int, pitch_u16: int, distance: float) -> Vec3:
    """The controller's eye formula, rebuilt from the stored fields.

    eye = focus + dist * (sin Y cos p, -sin p, cos Y cos p) with Y = field yaw + 180 deg.
    """
    def s16(v: int) -> int:
        return v - 0x10000 if v & 0x8000 else v
    yaw = math.radians(s16(yaw_u16) / mm.ANGLE_UNITS_PER_DEG + mm.YAW_FIELD_OFFSET_DEG)
    pitch = math.radians(s16(pitch_u16) / mm.ANGLE_UNITS_PER_DEG)
    cp = math.cos(pitch)
    return Vec3(focus.x + math.sin(yaw) * cp * distance,
                focus.y - math.sin(pitch) * distance,
                focus.z + math.cos(yaw) * cp * distance)


# --- identity ----------------------------------------------------------------
def test_identify_matches_serial_and_crc():
    info = SFNeoAdapter(FakeBackend()).identify()
    assert info.matched and info.game_id == mm.GAME_ID


def test_identify_rejects_other_disc():
    info = SFNeoAdapter(FakeBackend(serial="SLPS-25250")).identify()
    assert not info.matched


# --- stock reads -------------------------------------------------------------
def test_stock_pose_reads_back_as_measured():
    yaw, pitch = eye_angles(base_backend())
    assert yaw == pytest.approx(130.02, abs=0.05)
    assert pitch == pytest.approx(-27.98, abs=0.05)
    pose = SFNeoAdapter(base_backend()).read_game_pose()
    assert pose.distance() == pytest.approx(2000.0, abs=0.5)


def test_player_anchor_is_focus_minus_height():
    anchor = SFNeoAdapter(base_backend()).read_player()
    assert anchor.y == pytest.approx(BASE_ANCHOR_Y, abs=0.01)


def test_player_anchor_does_not_move_with_the_height_field():
    b = base_backend()
    b.write_float_block(mm.CAM_HEIGHT, [200.0])
    b.write_float_block(mm.CAM_FOCUS, [BASE_FOCUS[0], BASE_ANCHOR_Y + 200.0, BASE_FOCUS[2], 1.0])
    anchor = SFNeoAdapter(b).read_player()
    assert anchor.y == pytest.approx(BASE_ANCHOR_Y, abs=0.01)


def test_field_like_accepts_base_and_orbit_distance_rejects_loading():
    ad = SFNeoAdapter(base_backend())
    assert ad.is_field_like(ad.read_scene())
    b = base_backend()
    b.write_float_block(mm.CAM_FOCUS, [0.0, 0.0, 0.0, 1.0])
    b.write_float_block(mm.PARTY_POS, [0.0, 0.0, 0.0])
    b.write_float_block(mm.CAM_HEIGHT, [0.0])
    assert not SFNeoAdapter(b).is_field_like(SFNeoAdapter(b).read_scene())
    close = SceneState(player=Vec3(1.0, 2.0, 3.0),
                       game_pose=CameraPose(eye=Vec3(0, 0, 0.5), target=Vec3(0, 0, 0)),
                       fov_deg=0.0, max_dist_game=0.5)
    assert not ad.is_field_like(close)


def test_field_like_accepts_the_orbit_distance_it_writes():
    """The guard must not reject the camera it has just placed (the old 28.7 failure)."""
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_orbit_params(ad.read_player(), 130.0, -28.0, 2000.0)
    assert ad.is_field_like(ad.read_scene())


# --- moving field scene / pitch input regressions -----------------------------
@pytest.mark.parametrize("dy", [-180.0, -12.0, 12.0, 180.0])
def test_field_guard_accepts_smoothed_focus_lag_on_stairs(dy):
    b = base_backend()
    p = SFNeoAdapter(b).read_player()
    b.write_float_block(mm.PARTY_POS, [p.x, p.y + dy, p.z])
    ad = SFNeoAdapter(b)
    assert ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("mode", [2, 3, 4, 5, 99])
def test_field_guard_rejects_fixed_transition_and_scripted_modes(mode):
    b = base_backend()
    b.write_u32(mm.CAM_MODE, mode)
    ad = SFNeoAdapter(b)
    assert not ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("mode", [1, 2, 3, 4])
def test_field_guard_rejects_non_party_focus_even_at_matching_height(mode):
    b = base_backend()
    b.write_u32(mm.CAM_FOCUS_MODE, mode)
    ad = SFNeoAdapter(b)
    assert not ad.is_field_like(ad.read_scene())


def test_runtime_keeps_publishing_during_stair_height_change():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
    b = base_backend()
    b.write_u32(mm.PAD_CALL_SITE, mm.PAD_CALL_WORD)
    ad = SFNeoAdapter(b)
    s = CameraSettings(mode=MODE_ORBIT, distance=673.4, pitch_deg=-25, look_height=39.64)
    rt = CameraRuntime(ad, s)
    rt.set_stick(0.8, 0)
    rt._tick(0.01, None)
    writes = rt.stats.total_writes
    p = ad.read_player()
    # The party climbs, but the game's focus still holds the previous frame.
    b.write_float_block(mm.PARTY_POS, [p.x, p.y + 100, p.z])
    rt._scene_time = 0
    rt._tick(0.01, None)
    assert rt.stats.total_writes > writes
    assert rt.stats.last_error == ""
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(139.64)


def test_runtime_passes_relative_height_not_a_second_player_sample():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings
    b = base_backend()
    ad = SFNeoAdapter(b)
    s = CameraSettings(look_height=39.64, target_offset=[0, 10, 0])
    rt = CameraRuntime(ad, s)
    # A centre computed from an earlier party sample must not be interpreted as
    # a relative height by subtracting the party's newer Y.
    old = ad.read_player()
    b.write_float_block(mm.PARTY_POS, [old.x, old.y + 80, old.z])
    rt._publish_orbit((old.x, old.y + 49.64, old.z), 130, -28, 2000)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(149.64)


def test_sfneo_pitch_input_reaches_overhead_not_underside_with_old_limits():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings
    ad = SFNeoAdapter(base_backend())
    s = CameraSettings(pitch_deg=-28, pitch_min_deg=-25, pitch_max_deg=85)
    rt = CameraRuntime(ad, s)
    rt.set_stick(1, 0)
    rt._integrate(0.01)
    assert s.pitch_deg == -28  # horizontal input must not snap a stock pitch
    rt.set_stick(0, 1)
    rt._integrate(10)
    assert s.pitch_deg == ad.PITCH_RANGE[0] == -89.5
    pose = orbit_pose(Vec3(0, 0, 0), 0, math.radians(s.pitch_deg), 2000)
    assert pose.eye.y > 1999
    rt.set_stick(0, -1)
    rt._integrate(10)
    assert s.pitch_deg == ad.PITCH_RANGE[1] == 25
    rt.set_stick(0, 0)
    rt._integrate(1)
    assert s.pitch_deg == 25


def test_sfneo_pitch_invert_is_additional_to_native_input_sign():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings
    s = CameraSettings(pitch_deg=-28, invert_y=True)
    rt = CameraRuntime(SFNeoAdapter(base_backend()), s)
    rt.set_stick(0, 1)
    rt._integrate(0.1)
    assert s.pitch_deg > -28


@pytest.mark.parametrize("adapter_name", ["ffx2", "suikoden5"])
def test_other_games_keep_the_existing_pitch_input_convention(adapter_name):
    from core.camera_runtime.engine import CameraRuntime, CameraSettings
    from adapters.ffx2.adapter import FFX2Adapter
    from adapters.suikoden5.adapter import Suikoden5Adapter
    cls = {"ffx2": FFX2Adapter, "suikoden5": Suikoden5Adapter}[adapter_name]
    s = CameraSettings(pitch_deg=20, pitch_min_deg=-5, pitch_max_deg=85)
    rt = CameraRuntime(cls(base_backend()), s)
    rt.set_stick(0, 1)
    rt._integrate(0.1)
    assert s.pitch_deg == pytest.approx(35)
    rt._integrate(10)
    assert s.pitch_deg == 85


# --- defaults ----------------------------------------------------------------
def test_default_settings_are_the_stock_framing():
    d = SFNeoAdapter(base_backend()).default_settings()
    assert d["distance"] == pytest.approx(2000.0)
    assert d["look_height"] == 0.0
    assert d["fov_deg"] == pytest.approx(fov_from_scale(mm.STOCK_PROJ_SX))


def test_slider_ranges_contain_the_stock_values():
    lo, hi = DISTANCE_RANGE
    assert lo < 2000.0 < hi
    lo, hi = LOOK_HEIGHT_RANGE
    assert lo < 0.0 < hi


# --- orbit writes ------------------------------------------------------------
def test_orbit_yaw_zero_change_keeps_stock_fields():
    b = base_backend()
    yaw, pitch = eye_angles(b)
    SFNeoAdapter(b).write_orbit_params(SFNeoAdapter(b).read_player(), yaw, pitch, 2000.0)
    assert b.get_u16(mm.CAM_YAW) == pytest.approx(56438, abs=2)
    assert b.get_u16(mm.CAM_PITCH) == pytest.approx(0xEC1B, abs=2)     # -5093


def test_orbit_plus_10_degrees_matches_measured_field():
    """+10 deg of eye yaw gave yaw field 58258 in the emulator (orbit_gate_off.py)."""
    b = base_backend()
    yaw, pitch = eye_angles(b)
    SFNeoAdapter(b).write_orbit_params(SFNeoAdapter(b).read_player(), yaw + 10.0, pitch, 2000.0)
    assert b.get_u16(mm.CAM_YAW) == pytest.approx(58258, abs=2)


def test_stock_fields_rebuild_the_measured_base_eye():
    eye = game_eye(Vec3(*BASE_FOCUS), 56438, (-5093) & 0xFFFF, 2000.0)
    assert eye.x == pytest.approx(21.05, abs=1.0)
    assert eye.y == pytest.approx(271.87, abs=1.0)
    assert eye.z == pytest.approx(-4352.84, abs=1.0)


def test_write_pose_fields_rebuild_the_requested_eye():
    b = base_backend()
    focus = Vec3(*BASE_FOCUS)
    want = orbit_pose(focus, math.radians(35.0), math.radians(-20.0), 2000.0)
    SFNeoAdapter(b).write_pose(want)
    got = game_eye(focus, b.get_u16(mm.CAM_YAW), b.get_u16(mm.CAM_PITCH), 2000.0)
    assert (got - want.eye).length() < 0.5
    assert b.read_floats(mm.CAM_DISTANCE, 1)[0] == pytest.approx(2000.0)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(mm.STOCK_HEIGHT, abs=0.01)


# --- look height (the focus height) ------------------------------------------
def test_zero_look_height_writes_the_stock_focus_height():
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_orbit_params(ad.read_player(), 130.0, -28.0, 2000.0)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(mm.STOCK_HEIGHT, abs=0.01)


def test_look_height_moves_the_focus_height_and_keeps_the_anchor():
    b = base_backend()
    ad = SFNeoAdapter(b)
    anchor = ad.read_player()
    centre = Vec3(anchor.x, anchor.y + 50.0, anchor.z)
    ad.write_orbit_params(centre, 130.0, -28.0, 2000.0)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(mm.STOCK_HEIGHT + 50.0, abs=0.01)
    assert ad.read_player().y == pytest.approx(anchor.y, abs=0.01)


# --- smoothing gate (the patch) ----------------------------------------------
def test_gate_on_off_is_compare_and_swap_on_one_byte():
    b = base_backend()
    ad = SFNeoAdapter(b)
    assert ad.patch_state() == "stock"
    ad.set_patch(True)
    assert b.mem[mm.SMOOTH_GATE] == mm.SMOOTH_GATE_APPLIED
    assert ad.patch_state() == "applied" and ad.patch_active()
    ad.set_patch(False)
    assert b.mem[mm.SMOOTH_GATE] == mm.SMOOTH_GATE_STOCK
    assert ad.patch_state() == "stock"


def test_gate_keeps_neighbouring_bytes():
    b = base_backend()
    for i, v in enumerate((0xAA, 0xBB, 0xCC)):
        b.mem[mm.SMOOTH_GATE - 3 + i] = v
    SFNeoAdapter(b).set_patch(True)
    assert b.mem[mm.SMOOTH_GATE - 3] == 0xAA
    assert b.mem[mm.SMOOTH_GATE - 2] == 0xBB
    assert b.mem[mm.SMOOTH_GATE - 1] == 0xCC


def test_gate_unknown_value_raises_before_writing():
    b = base_backend()
    b.mem[mm.SMOOTH_GATE] = 7
    ad = SFNeoAdapter(b)
    with pytest.raises(PatchConflict):
        ad.set_patch(True)
    assert b.mem[mm.SMOOTH_GATE] == 7
    assert ad.patch_state() == "unknown"


# --- field of view -----------------------------------------------------------
def test_stock_fov_reads_back_from_the_view_projection():
    ad = SFNeoAdapter(base_backend())
    assert ad.read_fov_deg() == pytest.approx(fov_from_scale(mm.STOCK_PROJ_SX), abs=0.01)
    assert ad.read_fov_deg() == pytest.approx(31.03, abs=0.02)


def test_write_fov_installs_the_cave_and_the_emulated_load_draws_it():
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_fov_deg(45.0)
    assert fov_cave.call_site_state(b) == "patched"
    emulate_vp_load(b)
    assert ad.read_fov_deg() == pytest.approx(45.0, abs=0.01)
    assert ad.fov_in_sync(45.0)


def test_fov_writes_do_not_compound():
    """Each write is measured against the unscaled scale, with a frame between writes."""
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_fov_deg(45.0)
    emulate_vp_load(b)
    ad.write_fov_deg(60.0)
    emulate_vp_load(b)
    assert ad.read_fov_deg() == pytest.approx(60.0, abs=0.01)


def test_map_overlay_matrix_keeps_its_size_while_the_field_is_zoomed():
    """The map and overlays load their own matrix through the same call; they must not change."""
    b = base_backend()
    ad = SFNeoAdapter(b)
    map_vp = 0x01104A00                       # any other struct's matrix, not CAM_VP
    ad.write_fov_deg(45.0)
    emulate_vp_load(b, vp_addr=map_vp)
    assert b.read_floats(map_vp, 16) == pytest.approx(BASE_VP)
    emulate_vp_load(b)
    assert ad.read_fov_deg() == pytest.approx(45.0, abs=0.01)


def test_capture_original_fov_is_the_stock_value_even_while_overridden():
    b = base_backend()
    ad = SFNeoAdapter(b)
    stock = ad.capture_original_fov()
    ad.write_fov_deg(45.0)
    emulate_vp_load(b)
    assert ad.capture_original_fov() == pytest.approx(stock, abs=0.01)


def test_restore_fov_gives_the_game_its_own_call_back():
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_fov_deg(45.0)
    ad.restore_fov()
    assert b.read_u32(mm.VP_LOAD_CALL) == mm.VP_LOAD_WORD
    assert fov_cave.read_ratio(b)[0] is False
    emulate_vp_load(b)
    assert ad.read_fov_deg() == pytest.approx(31.03, abs=0.02)


def test_restore_fov_is_a_no_op_when_never_overridden():
    b = base_backend()
    before = dict(b.mem)
    SFNeoAdapter(b).restore_fov()
    assert b.mem == before


def test_write_fov_refuses_a_foreign_call_site():
    b = base_backend()
    b.write_u32(mm.VP_LOAD_CALL, 0x00000000)
    with pytest.raises(fov_cave.CavePatchError):
        SFNeoAdapter(b).write_fov_deg(45.0)


def test_write_fov_refuses_a_non_empty_cave_area():
    b = base_backend()
    b.write_u32(mm.FOV_CAVE + 8, 0x12345678)
    with pytest.raises(fov_cave.CavePatchError):
        SFNeoAdapter(b).write_fov_deg(45.0)
    assert fov_cave.call_site_state(b) == "original"


def test_fov_in_sync_only_after_the_load():
    b = base_backend()
    ad = SFNeoAdapter(b)
    ad.write_fov_deg(45.0)
    assert not ad.fov_in_sync(45.0)       # the next frame has not drawn it yet
    emulate_vp_load(b)
    assert ad.fov_in_sync(45.0)


def test_cave_instructions_decode_as_intended():
    words = fov_cave.cave_words()
    assert words[0] == 0x3C080035                              # lui t0,0x0035
    assert words[1] == 0x35086700                              # ori t0,t0,0x6700
    jal_index = words.index(0x0C06A820)                        # the original VP load
    beq = words[3]
    assert beq >> 26 == 0x04                                   # beq
    target = 4 + ((beq & 0xFFFF) << 2) // 4
    assert target == jal_index                                 # skip the scaling to the call
    mul = 0x46082102                                           # mul.s f4,f4,f8
    assert (mul >> 26) == 0x11 and ((mul >> 21) & 0x1F) == 0x10
    assert (mul >> 16) & 0x1F == 8 and (mul >> 11) & 0x1F == 4 and (mul >> 6) & 0x1F == 4
    assert mul & 0x3F == 0x02
    assert words[-1] == 0                                      # nop (delay slot of the return)
    assert words[-2] == 0x08000000 | ((mm.VP_LOAD_RETURN >> 2) & 0x03FFFFFF)   # j return
    assert words[-3] == 0                                      # nop (delay slot of the call)
    assert words[-4] == 0x0C06A820                             # jal FUN_001AA080


def test_cave_only_scales_the_field_camera_matrix():
    """The camera check: lui/ori build CAM_VP and bne skips the scaling for any other a0."""
    words = fov_cave.cave_words()
    jal_index = words.index(0x0C06A820)
    assert words[5] == 0x3C0A0000 | (mm.CAM_VP >> 16)         # lui t2,hi(CAM_VP)
    assert words[6] == 0x354A0000 | (mm.CAM_VP & 0xFFFF)      # ori t2,t2,lo(CAM_VP)
    bne = words[7]
    assert bne >> 26 == 0x05                                   # bne
    assert (bne >> 21) & 0x1F == 4 and (bne >> 16) & 0x1F == 10   # a0, t2
    assert 8 + ((bne & 0xFFFF) << 2) // 4 == jal_index         # not the camera -> call only


def test_probe_reports_height_fov_and_gate():
    out = probe(base_backend())
    assert out["info"]["matched"] and out["scene"]["gate"] == "stock"
    assert out["scene"]["height"] == pytest.approx(mm.STOCK_HEIGHT, abs=0.01)
    assert out["scene"]["fov_deg"] == pytest.approx(31.03, abs=0.02)


def _signed16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def _branch_target(index: int, word: int) -> int:
    return index + 1 + _signed16(word & 0xFFFF)


def test_pad_cave_branches_land_where_intended():
    words = pad_cave.cave_words()
    assert len(words) == 20
    assert words[0] == 0x90A20000                                       # lbu v0,0(a1), the original load
    assert _branch_target(3, words[3]) == 18                            # flag off -> done
    assert _branch_target(9, words[9]) == 17                            # first source -> mask
    assert _branch_target(15, words[15]) == 18                          # second source not matched -> done
    assert words[17] == 0x3402007F                                      # ori v0,zero,0x7F
    assert words[18] == 0x08000000 | ((mm.PAD_RETURN >> 2) & 0x03FFFFFF)   # j PAD_RETURN
    assert words[19] == 0x24A50001                                      # addiu a1,a1,1 (the delay slot)


def test_pad_cave_compares_the_two_right_stick_sources():
    words = pad_cave.cave_words()
    for hi_index, lo_index, source in ((5, 6, mm.PAD_RX_SOURCES[0]), (11, 12, mm.PAD_RX_SOURCES[1])):
        assert words[hi_index] == 0x3C1B0000 | (source >> 16)           # lui k1,hi(source)
        assert words[lo_index] == 0x377B0000 | (source & 0xFFFF)        # ori k1,k1,lo(source)


def _pad_backend() -> FakeBackend:
    b = FakeBackend()
    b.write_u32(mm.PAD_CALL_SITE, mm.PAD_CALL_WORD)
    return b


def test_stick_block_installs_the_cave_and_gives_the_load_back():
    b = _pad_backend()
    ad = SFNeoAdapter(b)
    ad.set_stick_block(True)
    assert pad_cave.call_site_state(b) == "patched"
    assert pad_cave.read_flag(b) is True
    assert b.read_u32(mm.PAD_CAVE) == pad_cave.cave_words()[0]
    ad.set_stick_block(False)
    assert pad_cave.call_site_state(b) == "original"
    assert pad_cave.read_flag(b) is False


def test_stick_block_is_put_back_after_the_game_resets_the_memory():
    # a savestate load restores the original call site and clears the flag; asking again
    # for the block must put it back, since the engine re-checks while the orbit runs
    b = _pad_backend()
    ad = SFNeoAdapter(b)
    ad.set_stick_block(True)
    b.write_u32(mm.PAD_CALL_SITE, mm.PAD_CALL_WORD)
    b.write_u32(mm.PAD_BLOCK_FLAG, 0)
    ad.set_stick_block(True)
    assert pad_cave.call_site_state(b) == "patched"
    assert pad_cave.read_flag(b) is True


def test_stick_block_refuses_a_foreign_call_site():
    b = _pad_backend()
    b.write_u32(mm.PAD_CALL_SITE, 0x00000000)
    with pytest.raises(pad_cave.CavePatchError):
        SFNeoAdapter(b).set_stick_block(True)


def test_fov_and_stick_caves_do_not_overlap():
    fov = (mm.FOV_CAVE, mm.FOV_CAVE + 4 * len(fov_cave.cave_words()))
    pad = (mm.PAD_CAVE, mm.PAD_CAVE + 4 * len(pad_cave.cave_words()))
    assert fov[1] <= pad[0] or pad[1] <= fov[0]


def test_fov_and_stick_caves_install_in_either_order():
    # the orbit (stick block) and the FOV can be switched on in any order
    for first, second in ((pad_cave, fov_cave), (fov_cave, pad_cave)):
        b = FakeBackend()
        b.write_u32(mm.PAD_CALL_SITE, mm.PAD_CALL_WORD)
        b.write_u32(mm.VP_LOAD_CALL, mm.VP_LOAD_WORD)
        first.install(b)
        second.install(b)
        assert fov_cave.call_site_state(b) == "patched"
        assert pad_cave.call_site_state(b) == "patched"
