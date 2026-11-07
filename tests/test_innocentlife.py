"""Synthetic-memory contracts; never connect to or control a live emulator.

The small R5900 runner executes emitted guest instructions with one native
builder stub. This proves publication/ABI/restoration contracts, not PS2
scheduling, visual rendering, or unverified menu/event coverage.
"""
from __future__ import annotations

import math
import struct
import threading

import pytest

from adapters.innocentlife import InnocentLifeAdapter, caves, memory_map as mm
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
from tests.test_druaga import FakeBackend as ByteBackend
from tests.test_radiata import CaveMachine as BaseMachine

PLAYER = Vec3(100, 20, -50)
NATIVE = orbit_pose(PLAYER + Vec3(0, -15, 0), math.pi, math.radians(35), 90)
GP = 0x23E9F0
NATIVE_X_FACTOR = 0.7999999523162842
NATIVE_Y_FACTOR = 0.9333332777023315


def seed_projection(backend, focal):
    """Model the native builder's screen-space output, not a requested FOV mirror."""
    projection = [0.0] * 16
    projection[0] = focal * backend.read_f32(mm.PROJECTION_X_FACTOR)
    projection[5] = focal * backend.read_f32(mm.PROJECTION_Y_FACTOR)
    projection[8] = projection[9] = 2048.0
    projection[11] = 1.0
    backend.seed_floats(mm.PROJECTION, projection)


def expected_focal(backend, degrees):
    return 256.0 / (backend.read_f32(mm.PROJECTION_X_FACTOR)
                    * math.tan(math.radians(degrees) / 2))


class FakeBackend(ByteBackend):
    """A host write may schedule one synthetic render-tail guest callback."""
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)
        self._memory_lock = threading.RLock()
        self.auto_guest = True
        self.in_guest = False
        self.before_guest = None
        self.host_writes = []
        self.guest_cycles = 0

    def title(self):
        return "INNOCENT LIFE"

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]

    def seed(self, address, data):
        with self._memory_lock:
            super().seed(address, data)

    def bytes_at(self, address, length):
        with self._memory_lock:
            return super().bytes_at(address, length)

    def write_u32(self, address, value):
        # One synthetic EE CPU owns its stack and lifecycle callback, even when
        # a GUI status worker reads this transport concurrently. A native PINE
        # backend has its own socket serialization; sparse dict memory does not.
        with self._memory_lock:
            if not self.in_guest:
                self.host_writes.append((address, value & 0xFFFFFFFF))
            super().write_u32(address, value)
            if (not self.in_guest and self.auto_guest
                    and super().read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
                    and super().read_u32(mm.RENDER_HOOK) == caves.RENDER_PAIR[0]):
                self.in_guest = True
                try:
                    self.guest_cycles += 1
                    if self.before_guest:
                        self.before_guest(self)
                    CaveMachine(self).render()
                finally:
                    self.in_guest = False


class CaveMachine(BaseMachine):
    def __init__(self, backend):
        super().__init__(backend)
        self.regs[28] = GP
        self.on_builder = None

    def execute(self, word):
        op, rs, rt = word >> 26, word >> 21 & 31, word >> 16 & 31
        if op == 0x24:  # lbu
            imm = word & 65535
            signed = imm - 65536 if imm & 32768 else imm
            self.put(rt, self.b.bytes_at((self.regs[rs] + signed) & 0xFFFFFFFF, 1)[0])
        elif op == 0x11 and rs == 4:  # mtc1, no other FPU register changes
            self.fpu[word >> 11 & 31] = struct.unpack("<f", struct.pack("<I", self.regs[rt] & 0xFFFFFFFF))[0]
        else:
            super().execute(word)

    def native(self, target):
        if target == mm.MOVE_CONTINUE:
            self.calls.append(("move", self.fpu[12], self.fpu[0]))
            return
        assert target == mm.FUN_BUILD_VIEW
        camera = self.regs[m.A0]
        eye = Vec3(*self.b.read_floats(camera, 3))
        pitch, yaw = self.b.read_f32(camera + 0x10), self.b.read_f32(camera + 0x14)
        forward = Vec3(math.sin(yaw) * math.cos(pitch), -math.sin(pitch), math.cos(yaw) * math.cos(pitch))
        focal = self.b.read_f32(camera + 0x7C)
        self.calls.append(("build", camera, eye, pitch, yaw, self.b.read_f32(camera + 0x18), focal))
        seed_projection(self.b, focal)
        self.b.seed_floats(mm.CAM_FORWARD, (*forward.as_tuple(), 1))
        self.b.seed_floats(mm.VIEW, (*eye.as_tuple(), pitch, yaw))
        if self.on_builder:
            self.on_builder(self)
        # Model caller-saved GPR destruction; return values must survive lifecycle.
        for reg in (*range(m.T0, m.T7 + 1), m.A0, m.A1, m.A2, m.A3):
            self.regs[reg] = 0xBAD00000 | reg
        self.regs[m.V0], self.regs[m.V1] = 123, 456

    def render(self, camera=mm.CAMERA):
        self.regs[m.A0] = camera
        self.run(mm.RENDER_CAVE)
        return self.calls[-1]

    def movement(self, actor=mm.PLAYER):
        self.regs[m.S2] = actor
        self.run(mm.MOVE_CAVE)
        return self.calls[-1]


def seed_field(backend):
    for address, value in mm.EXACT_GUARDS:
        backend.seed_u32(address, value)
    backend.seed_u32(mm.FIELD_OWNER, 0xB00000)
    backend.seed_u32(mm.PLAYER + mm.PLAYER_FLAGS, 0xBC)  # verified ordinary idle state
    backend.seed_u32(mm.NATIVE_FLAGS, 0x100)
    backend.seed_u32(mm.INPUT_GUARD_BYTE, 0)
    backend.seed_floats(mm.PLAYER, (*PLAYER.as_tuple(), 1))
    backend.seed_floats(mm.CAM_EYE, (*NATIVE.eye.as_tuple(), 1))
    backend.seed_floats(mm.CAM_PITCH, (-math.radians(35), 0, 0.25))
    backend.seed_floats(mm.CAM_LOOK_HEIGHT, [-15])
    backend.seed_floats(mm.CAM_FOCAL, [mm.STOCK_FOCAL])
    backend.seed_floats(mm.PROJECTION_X_FACTOR, [NATIVE_X_FACTOR])
    backend.seed_floats(mm.PROJECTION_Y_FACTOR, [NATIVE_Y_FACTOR])
    seed_projection(backend, backend.read_f32(mm.CAM_FOCAL))
    backend.seed_floats(mm.CAM_FORWARD, [0, 0.573576, 0.819152, 99])
    backend.seed_u32(mm.CLOCK_HOURS, 8)
    backend.seed_u32(mm.CLOCK_MINUTES, 9)
    backend.seed_u32(mm.CLOCK_SECONDS, 7)
    for address, stock, _, _, _ in caves.RESOURCES:
        for i, word in enumerate(stock):
            backend.seed_u32(address + 4 * i, word)
    backend.seed_u32(mm.MOVE_CONTINUE, mm.MOVE_CONTINUE_STOCK)
    backend.seed_u32(mm.CLOCK_HOOK, mm.CLOCK_STOCK)
    return backend


@pytest.fixture
def be():
    return seed_field(FakeBackend())


def active_bank(backend):
    return mm.MOD_BLOCK + mm.SLOTS[backend.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def assert_stock(backend):
    assert caves.matches(backend, 0)


@pytest.mark.parametrize("serial,crc,expected", [
    (mm.GAME_ID, mm.DISC_CRC, True), (" slps-25763 ", " 9ac21f92 ", True),
    (mm.GAME_ID, "DEADBEEF", False), ("SLPS-00000", mm.DISC_CRC, False), ("", "", False),
])
def test_identity_requires_serial_and_crc(serial, crc, expected):
    backend = FakeBackend(serial, crc)
    assert InnocentLifeAdapter(backend).identify().matched is expected
    assert not backend.writes


def test_reads_features_defaults_and_native_horizontal_fov_without_writes(be):
    ad = InnocentLifeAdapter(be)
    assert ad.read_player() == PLAYER
    assert ad.read_scene().valid
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(NATIVE.eye.as_tuple())
    assert ad.read_game_pose().target.as_tuple() == pytest.approx(NATIVE.target.as_tuple(), abs=1e-5)
    assert ad.read_game_time() == "08:09:07"
    assert not ad.time_paused()
    assert ad.PITCH_DISPLAY_SIGN == ad.PITCH_INPUT_SIGN == 1
    assert ad.features == dict(orbit=True, free_camera=False, fov=True,
                               position_offsets=True, target_offsets=True,
                               per_frame_write=False, game_time_pause=True)
    assert ad.default_settings() == dict(distance=90, look_height=-15, pitch_deg=35, yaw_deg=180,
                                         fov_deg=pytest.approx(71.635048, abs=1e-5))
    assert ad.capture_original_fov() == pytest.approx(71.635048, abs=1e-5)
    assert ad.read_fov_deg() == pytest.approx(71.635048, abs=1e-5)
    # Host float32 multiplication may differ by one ULP from R5900 rounding.
    assert ad.read_fov_scale() == pytest.approx(354.723999, abs=5e-5)
    assert be.read_f32(mm.PROJECTION + 0x14) == pytest.approx(413.844696, abs=5e-5)
    ad.restore_fov()
    ad.set_stick_block(True)
    assert not be.writes


@pytest.mark.parametrize("degrees", [20, 60, 110])
def test_fov_uses_copied_camera_builder_and_real_projection_preserving_native(be, degrees):
    ad = InnocentLifeAdapter(be)
    native = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    forward = be.bytes_at(mm.CAM_FORWARD, 16)
    ad.set_patch(True)
    ad.write_fov_deg(degrees)
    # Publication alone does not pretend that the game has rendered the new lens.
    assert not ad.fov_in_sync(degrees)
    call = CaveMachine(be).render()
    focal = expected_focal(be, degrees)
    assert call[1] == mm.MOD_BLOCK + mm.MB_CAMERA_SCRATCH
    assert call[6] == pytest.approx(focal)
    assert be.read_f32(active_bank(be) + mm.SLOT_FOCAL) == pytest.approx(focal)
    assert be.read_f32(mm.PROJECTION) == pytest.approx(256 / math.tan(math.radians(degrees) / 2))
    assert be.read_f32(mm.PROJECTION + 0x14) == pytest.approx(focal * NATIVE_Y_FACTOR)
    assert ad.read_fov_deg() == pytest.approx(degrees, abs=1e-5)
    assert ad.fov_in_sync(degrees)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT | mm.FLAG_FOV
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) == mm.FLAG_ORBIT
    assert not mm.ALL_FLAGS & mm.FLAG_FOV
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    assert be.bytes_at(mm.CAM_FORWARD, 16) == forward
    assert not any(mm.CAMERA <= a < mm.CAMERA + mm.CAMERA_SIZE
                   or mm.PROJECTION <= a < mm.PROJECTION + 0x40 for a, _ in be.host_writes)
    # Requested values/bank flags are insufficient when the actual output differs.
    be.seed_floats(mm.PROJECTION, [123])
    assert not ad.fov_in_sync(degrees)
    assert ad.read_fov_deg() == pytest.approx(math.degrees(2 * math.atan(256 / 123)))


def test_restore_fov_copies_then_current_scripted_native_focal(be):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    CaveMachine(be).render()
    be.seed_floats(mm.CAM_FOCAL, [620.5])
    native = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    assert ad.capture_original_fov() == pytest.approx(math.degrees(2 * math.atan(256 / (620.5 * NATIVE_X_FACTOR))))
    ad.restore_fov()
    assert not be.read_u32(active_bank(be) + mm.SLOT_FLAGS) & mm.FLAG_FOV
    call = CaveMachine(be).render()
    assert call[6] == 620.5
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT
    assert be.read_f32(mm.PROJECTION) == pytest.approx(620.5 * NATIVE_X_FACTOR)
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    assert ad.patch_active() and not ad.fov_in_sync(60)
    ad.restore()
    assert_stock(be)
    assert be.read_f32(mm.CAM_FOCAL) == 620.5


@pytest.mark.parametrize("degrees", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_fov_is_rejected_with_zero_writes(be, degrees):
    ad = InnocentLifeAdapter(be)
    with pytest.raises(ValueError, match="non-finite"):
        ad.write_fov_deg(degrees)
    assert not ad.fov_in_sync(degrees)
    assert not be.writes


@pytest.mark.parametrize("factor", [float("nan"), float("inf"), -float("inf"), 0, -1, .09, 4, 1e8])
def test_invalid_projection_factor_rejects_fov_before_any_preparation(be, factor):
    be.seed_floats(mm.PROJECTION_X_FACTOR, [factor])
    ad = InnocentLifeAdapter(be)
    with pytest.raises(caves.PatchConflict, match="projection X factor"):
        ad.write_fov_deg(60)
    with pytest.raises(caves.PatchConflict, match="projection X factor"):
        ad.capture_original_fov()
    assert not be.writes


@pytest.mark.parametrize("scale", [float("nan"), float("inf"), -float("inf"), 0, -1])
def test_invalid_projection_output_is_unavailable_not_a_requested_value(be, scale):
    be.seed_floats(mm.PROJECTION, [scale])
    assert InnocentLifeAdapter(be).read_fov_deg() == 0
    assert not be.writes


@pytest.mark.parametrize("degrees,clamped", [(0, 20), (180, 110)])
def test_finite_fov_requests_are_clamped_to_supported_range(be, degrees, clamped):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(degrees)
    CaveMachine(be).render()
    assert ad.read_fov_deg() == pytest.approx(clamped, abs=1e-5)
    assert ad.fov_in_sync(degrees)


def test_fov_request_without_orbit_never_enables_a_standalone_lifecycle_lane(be):
    ad = InnocentLifeAdapter(be)
    ad.write_fov_deg(60)
    assert_stock(be)
    assert not be.writes
    assert not ad.patch_active() and not ad.fov_in_sync(60)
    ad.set_time_paused(True)
    assert caves.matches(be, mm.FLAG_TIME)
    assert CaveMachine(be).render()[1] == mm.CAMERA
    assert ad.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-5)
    assert not ad.patch_active() and ad.time_paused()
    ad.restore_fov()
    assert ad.time_paused() and caves.matches(be, mm.FLAG_TIME)
    ad.set_patch(True)
    CaveMachine(be).render()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT
    ad.restore()
    assert_stock(be)


BAD_GUARDS = ([(address, value ^ 1) for address, value in mm.EXACT_GUARDS]
              + [(mm.FIELD_OWNER, 0), (mm.NATIVE_FLAGS, 0x28008),
                 (mm.INPUT_GUARD_BYTE, 0x20)])


@pytest.mark.parametrize("address,value", BAD_GUARDS)
def test_host_scene_guards_refuse_orbit_before_any_write(be, address, value):
    be.seed_u32(address, value)
    ad = InnocentLifeAdapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        ad.set_patch(True)
    with pytest.raises(caves.PatchConflict):
        ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize("address", [mm.CAM_EYE, mm.CAM_PITCH, mm.CAM_YAW, mm.PLAYER, mm.CAM_FOCAL])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 1e8])
def test_native_geometry_validation_is_read_only(be, address, bad):
    be.seed_floats(address, [bad])
    ad = InnocentLifeAdapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize("field", ["centre", "yaw_deg", "pitch_deg", "distance", "pos_offset", "target_offset"])
def test_nonfinite_requests_are_rejected_without_writes(be, field):
    args = dict(centre=PLAYER, yaw_deg=0, pitch_deg=35, distance=90,
                pos_offset=Vec3(0, 0, 0), target_offset=Vec3(0, -15, 0))
    args[field] = Vec3(float("nan"), 0, 0) if field in ("centre", "pos_offset", "target_offset") else float("inf")
    with pytest.raises(ValueError):
        InnocentLifeAdapter(be).write_orbit_params(**args)
    assert not be.writes


@pytest.mark.parametrize("position", [Vec3(0, 0, -100), Vec3(0, 10, -100)])
def test_singular_offset_view_rejected_before_preparation(be, position):
    with pytest.raises(ValueError, match="singular"):
        InnocentLifeAdapter(be).write_orbit_params(PLAYER, 0, 0, 100,
                                                  pos_offset=position, target_offset=Vec3(0, 0, 0))
    assert not be.writes


@pytest.mark.parametrize("site", range(len(caves.RESOURCES)))
@pytest.mark.parametrize("resource", ["hook", "delay", "cave"])
@pytest.mark.parametrize("lane", ["orbit", "time", "fov"])
def test_all_unknown_resources_rejected_before_any_write(be, site, resource, lane):
    address, _, _, cave, words = caves.RESOURCES[site]
    bad = address if resource == "hook" else address + 4 if resource == "delay" else cave + 4 * (len(words) - 1)
    be.seed_u32(bad, 0xDEADBEEF)
    ad = InnocentLifeAdapter(be)
    with pytest.raises(caves.PatchConflict):
        if lane == "fov":
            ad.write_fov_deg(60)
        else:
            (ad.set_patch if lane == "orbit" else ad.set_time_paused)(True)
    assert not be.writes


@pytest.mark.parametrize("address", [mm.CLOCK_HOOK, mm.MOVE_CONTINUE, mm.MOD_BLOCK, mm.MOD_BLOCK + mm.BLOCK_SIZE - 4])
def test_unknown_clock_continuation_or_control_occupancy_has_zero_writes(be, address):
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict):
        InnocentLifeAdapter(be).set_time_paused(True)
    assert not be.writes


@pytest.mark.parametrize("site", range(len(caves.RESOURCES)))
@pytest.mark.parametrize("damage", ["nonzero", "zero"])
def test_reachable_damaged_cave_never_rebuilt_or_force_restored(be, site, damage):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    _, _, _, address, words = caves.RESOURCES[site]
    be.seed(address, bytes(len(words) * 4))
    if damage == "nonzero":
        be.seed_u32(address + 4, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        ad.set_patch(True)
    with pytest.raises(caves.PatchConflict):
        ad.restore()
    assert not be.writes


@pytest.mark.parametrize("yaw,pitch", [(0, 35), (90, 60), (-135, -20), (720, 89)])
def test_offsets_native_angles_match_actual_view_and_preserve_native_rig(be, yaw, pitch):
    ad = InnocentLifeAdapter(be)
    original = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    original_forward = be.bytes_at(mm.CAM_FORWARD, 16)
    position, target = Vec3(7, 2, -10), Vec3(3, -15, 8)
    ad.write_orbit_params(Vec3(9000, 8000, 7000), yaw, pitch, 90,
                          pos_offset=position, target_offset=target)
    relative = orbit_pose(target, math.radians(yaw), math.radians(pitch), 90)
    relative = CameraPose(relative.eye + position, relative.target)
    bank = active_bank(be)
    forward = relative.target - relative.eye
    assert be.read_f32(bank + mm.SLOT_YAW) == pytest.approx(math.atan2(forward.x, forward.z))
    assert be.read_f32(bank + mm.SLOT_PITCH) == pytest.approx(-math.atan2(forward.y, math.hypot(forward.x, forward.z)))
    fresh = PLAYER + Vec3(10, -20, 30)
    be.seed_floats(mm.PLAYER, (*fresh.as_tuple(), 1))
    runner = CaveMachine(be)
    saved = {r: runner.regs[r] for r in (m.SP, 31, 28, *range(16, 24))}
    call = runner.render()
    assert call[1] == mm.MOD_BLOCK + mm.MB_CAMERA_SCRATCH
    assert call[2].as_tuple() == pytest.approx((relative.eye + fresh).as_tuple(), abs=2e-5)
    assert call[5] == 0
    assert ad.read_game_pose().target.as_tuple() == pytest.approx((relative.target + fresh).as_tuple())
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == original
    assert be.bytes_at(mm.CAM_FORWARD, 16) == original_forward
    assert {r: runner.regs[r] for r in saved} == saved
    assert runner.regs[m.V0] == 123 and runner.regs[m.V1] == 456
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


def test_native_callee_can_use_argument_home_without_damaging_wrapper_frame(be):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    runner = CaveMachine(be)
    saved_ra, saved_sp = runner.regs[31], runner.regs[m.SP]
    native_forward = be.bytes_at(mm.CAM_FORWARD, 16)
    def use_argument_home(machine):
        be.seed(machine.regs[m.SP], bytes([0xAB]) * 0x20)
    runner.on_builder = use_argument_home
    runner.render()
    assert (runner.regs[31], runner.regs[m.SP]) == (saved_ra, saved_sp)
    assert be.bytes_at(mm.CAM_FORWARD, 16) == native_forward
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


def test_bank_sequence_publication_order_and_wraparound(be):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    slot = (be.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1) ^ 1
    bank = mm.MOD_BLOCK + mm.SLOTS[slot]
    be.seed_u32(bank + mm.SLOT_SEQUENCE, 0xFFFFFFFE)
    be.host_writes.clear()
    ad.write_fov_deg(60)
    writes = be.host_writes
    seq = [(i, value) for i, (address, value) in enumerate(writes) if address == bank]
    flip = next(i for i, (address, _) in enumerate(writes) if address == mm.MOD_BLOCK + mm.MB_SLOT)
    assert [value for _, value in seq] == [1, 0]
    assert seq[0][0] < seq[1][0] < flip
    assert all(bank <= address < bank + mm.SLOT_SIZE for address, _ in writes[:flip])
    focal_write = next(i for i, (address, _) in enumerate(writes) if address == bank + mm.SLOT_FOCAL)
    flags_write = next(i for i, (address, _) in enumerate(writes) if address == bank + mm.SLOT_FLAGS)
    assert seq[0][0] < focal_write < flags_write < seq[1][0] < flip
    assert be.read_f32(bank + mm.SLOT_FOCAL) == pytest.approx(expected_focal(be, 60))
    assert be.read_u32(bank + mm.SLOT_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV


@pytest.mark.parametrize("address,value", BAD_GUARDS)
def test_guest_scene_checks_fall_back_render_and_movement(be, address, value):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    be.seed_u32(address, value)
    runner = CaveMachine(be)
    assert runner.render()[1] == mm.CAMERA
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert ad.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-5)
    assert not ad.fov_in_sync(60)
    assert runner.movement()[1] == be.read_f32(mm.CAM_YAW)


@pytest.mark.parametrize("damage", ["odd", "changed", "flags", "player", "magic"])
def test_guest_rejects_unstable_or_unowned_bank(be, damage):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    bank = active_bank(be)
    if damage == "odd":
        be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif damage == "flags":
        be.seed_u32(bank + mm.SLOT_FLAGS, 0)
    elif damage == "player":
        be.seed_u32(bank + mm.SLOT_PLAYER, mm.PLAYER + 16)
    elif damage == "magic":
        be.seed_u32(mm.MOD_BLOCK, 0)
    else:
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                be.seed_u32(address, value + 2)
            return value
        be.read_u32 = changed
    call = CaveMachine(be).render()
    assert call[1] == mm.CAMERA and call[6] == be.read_f32(mm.CAM_FOCAL)
    if damage != "magic":  # Do not write diagnostics inside an unowned control block.
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert not ad.fov_in_sync(60)
    assert CaveMachine(be).movement()[1] == be.read_f32(mm.CAM_YAW)


@pytest.mark.parametrize("flags", [0xBC, 0xBE])
def test_transient_actor_input_bit_is_not_a_camera_scene_guard(be, flags):
    be.seed_u32(mm.PLAYER + mm.PLAYER_FLAGS, flags)
    ad = InnocentLifeAdapter(be)
    assert ad.read_scene().valid
    ad.write_orbit_params(PLAYER, 90, 35, 90, target_offset=Vec3(0, -15, 0))
    assert CaveMachine(be).render()[1] == mm.MOD_BLOCK + mm.MB_CAMERA_SCRATCH
    # Entry is the native input consumer, already downstream of native actor
    # input checks; actor identity and the structural scene guards still apply.
    substituted = CaveMachine(be).movement()[1]
    assert substituted == be.read_f32(active_bank(be) + mm.SLOT_YAW)
    assert substituted != pytest.approx(be.read_f32(mm.CAM_YAW))


def test_movement_preserves_128bit_scratch_f0_and_native_jal_boundary(be):
    ad = InnocentLifeAdapter(be)
    ad.write_orbit_params(PLAYER, 70, 35, 90, pos_offset=Vec3(20, 0, 0), target_offset=Vec3(0, -15, 0))
    runner = CaveMachine(be)
    for reg in range(m.T0, m.T5 + 1):
        runner.regs[reg] = (1 << 120) | (reg << 64) | reg
    saved = {reg: runner.regs[reg] for reg in range(m.T0, m.T5 + 1)}
    runner.fpu[0], runner.fpu[1] = 0.75, 123.25
    call = runner.movement()
    assert call[1] == be.read_f32(active_bank(be) + mm.SLOT_YAW)
    assert call[2] == runner.fpu[0] == 0.75
    assert runner.fpu[1] == 123.25
    assert {reg: runner.regs[reg] for reg in saved} == saved
    assert runner.regs[m.V0] == mm.CAMERA
    assert be.read_u32(mm.MOVE_CONTINUE) == mm.MOVE_CONTINUE_STOCK
    assert CaveMachine(be).movement(mm.PLAYER + 0x100)[1] == be.read_f32(mm.CAM_YAW)


@pytest.mark.parametrize("order", ["orbit_first", "time_first"])
def test_independent_lane_release_and_complete_cleanup(be, order):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    ad.set_time_paused(True)
    CaveMachine(be).render()
    assert ad.patch_active() and ad.time_paused() and ad.fov_in_sync(60)
    code = be.bytes_at(mm.RENDER_CAVE, len(caves.RENDER_WORDS) * 4)
    if order == "orbit_first":
        ad.set_patch(False)
        assert not ad.patch_active() and ad.time_paused()
        assert caves.matches(be, mm.FLAG_TIME)
        assert CaveMachine(be).render()[1] == mm.CAMERA
        assert ad.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-5)
        ad.set_time_paused(False)
    else:
        ad.set_time_paused(False)
        assert ad.patch_active() and not ad.time_paused()
        assert caves.matches(be, mm.FLAG_ORBIT)
        CaveMachine(be).render()
        assert ad.fov_in_sync(60)
        ad.restore_fov()
        CaveMachine(be).render()
        assert ad.patch_active() and not ad.time_paused()
        assert ad.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-5)
        ad.set_patch(False)
    assert_stock(be)
    assert be.bytes_at(mm.RENDER_CAVE, len(code)) == code
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    # Only the bootstrap first word is ever a host code-page write.
    native_sites = {mm.RENDER_HOOK, mm.RENDER_HOOK + 4, mm.MOVE_HOOK, mm.MOVE_HOOK + 4, mm.CLOCK_HOOK}
    assert [(a, v) for a, v in be.host_writes if a in native_sites] == [(mm.RENDER_HOOK, caves.RENDER_PAIR[0])]


def test_clock_only_is_independent_of_scene_and_scripted_time_values(be):
    ad = InnocentLifeAdapter(be)
    be.seed_u32(mm.CAMERA_PTR, 0)
    assert not ad.read_scene().valid
    ad.set_time_paused(True)
    assert ad.time_paused() and not ad.patch_active()
    assert caves.matches(be, mm.FLAG_TIME)
    assert CaveMachine(be).render()[1] == mm.CAMERA
    be.seed_u32(mm.CLOCK_HOURS, 23)  # Scripted setters remain possible.
    assert ad.read_game_time() == "23:09:07"
    ad.set_patch(False)
    assert ad.time_paused()
    ad.restore()
    assert_stock(be)


@pytest.mark.parametrize("during", ["install", "release"])
def test_paused_guest_timeout_is_bounded_actionable_and_retryable(be, monkeypatch, during):
    ad = InnocentLifeAdapter(be)
    if during == "release":
        ad.set_time_paused(True)
    be.auto_guest = False
    ticks = iter([0, 0, 0.2, 0.4, 0.51, 0.7])
    monkeypatch.setattr(caves.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(caves.time, "sleep", lambda _: None)
    with pytest.raises(caves.PatchConflict, match="resume before"):
        ad.set_time_paused(during == "install")
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    assert be.read_u32(mm.RENDER_HOOK) == caves.RENDER_PAIR[0]
    be.auto_guest = True
    # Resuming lets the retained bootstrap drain the original pending mask.
    be.in_guest = True
    try:
        CaveMachine(be).render()
    finally:
        be.in_guest = False
    monkeypatch.setattr(caves.time, "monotonic", lambda: 1)
    ad.set_time_paused(False)
    assert_stock(be)


@pytest.mark.parametrize("site", [mm.RENDER_HOOK + 4, mm.MOVE_HOOK + 4, mm.CLOCK_HOOK, mm.MOVE_CONTINUE])
def test_guest_lifecycle_validates_all_sites_before_any_code_store(be, site):
    ad = InnocentLifeAdapter(be)
    def corrupt(backend):
        backend.seed_u32(site, 0xDEADBEEF)
    be.before_guest = corrupt
    with pytest.raises(caves.PatchConflict, match="changed during"):
        ad.set_time_paused(True)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT
    assert be.read_u32(mm.CLOCK_HOOK) == (0xDEADBEEF if site == mm.CLOCK_HOOK else mm.CLOCK_STOCK)
    assert caves.read_words(be, mm.MOVE_HOOK, 2) == (mm.MOVE_STOCK[0], 0xDEADBEEF if site == mm.MOVE_HOOK + 4 else mm.MOVE_STOCK[1])


def test_pending_mask_is_not_overwritten_until_guest_acknowledges(be, monkeypatch):
    import itertools
    ad = InnocentLifeAdapter(be)
    ad.set_time_paused(True)
    be.auto_guest = False
    be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    be.host_writes.clear()
    ticks = itertools.count()
    monkeypatch.setattr(caves.time, "monotonic", lambda: next(ticks) * .2)
    monkeypatch.setattr(caves.time, "sleep", lambda _: None)
    with pytest.raises(caves.PatchConflict, match="resume before"):
        ad.set_time_paused(True)
    assert not be.host_writes
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    be.in_guest = True
    try:
        CaveMachine(be).render()
    finally:
        be.in_guest = False
    assert_stock(be)
    be.auto_guest = True
    ad.set_time_paused(True)
    assert caves.matches(be, mm.FLAG_TIME)


def test_guest_snapshot_survives_two_publications_inside_builder(be):
    ad = InnocentLifeAdapter(be)
    ad.write_orbit_params(PLAYER, 20, 35, 90, target_offset=Vec3(0, -15, 0))
    ad.write_fov_deg(20)
    expected = be.read_floats(active_bank(be) + mm.SLOT_EYE, 3)
    focal = be.read_f32(active_bank(be) + mm.SLOT_FOCAL)
    original = be.bytes_at(mm.CAM_FORWARD, 16)
    runner = CaveMachine(be)
    def publish_twice(machine):
        ad.write_orbit_params(PLAYER, 80, 50, 120, target_offset=Vec3(3, -15, 4))
        ad.write_fov_deg(110)  # reuses the original source bank; geometry/lens snapshot must survive
        assert be.read_floats(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_EYE, 3) == expected
        assert be.read_f32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_FOCAL) == focal
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_FLAGS) & mm.FLAG_FOV
    runner.on_builder = publish_twice
    call = runner.render()
    assert call[2].as_tuple() == pytest.approx(tuple(a + b for a, b in zip(PLAYER.as_tuple(), expected)))
    assert call[6] == focal
    assert ad.read_fov_deg() == pytest.approx(20, abs=1e-5)
    assert be.read_f32(active_bank(be) + mm.SLOT_FOCAL) == pytest.approx(expected_focal(be, 110))
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 3) != expected
    assert be.bytes_at(mm.CAM_FORWARD, 16) == original
    CaveMachine(be).render()
    assert ad.fov_in_sync(110)


def test_nested_render_does_not_overwrite_outer_forward_backup(be):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    original = be.bytes_at(mm.CAM_FORWARD, 16)
    runner = CaveMachine(be)
    def nested(machine):
        saved = be.bytes_at(mm.MOD_BLOCK + mm.MB_SAVED_FORWARD, 16)
        inner = CaveMachine(be)
        inner.regs[m.SP] = machine.regs[m.SP]
        assert inner.render()[1] == mm.CAMERA
        assert be.bytes_at(mm.MOD_BLOCK + mm.MB_SAVED_FORWARD, 16) == saved
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == mm.FLAG_ORBIT
    runner.on_builder = nested
    runner.render()
    assert be.bytes_at(mm.CAM_FORWARD, 16) == original
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


@pytest.mark.parametrize("operation", ["publish", "patch", "clock", "fov", "restore_fov", "restore"])
def test_each_adapter_write_transaction_inspects_each_cave_word_exactly_once(be, monkeypatch, operation):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    be.reads.clear()
    inspections = []
    original = caves.preflight
    def inspect(backend):
        result = original(backend)
        inspections.append(result)
        return result
    monkeypatch.setattr(caves, "preflight", inspect)
    if operation == "publish":
        ad.write_orbit_params(PLAYER, 80, 35, 90, target_offset=Vec3(0, -15, 0))
    elif operation == "patch":
        ad.set_patch(True)
    elif operation == "clock":
        ad.set_time_paused(True)
    elif operation == "fov":
        ad.write_fov_deg(60)
    elif operation == "restore_fov":
        ad.restore_fov()
    else:
        ad.restore()
    assert len(inspections) == 1
    # A synchronized Orbit publication needs no lifecycle guest callback, so
    # these stable transactions contain host reads only, not guest fetches.
    if operation in ("publish", "patch", "fov", "restore_fov"):
        from collections import Counter
        counts = Counter(address for address, length in be.reads if length == 4)
        for _, _, _, address, words in caves.RESOURCES:
            assert all(counts[address + i * 4] == 1 for i in range(len(words)))


def test_inspection_is_immutable_local_and_next_publication_revalidates_code(be):
    from dataclasses import FrozenInstanceError
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    inspection = caves.preflight(be)
    with pytest.raises(FrozenInstanceError):
        inspection.needs_magic = True
    be.seed_u32(mm.MOVE_CAVE + 8, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        ad.write_orbit_params(PLAYER, 80, 35, 90, target_offset=Vec3(0, -15, 0))
    assert not be.writes


@pytest.mark.parametrize("operation", ["prepare", "sync"])
def test_public_cave_apis_keep_independent_preflight(be, operation):
    ad = InnocentLifeAdapter(be)
    ad.set_patch(True)
    be.seed_u32(mm.RENDER_CAVE + 8, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        if operation == "prepare":
            caves.prepare(be)
        else:
            caves.sync(be, mm.FLAG_ORBIT)
    assert not be.writes


def test_stock_state_reload_republishes_cached_orbit_fov_and_time_requests(be):
    ad = InnocentLifeAdapter(be)
    ad.write_orbit_params(PLAYER, 80, 40, 100, pos_offset=Vec3(1, 2, 3), target_offset=Vec3(4, -15, 6))
    ad.write_fov_deg(110)
    ad.set_time_paused(True)
    expected = be.read_floats(active_bank(be) + mm.SLOT_EYE, 4)
    be.mem = seed_field(FakeBackend()).mem
    ad.set_time_paused(True)
    assert caves.matches(be, mm.ALL_FLAGS)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 4) == expected
    assert be.read_u32(active_bank(be) + mm.SLOT_SEQUENCE) % 2 == 0
    assert be.read_u32(active_bank(be) + mm.SLOT_FLAGS) == mm.ALL_FLAGS | mm.FLAG_FOV
    assert be.read_f32(active_bank(be) + mm.SLOT_FOCAL) == pytest.approx(expected_focal(be, 110))
    CaveMachine(be).render()
    assert ad.fov_in_sync(110) and ad.time_paused()
    ad.restore()
    assert_stock(be)


def test_runtime_recheck_center_restore_and_abandon_compatibility(be):
    ad = InnocentLifeAdapter(be)
    runtime = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, pitch_deg=35, yaw_deg=180,
                                              distance=90, look_height=-15, pause_game_time=True,
                                              use_fov=True, fov_deg=60,
                                              pos_offset=[1, 2, 3], target_offset=[4, 5, 6]))
    runtime._tick(.01, None)
    assert not runtime.stats.last_error
    assert caves.matches(be, mm.ALL_FLAGS)
    CaveMachine(be).render()
    assert ad.fov_in_sync(60)
    expected = be.read_floats(active_bank(be) + mm.SLOT_EYE, 4)
    be.mem = seed_field(FakeBackend()).mem
    runtime._patch_checked = runtime._scene_time = runtime._fov_checked = 0
    runtime._tick(.01, None)
    assert caves.matches(be, mm.ALL_FLAGS)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 4) == expected
    CaveMachine(be).render()
    assert ad.fov_in_sync(60)
    be.seed_floats(mm.CAM_FOCAL, [620.5])
    runtime.restore()
    assert_stock(be)
    assert not runtime.settings.use_fov and not runtime.settings.pause_game_time
    assert be.read_f32(mm.CAM_FOCAL) == 620.5
    assert ad.read_fov_deg() == pytest.approx(math.degrees(2 * math.atan(256 / (620.5 * NATIVE_X_FACTOR))))
    native = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    assert runtime.center_on_target()
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    runtime.restore()
    ad.set_patch(True)
    ad.write_fov_deg(20)
    CaveMachine(be).render()
    assert ad.fov_in_sync(20)
    be.writes.clear()
    runtime.abandon()
    runtime.restore()
    runtime._tick(.01, None)
    assert not be.writes


def test_guarded_backend_blocks_apply_and_restore_after_switch(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = InnocentLifeAdapter(guard)
    ad.set_time_paused(True)
    be.serial = "SLPS-00000"
    assert guard.verify() == CHANGED
    be.writes.clear()
    # Already-synchronized clock requests can be read-only; actual apply and
    # release writes must still go through the normal GUI backend lease.
    ad.set_time_paused(True)
    with pytest.raises(WriteBlocked):
        ad.set_patch(True)
    with pytest.raises(WriteBlocked):
        ad.restore()
    with pytest.raises(WriteBlocked):
        ad.write_fov_deg(60)
    with pytest.raises(WriteBlocked):
        ad.restore_fov()
    assert not be.writes


def test_cave_bank_scratch_bounds_and_branch_delay_safety():
    assert mm.RENDER_CAVE + len(caves.RENDER_WORDS) * 4 <= mm.MOVE_CAVE
    assert mm.MOVE_CAVE + len(caves.MOVE_WORDS) * 4 <= mm.MOD_BLOCK
    assert mm.MB_SNAPSHOT + mm.SLOT_SIZE <= mm.SLOTS[0]
    assert mm.SLOTS[0] + mm.SLOT_SIZE <= mm.SLOTS[1]
    assert mm.SLOTS[1] + mm.SLOT_SIZE <= mm.MB_CAMERA_SCRATCH
    assert mm.MB_CAMERA_SCRATCH + mm.CAMERA_SIZE <= mm.BLOCK_SIZE
    assert mm.MOD_BLOCK + mm.BLOCK_SIZE <= mm.RESERVED_END
    assert caves.MOVE_PAIR[1] == m.NOP
    for _, _, _, _, words in caves.RESOURCES:
        for i, word in enumerate(words):
            if word >> 26 in (4, 5):
                imm = word & 65535
                offset = imm - 65536 if imm & 32768 else imm
                assert 0 <= i + 1 + offset < len(words)
            if word >> 26 in (2, 3, 4, 5) or word == 0x03E00008:
                delay = words[i + 1]
                assert delay >> 26 not in (2, 3, 4, 5)
                assert delay != 0x03E00008
