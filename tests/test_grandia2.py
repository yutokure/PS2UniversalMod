"""Grandia II synthetic-memory contracts: no emulator or game-derived binaries.

The emitted R5900 instructions execute in a deliberately small interpreter.
Native camera, NJ builder, projection cache and field boundaries are synthetic
stubs: these tests prove arguments/ownership/restoration, not PS2 rendering,
real frustum math, scheduling, or coverage of unverified menu/event scenes.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.grandia2 import Grandia2Adapter, caves, memory_map as mm
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
from tests.test_druaga import FakeBackend as ByteBackend
from tests.test_radiata import CaveMachine as BaseMachine

OWNER, NODE, STACK = 0x500000, 0x501000, 0x1165ED0
CACHE_COUNT, CACHE_BASE = 0x84D348, 0x84D350
PLAYER = Vec3(100, 25, -50)
NATIVE = orbit_pose(PLAYER + Vec3(0, 180, 0), math.radians(45), math.radians(-30), 2400)
PAD = 0x510000


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def focal_for(degrees, width=640, aspect=1):
    return width / (2 * math.tan(math.radians(degrees) / 2) * aspect)


def active_bank(b):
    return mm.MOD_BLOCK + mm.SLOTS[b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def rendered_regions(b):
    return {address: b.bytes_at(address, size) for address, size in (
        (mm.NJ_STATE, mm.NJ_STATE_SIZE), (mm.VIEW, 0x80), (STACK, 64),
        (mm.FIELD_FOCAL, 4), (mm.NJ_FLAGS, 4), (mm.PROJECTION_RECORD_PTR, 4))}


class FakeBackend(ByteBackend):
    """Publication may schedule EE render→tail→submit callbacks, never a live VM."""
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)
        self.auto_guest = True
        self.in_guest = False
        self.host_writes = []
        self.guest_cycles = []
        self.before_guest = None
        self.after_guest = None
        self.cache = {}
        self.native_focal = focal_for(20)

    def title(self):
        return 'GRANDIA II'

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]

    def write_u32(self, address, value):
        if not self.in_guest:
            self.host_writes.append((address, value & 0xFFFFFFFF))
        super().write_u32(address, value)
        if (not self.in_guest and self.auto_guest
                and self.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
                and self.read_u32(mm.RENDER_HOOK) == caves.RENDER_PAIR[0]):
            self.in_guest = True
            try:
                if self.before_guest:
                    self.before_guest(self)
                machine = CaveMachine(self)
                machine.render()
                machine.finish()
                machine.submit()
                self.guest_cycles.append(machine)
                if self.after_guest:
                    self.after_guest(self)
            finally:
                self.in_guest = False

    def projection(self, focal):
        """Keep queued immutable records even after restoring current pointer."""
        focal = f32(focal)
        self.seed_floats(mm.NJ_FOCAL, [focal])
        if focal not in self.cache:
            address = CACHE_BASE + len(self.cache) * 0x1C
            self.cache[focal] = address
            self.seed_floats(address, [1, .91, 350, 60000, focal, 320, 240])
            self.seed_u32(CACHE_COUNT, len(self.cache))
        self.seed_u32(mm.PROJECTION_RECORD_PTR, self.cache[focal])


def seed_field(b, *, mode=8, native_fov=20, aspect=1):
    for address, value in mm.EXACT_GUARDS:
        b.seed_u32(address, value)
    b.seed_u32(mm.CAMERA, mode)
    b.seed_u32(mm.PLAYER_PTR, OWNER)
    b.seed_u32(OWNER + mm.ACTOR_NODE, NODE)
    b.seed_floats(NODE + mm.NODE_POSITION, PLAYER.as_tuple())
    # A tempting but wrong player mirror must not be selected.
    b.seed_floats(mm.PLAYER_MIRROR, [999, 888, 777])
    b.seed_floats(mm.CAM_EYE, NATIVE.eye.as_tuple())
    b.seed_floats(mm.CAM_TARGET, NATIVE.target.as_tuple())
    b.seed_floats(mm.CAM_DISTANCE, [2400])
    b.seed_u32(mm.CAM_PITCH, 5461)
    b.seed_u32(mm.CAM_YAW, 8192)
    b.seed_u32(mm.CAM_FOV, round(native_fov * 65536 / 360))
    b.seed_floats(mm.CAMERA + 0x24, [-350, -60000, 1])
    forward = (NATIVE.target - NATIVE.eye).scaled(1 / NATIVE.distance())
    b.seed_floats(mm.NJ_CAMERA, (*NATIVE.eye.as_tuple(), *forward.as_tuple()))
    b.seed_u32(mm.NJ_CAMERA + 0x18, 135)  # render scratch must explicitly remove roll
    b.seed_u32(mm.NJ_CAMERA + 0x1C, round(native_fov * 65536 / 360))
    b.seed_floats(mm.NJ_CAMERA + 0x20, [-350, -60000, 1])
    b.seed(mm.NJ_STATE, bytes((i * 7 + 3) & 255 for i in range(mm.NJ_STATE_SIZE)))
    b.seed_floats(mm.SCREEN_WIDTH, [640, 480, 320, 240])
    b.seed_floats(mm.ASPECT_X, [aspect, .91])
    b.seed_u32(mm.NJ_STACK_PTR, STACK)
    b.seed_u32(mm.NJ_STATE + 0x98, STACK)  # current matrix pointer 0x2EA330
    b.seed_u32(mm.NJ_FLAGS, 7)
    b.seed_floats(STACK, [float(i) for i in range(16)])
    b.seed_floats(mm.VIEW, [float(i + 100) for i in range(32)])
    b.native_focal = focal_for(native_fov, aspect=aspect)
    b.projection(b.native_focal)
    b.seed_floats(mm.FIELD_FOCAL, [b.native_focal])
    for address, stock, _ in caves.SITES:
        for i, word in enumerate(stock):
            b.seed_u32(address + i * 4, word)
    return b


@pytest.fixture
def be():
    return seed_field(FakeBackend())


class CaveMachine(BaseMachine):
    """Use standard emitted ops; SD/LD preserve the full synthetic return PC."""
    def __init__(self, backend):
        super().__init__(backend)
        self.native_snapshots = []
        self.on_builder = None
        self.on_native_camera = None
        self.on_submit = None

    def run(self, address):
        previous = self.b.in_guest
        self.b.in_guest = True
        try:
            return super().run(address)
        finally:
            self.b.in_guest = previous

    def _build(self, camera):
        eye = self.b.read_floats(camera, 3)
        forward = self.b.read_floats(camera + 0x0C, 3)
        # Synthetic numeric matrix identity is enough to expose overwritten
        # state. This does not claim to emulate Ninja's handedness or inverse.
        matrix = [*forward, 0, 0, 1, 0, 0, 0, 0, 1, 0, *eye, 1]
        self.b.seed_floats(mm.NJ_VIEW, matrix)
        self.b.seed_floats(mm.NJ_VIEW + 64, [-x for x in matrix])
        self.b.seed_floats(self.b.read_u32(mm.NJ_STACK_PTR), matrix)
        self.b.seed_u32(mm.NJ_FLAGS, 1)
        angle = self.b.read_u32(camera + 0x1C)
        half = angle // 2 * math.tau / 65536
        self.b.projection(self.b.read_f32(mm.SCREEN_WIDTH)
                          / (2 * math.tan(half) * self.b.read_f32(mm.ASPECT_X)))
        return tuple(eye), tuple(forward)

    def native(self, target):
        if target == mm.FUN_NATIVE_CAMERA:
            self.calls.append(('native', self.regs[m.A0]))
            if self.on_native_camera:
                self.on_native_camera(self)
            self._build(mm.NJ_CAMERA)
            self.b.projection(self.b.native_focal)
            self.b.seed_floats(mm.FIELD_FOCAL, [self.b.native_focal])
            expected = rendered_regions(self.b)
            # The cave saves the NEW native view and its inverse, not last
            # frame's still-stale field VIEW/WORLD at this call boundary.
            expected[mm.VIEW] = (self.b.bytes_at(mm.NJ_VIEW, 64)
                                 + struct.pack('<16f', *reversed(self.b.read_floats(mm.NJ_VIEW, 16))))
            self.native_snapshots.append(expected)
        elif target == mm.FUN_INVERT:
            address = self.regs[m.A0]
            self.calls.append(('inverse', address))
            self.b.seed_floats(address, list(reversed(self.b.read_floats(address, 16))))
        elif target == mm.FUN_NJ_CAMERA:
            camera = self.regs[m.A0]
            eye, forward = self._build(camera)
            self.calls.append(('nj', camera, eye, forward,
                               self.b.read_u32(camera + 0x18),
                               self.b.bytes_at(camera + 0x20, 8)))
            if self.on_builder:
                self.on_builder(self)
        elif target == mm.FUN_SET_FOCAL:
            self.calls.append(('focal', self.fpu[12]))
            self.b.projection(self.fpu[12])
        elif target == mm.FUN_MOVE:
            camera = self.regs[m.A1]
            self.calls.append(('move', self.regs[m.A0], camera,
                               self.b.read_u32(camera + 0x58)))
            return
        elif target == mm.FUN_NATIVE_TAIL:
            self.calls.append(('tail',))
            return
        elif target == mm.FUN_FRAME_SUBMIT:
            self.calls.append(('submit',))
            if self.on_submit:
                self.on_submit(self)
        else:
            raise AssertionError(f'unexpected native boundary {target:08X}')
        # Native calls may destroy all caller-saved registers.
        for reg in (m.V0, m.V1, m.A0, m.A1, m.A2, m.A3, *range(m.T0, m.T7 + 1)):
            self.regs[reg] = 0xBAD00000 | reg

    def render(self):
        self.regs[m.A0] = mm.CAMERA
        self.run(mm.RENDER_CAVE)
        # The unmodified field instructions after the cave copy/invert outputs.
        self.b.seed(mm.VIEW, self.b.bytes_at(mm.NJ_VIEW, 64))
        self.b.seed_floats(mm.WORLD, list(reversed(self.b.read_floats(mm.NJ_VIEW, 16))))
        return next((c for c in self.calls if c[0] == 'nj'), None)

    def finish(self):
        """Restore numeric outputs at field tail, before queued frame emission."""
        self.run(mm.TAIL_CAVE)

    def submit(self):
        """Submit queued native frame, then service the final detach request."""
        self.run(mm.FINISH_CAVE)

    def movement(self):
        self.regs[m.A0], self.regs[m.A1] = PAD, mm.CAMERA
        self.run(mm.MOVE_CAVE)
        return self.calls[-1]


def activate(be):
    adapter = Grandia2Adapter(be)
    adapter.set_patch(True)
    return adapter


def test_generated_resources_fit_owned_nonoverlapping_allocations():
    assert len(caves.SITES) == 7
    assert len(caves.RESOURCES) == 5
    regions = sorted((a, a + len(words) * 4) for a, words in caves.RESOURCES)
    assert all(end <= next_start for (_, end), (next_start, _) in zip(regions, regions[1:]))
    assert all(not start <= mm.MOD_BLOCK < end for start, end in regions)


@pytest.mark.parametrize('serial,crc,matched', [
    (mm.GAME_ID, mm.DISC_CRC, True), (' slpm-65081 ', ' b6ab7bc2 ', True),
    (mm.GAME_ID, 'DEADBEEF', False), ('SLPM-00000', mm.DISC_CRC, False), ('', '', False),
])
def test_identity_requires_serial_and_crc(serial, crc, matched):
    b = FakeBackend(serial, crc)
    assert Grandia2Adapter(b).identify().matched is matched
    assert not b.writes


@pytest.mark.parametrize('mode', [0, 8])
def test_indoor_fixed_and_outdoor_modes_read_owned_actor_without_writes(mode):
    b = seed_field(FakeBackend(), mode=mode)
    ad = Grandia2Adapter(b)
    assert ad.read_player() == PLAYER
    assert ad.read_scene().valid
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(NATIVE.eye.as_tuple())
    assert ad.features == dict(orbit=True, free_camera=False, fov=True,
                               position_offsets=True, target_offsets=True,
                               per_frame_write=False)
    assert ad.default_settings()['fov_deg'] == 20
    assert ad.PITCH_DISPLAY_SIGN == ad.PITCH_INPUT_SIGN == -1
    assert not b.writes


@pytest.mark.parametrize('degrees', [20, 40, 60, 100, 110])
@pytest.mark.parametrize('aspect', [1, 1.25])
def test_fov_roundtrip_uses_real_emitted_builder_then_final_focal_and_restores_tail(degrees, aspect):
    b = seed_field(FakeBackend(), aspect=aspect)
    ad = activate(b)
    native_camera = b.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    nj_camera = b.bytes_at(mm.NJ_CAMERA, mm.NJ_CAMERA_SIZE)
    ad.write_fov_deg(degrees)
    b.auto_guest = False
    machine = CaveMachine(b)
    call = machine.render()
    assert [c[0] for c in machine.calls] == ['native', 'inverse', 'nj', 'focal']
    assert call[1] == mm.MOD_BLOCK + mm.MB_NJ_SCRATCH
    assert call[4] == 0  # roll removed only in the scratch copy
    assert call[5] == b.bytes_at(mm.NJ_CAMERA + 0x20, 8)
    expected = focal_for(degrees, aspect=aspect)
    assert machine.calls[-1][1] == pytest.approx(expected)
    assert b.read_f32(mm.NJ_FOCAL) == pytest.approx(expected)
    assert b.read_f32(mm.FIELD_FOCAL) == pytest.approx(expected)
    assert ad.read_fov_deg() == pytest.approx(degrees, abs=1e-4)
    assert ad.fov_in_sync(degrees)
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT | mm.FLAG_FOV
    queued = b.bytes_at(CACHE_BASE, b.read_u32(CACHE_COUNT) * 0x1C)
    count = b.read_u32(CACHE_COUNT)
    machine.finish()
    assert machine.calls[-1] == ('tail',)
    assert rendered_regions(b) == machine.native_snapshots[0]
    assert b.bytes_at(CACHE_BASE, count * 0x1C) == queued
    assert b.read_u32(CACHE_COUNT) == count
    assert b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert b.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native_camera
    assert b.bytes_at(mm.NJ_CAMERA, mm.NJ_CAMERA_SIZE) == nj_camera
    assert ad.fov_in_sync(degrees)  # diagnostics survive numeric restoration
    assert all(mm.MOD_BLOCK <= a < mm.MOD_BLOCK + mm.BLOCK_SIZE
               or any(a == site for site, _, _ in caves.SITES)
               or any(start <= a < start + len(words) * 4 for start, words in caves.RESOURCES)
               for a, _ in b.host_writes)


@pytest.mark.parametrize('requested,expected', [(1, 20), (19, 20), (20, 20), (60, 60),
                                               (61, 61), (100, 100), (110, 110),
                                               (111, 110), (1e20, 110)])
def test_fov_range_contract_bounds_publication_and_sync_to_supported_lens(be, requested, expected):
    assert Grandia2Adapter.FOV_RANGE == (20.0, 110.0)
    ad = activate(be)
    native = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    ad.write_fov_deg(requested)
    assert be.read_f32(active_bank(be) + mm.SLOT_FOCAL) == pytest.approx(focal_for(expected))
    machine = CaveMachine(be)
    machine.render()
    assert machine.calls[-1] == ('focal', pytest.approx(focal_for(expected)))
    assert ad.read_fov_deg() == pytest.approx(expected, abs=1e-4)
    assert ad.fov_in_sync(expected)
    assert ad.fov_in_sync(requested)  # sync applies the same range as publication
    assert not ad.fov_in_sync(40 if expected != 40 else 60)
    machine.finish()
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native


def test_orbit_without_fov_override_keeps_latest_native_focal(be):
    ad = activate(be)
    be.native_focal = focal_for(34)
    machine = CaveMachine(be)
    machine.render()
    assert machine.calls[-1] == ('focal', pytest.approx(be.native_focal))
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT
    machine.finish()
    assert ad.read_fov_deg() == pytest.approx(34, abs=1e-4)
    ad.write_fov_deg(40)
    ad.restore_fov()
    machine = CaveMachine(be)
    machine.render()
    assert machine.calls[-1] == ('focal', pytest.approx(be.native_focal))
    machine.finish()
    assert not ad.fov_in_sync(40)


def test_fov_only_request_and_compatibility_hooks_do_not_install_or_write(be):
    ad = Grandia2Adapter(be)
    ad.write_fov_deg(60)
    ad.restore_fov()
    ad.restore()
    ad.set_stick_block(True)
    ad.write_projection_scale(10)
    ad.write_eye_offset(Vec3(1, 2, 3))
    assert caves.site_state(be) == 'stock'
    assert not be.writes


def test_latest_actor_relative_offsets_and_actual_sight_yaw_only_change_move_copy(be):
    ad = activate(be)
    native = be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    pos = Vec3(900, 40, -180)
    target = Vec3(15, 200, -25)
    ad.write_orbit_params(PLAYER + target, 15, -25, 1000,
                          pos_offset=pos, target_offset=target)
    relative = orbit_pose(target, math.radians(15), math.radians(-25), 1000)
    expected = CameraPose(relative.eye + pos, relative.target)
    newer = PLAYER + Vec3(70, 9, -35)
    be.seed_floats(NODE + mm.NODE_POSITION, newer.as_tuple())
    machine = CaveMachine(be)
    call = machine.render()
    assert call[2] == pytest.approx((newer + expected.eye).as_tuple())
    forward = (expected.target - expected.eye).scaled(1 / expected.distance())
    assert call[3] == pytest.approx(forward.as_tuple())
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_RENDER_TARGET, 3) == pytest.approx(
        (newer + target).as_tuple())
    move = CaveMachine(be).movement()
    yaw = round(math.atan2(expected.eye.x - expected.target.x,
                           expected.eye.z - expected.target.z) * 65536 / math.tau)
    assert move == ('move', PAD, mm.MOD_BLOCK + mm.MB_MOVE_CAMERA, yaw & 0xFFFFFFFF)
    assert yaw != round(15 * 65536 / 360)
    copied = bytearray(native)
    struct.pack_into('<I', copied, 0x58, yaw & 0xFFFFFFFF)
    assert be.bytes_at(mm.MOD_BLOCK + mm.MB_MOVE_CAMERA, mm.CAMERA_SIZE) == bytes(copied)
    assert be.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    machine.finish()


@pytest.mark.parametrize('mutation', ['odd', 'torn', 'owner', 'node', 'mode', 'guard', 'slot_off', 'global_off'])
def test_guest_rejects_incoherent_bank_owner_or_field_and_movement_falls_back(be, mutation):
    activate(be)
    bank = active_bank(be)
    if mutation == 'odd': be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif mutation == 'owner': be.seed_u32(mm.PLAYER_PTR, OWNER + 0x100)
    elif mutation == 'node': be.seed_u32(OWNER + mm.ACTOR_NODE, NODE + 0x100)
    elif mutation == 'mode': be.seed_u32(mm.CAMERA, 2)
    elif mutation == 'guard': be.seed_u32(mm.EXACT_GUARDS[0][0], 1)
    elif mutation == 'slot_off': be.seed_u32(bank + mm.SLOT_FLAGS, 0)
    elif mutation == 'global_off': be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    elif mutation == 'torn':
        original = be.read_u32
        reads = 0
        def torn_read(address):
            nonlocal reads
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                reads += 1
                if reads % 3 == 0: return value + 2
            return value
        be.read_u32 = torn_read
    machine = CaveMachine(be)
    assert machine.render() is None
    assert [c[0] for c in machine.calls] == ['native']
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    move = CaveMachine(be).movement()
    assert move == ('move', PAD, mm.CAMERA, be.read_u32(mm.CAM_YAW))


@pytest.mark.parametrize('address,value', [
    *[(a, v ^ 1) for a, v in mm.EXACT_GUARDS],
    (mm.CAMERA, 2), (mm.PLAYER_PTR, 0), (mm.PLAYER_PTR, 0x500001),
    (OWNER + mm.ACTOR_NODE, 0), (OWNER + mm.ACTOR_NODE, 0x1FFFFFF),
])
def test_host_guard_rejects_unknown_scene_or_owner_before_writing(be, address, value):
    be.seed_u32(address, value)
    ad = Grandia2Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('address', [
    *(site + off for site, _stock, _hook in caves.SITES for off in (0, 4)),
    *(start + off for start, words in caves.RESOURCES for off in (0, (len(words) - 1) * 4)),
    mm.MOD_BLOCK, mm.MOD_BLOCK + 0x10,
])
@pytest.mark.parametrize('operation', ['enable', 'pose', 'fov', 'restore'])
def test_unknown_hook_cave_or_block_rejects_entire_operation_before_any_write(be, address, operation):
    be.seed_u32(address, 0xDEADBEEF)
    ad = Grandia2Adapter(be)
    with pytest.raises(caves.PatchConflict):
        if operation == 'enable': ad.set_patch(True)
        elif operation == 'pose': ad.write_orbit_params(PLAYER, 70, -20, 1500)
        elif operation == 'fov': ad.write_fov_deg(60)
        else: ad.restore()
    assert not be.writes


def test_seven_site_lifecycle_host_bootstraps_only_render_guest_owns_final_detach(be):
    ad = activate(be)
    assert caves.site_state(be) == 'applied'
    assert all(caves.read_words(be, address, len(hook)) == hook
               for address, _stock, hook in caves.SITES)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_ACK
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == mm.FLAG_ORBIT
    assert [call[0] for call in be.guest_cycles[-1].calls][-2:] == ['tail', 'submit']
    host_sites = [(a, v) for a, v in be.host_writes if any(a == s for s, _, _ in caves.SITES)]
    assert host_sites == [(mm.RENDER_HOOK, caves.RENDER_PAIR[0])]
    ad.restore()
    assert caves.site_state(be) == 'stock'
    assert all(caves.read_words(be, address, len(stock)) == stock
               for address, stock, _hook in caves.SITES)
    assert [call[0] for call in be.guest_cycles[-1].calls] == ['native', 'tail', 'submit']
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert [(a, v) for a, v in be.host_writes if any(a == s for s, _, _ in caves.SITES)] == host_sites
    assert all(c.regs[m.SP] == 0x1F00000 for c in be.guest_cycles)


@pytest.mark.parametrize('address', [
    site + off for site, _stock, _hook in caves.SITES for off in (0, 4)
])
def test_guest_conflict_validates_all_sites_before_instruction_changes(be, address):
    activate(be)
    be.auto_guest = False
    be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    be.seed_u32(address, 0xBAD0BAD0)
    previous = [caves.read_words(be, a, 2) for a, _, _ in caves.SITES]
    machine = CaveMachine(be)
    machine.finish()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    assert [caves.read_words(be, a, 2) for a, _, _ in caves.SITES] == previous
    machine.submit()
    assert machine.calls == [('tail',), ('submit',)]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT
    assert [caves.read_words(be, a, 2) for a, _, _ in caves.SITES] == previous


def test_detach_inside_builder_waits_past_numeric_restore_until_native_frame_submit(be):
    activate(be)
    be.auto_guest = False
    machine = CaveMachine(be)
    def detach_inside_builder(cpu):
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 1
        be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
        be.seed_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    def before_submit_returns(cpu):
        # Native submit still needs every hook for the final queued Orbit frame.
        assert rendered_regions(be) == machine.native_snapshots[0]
        assert all(caves.read_words(be, address, len(hook)) == hook
                   for address, _stock, hook in caves.SITES)
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    machine.on_builder = detach_inside_builder
    machine.on_submit = before_submit_returns
    machine.render()
    assert caves.site_state(be) == 'applied'
    machine.finish()
    assert rendered_regions(be) == machine.native_snapshots[0]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert all(caves.read_words(be, address, len(hook)) == hook
               for address, _stock, hook in caves.SITES)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_SYNC
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == mm.FLAG_ORBIT
    machine.submit()
    assert machine.calls[-2:] == [('tail',), ('submit',)]
    assert rendered_regions(be) == machine.native_snapshots[0]
    assert caves.site_state(be) == 'stock'
    assert all(caves.read_words(be, address, len(stock)) == stock
               for address, stock, _hook in caves.SITES)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_ACK
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert machine.regs[m.SP] == 0x1F00000


def test_bank_snapshot_remains_stable_across_two_host_publications_inside_nj_builder(be):
    ad = activate(be)
    ad.write_orbit_params(PLAYER, 20, -30, 1400)
    ad.write_fov_deg(40)
    previous_bank = be.bytes_at(active_bank(be), mm.SLOT_SIZE)
    machine = CaveMachine(be)
    def publish_twice(cpu):
        ad.write_orbit_params(PLAYER, 90, -10, 1900)
        ad.write_fov_deg(100)
        ad.write_orbit_params(PLAYER, 150, -40, 2100)
    machine.on_builder = publish_twice
    call = machine.render()
    previous_eye = struct.unpack_from('<3f', previous_bank, mm.SLOT_EYE)
    assert call[2] == pytest.approx(tuple(a + b for a, b in zip(PLAYER.as_tuple(), previous_eye)))
    assert machine.calls[-1] == ('focal', pytest.approx(focal_for(40)))
    assert be.bytes_at(mm.MOD_BLOCK + mm.MB_SNAPSHOT, mm.SLOT_SIZE) == previous_bank
    assert be.bytes_at(active_bank(be), mm.SLOT_SIZE) != previous_bank
    machine.finish()
    newer = CaveMachine(be)
    newer.render()
    assert newer.calls[-1] == ('focal', pytest.approx(focal_for(100)))
    newer.finish()


def test_stock_state_reload_republishes_cached_pose_lens_and_seven_hooks(be):
    ad = activate(be)
    ad.write_orbit_params(PLAYER, 80, -40, 1800,
                          pos_offset=Vec3(70, 20, -30), target_offset=Vec3(10, 180, -15))
    ad.write_fov_deg(100)
    previous = be.bytes_at(active_bank(be) + mm.SLOT_EYE, mm.SLOT_SIZE - mm.SLOT_EYE)
    replacement = seed_field(FakeBackend())
    be.mem, be.cache = replacement.mem, replacement.cache
    ad.set_patch(True)
    assert caves.site_state(be) == 'applied'
    assert be.bytes_at(active_bank(be) + mm.SLOT_EYE, mm.SLOT_SIZE - mm.SLOT_EYE) == previous
    assert be.read_u32(active_bank(be) + mm.SLOT_SEQUENCE) % 2 == 0
    assert ad.fov_in_sync(100)
    assert ad.read_fov_deg() == pytest.approx(100, abs=1e-4)
    ad.restore()
    assert caves.site_state(be) == 'stock'


def test_guarded_backend_blocks_new_publication_and_restore_after_game_switch(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = Grandia2Adapter(guard)
    ad.set_patch(True)
    be.serial = 'SLPS-00000'
    assert guard.verify() == CHANGED
    be.writes.clear()
    with pytest.raises(WriteBlocked): ad.set_patch(True)
    with pytest.raises(WriteBlocked): ad.write_fov_deg(60)
    with pytest.raises(WriteBlocked): ad.restore()
    assert not be.writes


@pytest.mark.parametrize('address,bad', [
    (NODE + mm.NODE_POSITION, float('nan')), (mm.CAM_EYE, float('inf')),
    (mm.FIELD_FOCAL, 0), (mm.SCREEN_WIDTH, 0), (mm.ASPECT_X, float('nan')),
])
def test_invalid_native_geometry_and_lens_fail_before_publication(be, address, bad):
    be.seed_floats(address, [bad])
    ad = Grandia2Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_pose_and_fov_rejected_before_writes(be, bad):
    ad = Grandia2Adapter(be)
    with pytest.raises(ValueError): ad.write_orbit_params(PLAYER, bad, -20, 1000)
    with pytest.raises(ValueError): ad.write_fov_deg(bad)
    assert not be.writes
