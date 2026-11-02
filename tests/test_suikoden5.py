"""Suikoden V adapter tests on a fake PINE backend (no emulator needed)."""
from __future__ import annotations

import math
import struct

import pytest

from adapters.suikoden5 import caves, memory_map as mm
from adapters.suikoden5.adapter import Suikoden5Adapter
from core import mips_asm as m
from core.camera_math.orbit import Vec3


class FakeBackend:
    def __init__(self) -> None:
        self.mem: dict[int, int] = {}
        self.gid, self.crcv, self.ttl = mm.GAME_ID, mm.DISC_CRC.lower(), "Suikoden V"

    # words
    def read_u32(self, a: int) -> int:
        return self.mem.get(a, 0)

    def write_u32(self, a: int, v: int) -> None:
        self.mem[a] = v & 0xFFFFFFFF

    def read_floats(self, a: int, n: int) -> list[float]:
        return [struct.unpack("<f", struct.pack("<I", self.read_u32(a + 4 * i)))[0] for i in range(n)]

    def write_floats(self, a: int, vals) -> None:
        for i, v in enumerate(vals):
            self.write_u32(a + 4 * i, struct.unpack("<I", struct.pack("<f", float(v)))[0])

    write_float_block = write_floats

    def game_id(self): return self.gid
    def crc(self): return self.crcv
    def title(self): return self.ttl

    # the stock code at the two hook sites
    def stock(self) -> None:
        for i, w in enumerate(mm.CAM_HOOK_WORDS):
            self.write_u32(mm.CAM_HOOK + 4 * i, w)
        for i, w in enumerate(mm.ZOOM_HOOK_WORDS):
            self.write_u32(mm.ZOOM_HOOK + 4 * i, w)


@pytest.fixture
def be():
    b = FakeBackend()
    b.stock()
    # the game's camera globals in a typical field: focus, eye, pitch, yaw, dist, fov
    b.write_floats(mm.G_FOCUS, [65.6, 14.4, 5.1])
    b.write_floats(mm.G_EYE, [415.9, 104.4, 176.0])
    b.write_floats(mm.G_PITCH, [13.0]); b.write_floats(mm.G_YAW, [244.0])
    b.write_floats(mm.G_DISTANCE, [400.0]); b.write_floats(mm.G_FOV, [20.0])
    return b


# --- encoders and cave layout -------------------------------------------------------------
def test_encoders_match_game_words():
    assert m.add_s(2, 3, 2) == mm.CAM_HOOK_WORDS[0]
    assert m.swc1(2, m.T0, -0x2424) == mm.CAM_HOOK_WORDS[1]
    assert m.addiu(m.SP, m.SP, -0x70) == mm.ZOOM_HOOK_WORDS[0]
    assert m.jal(mm.FUN_FOV) == 0x0C08DBD8
    assert m.lwc1(2, m.S3, 0x10) == 0xC6620010


def test_cave_regions_do_not_overlap_and_fit():
    assert mm.MOD_BLOCK + 0x80 <= mm.CAVE_CAMERA
    assert mm.CAVE_CAMERA + 4 * len(caves.CAMERA_WORDS) <= mm.CAVE_ZOOM
    assert mm.CAVE_ZOOM + 4 * len(caves.ZOOM_WORDS) <= mm.CAVE_END
    assert mm.CAVE_END <= 0x4BDFBC          # the zero run found in the ELF and all five states


def test_camera_cave_ends_by_returning_into_the_original_code():
    words = caves.CAMERA_WORDS
    assert words[-2] == m.j(mm.CAM_RETURN) and words[-1] == m.NOP
    assert m.jal(mm.FUN_FOV) in words and m.jal(mm.FUN_NEARFAR) in words


def test_every_branch_stays_inside_its_cave():
    for words in (caves.CAMERA_WORDS, caves.ZOOM_WORDS):
        for i, w in enumerate(words):
            if w >> 26 in (4, 5):                       # beq / bne
                off = w & 0xFFFF
                off = off - 0x10000 if off & 0x8000 else off
                assert 0 <= i + 1 + off < len(words)


def test_zoom_cave_zeroes_only_the_two_right_stick_bytes():
    sb = [w for w in caves.ZOOM_WORDS if w >> 26 == 0x28]    # sb
    assert len(sb) == 2
    offs = sorted(((w & 0xFFFF) ^ 0x8000) - 0x8000 + 0x830000 for w in sb)
    assert offs == [mm.PAD_RIGHT_X, mm.PAD_RIGHT_Y]


def test_hooks_are_two_words_at_the_sites():
    assert caves.CAMERA_HOOK == (m.j(mm.CAVE_CAMERA), m.NOP)
    # the zoom entry keeps its second word: it runs in the jump's delay slot
    assert caves.ZOOM_HOOK == (m.j(mm.CAVE_ZOOM), mm.ZOOM_HOOK_WORDS[1])


# --- install / uninstall -------------------------------------------------------------------
def test_install_is_idempotent_and_reversible(be):
    assert caves.camera_site_state(be) == "original"
    caves.install_camera(be)
    caves.install_camera(be)
    assert caves.camera_site_state(be) == "patched"
    assert caves._read(be, mm.CAVE_CAMERA, len(caves.CAMERA_WORDS)) == caves.CAMERA_WORDS
    assert caves.block_valid(be)
    caves.uninstall_camera(be)
    assert caves.camera_site_state(be) == "original"
    assert (be.read_u32(mm.CAM_HOOK), be.read_u32(mm.CAM_HOOK + 4)) == mm.CAM_HOOK_WORDS


def test_unknown_word_at_a_site_is_never_overwritten(be):
    be.write_u32(mm.CAM_HOOK, 0x12345678)
    with pytest.raises(caves.CavePatchError):
        caves.install_camera(be)
    assert be.read_u32(mm.CAM_HOOK) == 0x12345678
    be.write_u32(mm.ZOOM_HOOK, 0x1)
    with pytest.raises(caves.CavePatchError):
        caves.install_zoom(be)


def test_busy_cave_area_is_refused(be):
    be.write_u32(mm.CAVE_CAMERA + 8, 0xDEADBEEF)
    with pytest.raises(caves.CavePatchError):
        caves.install_camera(be)
    assert caves.camera_site_state(be) == "original"


def test_uninstall_leaves_foreign_words_alone(be):
    be.write_u32(mm.CAM_HOOK, 0xABCDEF01)
    caves.uninstall_camera(be)
    assert be.read_u32(mm.CAM_HOOK) == 0xABCDEF01


# --- adapter ---------------------------------------------------------------------------------
def test_identify_checks_serial_and_crc(be):
    ad = Suikoden5Adapter(be)
    assert ad.identify().matched
    be.crcv = "00000000"
    assert not ad.identify().matched
    be.crcv, be.gid = mm.DISC_CRC, "SLPS-25250"
    assert not ad.identify().matched


def test_engine_frame_is_ffx2_style_y_down(be):
    ad = Suikoden5Adapter(be)
    pose = ad.read_game_pose()
    assert pose.target.y == pytest.approx(-14.4, abs=1e-3)       # game +Y up -> engine +Y down
    yaw, pitch = pose.yaw_pitch()
    # stock game yaw 244 / pitch 13  ->  engine yaw 64 / pitch 13
    assert math.degrees(yaw) == pytest.approx(64.0, abs=0.2)
    assert math.degrees(pitch) == pytest.approx(13.0, abs=0.2)
    assert pose.distance() == pytest.approx(400.0, abs=0.5)


def test_write_orbit_params_maps_angles_and_flags(be):
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    anchor = ad.read_player()
    ad.write_orbit_params(anchor, 64.0, 13.0, 400.0)
    mb = lambda o: be.read_floats(mm.MOD_BLOCK + o, 1)[0]
    assert mb(mm.MB_YAW) == pytest.approx(244.0)           # engine yaw - 180
    assert mb(mm.MB_PITCH) == pytest.approx(13.0)
    assert mb(mm.MB_DISTANCE) == pytest.approx(400.0)
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_OFF_X, 3) == [0.0, 0.0, 0.0]
    assert caves.read_flags(be) & mm.FLAGS_ORBIT == mm.FLAGS_ORBIT
    ad.write_orbit_params(anchor, -90.0, 30.0, 250.0)
    assert mb(mm.MB_YAW) == pytest.approx(90.0)            # wraps into 0..360


def test_centre_and_position_offsets_become_world_offsets(be):
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    a = ad.read_player()
    # engine +Y is down: a centre 10 below the anchor is 10 lower in the game (-Y)
    ad.write_orbit_params(Vec3(a.x + 3, a.y + 10, a.z - 2), 64.0, 13.0, 400.0,
                          pos_offset=Vec3(1.0, 2.0, 0.5))
    ox, oy, oz = be.read_floats(mm.MOD_BLOCK + mm.MB_OFF_X, 3)
    assert (ox, oy, oz) == pytest.approx((4.0, -12.0, -1.5), abs=1e-5)


def test_fov_flag_and_restore(be):
    ad = Suikoden5Adapter(be)
    ad.write_fov_deg(60.0)
    assert caves.read_flags(be) & mm.FLAG_FOV
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_FOV, 1)[0] == pytest.approx(60.0)
    ad.write_fov_deg(500.0)                                 # clamped to the engine range
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_FOV, 1)[0] == pytest.approx(110.0)
    ad.restore_fov()
    assert not caves.read_flags(be) & mm.FLAG_FOV
    assert caves.camera_site_state(be) == "original"       # nothing left that needs the hook


def test_restore_keeps_the_hook_while_fov_is_still_wanted(be):
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(50.0)
    ad.set_patch(False)
    assert caves.camera_site_state(be) == "patched"         # FOV still needs it
    ad.restore_fov()
    assert caves.camera_site_state(be) == "original"


def test_stick_block_installs_and_releases_the_zoom_hook(be):
    ad = Suikoden5Adapter(be)
    ad.set_stick_block(True)
    assert caves.zoom_site_state(be) == "patched"
    assert caves.read_flags(be) & mm.FLAG_BLOCK_RSTICK
    ad.set_stick_block(False)
    assert caves.zoom_site_state(be) == "original"
    assert not caves.read_flags(be) & mm.FLAG_BLOCK_RSTICK


def test_uninstall_all_restores_every_stock_word(be):
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    ad.set_stick_block(True)
    ad.write_fov_deg(45.0)
    ad.uninstall_all()
    assert caves.camera_site_state(be) == "original" and caves.zoom_site_state(be) == "original"
    assert caves.read_flags(be) == 0


def test_heartbeat_guard_goes_false_when_the_camera_update_stops(be, monkeypatch):
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    be.write_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT, 5)
    be.write_floats(mm.MOD_BLOCK + mm.MB_NATIVE_FOCUS, [65.6, 14.4, 5.1])   # what the live cave stores
    scene = ad.read_scene()
    assert ad.is_field_like(scene)
    t = [1000.0]
    monkeypatch.setattr("adapters.suikoden5.adapter.time.monotonic", lambda: t[0])
    ad._hb_seen = None
    assert ad.is_field_like(scene)                           # first sight of the counter
    t[0] += 5.0                                              # counter frozen for 5 s: loading/event
    assert not ad.is_field_like(scene)
    be.write_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT, 6)
    assert ad.is_field_like(scene)


def test_zero_focus_is_not_a_field(be):
    be.write_floats(mm.G_FOCUS, [0.0, 0.0, 0.0])
    ad = Suikoden5Adapter(be)
    assert not ad.is_field_like(ad.read_scene())


def test_zoom_stage_helpers(be):
    ad = Suikoden5Adapter(be)
    assert ad.read_zoom_stage() is None                      # cave has not seen the camera yet
    ad.set_patch(True)
    be.write_u32(mm.MOD_BLOCK + mm.MB_CTL_PTR, 0x129D7D8)
    be.write_u32(0x129D7D8 + mm.CTL_ZOOM_STAGE, 0x00010002)  # upper half belongs to something else
    assert ad.read_zoom_stage() == 2
    assert ad.set_zoom_stage(1) == 300.0
    assert be.read_u32(0x129D7D8 + mm.CTL_ZOOM_STAGE) == 0x00010001
    assert [ad.stage_distance(i) for i in range(3)] == [400.0, 300.0, 200.0]


def test_default_settings_reproduce_the_stock_framing():
    d = Suikoden5Adapter(FakeBackend()).default_settings()
    assert d["distance"] == 400.0 and d["pitch_deg"] == 13.0 and d["fov_deg"] == 20.0
    assert d["yaw_deg"] == pytest.approx(64.0)
    assert d["look_height"] == 0.0


def test_gui_registers_the_adapter():
    pytest.importorskip("PySide6")
    from gui.camera_controller import app
    assert app.ADAPTER_BY_GAME_ID["SLPM-66286"] is Suikoden5Adapter
    assert "SLPM-66286" in app.SUPPORTED_IDS


def test_switching_the_orbit_on_never_shows_a_zero_frame(be):
    """The flags go on only after the override slots hold what the game draws now."""
    ad = Suikoden5Adapter(be)
    order = []
    real = be.write_u32

    def spy(a, v):
        if a == mm.MOD_BLOCK + mm.MB_FLAGS and v & mm.FLAGS_ORBIT:
            order.append(tuple(be.read_floats(mm.MOD_BLOCK + mm.MB_DISTANCE, 3)))
        real(a, v)

    be.write_u32 = spy
    ad.set_patch(True)
    assert order and order[0] == pytest.approx((400.0, 13.0, 244.0))


def test_a_reinstalled_hook_starts_from_the_last_orbit_not_the_game_camera(be):
    """After a savestate load the hook comes back at the orbit the user had (no jump)."""
    ad = Suikoden5Adapter(be)
    ad.set_patch(True)
    ad.write_orbit_params(ad.read_player(), 10.0, 33.0, 280.0)
    be.mem.clear()                      # a savestate load: RAM reverts, our words are gone
    be.stock()
    be.write_floats(mm.G_FOCUS, [65.6, 14.4, 5.1]); be.write_floats(mm.G_YAW, [244.0])
    order = []
    real = be.write_u32

    def spy(a, v):
        if a == mm.MOD_BLOCK + mm.MB_FLAGS and v & mm.FLAGS_ORBIT:
            order.append(tuple(be.read_floats(mm.MOD_BLOCK + mm.MB_DISTANCE, 3)))
        real(a, v)

    be.write_u32 = spy
    ad.set_patch(True)
    assert order[0] == pytest.approx((280.0, 33.0, 190.0))
