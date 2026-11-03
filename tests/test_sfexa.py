"""Exa-specific unit tests; no emulator, extracted binary or Neo adapter required.

Numeric baseline summaries were read from SLPM-66646/8B383FDF's supplied base
state: camera010FE800, actor00C65880+520, distance1000, height250, yaw0,
pitch-364, vertical FOV7281. The frame helper below models the known parameter
math only: it is not a substitute for rendered FOV/input integration testing.
"""
from __future__ import annotations

import math
from pathlib import Path
import struct
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.shiningforceexa import memory_map as mm  # noqa: E402
from adapters.shiningforceexa.adapter import (  # noqa: E402
    DISTANCE_RANGE,
    LOOK_HEIGHT_RANGE,
    PatchConflict,
    SFExaAdapter,
    SceneState,
    fov_from_scale,
    probe,
)
from core.camera_math.orbit import (  # noqa: E402
    CameraPose, FOV_MAX_DEG, FOV_MIN_DEG, Vec3, orbit_pose,
)

BASE_EYE = (-908.9829711914062, 223.7811737060547, -1056.7510986328125)
BASE_FOCUS = (-908.9829711914062, 188.89019775390625, -57.360042572021484)
BASE_PLAYER = (-908.9829711914062, -61.109806060791016, -57.360042572021484)
BASE_ACTOR = 0x00C65880
BASE_YAW, BASE_PITCH, BASE_VFOV = 0, -364, 7281
BASE_VP = [
    1.9234572649002075, 0.0, 0.0, 0.0,
    0.0, 2.7461228370666504, 0.0, -0.034890975803136826,
    0.0, 0.09587328135967255, 0.0, 0.9993910789489746,
    1748.3897705078125, -513.21630859375, 1.0, 1063.9154052734375,
]


class FakeBackend:
    """Sparse byte image; seed writes and adapter writes are kept distinct."""

    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        self.mem: dict[int, int] = {}
        self.writes: list[tuple[int, bytes]] = []
        self.reads: list[tuple[int, int]] = []
        self.serial, self.disc_crc = serial, crc

    def game_id(self): return self.serial
    def crc(self): return self.disc_crc
    def title(self): return "SHINING FORCE EXA"

    def seed(self, addr, data):
        self.mem.update((addr + i, value) for i, value in enumerate(data))

    def bytes_at(self, addr, count):
        self.reads.append((addr, count))
        return bytes(self.mem.get(addr + i, 0) for i in range(count))

    def write_bytes(self, addr, data):
        self.writes.append((addr, data))
        self.seed(addr, data)

    def read_u32(self, addr):
        return struct.unpack("<I", self.bytes_at(addr, 4))[0]

    def write_u32(self, addr, value):
        self.write_bytes(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def read_floats(self, addr, count):
        return list(struct.unpack(f"<{count}f", self.bytes_at(addr, 4 * count)))

    def write_float_block(self, addr, values):
        values = tuple(values)
        self.write_bytes(addr, struct.pack(f"<{len(values)}f", *values))

    def seed_u32(self, addr, value):
        self.seed(addr, struct.pack("<I", value & 0xFFFFFFFF))

    def seed_floats(self, addr, values):
        values = tuple(values)
        self.seed(addr, struct.pack(f"<{len(values)}f", *values))

    def u16(self, addr):
        return struct.unpack("<H", self.bytes_at(addr, 2))[0]

    def seed_u16(self, addr, value):
        self.seed(addr, struct.pack("<H", value & 65535))


def base_backend():
    b = FakeBackend()
    b.seed_u32(mm.CAM_ACTIVE_PTR, mm.CAM_STRUCT)
    b.seed_u32(mm.PARTY_ACTOR_PTR, BASE_ACTOR)
    b.seed_floats(mm.CAM_EYE, (*BASE_EYE, 1))
    b.seed_floats(mm.CAM_FOCUS, (*BASE_FOCUS, 1))
    b.seed_floats(BASE_ACTOR + 0x520, BASE_PLAYER)
    b.seed_floats(mm.CAM_DISTANCE, (1000,))
    b.seed_floats(mm.CAM_HEIGHT, (250,))
    b.seed_floats(mm.CAM_ASPECT, (640 / 448,))
    b.seed_floats(mm.CAM_VP, BASE_VP)
    b.seed_u16(mm.CAM_YAW, BASE_YAW)
    b.seed_u16(mm.CAM_PITCH, BASE_PITCH)
    b.seed_u16(mm.CAM_FOV, BASE_VFOV)
    b.seed_u32(mm.CAM_MODE, 0)
    b.seed_u32(mm.CAM_FOCUS_MODE, 0)
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    b.seed_u32(mm.PAD_RX_LOAD, 0x92620166)
    b.seed_u32(mm.PAD_RY_LOAD, 0x92620167)
    b.seed_u32(mm.VP_LOAD_CALL, 0x0C06B128)
    b.seed_u32(mm.PAD_CALL_SITE, 0x90A20000)
    return b


def signed16(word):
    return word - 65536 if word & 0x8000 else word


def rendered_hfov(vunits, aspect):
    return math.degrees(2 * math.atan(aspect * math.tan(math.radians(vunits * 360 / 65536) / 2)))


def emulate_parameter_frame(b):
    """Model original eye/VP reconstruction, with no game execution claim."""
    actor = b.read_u32(mm.PARTY_ACTOR_PTR)
    player = Vec3(*b.read_floats(actor + 0x520, 3))
    height = b.read_floats(mm.CAM_HEIGHT, 1)[0]
    focus = Vec3(player.x, player.y + height, player.z)
    yaw = signed16(b.u16(mm.CAM_YAW)) * 360 / 65536 + 180
    pitch = signed16(b.u16(mm.CAM_PITCH)) * 360 / 65536
    distance = b.read_floats(mm.CAM_DISTANCE, 1)[0]
    pose = orbit_pose(focus, math.radians(yaw), math.radians(pitch), distance)
    b.seed_floats(mm.CAM_FOCUS, (*focus.as_tuple(), 1))
    b.seed_floats(mm.CAM_EYE, (*pose.eye.as_tuple(), 1))
    vfov = math.radians(b.u16(mm.CAM_FOV) * 360 / 65536)
    aspect = b.read_floats(mm.CAM_ASPECT, 1)[0]
    sy = 1 / math.tan(vfov / 2)
    # Only column norms matter for read_fov_deg(); translation is deliberately arbitrary.
    b.seed_floats(mm.CAM_VP, (sy / aspect, 0, 0, 0, 0, sy, 0, 0,
                              0, 0, 1, 0, 123, 456, 1, 789))


@pytest.mark.parametrize("serial,crc,matched", [
    ("SLPM-66646", "8B383FDF", True),
    (" slpm-66646 ", "8b383fdf ", True),
    ("SLPM-66646", "64F241D2", False),
    ("SLPM-65908", "8B383FDF", False),
    ("SLPM-65908", "64F241D2", False),
    ("", "", False),
])
def test_identity_requires_both_exa_serial_and_crc(serial, crc, matched):
    b = FakeBackend(serial, crc)
    info = SFExaAdapter(b).identify()
    assert info.matched is matched
    assert bool(info.reason) is not matched
    assert not b.writes


def test_identity_transport_error_is_not_a_match():
    b = FakeBackend()
    b.game_id = lambda: (_ for _ in ()).throw(OSError("disconnected"))
    info = SFExaAdapter(b).identify()
    assert not info.matched and "disconnected" in info.reason
    assert not b.writes


def test_independent_exa_map_and_defaults():
    assert mm.CAM_STRUCT == 0x010FE800
    assert mm.PARTY_ACTOR_PTR == 0x00451140
    assert mm.PARTY_POS_OFFSET == 0x520
    assert mm.PARTY_POS == BASE_ACTOR + 0x520
    assert (mm.PAD_RX_LOAD, mm.PAD_RY_LOAD) == (0x1AD27C, 0x1AD290)
    ad = SFExaAdapter(base_backend())
    defaults = ad.default_settings()
    assert defaults["distance"] == 1000
    assert defaults["look_height"] == ad.default_look_height() == 0
    assert defaults["fov_deg"] == pytest.approx(fov_from_scale(BASE_VP[0]))
    assert DISTANCE_RANGE[0] < 1000 < DISTANCE_RANGE[1]
    assert LOOK_HEIGHT_RANGE[0] < 0 < LOOK_HEIGHT_RANGE[1]
    assert ad.features["orbit"] and ad.features["fov"]
    assert not ad.features["free_camera"]
    assert not ad.features["position_offsets"] and not ad.features["target_offsets"]


def test_baseline_pose_player_fov_and_probe_are_exa_not_neo():
    b = base_backend()
    ad = SFExaAdapter(b)
    pose = ad.read_game_pose()
    assert pose.eye.as_tuple() == pytest.approx(BASE_EYE)
    assert pose.target.as_tuple() == pytest.approx(BASE_FOCUS)
    yaw, pitch = map(math.degrees, pose.yaw_pitch())
    assert abs(yaw) == pytest.approx(180, abs=.001)
    assert pitch == pytest.approx(-364 * 360 / 65536, abs=.002)
    assert pose.distance() == pytest.approx(1000, abs=.002)
    assert ad.read_player().as_tuple() == pytest.approx(BASE_PLAYER)
    assert ad.read_height() == 250
    assert ad.read_fov_deg() == pytest.approx(rendered_hfov(7281, 640 / 448), abs=.01)
    assert ad.read_fov_deg() > 54
    out = probe(b)
    assert out["info"]["matched"] and out["scene"]["field_like"]
    assert out["scene"]["height"] == 250
    assert out["scene"]["gate"] == "stock"
    assert not b.writes


def test_probe_does_not_read_camera_for_other_game():
    b = FakeBackend(crc="64F241D2")
    assert "scene" not in probe(b)
    assert not b.reads and not b.writes


@pytest.mark.parametrize("actor", [0, 0xFFFF0, 0x00C65881, 0x01FFFAF0, 0x02000000])
def test_actor_pointer_guards_avoid_out_of_bounds_memory(actor):
    b = base_backend()
    b.seed_u32(mm.PARTY_ACTOR_PTR, actor)
    ad = SFExaAdapter(b)
    assert ad.read_player().as_tuple() == (0, 0, 0)
    assert b.reads == [(mm.PARTY_ACTOR_PTR, 4)]
    assert not ad.is_field_like(ad.read_scene())
    assert not b.writes


def test_actor_position_follows_valid_relocated_pointer_not_baseline_address():
    b = base_backend()
    moved_actor = 0x00C70000
    b.seed_u32(mm.PARTY_ACTOR_PTR, moved_actor)
    b.seed_floats(moved_actor + 0x520, (12, -34, 56))
    b.seed_floats(moved_actor + 0x510, (111, 222, 333))
    assert SFExaAdapter(b).read_player().as_tuple() == (12, -34, 56)
    assert (mm.PARTY_POS, 12) not in b.reads


@pytest.mark.parametrize("operation", ["set_patch", "write_orbit", "write_fov"])
def test_active_camera_mismatch_refuses_parameter_writes(operation):
    b = base_backend()
    b.seed_u32(mm.CAM_ACTIVE_PTR, 0x01104900)
    ad = SFExaAdapter(b)
    with pytest.raises(PatchConflict, match="camera"):
        if operation == "set_patch": ad.set_patch(True)
        elif operation == "write_orbit": ad.write_orbit_params(Vec3(*BASE_PLAYER), 120, -25, 1500)
        else: ad.write_fov_deg(70)
    assert not b.writes
    assert not ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("yaw,pitch,distance", [(0, -30, 1000), (35, -20, 1650),
                                                (180, -2, 1000), (270, 15, 600),
                                                (359, -89.5, 3000), (-179, 25, 6000)])
def test_orbit_fields_reconstruct_requested_eye_without_touching_outputs(yaw, pitch, distance):
    b = base_backend()
    ad = SFExaAdapter(b)
    player = ad.read_player()
    output = (b.bytes_at(mm.CAM_EYE, 32), b.bytes_at(mm.CAM_VP, 64))
    ad.write_orbit_params(player, yaw, pitch, distance, look_height=40)
    assert signed16(b.u16(mm.CAM_PITCH)) / mm.ANGLE_UNITS_PER_DEG == pytest.approx(pitch, abs=.003)
    assert b.read_floats(mm.CAM_DISTANCE, 1)[0] == distance
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == 290
    assert output == (b.bytes_at(mm.CAM_EYE, 32), b.bytes_at(mm.CAM_VP, 64))
    assert {a for a, _ in b.writes} == {mm.CAM_YAW_WORD, mm.CAM_DISTANCE, mm.CAM_HEIGHT}
    emulate_parameter_frame(b)
    want = orbit_pose(Vec3(player.x, player.y + 290, player.z),
                      math.radians(yaw), math.radians(pitch), distance)
    assert (ad.read_game_pose().eye - want.eye).length() < .4


def test_baseline_angle_write_round_trips_measured_halfwords():
    b = base_backend()
    ad = SFExaAdapter(b)
    yaw, pitch = map(math.degrees, ad.read_game_pose().yaw_pitch())
    ad.write_orbit_params(ad.read_player(), yaw, pitch, 1000)
    assert b.u16(mm.CAM_YAW) == BASE_YAW
    assert signed16(b.u16(mm.CAM_PITCH)) == BASE_PITCH


def test_positive_look_height_raises_focus_without_moving_actor():
    b = base_backend()
    ad = SFExaAdapter(b)
    p = ad.read_player()
    ad.write_orbit_params(Vec3(p.x, p.y + 50, p.z), 180, -2, 1000)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == 300
    assert ad.read_player().as_tuple() == pytest.approx(BASE_PLAYER)


def test_relative_look_height_avoids_second_actor_sample_drift():
    b = base_backend()
    ad = SFExaAdapter(b)
    stale = ad.read_player()
    b.seed_floats(BASE_ACTOR + 0x520, (stale.x, stale.y + 80, stale.z))
    ad.write_orbit_params(stale, 180, -2, 1000, look_height=49.64)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(299.64, abs=.001)


def test_write_pose_uses_native_params_and_preserves_requested_focus_height():
    b = base_backend()
    ad = SFExaAdapter(b)
    player = ad.read_player()
    focus = Vec3(player.x, player.y + 325, player.z)
    want = orbit_pose(focus, math.radians(35), math.radians(-20), 1400)
    ad.write_pose(want)
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(325)
    emulate_parameter_frame(b)
    assert (ad.read_game_pose().eye - want.eye).length() < .15


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_orbit_rejected_before_any_write(index, value):
    b = base_backend()
    values = [180, -2, 1000, 0]
    values[index] = value
    with pytest.raises(ValueError):
        SFExaAdapter(b).write_orbit_params(Vec3(*BASE_PLAYER), *values[:3], look_height=values[3])
    assert not b.writes


@pytest.mark.parametrize("dy", [-180, -12, 12, 180])
def test_scene_accepts_smoothed_party_height_lag(dy):
    b = base_backend()
    b.seed_floats(BASE_ACTOR + 0x520, (BASE_PLAYER[0], BASE_PLAYER[1] + dy, BASE_PLAYER[2]))
    ad = SFExaAdapter(b)
    assert ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("mode", [0, 1])
def test_scene_accepts_verified_follow_dispatches(mode):
    b = base_backend()
    b.seed_u32(mm.CAM_MODE, mode)
    ad = SFExaAdapter(b)
    assert ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("address,mode", [(mm.CAM_MODE, 2), (mm.CAM_MODE, 3),
                                         (mm.CAM_MODE, 5), (mm.CAM_MODE, 99),
                                         (mm.CAM_FOCUS_MODE, 1), (mm.CAM_FOCUS_MODE, 4)])
def test_scene_rejects_unverified_scripted_or_nonparty_dispatch(address, mode):
    b = base_backend()
    b.seed_u32(address, mode)
    ad = SFExaAdapter(b)
    scene = ad.read_scene()
    assert not scene.valid and scene.reason
    assert not ad.is_field_like(scene)


@pytest.mark.parametrize("address", [mm.CAM_EYE, mm.CAM_FOCUS, mm.PARTY_POS])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e7])
def test_scene_rejects_invalid_geometry(address, value):
    b = base_backend()
    b.seed_floats(address, (value, 3, 4))
    ad = SFExaAdapter(b)
    assert not ad.is_field_like(ad.read_scene())


@pytest.mark.parametrize("distance", [0, 1, 100, 10000, 10001])
def test_scene_rejects_loading_or_implausible_distance(distance):
    ad = SFExaAdapter(base_backend())
    scene = SceneState(Vec3(1, 2, 3), CameraPose(Vec3(0, 0, distance), Vec3(0, 0, 0)), 55, distance)
    assert not ad.is_field_like(scene)


def test_gate_changes_one_byte_and_is_idempotent():
    b = base_backend()
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0xA501BBAA)
    ad = SFExaAdapter(b)
    assert ad.patch_state() == "stock"
    ad.set_patch(True)
    assert b.read_u32(mm.SMOOTH_GATE_WORD) == 0xA500BBAA
    assert ad.patch_state() == "applied" and ad.patch_active()
    writes = list(b.writes)
    ad.set_patch(True)
    assert b.writes == writes
    ad.set_patch(False)
    assert b.read_u32(mm.SMOOTH_GATE_WORD) == 0xA501BBAA
    assert not ad.patch_active()


def test_unknown_gate_raises_without_memory_or_ownership_changes():
    b = base_backend()
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01070000)
    ad = SFExaAdapter(b)
    with pytest.raises(PatchConflict): ad.set_patch(True)
    assert not b.writes
    assert ad.patch_state() == "unknown"
    assert not ad._orbit_on and not ad._saved


def test_native_params_restore_only_owned_values():
    b = base_backend()
    before = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 120, -35, 1700, look_height=75)
    # A scene load replaces height; it is not ours to undo on exit.
    b.seed_floats(mm.CAM_HEIGHT, (333,))
    ad.set_patch(False)
    assert b.read_u32(mm.CAM_YAW_WORD) == before[mm.CAM_YAW_WORD]
    assert b.read_u32(mm.CAM_DISTANCE) == before[mm.CAM_DISTANCE]
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == 333
    assert not ad._saved and not ad._written


def test_orbit_reapplies_after_stock_state_restores_gate_and_fields():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 120, -35, 1700, look_height=75)
    expected = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    b.seed_u16(mm.CAM_YAW, 0)
    b.seed_u16(mm.CAM_PITCH, -364)
    b.seed_floats(mm.CAM_DISTANCE, (1000,))
    b.seed_floats(mm.CAM_HEIGHT, (250,))
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    ad.set_patch(True)
    assert all(b.read_u32(a) == w for a, w in expected.items())
    assert ad.patch_active()


@pytest.mark.parametrize("deg", [20, 45, 70, 90, 110])
@pytest.mark.parametrize("aspect", [640 / 448, 16 / 9, 1.0])
def test_fov_horizontal_to_vertical_conversion_and_rendered_readback(deg, aspect):
    b = base_backend()
    b.seed_floats(mm.CAM_ASPECT, (aspect,))
    b.seed_u16(mm.CAM_FOV & ~3, 0xBEEF)  # Roll and FOV share one aligned word.
    ad = SFExaAdapter(b)
    ad.write_fov_deg(deg)
    vdeg = 2 * math.degrees(math.atan(math.tan(math.radians(deg) / 2) / aspect))
    assert b.u16(mm.CAM_FOV) == pytest.approx(round(vdeg * 65536 / 360), abs=1)
    assert b.u16(mm.CAM_FOV & ~3) == 0xBEEF
    assert ad.patch_active()
    assert ad.read_fov_deg() == pytest.approx(fov_from_scale(BASE_VP[0]))
    emulate_parameter_frame(b)
    assert ad.read_fov_deg() == pytest.approx(deg, abs=.012)
    assert ad.fov_in_sync(deg)
    assert {a for a, _ in b.writes} <= {mm.CAM_FOV_WORD, mm.SMOOTH_GATE_WORD}


def test_fov_reads_column_norm_not_control_halfword_or_projection_translation():
    b = base_backend()
    sx = 1 / math.tan(math.radians(72) / 2)
    vp = list(BASE_VP)
    vp[0], vp[4], vp[8] = .6 * sx, .8 * sx, 0
    vp[12] = 999999
    b.seed_floats(mm.CAM_VP, vp)
    b.seed_u16(mm.CAM_FOV, 111)
    assert SFExaAdapter(b).read_fov_deg() == pytest.approx(72, abs=.001)


@pytest.mark.parametrize("aspect", [0, .5, 3, 4, float("nan"), float("inf")])
def test_invalid_aspect_refuses_fov_before_any_write(aspect):
    b = base_backend()
    b.seed_floats(mm.CAM_ASPECT, (aspect,))
    with pytest.raises(PatchConflict): SFExaAdapter(b).write_fov_deg(70)
    assert not b.writes


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_fov_refuses_before_any_write(value):
    b = base_backend()
    with pytest.raises(ValueError): SFExaAdapter(b).write_fov_deg(value)
    assert not b.writes


@pytest.mark.parametrize("value,clamped", [(-100, FOV_MIN_DEG), (999, FOV_MAX_DEG)])
def test_fov_clamps_supported_horizontal_range(value, clamped):
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.write_fov_deg(value)
    emulate_parameter_frame(b)
    assert ad.read_fov_deg() == pytest.approx(clamped, abs=.012)


def test_fov_does_not_compound_and_capture_original_survives_overrides():
    b = base_backend()
    ad = SFExaAdapter(b)
    stock = ad.capture_original_fov()
    for deg in (45, 80, 60, 60):
        ad.write_fov_deg(deg)
        emulate_parameter_frame(b)
        assert ad.read_fov_deg() == pytest.approx(deg, abs=.012)
        assert ad.capture_original_fov() == pytest.approx(stock, abs=.01)
    b.seed_u16(mm.CAM_FOV & ~3, 0xCAFE)
    ad.restore_fov()
    assert b.u16(mm.CAM_FOV) == BASE_VFOV
    assert b.u16(mm.CAM_FOV & ~3) == 0xCAFE
    assert ad.patch_state() == "stock"
    b.writes.clear()
    ad.restore_fov()
    assert not b.writes


def test_restore_never_enabled_fov_is_no_op():
    b = base_backend()
    SFExaAdapter(b).restore_fov()
    assert not b.writes


@pytest.mark.parametrize("fov_first", [True, False])
def test_fov_and_orbit_share_gate_and_release_in_either_order(fov_first):
    b = base_backend()
    stock = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    ad = SFExaAdapter(b)
    if fov_first: ad.write_fov_deg(70)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 110, -25, 1500, look_height=30)
    if not fov_first: ad.write_fov_deg(70)
    ad.set_patch(False)
    assert ad.patch_active(), "FOV still owns the gate"
    ad.restore_fov()
    assert ad.patch_state() == "stock"
    assert b.u16(mm.CAM_FOV) == BASE_VFOV
    assert all(b.read_u32(a) == w for a, w in stock.items())


@pytest.mark.parametrize("unknown_site", [mm.PAD_RX_LOAD, mm.PAD_RY_LOAD])
@pytest.mark.parametrize("on", [True, False])
def test_pad_preflight_refuses_unknown_at_either_site_without_partial_write(unknown_site, on):
    b = base_backend()
    b.seed_u32(unknown_site, 0xDEADBEEF)
    with pytest.raises(PatchConflict): SFExaAdapter(b).set_stick_block(on)
    assert not b.writes


@pytest.mark.parametrize("states", [(False, False), (True, False), (False, True), (True, True)])
def test_pad_known_mixed_states_are_recoverable_idempotently(states):
    b = base_backend()
    for addr, stock, applied in zip((mm.PAD_RX_LOAD, mm.PAD_RY_LOAD),
                                    (mm.PAD_RX_WORD, mm.PAD_RY_WORD), states):
        b.seed_u32(addr, mm.PAD_NEUTRAL_WORD if applied else stock)
    ad = SFExaAdapter(b)
    ad.set_stick_block(True)
    assert b.read_u32(mm.PAD_RX_LOAD) == b.read_u32(mm.PAD_RY_LOAD) == 0x2402007F
    b.writes.clear()
    ad.set_stick_block(True)
    assert not b.writes
    ad.set_stick_block(False)
    assert b.read_u32(mm.PAD_RX_LOAD) == 0x92620166
    assert b.read_u32(mm.PAD_RY_LOAD) == 0x92620167
    b.writes.clear()
    ad.set_stick_block(False)
    assert not b.writes


def test_pad_state_reload_reapplies_only_two_loads_not_raw_packet_or_generic_memcpy():
    b = base_backend()
    raw = bytes((0, 0, 0xFF, 0xFF, 0xFF, 0x00, 0x80, 0x7F))
    b.seed(mm.PAD_ROOT + 0x1A, raw)
    ad = SFExaAdapter(b)
    ad.set_stick_block(True)
    b.seed_u32(mm.PAD_RY_LOAD, mm.PAD_RY_WORD)
    b.writes.clear()
    ad.set_stick_block(True)
    assert [a for a, _ in b.writes] == [mm.PAD_RY_LOAD]
    assert b.bytes_at(mm.PAD_ROOT + 0x1A, len(raw)) == raw
    assert b.read_u32(mm.PAD_CALL_SITE) == 0x90A20000
    assert b.read_u32(mm.VP_LOAD_CALL) == 0x0C06B128


def test_runtime_original_restore_releases_params_fov_and_both_inline_loads():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT, MODE_ORIGINAL
    b = base_backend()
    original = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_DISTANCE,
                                           mm.CAM_HEIGHT, mm.CAM_FOV_WORD)}
    ad = SFExaAdapter(b)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT))
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 115, -30, 1450, look_height=55)
    ad.write_fov_deg(75)
    rt._sync_stick_block(True)
    rt.restore()
    assert rt.settings.mode == MODE_ORIGINAL and not rt.settings.use_fov
    assert all(b.read_u32(a) == w for a, w in original.items())
    assert ad.patch_state() == "stock"
    assert b.read_u32(mm.PAD_RX_LOAD) == mm.PAD_RX_WORD
    assert b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_RY_WORD
    assert rt.stats.last_error == ""


def test_runtime_keeps_publishing_while_actor_height_lags_camera_focus():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
    b = base_backend()
    ad = SFExaAdapter(b)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, distance=1000, pitch_deg=-2, look_height=35))
    rt.set_stick(.8, 0)
    rt._tick(.01, None)
    writes = rt.stats.total_writes
    p = ad.read_player()
    b.seed_floats(BASE_ACTOR + 0x520, (p.x, p.y + 100, p.z))
    rt._scene_time = 0
    rt._tick(.01, None)
    assert rt.stats.total_writes > writes
    assert rt.stats.last_error == ""
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == pytest.approx(285)


def test_all_native_operations_avoid_output_writes_caves_and_neo_addresses():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 130, -20, 1300, look_height=10)
    ad.write_fov_deg(65)
    ad.set_stick_block(True)
    ad.set_stick_block(False)
    ad.set_patch(False)
    ad.restore_fov()
    allowed = {mm.CAM_YAW_WORD, mm.CAM_DISTANCE, mm.CAM_HEIGHT,
               mm.CAM_FOV_WORD, mm.SMOOTH_GATE_WORD, mm.PAD_RX_LOAD, mm.PAD_RY_LOAD}
    assert {a for a, _ in b.writes} <= allowed
    assert not any(name.endswith("_CAVE") for name in vars(mm))
    assert SFExaAdapter.__mro__[1:] == (object,)


def test_runtime_native_center_writes_only_params_then_orbit_and_original_restore():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
    b = base_backend()
    original = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    output = (b.bytes_at(mm.CAM_EYE, 32), b.bytes_at(mm.CAM_VP, 64))
    ad = SFExaAdapter(b)
    rt = CameraRuntime(ad, CameraSettings(distance=1300, look_height=45))
    assert rt.center_on_target()
    assert rt.stats.last_error == ""
    assert b.read_floats(mm.CAM_DISTANCE, 1)[0] == 1300
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == 295
    assert abs(rt.settings.yaw_deg) == pytest.approx(180, abs=.002)
    assert rt.settings.pitch_deg == pytest.approx(-364 * 360 / 65536, abs=.002)
    assert rt.settings.distance == pytest.approx(1300)
    assert {a for a, _ in b.writes} <= {mm.CAM_YAW_WORD, mm.CAM_HEIGHT,
                                       mm.CAM_DISTANCE, mm.SMOOTH_GATE_WORD}
    assert output == (b.bytes_at(mm.CAM_EYE, 32), b.bytes_at(mm.CAM_VP, 64))
    emulate_parameter_frame(b)
    assert ad.read_game_pose().target.y == pytest.approx(BASE_PLAYER[1] + 295, abs=.001)
    rt.settings.mode = MODE_ORBIT
    rt.set_stick(.5, 0)
    rt._tick(.01, None)
    assert rt.stats.last_error == ""
    assert b.read_u32(mm.PAD_RX_LOAD) == b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_NEUTRAL_WORD
    rt.restore()
    assert all(b.read_u32(a) == w for a, w in original.items())
    assert ad.patch_state() == "stock"
    assert b.read_u32(mm.PAD_RX_LOAD) == mm.PAD_RX_WORD
    assert b.read_u32(mm.PAD_RY_LOAD) == mm.PAD_RY_WORD


def test_runtime_center_rejects_scripted_camera_without_writes():
    from core.camera_runtime.engine import CameraRuntime, CameraSettings
    b = base_backend()
    b.seed_u32(mm.CAM_MODE, 3)
    rt = CameraRuntime(SFExaAdapter(b), CameraSettings())
    assert not rt.center_on_target()
    assert "scene guard" in rt.stats.last_error
    assert not b.writes


def test_state_reload_rebases_original_params_before_reapply_and_restore():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 120, -35, 1700, look_height=75)
    ad.write_fov_deg(70)
    # A different known stock field state has different original framing and roll.
    b.seed_u16(mm.CAM_YAW, 5000)
    b.seed_u16(mm.CAM_PITCH, -2000)
    b.seed_floats(mm.CAM_DISTANCE, (850,))
    b.seed_floats(mm.CAM_HEIGHT, (320,))
    b.seed_u16(mm.CAM_FOV_WORD, 1234)
    b.seed_u16(mm.CAM_FOV, 6000)
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    loaded = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT,
                                        mm.CAM_DISTANCE, mm.CAM_FOV_WORD)}
    ad.set_patch(True)
    assert b.read_floats(mm.CAM_DISTANCE, 1)[0] == 1700
    ad.write_fov_deg(70)
    ad.set_patch(False)
    ad.restore_fov()
    assert all(b.read_u32(a) == w for a, w in loaded.items())
    assert ad.patch_state() == "stock"


def test_state_reload_fov_first_then_patch_republishes_orbit_and_restores_loaded_baseline():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 120, -35, 1700, look_height=75)
    ad.write_fov_deg(70)
    desired = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    b.seed_u16(mm.CAM_YAW, 5000)
    b.seed_u16(mm.CAM_PITCH, -2000)
    b.seed_floats(mm.CAM_DISTANCE, (850,))
    b.seed_floats(mm.CAM_HEIGHT, (320,))
    b.seed_u16(mm.CAM_FOV_WORD, 1234)
    b.seed_u16(mm.CAM_FOV, 6000)
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    loaded = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT,
                                        mm.CAM_DISTANCE, mm.CAM_FOV_WORD)}
    ad.write_fov_deg(70)  # FOV notices the loaded gate first and closes it.
    assert ad.patch_active()
    assert b.read_u32(mm.CAM_YAW_WORD) != desired[mm.CAM_YAW_WORD]
    ad.set_patch(True)
    assert all(b.read_u32(a) == w for a, w in desired.items())
    ad.set_patch(False)
    ad.restore_fov()
    assert all(b.read_u32(a) == w for a, w in loaded.items())


def test_orbit_recheck_republishes_overwritten_parameters_even_when_gate_stays_off():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 120, -35, 1700, look_height=75)
    desired = {a: b.read_u32(a) for a in (mm.CAM_YAW_WORD, mm.CAM_HEIGHT, mm.CAM_DISTANCE)}
    b.seed_floats(mm.CAM_HEIGHT, (320,))
    b.seed_u16(mm.CAM_YAW, 5000)
    assert ad.patch_active()
    ad.set_patch(True)
    assert all(b.read_u32(a) == w for a, w in desired.items())


@pytest.mark.parametrize("sync_original_first", [False, True])
def test_fov_only_state_reload_rebases_original_fov_before_reapply(sync_original_first):
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.write_fov_deg(70)
    # FOV is enabled in Original, without ever requesting Orbit.
    assert not ad._orbit_on
    b.seed_u16(mm.CAM_FOV_WORD, 2222)
    b.seed_u16(mm.CAM_FOV, 6000)
    b.seed_floats(mm.CAM_HEIGHT, (320,))
    b.seed_floats(mm.CAM_DISTANCE, (850,))
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    if sync_original_first:
        ad.set_patch(False)  # runtime checks the Original patch before servicing FOV
    ad.write_fov_deg(70)
    ad.restore_fov()
    assert b.u16(mm.CAM_FOV) == 6000
    assert b.u16(mm.CAM_FOV_WORD) == 2222
    assert b.read_floats(mm.CAM_DISTANCE, 1)[0] == 850
    assert b.read_floats(mm.CAM_HEIGHT, 1)[0] == 320
    assert ad.patch_state() == "stock"


def test_restore_fov_does_not_overwrite_a_new_scene_foreign_value():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.write_fov_deg(70)
    b.seed_u16(mm.CAM_FOV_WORD, 0xABCD)
    b.seed_u16(mm.CAM_FOV, 5000)
    ad.restore_fov()
    assert b.u16(mm.CAM_FOV) == 5000
    assert b.u16(mm.CAM_FOV_WORD) == 0xABCD
    assert ad.patch_state() == "stock"


def test_failed_fov_gate_preflight_does_not_claim_ownership_or_restore_over_new_scene():
    b = base_backend()
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01070000)
    ad = SFExaAdapter(b)
    with pytest.raises(PatchConflict):
        ad.write_fov_deg(70)
    assert not b.writes
    assert not ad._fov_on and ad._saved_fov is None
    # After the failed request a valid scene appears; a no-op restore cannot touch it.
    b.seed_u32(mm.SMOOTH_GATE_WORD, 0x01010000)
    b.seed_u16(mm.CAM_FOV, 5000)
    ad.restore_fov()
    assert b.u16(mm.CAM_FOV) == 5000
    assert not b.writes


def test_unsupported_offset_and_projection_operations_are_noops():
    b = base_backend()
    ad = SFExaAdapter(b)
    ad.write_eye_offset(Vec3(1, 2, 3))
    ad.clear_eye_offset()
    ad.write_aim(Vec3(4, 5, 6))
    ad.write_projection_centre(1)
    ad.write_projection_scale(2)
    ad.set_projection_source(True)
    ad.restore_aim()
    ad.write_walk_target(Vec3(1, 2, 3))
    ad.copy_stock_params()
    assert not b.writes
