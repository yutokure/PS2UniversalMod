"""Symphonia adapter/cave contracts on synthetic memory, never a live emulator.

The existing small R5900 interpreter executes generated caves with native math/
projection boundaries stubbed. These tests establish publication, ABI, ownership
and restoration contracts, not PS2 timing, visual output or all gameplay scenes.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.talesofsymphonia.adapter import TalesOfSymphoniaAdapter, canonical, native
from adapters.talesofsymphonia import caves, memory_map as mm
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
from tests.test_druaga import FakeBackend as ByteBackend
from tests.test_innocentlife import CaveMachine as BaseMachine

ROOT = 0x01000000
PLAYER_NATIVE = Vec3(100, 200, 10)
PLAYER = canonical(PLAYER_NATIVE)
EYE_NATIVE, TARGET_NATIVE = Vec3(100, -1200, 800), Vec3(100, 200, 97)
NATIVE = CameraPose(canonical(EYE_NATIVE), canonical(TARGET_NATIVE))
TOWN_VERTICAL_FOV = 27.0


def stock_lens(backend):
    """Model native input quantization independently from adapter diagnostics."""
    if backend.read_u32(mm.MODE) == mm.WORLD_MODE:
        aspect = 10 / 7
        units = 0x0D70 if backend.read_u32(mm.WORLD_MAP_ID) & 65535 else 0x1684
        vertical_half = units * math.pi / 65536
    else:
        aspect = 4 / 3
        index = backend.read_u32(mm.TOWN_CAMERA_INDEX) & 255
        degrees = backend.read_f32(mm.TOWN_CAMERA_BASE + index * 0x94 + 0x58)
        half_units = int(degrees * 65536 / 360) // 2
        vertical_half = half_units * 2 * math.pi / 65536
    sy = 1 / math.tan(vertical_half)
    return sy / aspect, sy


def stock_fov(backend):
    return math.degrees(2 * math.atan(1 / stock_lens(backend)[0]))
INPUT_EYE, INPUT_TARGET, INPUT_UP = 0x01DF0000, 0x01DF0020, 0x01DF0040
INPUT_PROJECTION, OUTPUT_VIEW = 0x01DF0100, 0x01DF0200


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


class FakeBackend(ByteBackend):
    """Host transport plus one explicitly modelled EE lifecycle callback."""
    available = connected = True

    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)
        self.auto_guest = True
        self.in_guest = False
        self.host_writes = []
        self.before_guest = None

    def title(self):
        return 'TALES OF SYMPHONIA'

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]

    def write_u32(self, address, value):
        if not self.in_guest:
            self.host_writes.append((address, value & 0xFFFFFFFF))
        super().write_u32(address, value)
        if (self.auto_guest and not self.in_guest
                and self.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC):
            bootstrap = any(self.read_u32(site) == mm.BOOTSTRAP_CAVE
                            for site in (mm.BOOT_TOWN_SITE, mm.BOOT_WORLD_SITE))
            attached = self.read_u32(mm.LENS_HOOK) == m.jal(mm.LENS_CAVE)
            if not (bootstrap or attached):
                return
            self.in_guest = True
            try:
                if self.before_guest:
                    self.before_guest(self)
                machine = CaveMachine(self)
                machine.bootstrap() if bootstrap else machine.lens()
            finally:
                self.in_guest = False


class CaveMachine(BaseMachine):
    """Execute only the ToS cave subset; native builders are independent stubs."""
    def __init__(self, backend):
        super().__init__(backend)
        self.regs[31] = 0x12345678
        self.on_native = None

    def execute(self, word):
        op, rs, rt = word >> 26, word >> 21 & 31, word >> 16 & 31
        if op == 0x11 and rs == 16 and word & 63 in (1, 2, 3):
            fs, ft, fd = word >> 11 & 31, rt, word >> 6 & 31
            a, b = self.fpu[fs], self.fpu[ft]
            result = a - b if word & 63 == 1 else a * b if word & 63 == 2 else a / b
            self.fpu[fd] = f32(result)
        else:
            super().execute(word)

    def native(self, target):
        if target == mm.LIFECYCLE_CAVE:
            # The shared helper is guest machine code, not a native stub. The
            # base runner handles nested JAL/return using the helper's own RA.
            self.run(target)
            return
        if target in (0x13BA20, 0x14DC20):
            call = ('callback', target, self.regs[m.A0], self.regs[m.A1])
        elif target == mm.LOOK_NATIVE:
            call = ('look', self.regs[m.A0], self.regs[m.A1], self.regs[m.A2],
                    tuple(self.b.read_floats(self.regs[m.A1], 3)),
                    tuple(self.b.read_floats(self.regs[m.A2], 3)), self.regs[m.A3])
        elif target == mm.LENS_NATIVE:
            matrix = tuple(self.b.read_floats(self.regs[m.A0], 16))
            self.b.seed_floats(mm.PROJECTION, matrix)
            call = ('lens', self.regs[m.A0], matrix)
        elif target == mm.TOWN_MOVE_NATIVE:
            call = ('town', self.fpu[12], self.fpu[13])
        elif target in (mm.COMPASS_NATIVE, *mm.MAP_NATIVE):
            call = ('hud', target, self.fpu[12], self.regs[m.A0], self.regs[m.A1])
        elif target == mm.RX_NATIVE:
            self.regs[m.V0] = 27
            call = ('rx', 27)
        elif target in (mm.WORLD_MOVE_HOOK + 8, *(site + 8 for site in mm.STREAM_HOOKS)):
            call = ('continue', target, self.fpu[0], self.fpu[2], self.fpu[4])
        else:
            raise AssertionError(f'unexpected Symphonia native boundary {target:08X}')
        self.calls.append(call)
        if self.on_native:
            self.on_native(self)

    def bootstrap(self, caller=None):
        mode = self.b.read_u32(mm.MODE)
        self.regs[31] = (0x27FD64 if mode == mm.WORLD_MODE else 0x13BD00) if caller is None else caller
        self.run(mm.BOOTSTRAP_CAVE)
        return self.calls[-1] if self.calls else None

    def look(self, caller=None):
        mode = self.b.read_u32(mm.MODE)
        caller = mm.LOOK_CALLERS[mode][0] if caller is None else caller
        self.b.seed_u32(self.regs[m.SP], caller)
        self.b.seed_floats(INPUT_EYE, (*EYE_NATIVE.as_tuple(), 1))
        self.b.seed_floats(INPUT_TARGET, (*TARGET_NATIVE.as_tuple(), 1))
        self.b.seed_floats(INPUT_UP, (0, 0, 1, 0))
        self.regs[m.A0], self.regs[m.A1] = OUTPUT_VIEW, INPUT_EYE
        self.regs[m.A2], self.regs[m.A3] = INPUT_TARGET, INPUT_UP
        self.run(mm.LOOK_CAVE)
        return self.calls[-1]

    def lens(self, caller=None):
        mode = self.b.read_u32(mm.MODE)
        caller = mm.LENS_CALLERS[mode][0] if caller is None else caller
        self.b.seed_u32(self.regs[m.SP] + 0x20, caller)
        sx, sy = stock_lens(self.b)
        matrix = [sx, 0, 0, 0, 0, sy, 0, 0,
                  0, 0, -1.02, -1, 0, 0, -202, 0]
        self.b.seed_floats(INPUT_PROJECTION, matrix)
        self.regs[m.A0] = INPUT_PROJECTION
        self.run(mm.LENS_CAVE)
        return self.calls[-1]

    def consumer(self, site, input_angle=2.5):
        _, _, _, address, _ = resource(site)
        # Emulate the original call-site delay before entering a jal wrapper.
        if site in mm.TOWN_MOVE_HOOKS:
            self.fpu[12], self.fpu[13] = 123.0, -456.0
        elif site in (mm.COMPASS_HOOK, *mm.MAP_HOOKS):
            self.fpu[12] = 0.875
        elif site == mm.WORLD_MOVE_HOOK or site in mm.STREAM_HOOKS:
            self.regs[1] = ROOT + 0x90000
            self.fpu[0] = input_angle
        self.run(address)
        return self.calls[-1] if self.calls else None


def resource(site):
    return next(item for item in caves.RESOURCES if item[0] == site)


def seed_scene(backend, mode=mm.TOWN_MODE):
    """No game binary or captured state: all geometry/resources are synthetic."""
    backend.seed_u32(mm.MODE, mode)
    backend.seed_u32(mm.SUBMODE, 0)
    backend.seed_u32(mm.TOWN_ACTOR, 0x13BA20 if mode == mm.TOWN_MODE else 0)
    backend.seed_u32(mm.BOOT_WORLD_SITE, 0x14DC20 if mode == mm.WORLD_MODE else 0)
    backend.seed_floats(mm.TOWN_PLAYER, PLAYER_NATIVE.as_tuple())
    backend.seed_floats(mm.TOWN_EYE, EYE_NATIVE.as_tuple())
    backend.seed_floats(mm.TOWN_TARGET, TARGET_NATIVE.as_tuple())
    backend.seed_u32(mm.WORLD_ROOT, ROOT)
    backend.seed_u32(ROOT, 1)
    # Native enemy-spawn timer saturates at 60 during ordinary world walking;
    # it is not a busy/menu flag (world update increments it independently).
    backend.seed_u32(ROOT + 0x94235, 60)
    backend.seed_floats(ROOT + mm.WORLD_POSITION, PLAYER_NATIVE.as_tuple())
    backend.seed_floats(ROOT + mm.WORLD_CAMERA_PITCH, (2.5, 3.125, 1200))
    delta = EYE_NATIVE - TARGET_NATIVE
    backward = delta.scaled(1 / delta.length())
    backend.seed_floats(mm.CAMERA_WORLD, (1, 0, 0, 0, 0, 1, 0, 0,
                                        *backward.as_tuple(), 0, *EYE_NATIVE.as_tuple(), 1))
    backend.seed_u32(mm.TOWN_CAMERA_INDEX, 0)
    backend.seed_floats(mm.TOWN_CAMERA_BASE + 0x58, (TOWN_VERTICAL_FOV,))
    sx, sy = stock_lens(backend)
    backend.seed_floats(mm.PROJECTION, (sx, 0, 0, 0, 0, sy, 0, 0,
                                      0, 0, -1.02, -1, 0, 0, -202, 0))
    for site, stock, _, _, _ in caves.RESOURCES:
        for index, word in enumerate(stock):
            backend.seed_u32(site + index * 4, word)
    return backend


def active_bank(backend):
    return mm.MOD_BLOCK + mm.SLOTS[backend.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def publish(backend, *, yaw=80, pitch=35, distance=1800, pos=None, target=None):
    adapter = TalesOfSymphoniaAdapter(backend)
    adapter.write_orbit_params(PLAYER, yaw, pitch, distance,
                               pos_offset=pos, target_offset=target or Vec3(0, -87, 0))
    return adapter


def run_guest(backend, action):
    before = backend.in_guest
    backend.in_guest = True
    try:
        return action(CaveMachine(backend))
    finally:
        backend.in_guest = before


@pytest.fixture(params=[mm.TOWN_MODE, mm.WORLD_MODE], ids=['town-dungeon', 'world'])
def be(request):
    return seed_scene(FakeBackend(), request.param)


@pytest.mark.parametrize('serial,crc,matched', [
    (mm.GAME_ID, mm.DISC_CRC, True), (' slps-25400 ', ' 830b6fb1 ', True),
    (mm.GAME_ID, 'DEADBEEF', False), ('SLPS-25401', mm.DISC_CRC, False), ('', '', False),
])
def test_identity_requires_serial_and_crc_without_writes(serial, crc, matched):
    backend = FakeBackend(serial, crc)
    assert TalesOfSymphoniaAdapter(backend).identify().matched is matched
    assert not backend.writes


@pytest.mark.parametrize('vector', [Vec3(1, 2, 3), Vec3(-1900, 45, 2700), Vec3(0, 0, 0)])
def test_z_up_conversion_is_local_and_exactly_invertible(vector):
    assert native(canonical(vector)) == vector
    assert canonical(native(vector)) == vector
    assert canonical(Vec3(0, 0, 1)) == Vec3(0, -1, 0)


def test_read_defaults_features_scene_are_read_only(be):
    ad = TalesOfSymphoniaAdapter(be)
    assert ad.read_scene().valid
    assert ad.read_player() == PLAYER
    assert ad.read_fov_deg() == pytest.approx(stock_fov(be), abs=1e-5)
    assert ad.features == dict(orbit=True, free_camera=False, fov=True,
                              position_offsets=True, target_offsets=True, per_frame_write=False)
    assert ad.default_settings()['distance'] == 1800
    assert ad.read_projection()[1] == 0
    assert not be.writes


BAD_SCENES = [(mm.SUBMODE, 1), (mm.MODE, 0), (mm.TOWN_SCRIPT_CAMERA, 1),
              (mm.TOWN_ALT_CAMERA, 1), (mm.TOWN_ACTOR, 0xDEADBEEF)]
WORLD_BAD = [(mm.WORLD_ROOT, 0), (mm.WORLD_ROOT, ROOT + 1), (mm.WORLD_ROOT, 0x1600000),
             (ROOT, 2), (ROOT + mm.WORLD_FLAGS, mm.WORLD_REJECT_MASK),
             *((ROOT + offset, 1) for offset in mm.WORLD_BUSY_BYTES)]


@pytest.mark.parametrize('address,value', BAD_SCENES + WORLD_BAD)
def test_host_scene_guard_refuses_unknown_mode_or_owner_before_any_write(address, value):
    mode = mm.WORLD_MODE if (address in (mm.WORLD_ROOT, ROOT) or ROOT <= address < ROOT + 0x100000) else mm.TOWN_MODE
    backend = seed_scene(FakeBackend(), mode)
    backend.seed_u32(address, value)
    ad = TalesOfSymphoniaAdapter(backend)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        ad.set_patch(True)
    assert not backend.writes


@pytest.mark.parametrize('field', ['centre', 'yaw_deg', 'pitch_deg', 'distance', 'pos_offset', 'target_offset', 'fov'])
def test_nonfinite_requests_reject_without_preparation(be, field):
    ad = TalesOfSymphoniaAdapter(be)
    args = dict(centre=PLAYER, yaw_deg=0, pitch_deg=35, distance=1800,
                pos_offset=Vec3(0, 0, 0), target_offset=Vec3(0, -87, 0))
    if field == 'fov':
        call = lambda: ad.write_fov_deg(float('nan'))
    else:
        args[field] = Vec3(float('nan'), 0, 0) if field in ('centre', 'pos_offset', 'target_offset') else float('inf')
        call = lambda: ad.write_orbit_params(**args)
    with pytest.raises(ValueError):
        call()
    assert not be.writes


@pytest.mark.parametrize('yaw,pitch,distance', [(0, 35, 1800), (90, -20, 500), (-135, 80, 2000)])
def test_publication_uses_native_relative_axes_actual_forward_and_even_sequence(be, yaw, pitch, distance):
    pos, target = Vec3(21, 13, -34), Vec3(5, -87, 7)
    ad = publish(be, yaw=yaw, pitch=pitch, distance=distance, pos=pos, target=target)
    expected = orbit_pose(target, math.radians(yaw), math.radians(pitch), distance)
    eye, aim = native(expected.eye + pos), native(expected.target)
    bank = active_bank(be)
    assert be.read_floats(bank + mm.SLOT_EYE, 4) == pytest.approx((*eye.as_tuple(), 1), abs=2e-4)
    assert be.read_floats(bank + mm.SLOT_TARGET, 4) == pytest.approx((*aim.as_tuple(), 1))
    forward = aim - eye
    assert be.read_floats(bank + mm.SLOT_FORWARD, 2) == pytest.approx((forward.x, forward.y), abs=2e-4)
    assert be.read_f32(bank + mm.SLOT_YAW) == pytest.approx(math.atan2(forward.x, forward.y) % math.tau)
    assert be.read_u32(bank + mm.SLOT_SEQUENCE) % 2 == 0
    assert be.read_u32(bank + mm.SLOT_MODE) == be.read_u32(mm.MODE)
    assert be.read_u32(bank + mm.SLOT_PLAYER) == (mm.TOWN_PLAYER if be.read_u32(mm.MODE) == mm.TOWN_MODE else ROOT + 4)
    assert ad.patch_active()


def test_publication_orders_odd_payload_even_then_slot_and_wraps(be):
    ad = publish(be)
    old_slot = be.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1
    address = mm.MOD_BLOCK + mm.SLOTS[old_slot ^ 1]
    be.seed_u32(address, 0xFFFFFFFE)
    be.host_writes.clear()
    ad.write_orbit_params(PLAYER, 25, 30, 1600, target_offset=Vec3(0, -80, 0))
    writes = be.host_writes
    assert writes[0] == (address, 1)
    even = writes.index((address, 0))
    flip = writes.index((mm.MOD_BLOCK + mm.MB_SLOT, old_slot ^ 1))
    assert 0 < even < flip
    assert all(address <= a < address + mm.SLOT_SIZE for a, _ in writes[:even + 1])


def test_generated_look_uses_fresh_player_copies_native_args_and_keeps_registers(be):
    ad = publish(be, pos=Vec3(20, 30, 40))
    bank = active_bank(be)
    newest = Vec3(900, -300, 75)
    player = be.read_u32(bank + mm.SLOT_PLAYER)
    be.seed_floats(player, newest.as_tuple())
    native_before = be.bytes_at(mm.TOWN_EYE, 32)
    machine = CaveMachine(be)
    for reg in (*caves.SCRATCH, *range(16, 24)):
        machine.regs[reg] = (reg << 96) | (reg << 64) | reg
    saved = {reg: machine.regs[reg] for reg in (*caves.SCRATCH, *range(16, 24), m.SP, 31)}
    call = machine.look()
    eye = Vec3(*be.read_floats(bank + mm.SLOT_EYE, 3)) + newest
    target = Vec3(*be.read_floats(bank + mm.SLOT_TARGET, 3)) + newest
    assert call[4] == pytest.approx(eye.as_tuple(), abs=2e-4)
    assert call[5] == pytest.approx(target.as_tuple(), abs=2e-4)
    assert call[2:4] != (INPUT_EYE, INPUT_TARGET)
    assert call[1] == OUTPUT_VIEW and call[6] == INPUT_UP
    assert {reg: machine.regs[reg] for reg in saved} == saved
    assert be.read_floats(INPUT_EYE, 3) == list(EYE_NATIVE.as_tuple())
    assert be.read_floats(INPUT_TARGET, 3) == list(TARGET_NATIVE.as_tuple())
    assert be.bytes_at(mm.TOWN_EYE, 32) == native_before
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == be.read_u32(mm.MODE)
    assert ad.heartbeat_word() == 1
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(canonical(eye).as_tuple(), abs=2e-4)


@pytest.mark.parametrize('damage', ['caller', 'odd', 'changed', 'mode', 'player', 'magic', 'scene'])
def test_generated_look_falls_back_to_original_args_for_unowned_or_unstable_input(be, damage):
    publish(be)
    bank = active_bank(be)
    caller = None
    if damage == 'caller': caller = 0xDEADBEEF
    elif damage == 'odd': be.seed_u32(bank, 3)
    elif damage == 'mode': be.seed_u32(bank + mm.SLOT_MODE, 0)
    elif damage == 'player': be.seed_u32(bank + mm.SLOT_PLAYER, 0x100000)
    elif damage == 'magic': be.seed_u32(mm.MOD_BLOCK, 0)
    elif damage == 'scene': be.seed_u32(mm.SUBMODE, 1)
    else:
        original = be.read_u32
        reads = 0
        def unstable(address):
            nonlocal reads
            result = original(address)
            if address == bank:
                reads += 1
                if reads == 2: return result + 2
            return result
        be.read_u32 = unstable
    call = CaveMachine(be).look(caller)
    assert call[2:4] == (INPUT_EYE, INPUT_TARGET)
    assert call[4:6] == (EYE_NATIVE.as_tuple(), TARGET_NATIVE.as_tuple())
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == 0


@pytest.mark.parametrize('degrees', [20, 60, 110])
def test_generated_lens_copies_only_sx_sy_preserves_projection_and_native_source(be, degrees):
    ad = publish(be)
    ad.write_fov_deg(degrees)
    call = CaveMachine(be).lens()
    assert call[1] != INPUT_PROJECTION
    original = be.read_floats(INPUT_PROJECTION, 16)
    expected = list(original)
    expected[0] = 1 / math.tan(math.radians(degrees) / 2)
    expected[5] = expected[0] * original[5] / original[0]
    assert call[2] == pytest.approx(expected, abs=1e-5)
    assert be.read_floats(INPUT_PROJECTION, 16) == original
    assert ad.read_fov_deg() == pytest.approx(degrees, abs=1e-4)
    assert ad.fov_in_sync(degrees)
    assert ad.capture_original_fov() == pytest.approx(stock_fov(be), abs=1e-5)
    ad.restore_fov()
    assert CaveMachine(be).lens()[1] == INPUT_PROJECTION
    assert ad.read_fov_deg() == pytest.approx(stock_fov(be), abs=1e-5)
    assert ad.patch_active()


def test_hud_or_unverified_lens_caller_is_not_overridden(be):
    ad = publish(be)
    ad.write_fov_deg(110)
    call = CaveMachine(be).lens(0xDEADBEEF)
    assert call[1] == INPUT_PROJECTION
    assert call[2][0] == pytest.approx(stock_lens(be)[0])


@pytest.mark.parametrize('site', [*mm.TOWN_MOVE_HOOKS, mm.COMPASS_HOOK, *mm.MAP_HOOKS,
                                  mm.WORLD_MOVE_HOOK, *mm.STREAM_HOOKS, mm.RX_HOOK])
def test_generated_consumers_use_accepted_snapshot_not_newer_host_bank(site):
    town = site in mm.TOWN_MOVE_HOOKS
    backend = seed_scene(FakeBackend(), mm.TOWN_MODE if town else mm.WORLD_MODE)
    ad = publish(backend, yaw=80, pos=Vec3(200, 0, 50))
    CaveMachine(backend).look()
    snapshot = mm.MOD_BLOCK + mm.MB_SNAPSHOT
    expected_xy = backend.read_floats(snapshot + mm.SLOT_FORWARD, 2)
    expected_yaw = backend.read_f32(snapshot + mm.SLOT_YAW)
    ad.write_orbit_params(PLAYER, -120, 20, 800, target_offset=Vec3(0, -50, 0))
    machine = CaveMachine(backend)
    machine.regs[m.A0], machine.regs[m.A1] = 111, 222
    saved = {reg: machine.regs[reg] for reg in (*caves.SCRATCH, m.SP, 31)}
    result = machine.consumer(site)
    if town:
        assert result[1:] == pytest.approx(expected_xy)
    elif site in (mm.COMPASS_HOOK, *mm.MAP_HOOKS):
        assert result[2] == pytest.approx(expected_yaw)
        assert result[3:] == (111, 222)
    elif site == mm.WORLD_MOVE_HOOK:
        assert machine.fpu[2] == pytest.approx(expected_yaw)
        assert machine.fpu[0] == pytest.approx(2.5 - expected_yaw, abs=1e-6)
    elif site in mm.STREAM_HOOKS:
        assert machine.fpu[4] == pytest.approx(expected_yaw)
    else:
        assert machine.regs[m.V0] == 0
    # Streaming A intentionally reproduces its displaced lui v0,0x4f00.
    assert {reg: machine.regs[reg] for reg in saved} == saved


@pytest.mark.parametrize('site', [mm.TOWN_MOVE_HOOKS[0], mm.COMPASS_HOOK, mm.WORLD_MOVE_HOOK,
                                  *mm.STREAM_HOOKS, mm.RX_HOOK])
@pytest.mark.parametrize('rejection', ['scene', 'accepted', 'owner'])
def test_generated_consumers_fall_back_native_on_scene_or_snapshot_owner_change(site, rejection):
    town = site in mm.TOWN_MOVE_HOOKS
    backend = seed_scene(FakeBackend(), mm.TOWN_MODE if town else mm.WORLD_MODE)
    publish(backend)
    CaveMachine(backend).look()
    if rejection == 'scene': backend.seed_u32(mm.SUBMODE, 1)
    elif rejection == 'accepted': backend.seed_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED, 0)
    else: backend.seed_u32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_PLAYER, 0x100000)
    machine = CaveMachine(backend)
    result = machine.consumer(site)
    if town: assert result[1:] == (123, -456)
    elif site == mm.COMPASS_HOOK: assert result[2] == .875
    elif site == mm.RX_HOOK: assert machine.regs[m.V0] == 27
    elif site == mm.WORLD_MOVE_HOOK: assert machine.fpu[2] == 3.125
    else: assert machine.fpu[4] == 3.125


@pytest.mark.parametrize('resource_index', range(len(caves.RESOURCES)))
@pytest.mark.parametrize('damage', ['hook', 'delay', 'cave'])
def test_every_unknown_resource_rejected_before_any_host_write(be, resource_index, damage):
    site, _, _, cave, words = caves.RESOURCES[resource_index]
    address = site if damage == 'hook' else site + 4 if damage == 'delay' else cave + 4 * (len(words) - 1)
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): TalesOfSymphoniaAdapter(be).set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('address', [mm.MOD_BLOCK, mm.MOD_BLOCK + mm.BLOCK_SIZE - 4])
def test_unknown_control_block_has_zero_writes(be, address):
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): TalesOfSymphoniaAdapter(be).set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('index', range(len(caves.CODE_RESOURCES)))
@pytest.mark.parametrize('operation', ['apply', 'release', 'fov'])
def test_active_zeroed_cave_cannot_be_repaired_or_force_restored(be, index, operation):
    ad = publish(be)
    address, words = caves.CODE_RESOURCES[index]
    be.seed(address, bytes(len(words) * 4))
    be.writes.clear()
    # FOV publication is hot: body-only damage is caught at the next full audit,
    # unlike exact site/control damage which is checked on every publication.
    if operation == 'fov':
        ad._audit_at = 0
    call = {'apply': lambda: ad.set_patch(True), 'release': lambda: ad.set_patch(False),
            'fov': lambda: ad.write_fov_deg(60)}[operation]
    with pytest.raises(caves.PatchConflict):
        call()
    assert not be.writes


def test_host_only_arms_data_callback_guest_installs_and_removes_every_pair(be):
    mode = be.read_u32(mm.MODE)
    boot_site = mm.BOOT_TOWN_SITE if mode == mm.TOWN_MODE else mm.BOOT_WORLD_SITE
    original = be.read_u32(boot_site)
    ad = publish(be)
    sites = {site + off for site, *_ in caves.RESOURCES for off in (0, 4)}
    assert not [(a, v) for a, v in be.host_writes if a in sites]
    assert [(a, v) for a, v in be.host_writes if a == boot_site] == [(boot_site, mm.BOOTSTRAP_CAVE)]
    assert be.read_u32(boot_site) == original
    retained = [(address, be.bytes_at(address, len(words) * 4)) for address, words in caves.CODE_RESOURCES]
    be.host_writes.clear()
    ad.set_patch(False)
    assert caves.matches(be, 0)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == 0
    assert not [(a, v) for a, v in be.host_writes if a in sites]
    for address, data in retained:
        assert be.bytes_at(address, len(data)) == data


@pytest.mark.parametrize('index', range(len(caves.RESOURCES)))
def test_guest_lifecycle_checks_all_pairs_before_any_executable_store(be, index):
    ad = publish(be)
    site = caves.RESOURCES[index][0]
    be.before_guest = lambda backend: backend.seed_u32(site + 4, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict, match='unknown instructions'):
        ad.set_patch(False)
    sites = {site + off for site, *_ in caves.RESOURCES for off in (0, 4)}
    assert not [(address, data) for address, data in be.writes if address in sites]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT


def test_timeout_is_bounded_and_pending_enable_is_retryable(be, monkeypatch):
    be.auto_guest = False
    ticks = iter(range(100000))
    monkeypatch.setattr(caves.time, 'monotonic', lambda: next(ticks) * .3)
    monkeypatch.setattr(caves.time, 'sleep', lambda _: None)
    ad = TalesOfSymphoniaAdapter(be)
    with pytest.raises(caves.PatchConflict, match='paused/unavailable'):
        ad.set_patch(True)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    assert be.read_u32(mm.LENS_HOOK) == mm.LENS_STOCK[0]
    site = mm.BOOT_TOWN_SITE if be.read_u32(mm.MODE) == mm.TOWN_MODE else mm.BOOT_WORLD_SITE
    assert be.read_u32(site) == mm.BOOTSTRAP_CAVE
    be.auto_guest = True
    run_guest(be, lambda machine: machine.bootstrap())
    ad.set_patch(True)
    assert ad.patch_active()
    ad.set_patch(False)
    assert caves.matches(be, 0)


def test_cancel_timed_out_enable_waits_for_owned_data_callback_and_never_installs(be, monkeypatch):
    site = mm.BOOT_TOWN_SITE if be.read_u32(mm.MODE) == mm.TOWN_MODE else mm.BOOT_WORLD_SITE
    original = be.read_u32(site)
    be.auto_guest = False
    ticks = iter(range(100000))
    monkeypatch.setattr(caves.time, 'monotonic', lambda: next(ticks) * .3)
    monkeypatch.setattr(caves.time, 'sleep', lambda _: None)
    ad = TalesOfSymphoniaAdapter(be)
    with pytest.raises(caves.PatchConflict, match='paused/unavailable'):
        ad.set_patch(True)
    assert caves.matches(be, 0)
    assert be.read_u32(site) == mm.BOOTSTRAP_CAVE
    be.auto_guest = True
    be.writes.clear()
    be.host_writes.clear()
    ad.set_patch(False)
    assert be.read_u32(site) == original
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert caves.matches(be, 0)
    sites = {address + offset for address, *_ in caves.RESOURCES for offset in (0, 4)}
    assert not [(address, value) for address, value in be.host_writes if address in sites]
    for address, stock, pair, *_ in caves.RESOURCES:
        assert not [(a, data) for a, data in be.writes
                    if a == address and struct.unpack('<I', data)[0] == pair[0] and pair[0] != stock[0]]


def test_paused_cancel_of_pending_data_bootstrap_times_out_then_resume_returns_original(be, monkeypatch):
    site = mm.BOOT_TOWN_SITE if be.read_u32(mm.MODE) == mm.TOWN_MODE else mm.BOOT_WORLD_SITE
    original = be.read_u32(site)
    be.auto_guest = False
    ticks = iter(range(100000))
    monkeypatch.setattr(caves.time, 'monotonic', lambda: next(ticks) * .3)
    monkeypatch.setattr(caves.time, 'sleep', lambda _: None)
    ad = TalesOfSymphoniaAdapter(be)
    with pytest.raises(caves.PatchConflict, match='paused/unavailable'):
        ad.set_patch(True)
    with pytest.raises(caves.PatchConflict, match='paused/unavailable|callback has not returned'):
        ad.set_patch(False)
    assert be.read_u32(site) == mm.BOOTSTRAP_CAVE
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    assert caves.matches(be, 0)
    run_guest(be, lambda machine: machine.bootstrap())
    assert be.read_u32(site) == original
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) == 0
    assert caves.matches(be, 0)
    be.writes.clear()
    ad.set_patch(False)
    assert be.read_u32(site) == original
    sites = {address + offset for address, *_ in caves.RESOURCES for offset in (0, 4)}
    assert not [(address, data) for address, data in be.writes if address in sites]


def test_stock_state_reload_republishes_requested_orbit_and_lens(be):
    mode = be.read_u32(mm.MODE)
    ad = publish(be, yaw=70)
    ad.write_fov_deg(60)
    expected = be.read_floats(active_bank(be) + mm.SLOT_EYE, 3)
    be.mem = seed_scene(FakeBackend(), mode).mem
    ad.set_patch(True)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 3) == expected
    CaveMachine(be).lens()
    assert ad.fov_in_sync(60)
    ad.set_patch(False)
    assert caves.matches(be, 0)


def test_runtime_center_restore_abandon_and_guard_contract(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = TalesOfSymphoniaAdapter(guard)
    runtime = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, distance=1800,
                                              look_height=-87, use_fov=True, fov_deg=60))
    runtime._tick(.01, None)
    assert not runtime.stats.last_error
    assert ad.patch_active()
    runtime.restore()
    assert caves.matches(be, 0)
    assert runtime.center_on_target()
    be.writes.clear()
    runtime.abandon()
    runtime.restore()
    runtime._tick(.01, None)
    assert not be.writes
    be.serial = 'SLPS-00000'
    assert guard.verify() == CHANGED
    with pytest.raises(WriteBlocked): ad.set_patch(True)
    with pytest.raises(WriteBlocked): ad.set_patch(False)
    assert not be.writes


@pytest.mark.parametrize('yaw', range(0, 360, 45))
@pytest.mark.parametrize('local_x,local_y', [(0, 1), (1, 0), (0, -1), (-1, 0)])
def test_world_native_input_heading_matches_render_forward_without_changing_speed(yaw, local_x, local_y):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    publish(backend, yaw=yaw)
    CaveMachine(backend).look()
    snapshot = mm.MOD_BLOCK + mm.MB_SNAPSHOT
    fx, fy = backend.read_floats(snapshot + mm.SLOT_FORWARD, 2)
    length = math.hypot(fx, fy)
    fx, fy = fx / length, fy / length
    # Native processed local +Y is Up. MCP tool analog +Y maps to Up too;
    # this is not the common host API's negative-Y-up convention.
    input_angle = math.atan2(local_x, -local_y)
    machine = CaveMachine(backend)
    machine.consumer(mm.WORLD_MOVE_HOOK, input_angle=input_angle)
    heading = machine.fpu[0]
    direction = math.sin(heading), -math.cos(heading)
    assert direction == pytest.approx((local_x * fy + local_y * fx,
                                      -local_x * fx + local_y * fy), abs=1e-6)
    assert math.hypot(*direction) == pytest.approx(1)
    assert backend.read_f32(ROOT + mm.WORLD_CAMERA_YAW) == 3.125


@pytest.mark.parametrize('timer', [0, 1, 30, 60])
def test_world_spawn_timer_is_not_a_busy_guard_on_host_or_guest(timer):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    backend.seed_u32(ROOT + 0x94235, timer)
    ad = publish(backend)
    assert ad.read_scene().valid
    call = CaveMachine(backend).look()
    assert call[2:4] != (INPUT_EYE, INPUT_TARGET)
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == mm.WORLD_MODE
    assert backend.read_u32(ROOT + 0x94235) == timer


@pytest.mark.parametrize('pitch,distance,want_pitch,want_distance', [
    (-90, 1, -25, 50), (95, 10000, 89.5, 6000),
])
def test_host_clamps_declared_pitch_and_distance_before_native_conversion(be, pitch, distance, want_pitch, want_distance):
    publish(be, yaw=35, pitch=pitch, distance=distance, target=Vec3(0, 0, 0))
    expected = native(orbit_pose(Vec3(0, 0, 0), math.radians(35), math.radians(want_pitch), want_distance).eye)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 3) == pytest.approx(expected.as_tuple(), abs=2e-4)


@pytest.mark.parametrize('requested,expected', [(0, 20), (180, 110)])
def test_fov_clamps_to_declared_range_and_fov_only_never_attaches(be, requested, expected):
    ad = TalesOfSymphoniaAdapter(be)
    ad.write_fov_deg(requested)
    assert not be.writes
    ad.set_patch(True)
    CaveMachine(be).lens()
    assert ad.read_fov_deg() == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize('damage', ['odd', 'changed', 'flags', 'mode', 'player', 'scene'])
def test_generated_lens_falls_back_without_partial_matrix_overrides(be, damage):
    ad = publish(be)
    ad.write_fov_deg(60)
    bank = active_bank(be)
    if damage == 'odd': be.seed_u32(bank, 3)
    elif damage == 'flags': be.seed_u32(bank + mm.SLOT_FLAGS, mm.FLAG_ORBIT)
    elif damage == 'mode': be.seed_u32(bank + mm.SLOT_MODE, 0)
    elif damage == 'player': be.seed_u32(bank + mm.SLOT_PLAYER, 0)
    elif damage == 'scene': be.seed_u32(mm.SUBMODE, 1)
    else:
        original = be.read_u32
        reads = 0
        def unstable(address):
            nonlocal reads
            result = original(address)
            if address == bank:
                reads += 1
                if reads == 2: return result + 2
            return result
        be.read_u32 = unstable
    machine = CaveMachine(be)
    call = machine.lens()
    assert call[1] == INPUT_PROJECTION
    assert call[2][0] == pytest.approx(stock_lens(be)[0])
    assert call[2][5] == pytest.approx(stock_lens(be)[1])


@pytest.mark.parametrize('kind', ['look', 'lens'])
def test_native_callee_outgoing_argument_home_preserves_wrapper_ra_sp(be, kind):
    ad = publish(be)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    saved = machine.regs[m.SP], machine.regs[31]
    machine.on_native = lambda runner: be.seed(runner.regs[m.SP], b'\xab' * 0x20)
    getattr(machine, kind)()
    assert (machine.regs[m.SP], machine.regs[31]) == saved


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 1e8])
def test_invalid_native_player_is_rejected_without_writes(be, bad):
    mode = be.read_u32(mm.MODE)
    player = mm.TOWN_PLAYER if mode == mm.TOWN_MODE else ROOT + 4
    be.seed_floats(player, (bad, 200, 10))
    ad = TalesOfSymphoniaAdapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


def code_body_reads(backend):
    return [(address, size) for address, size in backend.reads
            if any(start <= address < start + 4 * len(words)
                   for start, words in caves.CODE_RESOURCES)]


def warm_hot_backend(backend, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(caves.time, 'monotonic', lambda: now[0])
    ad = publish(backend)
    ad.write_fov_deg(60)
    backend.auto_guest = False
    backend.reads.clear()
    backend.writes.clear()
    backend.host_writes.clear()
    return ad, now


def update_pose(adapter, yaw=40):
    adapter.write_orbit_params(PLAYER, yaw, 35, 1800,
                               target_offset=Vec3(0, -87, 0))


def test_hot_pose_and_same_fov_use_small_constant_reads_without_body_scan(be, monkeypatch):
    ad, _now = warm_hot_backend(be, monkeypatch)
    counts = []
    for yaw in (40, 41, 42):
        be.reads.clear()
        update_pose(ad, yaw)
        counts.append(len(be.reads))
        assert 0 < counts[-1] < 160
        assert not code_body_reads(be)
    assert len(set(counts)) == 1
    be.reads.clear()
    ad.write_fov_deg(60)
    assert 0 < len(be.reads) < 160
    assert not code_body_reads(be)


def test_periodic_and_forced_audits_scan_all_code_resources_once(be, monkeypatch):
    ad, now = warm_hot_backend(be, monkeypatch)
    now[0] += .5
    update_pose(ad)
    assert not code_body_reads(be)
    be.reads.clear()
    now[0] += .51
    update_pose(ad)
    assert len(code_body_reads(be)) == sum(len(words) for _, words in caves.CODE_RESOURCES)
    be.reads.clear()
    ad.set_patch(True)
    assert len(code_body_reads(be)) == sum(len(words) for _, words in caves.CODE_RESOURCES)


@pytest.mark.parametrize('index', range(len(caves.CODE_RESOURCES)))
def test_body_only_corruption_is_deferred_until_full_audit_and_invalidates_cache(be, monkeypatch, index):
    ad, now = warm_hot_backend(be, monkeypatch)
    address, words = caves.CODE_RESOURCES[index]
    be.seed_u32(address + (len(words) - 1) * 4, 0xDEADBEEF)
    # Deliberate performance tradeoff, not immediate full-body protection.
    update_pose(ad)
    assert not code_body_reads(be)
    be.writes.clear()
    be.reads.clear()
    now[0] += 1.01
    with pytest.raises(caves.PatchConflict): update_pose(ad)
    assert not be.writes and code_body_reads(be)
    assert ad._prepared_backend is None
    be.reads.clear()
    with pytest.raises(caves.PatchConflict): update_pose(ad)
    assert not be.writes and code_body_reads(be)


@pytest.mark.parametrize('address', [
    *(site + offset for site, *_ in caves.RESOURCES for offset in (0, 4)), mm.MOD_BLOCK,
])
def test_hot_unknown_site_or_magic_rejects_before_any_parameter_write(be, monkeypatch, address):
    ad, _now = warm_hot_backend(be, monkeypatch)
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): update_pose(ad)
    assert not be.writes
    assert ad._prepared_backend is None


@pytest.mark.parametrize('address,value', [
    (mm.MOD_BLOCK + mm.MB_FLAGS, 0), (mm.MOD_BLOCK + mm.MB_FLAGS, 4),
    (mm.MOD_BLOCK + mm.MB_ACK_FLAGS, 0),
    (mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC),
    (mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_CONFLICT),
])
def test_hot_inconsistent_control_cannot_authorize_uninspected_cave_body(be, monkeypatch, address, value):
    ad, _now = warm_hot_backend(be, monkeypatch)
    be.seed_u32(address, value)
    # Correct live pair/control ownership is a prerequisite to the hot lease.
    # An inconsistent control may be reconciled, but only after a full audit.
    be.seed_u32(mm.BOOTSTRAP_CAVE, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): update_pose(ad)
    assert not be.writes and code_body_reads(be)
    assert ad._prepared_backend is None


@pytest.mark.parametrize('change', ['fresh-adapter', 'backend', 'epoch', 'guarded-epoch'])
def test_hot_preparation_authorization_is_local_to_adapter_backend_and_epoch(be, monkeypatch, change):
    ad, _now = warm_hot_backend(be, monkeypatch)
    target = be
    if change == 'fresh-adapter':
        ad = TalesOfSymphoniaAdapter(be)
    elif change == 'backend':
        target = seed_scene(FakeBackend(), be.read_u32(mm.MODE))
        publish(target)
        target.writes.clear()
        target.reads.clear()
        ad.backend = target
    elif change == 'epoch':
        be.epoch = 1
    else:
        be.epoch = 1
        guard = GuardedBackend(be)
        guard.bind(mm.GAME_ID, mm.DISC_CRC)
        ad = TalesOfSymphoniaAdapter(guard)
        be.auto_guest = True
        ad.set_patch(True)
        be.auto_guest = False
        be.epoch = 2
        be.writes.clear()
        be.reads.clear()
    target.seed_u32(mm.LIFECYCLE_CAVE, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): update_pose(ad)
    assert not target.writes
    assert code_body_reads(target)


def test_hot_stock_state_loss_reaudits_recovers_data_only_then_reuses_hot_lane(be, monkeypatch):
    ad, _now = warm_hot_backend(be, monkeypatch)
    mode = be.read_u32(mm.MODE)
    be.mem = seed_scene(FakeBackend(), mode).mem
    be.auto_guest = True
    update_pose(ad)
    assert code_body_reads(be)
    assert ad.patch_active()
    sites = {site + offset for site, *_ in caves.RESOURCES for offset in (0, 4)}
    assert not [(address, value) for address, value in be.host_writes if address in sites]
    be.auto_guest = False
    be.reads.clear()
    update_pose(ad, 45)
    assert not code_body_reads(be)


@pytest.mark.parametrize('world_map', [0, 1, 0x209])
def test_original_world_fov_uses_native_3d_lens_inputs_not_late_hud_projection(world_map):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    backend.seed_u32(mm.WORLD_MAP_ID, world_map)
    backend.seed_floats(mm.PROJECTION, (0.1,))
    ad = TalesOfSymphoniaAdapter(backend)
    expected = stock_fov(backend)
    assert ad.read_fov_deg() == pytest.approx(expected)
    assert ad.capture_original_fov() == pytest.approx(expected)
    assert ad.read_fov_scale() / 619 == pytest.approx(stock_lens(backend)[0])
    if world_map == 0:
        assert expected == pytest.approx(44.1046, abs=.0001)
    assert not backend.writes


@pytest.mark.parametrize('index,vertical', [(0, 27), (1, 36.75), (7, 49.123)])
def test_original_town_fov_follows_selected_rig_and_native_half_unit_truncation(index, vertical):
    backend = seed_scene(FakeBackend())
    backend.seed_u32(mm.TOWN_CAMERA_INDEX, index)
    backend.seed_floats(mm.TOWN_CAMERA_BASE + index * 0x94 + 0x58, (vertical,))
    backend.seed_floats(mm.PROJECTION, (0.1,))
    ad = TalesOfSymphoniaAdapter(backend)
    assert ad.read_fov_deg() == pytest.approx(stock_fov(backend))
    assert ad.capture_original_fov() == pytest.approx(stock_fov(backend))
    assert not backend.writes


@pytest.mark.parametrize('index,vertical', [(8, 27), (255, 27), (0, float('nan')),
                                           (0, 0), (0, 170)])
def test_invalid_town_lens_owner_and_vertical_input_are_read_only(index, vertical):
    backend = seed_scene(FakeBackend())
    backend.seed_u32(mm.TOWN_CAMERA_INDEX, index)
    backend.seed_floats(mm.TOWN_CAMERA_BASE + index * 0x94 + 0x58, (vertical,))
    ad = TalesOfSymphoniaAdapter(backend)
    with pytest.raises(caves.PatchConflict): ad.capture_original_fov()
    assert not ad.read_scene().valid
    assert not backend.writes


@pytest.mark.parametrize('mode,original', [(mm.TOWN_MODE, 0x13BA20),
                                          (mm.WORLD_MODE, 0x14DC20), (mm.WORLD_MODE, 0)])
def test_data_bootstrap_preserves_128bit_scratch_ra_native_args_and_original_callback(mode, original):
    backend = seed_scene(FakeBackend(), mode)
    backend.auto_guest = False
    inspection = caves.prepare(backend, caves.preflight(backend))
    site = mm.BOOT_TOWN_SITE if mode == mm.TOWN_MODE else mm.BOOT_WORLD_SITE
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_ORBIT)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_SITE, site)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_ORIGINAL, original)
    backend.seed_u32(site, mm.BOOTSTRAP_CAVE)
    machine = CaveMachine(backend)
    for register in (*caves.SCRATCH, m.A0, m.A1, m.V0, m.V1, 31):
        machine.regs[register] = (register << 112) | (register << 64) | register
    caller = 0x27FD64 if mode == mm.WORLD_MODE else 0x13BD00
    machine.regs[31] = (0xABCDEF << 64) | caller
    saved = list(machine.regs)
    result = machine.bootstrap(caller=machine.regs[31])
    assert machine.regs == saved
    assert backend.read_u32(site) == original
    assert caves.matches(backend, 1)
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_ACK
    if original:
        assert result == ('callback', original, saved[m.A0], saved[m.A1])
    else:
        assert result is None


@pytest.mark.parametrize('damage', ['magic', 'site', 'original', 'caller', 'pointer'])
def test_bootstrap_rejects_unowned_data_or_world_caller_without_any_guest_store(damage):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    backend.auto_guest = False
    caves.prepare(backend, caves.preflight(backend))
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 1)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_SITE, mm.BOOT_WORLD_SITE)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_ORIGINAL, 0x14DC20)
    backend.seed_u32(mm.BOOT_WORLD_SITE, mm.BOOTSTRAP_CAVE)
    caller = 0x27FD64
    if damage == 'magic': backend.seed_u32(mm.MOD_BLOCK, 0)
    elif damage == 'site': backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_SITE, 0x100000)
    elif damage == 'original': backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_ORIGINAL, 0xDEADBEEF)
    elif damage == 'caller': caller = 0xDEADBEEF
    else: backend.seed_u32(mm.BOOT_WORLD_SITE, 0xDEADBEEF)
    backend.writes.clear()
    CaveMachine(backend).bootstrap(caller)
    assert not backend.writes
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC


@pytest.mark.parametrize('address', [mm.LIFECYCLE_CAVE, mm.BOOTSTRAP_CAVE])
def test_shared_helper_occupancy_and_tos1_magic_refuse_initial_preparation(be, address):
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): TalesOfSymphoniaAdapter(be).set_patch(True)
    assert not be.writes
    be.seed_u32(address, 0)
    be.seed_u32(mm.MOD_BLOCK, 0x544F5331)
    with pytest.raises(caves.PatchConflict): TalesOfSymphoniaAdapter(be).set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('original', [0xDEADBEEF, 0x14DC24])
def test_unknown_world_callback_is_preserved_and_never_forced_into_bootstrap(original):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    backend.seed_u32(mm.BOOT_WORLD_SITE, original)
    with pytest.raises(caves.PatchConflict, match='callback is not available'):
        TalesOfSymphoniaAdapter(backend).set_patch(True)
    assert backend.read_u32(mm.BOOT_WORLD_SITE) == original
    sites = {site + offset for site, *_ in caves.RESOURCES for offset in (0, 4)}
    assert not [(address, value) for address, value in backend.host_writes
                if address in sites or address == mm.BOOT_WORLD_SITE]
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) != mm.CMD_SYNC


@pytest.mark.parametrize('address', [mm.LIFECYCLE_CAVE, mm.BOOTSTRAP_CAVE])
def test_pending_data_callback_with_stock_sites_cannot_authorize_rebuilding_a_missing_helper(address):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    caves.prepare(backend, caves.preflight(backend))
    backend.seed_u32(mm.BOOT_WORLD_SITE, mm.BOOTSTRAP_CAVE)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_SITE, mm.BOOT_WORLD_SITE)
    backend.seed_u32(mm.MOD_BLOCK + mm.MB_BOOT_ORIGINAL, 0x14DC20)
    words = dict(caves.CODE_RESOURCES)[address]
    backend.seed(address, bytes(len(words) * 4))
    backend.writes.clear()
    with pytest.raises(caves.PatchConflict, match='active data callback'):
        caves.preflight(backend)
    assert not backend.writes


def test_ack_is_not_complete_until_bootstrap_restores_native_data_callback(monkeypatch):
    backend = seed_scene(FakeBackend(), mm.WORLD_MODE)
    publish(backend)
    backend.seed_u32(mm.BOOT_WORLD_SITE, mm.BOOTSTRAP_CAVE)
    now = [10.0]
    monkeypatch.setattr(caves.time, 'monotonic', lambda: now[0])
    def native_return(_delay):
        now[0] += .01
        backend.seed_u32(mm.BOOT_WORLD_SITE, 0x14DC20)
    monkeypatch.setattr(caves.time, 'sleep', native_return)
    caves.wait_ack(backend, mm.FLAG_ORBIT, 10.5)
    assert now[0] > 10
    assert backend.read_u32(mm.BOOT_WORLD_SITE) == 0x14DC20
    backend.seed_u32(mm.BOOT_WORLD_SITE, mm.BOOTSTRAP_CAVE)
    with pytest.raises(caves.PatchConflict, match='callback has not returned'):
        caves.wait_ack(backend, mm.FLAG_ORBIT, now[0])


def test_caves_banks_and_branch_delay_layout_fit_owned_reservations():
    ordered = sorted(caves.CODE_RESOURCES)
    for (address, words), (next_address, _) in zip(ordered, ordered[1:]):
        assert address + 4 * len(words) <= next_address
    assert ordered[-1][0] + len(ordered[-1][1]) * 4 <= mm.MOD_BLOCK
    assert mm.MB_SNAPSHOT + mm.SLOT_SIZE <= mm.SLOTS[0]
    assert mm.SLOTS[0] + mm.SLOT_SIZE <= mm.SLOTS[1]
    assert mm.SLOTS[1] + mm.SLOT_SIZE <= mm.BLOCK_SIZE
    for _, words in caves.CODE_RESOURCES:
        for index, word in enumerate(words):
            if word >> 26 in (4, 5):
                offset = word & 65535
                if offset & 32768: offset -= 65536
                assert 0 <= index + 1 + offset < len(words)
            if word >> 26 in (2, 3, 4, 5) or word == 0x03E00008:
                assert words[index + 1] >> 26 not in (2, 3, 4, 5)
                assert words[index + 1] != 0x03E00008
