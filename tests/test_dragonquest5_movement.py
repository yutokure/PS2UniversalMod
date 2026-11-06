"""DQ5 movement cave contracts on invented sparse memory, without an emulator.

The inherited instruction runner executes the emitted caves only. ``native``
models the small tail continuations' known vector/heading equations, not the
complete native routine, R5900 trig precision, gameplay or PS2 scheduling.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.dragonquest5 import caves, memory_map as mm
from adapters.dragonquest5.adapter import DragonQuest5Adapter
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from tests.test_dragonquest5 import (
    ACTOR, NODE, PAD, PLAYER, CaveMachine as RenderMachine, FakeBackend, active_bank, seed_field,
)
from tests.test_radiata import CaveMachine as RadiataMachine


VECTOR_ACTIVE, FACING_ACTIVE = 0x546CF0, 0x5470CC
VECTOR_FALLBACK = (0x546CD4, 0x546CE8)
FACING_FALLBACK = (0x5470B0, 0x5470C0)
YAWS = tuple(range(-180, 180, 45))
DIRECTIONS = ((0, -1), (1, -1), (1, 0), (1, 1),
              (0, 1), (-1, 1), (-1, 0), (-1, -1))


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def seed_movement():
    b = seed_field(FakeBackend())
    # Movement ownership is stricter than render ownership. S3 is the manager,
    # never the actor; the manager-owned actor must equal PLAYER_PTR.
    b.seed_u32(mm.PLAYER_MANAGER + mm.MANAGER_ACTOR, ACTOR)
    b.seed_u32(ACTOR + mm.ACTOR_SCRIPTED, 0)
    b.seed_u32(ACTOR + mm.ACTOR_INPUT_FLAGS, mm.NORMAL_INPUT_FLAGS)
    return b


@pytest.fixture
def be():
    return seed_movement()


class Machine(RadiataMachine):
    """Execute caves and record ABI state before a limited native tail model."""
    def __init__(self, backend, *, gate=0):
        super().__init__(backend)
        # Nonzero upper lanes catch accidental LW/SW or LD/SD preservation.
        self.regs = [0] + [((0xC0FFEE00 + r) << 96) | ((0xABC00000 + r) << 64)
                           | ((0xDEF00000 + r) << 32) | (0x12000000 + r)
                           for r in range(1, 32)]
        self.regs[m.SP] = 0x01F00000
        self.regs[m.S3] = mm.PLAYER_MANAGER
        self.regs[m.V0] = gate
        self.fpu = [f32(20 + i / 8) for i in range(32)]
        self.axes = (0, -1)
        self.vector = None
        self.heading = None
        self.boundary = None
        self.entry_regs = None
        self.entry_fpu = None

    def execute(self, word):
        if word >> 26 == 0x24:  # LBU, needed for actor+0x28 only.
            base, rt = word >> 21 & 31, word >> 16 & 31
            off = word & 65535
            off = off - 65536 if off & 32768 else off
            self.put(rt, self.b.bytes_at((self.regs[base] + off) & 0xFFFFFFFF, 1)[0])
        else:
            super().execute(word)

    def native(self, dest):
        assert dest in (VECTOR_ACTIVE, FACING_ACTIVE, *VECTOR_FALLBACK, *FACING_FALLBACK)
        # Capture BEFORE modelling native continuation: this is the cave's ABI.
        self.boundary = (dest, tuple(self.regs), tuple(self.fpu))
        self.calls.append(dest)
        x, y = self.axes
        if dest in (VECTOR_ACTIVE, *VECTOR_FALLBACK):
            yaw = (self.fpu[12] if dest == VECTOR_ACTIVE else
                   self.b.read_f32(mm.CAM_YAW) if dest == VECTOR_FALLBACK[1] else 0.0)
            # Native signed LX/LY, with up == negative LY.
            self.vector = (x * math.cos(yaw) - y * math.sin(yaw),
                           -x * math.sin(yaw) - y * math.cos(yaw))
        elif dest == FACING_ACTIVE:
            # Native add.s at the selected tail: saved base heading + yaw.
            self.heading = f32(self.fpu[1] + self.fpu[0])
        else:
            yaw = self.b.read_f32(mm.CAM_YAW) if dest == FACING_FALLBACK[1] else 0.0
            self.heading = f32(self.fpu[0] + yaw)

    def enter(self, facing=False):
        if facing:
            self.fpu[0] = f32(2 * math.pi - math.atan2(*self.axes))
            self.fpu[1] = f32(-17.125)  # Must reload stack+0x114, not retain this.
        else:
            self.fpu[0] = f32(1.375)
            self.fpu[12] = f32(-0.875)
        self.entry_regs, self.entry_fpu = tuple(self.regs), tuple(self.fpu)
        self.boundary = None
        # The original branch delay has already executed on cave entry.
        self.execute(mm.FACING_STOCK[1] if facing else mm.MOVE_STOCK[1])
        self.run(mm.FACING_CAVE if facing else mm.MOVE_CAVE)
        assert self.boundary is not None
        return self.boundary[0]

    def assert_abi(self, outputs=()):
        _, regs, fpu = self.boundary
        assert regs == self.entry_regs  # Includes every upper GPR lane and RA.
        assert all(fpu[i] == value for i, value in enumerate(self.entry_fpu) if i not in outputs)


def publish(b, yaw=45, *, position=Vec3(0, 0, 0)):
    ad = DragonQuest5Adapter(b)
    ad.write_orbit_params(PLAYER, yaw, -35, 175, pos_offset=position, target_offset=Vec3(-4, 13, 8))
    return ad


def assert_fallback(machine, *, facing=False):
    expected = FACING_FALLBACK if facing else VECTOR_FALLBACK
    assert machine.boundary[0] == expected[int(bool(machine.regs[m.V0]))]
    machine.assert_abi()


@pytest.mark.parametrize('yaw', YAWS)
@pytest.mark.parametrize('axes', DIRECTIONS)
@pytest.mark.parametrize('gate', [0, 1])
@pytest.mark.parametrize('eye_offset', [Vec3(0, 0, 0), Vec3(31, -17, -43)], ids=['centred', 'eye_offset'])
def test_eight_yaws_and_directions_share_vector_and_facing_with_either_native_gate(
        be, yaw, axes, gate, eye_offset):
    target = Vec3(-4, 13, 8)
    publish(be, yaw, position=eye_offset)
    be.seed_u32(0x7B782C, gate)  # Native branch input, already loaded into V0.
    relative = orbit_pose(target, math.radians(yaw), math.radians(-35), 175)
    relative = CameraPose(relative.eye + eye_offset, relative.target)
    dx, dz = relative.target.x - relative.eye.x, relative.target.z - relative.eye.z
    forward = (dx / math.hypot(dx, dz), dz / math.hypot(dx, dz))
    expected_yaw = math.atan2(dx, dz)
    assert be.read_f32(active_bank(be) + mm.SLOT_YAW) == pytest.approx(expected_yaw, abs=2e-7)
    machine = Machine(be, gate=gate)
    machine.axes = axes
    original_sp = machine.regs[m.SP]
    assert machine.enter() == VECTOR_ACTIVE
    machine.assert_abi((12,))
    assert machine.fpu[12] == pytest.approx(expected_yaw, abs=2e-7)
    assert be.read_f32(original_sp + 0x104) == machine.entry_fpu[0]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == original_sp
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_NODE) == NODE
    assert be.read_f32(mm.MOD_BLOCK + mm.MB_MOVE_YAW) == machine.fpu[12]
    x, y = axes
    expected_vector = (x * forward[1] - y * forward[0], -x * forward[0] - y * forward[1])
    assert machine.vector == pytest.approx(expected_vector, abs=4e-7)
    assert machine.enter(facing=True) == FACING_ACTIVE
    machine.assert_abi((0, 1))
    assert machine.fpu[0] == pytest.approx(expected_yaw, abs=2e-7)
    assert machine.fpu[1] == be.read_f32(original_sp + 0x114) == machine.entry_fpu[0]
    actor_forward = (-math.sin(machine.heading), -math.cos(machine.heading))
    length = math.hypot(*machine.vector)
    assert actor_forward == pytest.approx(tuple(v / length for v in machine.vector), abs=1e-6)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0


def seed_native_map_lock(b, kind):
    """Invent native rig lock fields, not alternate/scripted camera ownership."""
    if kind == 'hard_lock':
        # Native map limits 1/1 derive veto=1 and yaw limits 0/0.
        veto, upper, lower, raw_upper, raw_lower = 1, 0.0, 0.0, 1, 1
    else:
        assert kind == 'finite_bounds'
        veto, upper, lower, raw_upper, raw_lower = 0, math.radians(15), math.radians(-15), 15, -15
    # Veto is a byte. Its neighbouring bytes are unrelated native state.
    b.seed_u32(mm.CAM_EYE + 0x204, 0xA1B2C300 | veto)
    b.seed_floats(mm.CAM_EYE + 0x21C, [upper, lower])
    b.seed_u32(mm.CAM_EYE + 0x48C, raw_upper)
    b.seed_u32(mm.CAM_EYE + 0x490, raw_lower)
    return {mm.CAM_EYE + off: b.bytes_at(mm.CAM_EYE + off, 4)
            for off in (0x200, 0x204, 0x21C, 0x220, 0x48C, 0x490)}


@pytest.mark.parametrize('lock', ['hard_lock', 'finite_bounds'])
@pytest.mark.parametrize('gate', [0, 1])
@pytest.mark.parametrize('yaw', range(0, 361, 30))
def test_ordinary_field_native_map_locks_allow_full_orbit_render_and_movement_without_rewriting_rig(
        be, lock, gate, yaw):
    # Only ordinary party-follow ownership is covered: +0x200 permission stays
    # 1 and all exact/suspension guards remain valid. These map restrictions
    # govern the native camera, not the independently published render pose.
    preserved = seed_native_map_lock(be, lock)
    be.seed_u32(0x7B782C, gate)
    preserved[0x7B782C] = be.bytes_at(0x7B782C, 4)
    for address in (mm.CAM_EYE, mm.CAM_TARGET, mm.CAM_YAW):
        preserved[address] = be.bytes_at(address, 16)
    native_world = be.bytes_at(mm.WORLD, 64)
    ad = DragonQuest5Adapter(be)
    scene = ad.read_scene()
    assert scene.valid and ad.is_field_like(scene)
    assert not be.writes
    target, position = Vec3(-4, 13, 8), Vec3(31, -17, -43)
    ad.write_orbit_params(PLAYER, yaw, -35, 175, pos_offset=position, target_offset=target)
    relative = orbit_pose(target, math.radians(yaw), math.radians(-35), 175)
    relative = CameraPose(relative.eye + position, relative.target)
    expected = CameraPose(relative.eye + PLAYER, relative.target + PLAYER)
    render = RenderMachine(be).render()
    assert render[0:2] == ('render', mm.RENDERER)
    assert render[2] == pytest.approx(ad._world(expected), abs=3e-5)
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(expected.eye.as_tuple(), abs=3e-5)
    assert ad.read_game_pose().target.as_tuple() == pytest.approx(expected.target.as_tuple(), abs=3e-5)
    assert ad.heartbeat_word() == 1
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert be.bytes_at(mm.WORLD, 64) == native_world
    machine = Machine(be, gate=gate)
    assert machine.enter() == VECTOR_ACTIVE
    machine.assert_abi((12,))
    forward = relative.target - relative.eye
    expected_forward = (forward.x / math.hypot(forward.x, forward.z),
                        forward.z / math.hypot(forward.x, forward.z))
    assert machine.vector == pytest.approx(expected_forward, abs=4e-7)
    assert machine.enter(True) == FACING_ACTIVE
    machine.assert_abi((0, 1))
    assert (-math.sin(machine.heading), -math.cos(machine.heading)) == pytest.approx(
        expected_forward, abs=1e-6)
    assert all(be.bytes_at(address, len(data)) == data for address, data in preserved.items())
    ad.set_patch(False)
    assert all(be.bytes_at(address, len(data)) == data for address, data in preserved.items())
    assert be.bytes_at(mm.WORLD, 64) == native_world
    assert not any(address < start + len(data) and start < address + len(written)
                   for address, written in be.writes for start, data in preserved.items())


@pytest.mark.parametrize('address,value', [(0x81B630, 0x01000100), (0x81B890, 1)],
                         ids=['rotation_permission_off', 'suspended_mode'])
def test_host_rejects_permission_off_or_suspended_mode_before_any_write(be, address, value):
    assert (0x81B630, 0x01000101) in mm.EXACT_GUARDS
    assert (0x81B890, 0) in mm.EXACT_GUARDS
    be.seed_u32(address, value)
    ad = DragonQuest5Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        ad.write_orbit_params(PLAYER, 270, -35, 175)
    with pytest.raises(caves.PatchConflict):
        ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('yaw', YAWS)
def test_published_yaw_uses_actual_eye_offset_not_gui_yaw_or_native_rig(be, yaw):
    ad = publish(be, yaw)
    original = be.read_f32(active_bank(be) + mm.SLOT_YAW)
    ad.write_orbit_params(PLAYER, yaw, -35, 175,
                          pos_offset=Vec3(35, 7, -22), target_offset=Vec3(4, 10, -6))
    bank = active_bank(be)
    world = be.read_floats(bank + mm.SLOT_WORLD, 16)
    target = be.read_floats(bank + mm.SLOT_TARGET, 3)
    actual = math.atan2(target[0] - world[12], target[2] - world[14])
    requested = be.read_f32(bank + mm.SLOT_YAW)
    assert requested == pytest.approx(actual, abs=3e-7)
    assert abs(math.atan2(math.sin(requested - original), math.cos(requested - original))) > .01
    assert requested != pytest.approx(be.read_f32(mm.CAM_YAW))


BAD_FIELD = [(f'exact_{address:X}', address, value ^ 1) for address, value in mm.EXACT_GUARDS]
BAD_FIELD += [(f'half_{address:X}', address, 1) for address in mm.ZERO_HALF_GUARDS]


@pytest.mark.parametrize('name,address,value', BAD_FIELD, ids=[case[0] for case in BAD_FIELD])
@pytest.mark.parametrize('facing', [False, True])
@pytest.mark.parametrize('gate', [0, 1])
def test_both_consumers_recheck_every_field_guard(be, name, address, value, facing, gate):
    publish(be)
    machine = Machine(be, gate=gate)
    if facing:
        assert machine.enter() == VECTOR_ACTIVE
    be.seed_u32(address, value)
    machine.enter(facing)
    assert_fallback(machine, facing=facing)
    if not facing:
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0


@pytest.mark.parametrize('address', mm.ZERO_HALF_GUARDS)
def test_halfword_and_scripted_byte_guards_ignore_adjacent_bytes(be, address):
    publish(be)
    be.seed_u32(address, 0xABCD0000)
    be.seed_u32(ACTOR + mm.ACTOR_SCRIPTED, 0xABCD0100)
    machine = Machine(be)
    assert machine.enter() == VECTOR_ACTIVE
    assert machine.enter(True) == FACING_ACTIVE


OWNERSHIP_REJECTIONS = ('bad_magic', 'disabled', 'fov_only', 'manager', 'manager_actor',
                        'scripted', 'scripted_high_bit', 'input_zero', 'input_missing_bit',
                        'input_extra_bit', 'node', 'actor_zero', 'actor_low',
                        'actor_unaligned', 'actor_at_margin', 'actor_straddles_ram', 'actor_above_ram')


def invalidate(b, machine, reason):
    if reason == 'bad_magic': b.seed_u32(mm.MOD_BLOCK, 0)
    elif reason == 'disabled': b.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    elif reason == 'fov_only': b.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_FOV)
    elif reason == 'manager': machine.regs[m.S3] = mm.PLAYER_MANAGER + 0x100
    elif reason == 'manager_actor': b.seed_u32(mm.PLAYER_MANAGER + mm.MANAGER_ACTOR, ACTOR + 0x2000)
    elif reason.startswith('scripted'):
        b.seed_u32(ACTOR + mm.ACTOR_SCRIPTED, 0x80 if reason == 'scripted_high_bit' else 1)
    elif reason == 'input_zero': b.seed_u32(ACTOR + mm.ACTOR_INPUT_FLAGS, 0)
    elif reason == 'input_missing_bit': b.seed_u32(ACTOR + mm.ACTOR_INPUT_FLAGS, mm.NORMAL_INPUT_FLAGS ^ 1)
    elif reason == 'input_extra_bit': b.seed_u32(ACTOR + mm.ACTOR_INPUT_FLAGS, mm.NORMAL_INPUT_FLAGS | 0x1000000)
    elif reason == 'node': b.seed_u32(ACTOR + mm.PLAYER_NODE, NODE + 0x1000)
    elif reason.startswith('actor_'):
        actor = {'actor_zero': 0, 'actor_low': 0xFFFF0,
                 'actor_unaligned': ACTOR + 1, 'actor_at_margin': 0x1FFFE00,
                 'actor_straddles_ram': 0x1FFFFF0, 'actor_above_ram': 0x2000000}[reason]
        b.seed_u32(mm.PLAYER_PTR, actor)
        b.seed_u32(mm.PLAYER_MANAGER + mm.MANAGER_ACTOR, actor)
        # If pointer validation were absent, all later ownership checks pass.
        b.seed_u32(actor + mm.ACTOR_SCRIPTED, 0)
        b.seed_u32(actor + mm.ACTOR_INPUT_FLAGS, mm.NORMAL_INPUT_FLAGS)
        b.seed_u32(actor + mm.PLAYER_NODE, NODE)
    else:
        raise AssertionError(reason)


@pytest.mark.parametrize('reason', OWNERSHIP_REJECTIONS)
@pytest.mark.parametrize('facing', [False, True])
@pytest.mark.parametrize('gate', [0, 1])
def test_movement_requires_orbit_and_current_unscripted_manager_owned_player(be, reason, facing, gate):
    publish(be)
    machine = Machine(be, gate=gate)
    if facing:
        assert machine.enter() == VECTOR_ACTIVE
    invalidate(be, machine, reason)
    machine.enter(facing)
    assert_fallback(machine, facing=facing)


@pytest.mark.parametrize('reason', ['odd', 'changed', 'slot_disabled', 'slot_fov', 'slot_node'])
@pytest.mark.parametrize('gate', [0, 1])
def test_vector_rejects_unstable_or_unowned_publication_without_latching(be, reason, gate):
    publish(be)
    bank = active_bank(be)
    if reason == 'odd': be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif reason == 'slot_disabled': be.seed_u32(bank + mm.SLOT_FLAGS, 0)
    elif reason == 'slot_fov': be.seed_u32(bank + mm.SLOT_FLAGS, mm.FLAG_FOV)
    elif reason == 'slot_node': be.seed_u32(bank + mm.SLOT_NODE, NODE + 0x1000)
    elif reason == 'changed':
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                be.seed_u32(address, value + 2)
            return value
        be.read_u32 = changed
    be.seed_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP, 0x01F00000)
    machine = Machine(be, gate=gate)
    machine.enter()
    assert_fallback(machine)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0
    machine.enter(True)
    assert_fallback(machine, facing=True)


@pytest.mark.parametrize('gate', [0, 1])
def test_real_host_fov_only_publication_keeps_native_movement_and_facing(be, gate):
    ad = DragonQuest5Adapter(be)
    ad.write_fov_deg(60)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
    assert be.read_u32(active_bank(be) + mm.SLOT_FLAGS) == mm.FLAG_FOV
    machine = Machine(be, gate=gate)
    machine.enter()
    assert_fallback(machine)
    machine.enter(True)
    assert_fallback(machine, facing=True)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0


def test_sequence_change_while_yaw_is_read_never_exposes_unstable_yaw_to_fpu(be):
    publish(be)
    bank = active_bank(be)
    original = be.read_u32
    def republish_during_yaw(address):
        value = original(address)
        if address == bank + mm.SLOT_YAW:
            be.seed_u32(bank + mm.SLOT_SEQUENCE, original(bank + mm.SLOT_SEQUENCE) + 2)
            be.seed_floats(bank + mm.SLOT_YAW, [-2.5])
        return value
    be.read_u32 = republish_during_yaw
    machine = Machine(be, gate=1)
    machine.enter()
    assert_fallback(machine)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0
    machine.enter(True)
    assert_fallback(machine, facing=True)


@pytest.mark.parametrize('reason', ['disabled', 'fov_only', 'scripted', 'manager', 'node'])
def test_every_vector_invocation_invalidates_old_facing_latch_before_guards(be, reason):
    publish(be)
    machine = Machine(be)
    assert machine.enter() == VECTOR_ACTIVE
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == machine.regs[m.SP]
    invalidate(be, machine, reason)
    machine.enter()
    assert_fallback(machine)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0
    # Restore every changed guard without executing another vector.
    be.seed_u32(mm.MOD_BLOCK, mm.MAGIC)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_ORBIT)
    be.seed_u32(ACTOR + mm.ACTOR_SCRIPTED, 0)
    be.seed_u32(ACTOR + mm.PLAYER_NODE, NODE)
    machine.regs[m.S3] = mm.PLAYER_MANAGER
    machine.enter(True)
    assert_fallback(machine, facing=True)


@pytest.mark.parametrize('gate', [0, 1])
def test_facing_consumes_same_latch_despite_two_publications_and_reads_no_new_bank(be, gate):
    ad = publish(be, -45, position=Vec3(21, 5, -13))
    machine = Machine(be, gate=gate)
    machine.axes = (1, -1)
    assert machine.enter() == VECTOR_ACTIVE
    yaw, vector = machine.fpu[12], machine.vector
    first_bank = active_bank(be)
    ad.write_orbit_params(PLAYER, 90, -20, 130)
    ad.write_orbit_params(PLAYER, 135, -25, 190)
    assert active_bank(be) == first_bank  # Even the old bank was overwritten.
    assert be.read_f32(first_bank + mm.SLOT_YAW) != pytest.approx(yaw)
    be.reads.clear()
    assert machine.enter(True) == FACING_ACTIVE
    machine.assert_abi((0, 1))
    assert machine.fpu[0] == yaw
    bank_ranges = [(mm.MOD_BLOCK + slot, mm.MOD_BLOCK + slot + mm.SLOT_SIZE) for slot in mm.SLOTS]
    assert not any(start <= a < end for a, _ in be.reads for start, end in bank_ranges)
    assert not any(a == mm.MOD_BLOCK + mm.MB_SLOT for a, _ in be.reads)
    actual_forward = (-math.sin(machine.heading), -math.cos(machine.heading))
    assert actual_forward == pytest.approx(tuple(v / math.hypot(*vector) for v in vector), abs=1e-6)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP) == 0
    machine.enter(True)  # Consumed once; there is no fresh vector latch.
    assert_fallback(machine, facing=True)


@pytest.mark.parametrize('reason', ['sp', 'node'])
def test_facing_requires_same_stack_frame_and_current_node_as_vector(be, reason):
    publish(be)
    machine = Machine(be, gate=1)
    assert machine.enter() == VECTOR_ACTIVE
    if reason == 'sp': machine.regs[m.SP] += 0x1000
    else: be.seed_u32(ACTOR + mm.PLAYER_NODE, NODE + 0x1000)
    machine.enter(True)
    assert_fallback(machine, facing=True)


@pytest.mark.parametrize('magic', [0, 0xDEADBEEF])
@pytest.mark.parametrize('facing', [False, True])
def test_bad_magic_preserves_unknown_control_block_without_guest_latch_writes(be, magic, facing):
    publish(be)
    machine = Machine(be, gate=1)
    if facing:
        assert machine.enter() == VECTOR_ACTIVE
    be.seed_u32(mm.MOD_BLOCK, magic)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP, machine.regs[m.SP])
    be.seed_u32(mm.MOD_BLOCK + mm.MB_MOVE_NODE, 0xDEADBEEF)
    before = dict(be.mem)
    be.writes.clear()
    machine.enter(facing)
    assert_fallback(machine, facing=facing)
    assert be.bytes_at(mm.MOD_BLOCK, mm.BLOCK_SIZE) == bytes(
        before.get(mm.MOD_BLOCK + i, 0) for i in range(mm.BLOCK_SIZE))
    # The SQ register-save frame is private stack; the stock delay store is
    # also required. No writes to foreign data are allowed without our magic.
    sp, off = machine.regs[m.SP], 0x114 if facing else 0x104
    allowed = set(range(sp - 80, sp)) | set(range(sp + off, sp + off + 4))
    changed = {a for a in before.keys() | be.mem.keys() if before.get(a, 0) != be.mem.get(a, 0)}
    assert changed <= allowed
    assert [a for a, _ in be.writes] == [sp + off]


@pytest.mark.parametrize('facing', [False, True])
@pytest.mark.parametrize('gate', [0, 1, 0x12345678])
def test_original_branch_fallback_keeps_delay_store_and_all_registers(be, facing, gate):
    publish(be)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_FOV)
    machine = Machine(be, gate=gate)
    assert machine.enter(facing) == (FACING_FALLBACK if facing else VECTOR_FALLBACK)[int(bool(gate))]
    assert_fallback(machine, facing=facing)
    offset = 0x114 if facing else 0x104
    assert be.read_f32(machine.regs[m.SP] + offset) == machine.entry_fpu[0]
    yaw = be.read_f32(mm.CAM_YAW) if gate else 0
    if facing:
        assert machine.heading == f32(machine.entry_fpu[0] + yaw)
    else:
        assert machine.vector == pytest.approx((math.sin(yaw), math.cos(yaw)))


def test_active_caves_change_only_private_stack_and_guest_latch_memory(be):
    publish(be)
    machine = Machine(be, gate=1)
    before = dict(be.mem)
    assert machine.enter() == VECTOR_ACTIVE
    machine.assert_abi((12,))
    assert machine.enter(True) == FACING_ACTIVE
    machine.assert_abi((0, 1))
    sp = machine.regs[m.SP]
    allowed = set(range(sp - 80, sp)) | set(range(sp + 0x104, sp + 0x108))
    allowed |= set(range(sp + 0x114, sp + 0x118))
    allowed |= set(range(mm.MOD_BLOCK + mm.MB_MOVE_SP, mm.MOD_BLOCK + mm.MB_MOVE_YAW + 4))
    changed = {a for a in before.keys() | be.mem.keys() if before.get(a, 0) != be.mem.get(a, 0)}
    assert changed <= allowed
    # These addresses must not be used as alternative movement outputs.
    for address, size in ((ACTOR, 0x200), (PAD, 0x200), (mm.CAM_YAW, 16),
                          (mm.CAM_EYE, 16), (mm.CAM_TARGET, 16), (mm.WORLD, 64)):
        assert be.bytes_at(address, size) == bytes(before.get(address + i, 0) for i in range(size))


def test_movement_cave_layout_tail_destinations_and_register_write_allowlist():
    assert mm.MOVE_CAVE == 0xF3400 and mm.FACING_CAVE == 0xF3800
    assert mm.MB_MOVE_SP == 0x140 and mm.MB_MOVE_NODE == 0x144 and mm.MB_MOVE_YAW == 0x148
    assert mm.PAD_CAVE + 4 * len(caves.PAD_WORDS) <= mm.MOVE_CAVE
    assert mm.MOVE_CAVE + 4 * len(caves.MOVE_WORDS) <= mm.FACING_CAVE
    assert mm.FACING_CAVE + 4 * len(caves.FACING_WORDS) <= mm.MOD_BLOCK
    assert mm.MB_MOVE_YAW + 4 <= mm.SLOTS[0]
    for hook, stock, words, start, tails in (
            (mm.MOVE_HOOK, mm.MOVE_STOCK, caves.MOVE_WORDS, mm.MOVE_CAVE, {VECTOR_ACTIVE, *VECTOR_FALLBACK}),
            (mm.FACING_HOOK, mm.FACING_STOCK, caves.FACING_WORDS, mm.FACING_CAVE, {FACING_ACTIVE, *FACING_FALLBACK})):
        resource = next(r for r in caves.RESOURCES if r[0] == hook)
        assert resource[2] == (m.j(start), stock[1])
        assert stock[1] == m.swc1(0, m.SP, 0x104 if start == mm.MOVE_CAVE else 0x114)
        assert words[0] == m.addiu(m.SP, m.SP, -80)
        assert {((w & 0x3FFFFFF) << 2) for w in words if w >> 26 == 2} == tails
        saved = [(w >> 16 & 31, w & 65535) for w in words if w >> 26 == 0x1F]
        restored = [(w >> 16 & 31, w & 65535) for w in words if w >> 26 == 0x1E]
        expected = [(reg, 16 * i) for i, reg in enumerate(range(m.T0, m.T4 + 1))]
        assert saved == expected and restored == expected * 2
        for i, word in enumerate(words):
            op = word >> 26
            assert op != 3  # A mid-function hook must not replace RA with JAL.
            if op in (4, 5):
                off = word & 65535
                off = off - 65536 if off & 32768 else off
                assert 0 <= i + 1 + off < len(words)
            dest = ((word >> 11) & 31) if op == 0 and word else (
                (word >> 16) & 31 if op in (9, 0x0B, 0x0C, 0x0D, 0x0F, 0x1E, 0x23, 0x24, 0x25) else None)
            assert dest is None or dest in (m.ZERO, m.SP, *range(m.T0, m.T4 + 1))
