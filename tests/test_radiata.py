"""Radiata adapter contracts on synthetic sparse memory, without emulator/game data.

The local instruction interpreter models only emitted cave instructions and call
boundaries, not PS2 scheduling, rendering, frustum math, or unverified scenes.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.radiatastories import caves, memory_map as mm
from adapters.radiatastories.adapter import RadiataStoriesAdapter
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
from core.memory_backend.guard import GuardedBackend, WriteBlocked, CHANGED
from tests.test_druaga import FakeBackend as ByteBackend

FIELD, OWNER, CAM, TARGET = 0x01000000, 0x01002000, 0x01003000, 0x01004000
SCENE, MANAGER, RECORDS = 0x01005000, 0x01006000, 0x01007000
ACTOR, NODE, RENDERER = 0x01008000, 0x01009000, 0x0100A000
PLAYER = Vec3(123.0, 950.0, -4200.0)
NATIVE = orbit_pose(PLAYER + Vec3(0, -90, 0), math.pi, math.radians(20), 1500)


class FakeBackend(ByteBackend):
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)

    def title(self):
        return "RADIATA STORIES"


def seed_field(b, *, player_slot=0, xscale=1.0, yscale=1.0):
    count = max(2, player_slot + 1)
    for address, value in (
        (mm.FIELD_MANAGER_PTR, FIELD), (FIELD + mm.FIELD_OWNER, OWNER),
        (OWNER + mm.OWNER_CAMERA, CAM), (OWNER + mm.OWNER_TARGET, TARGET),
        (CAM, mm.CAMERA_VTABLE), (TARGET, mm.NODE_VTABLE),
        (mm.RENDERER_PTR, RENDERER), (RENDERER + mm.RENDERER_CAMERA, CAM),
        (mm.SCENE_PTR, SCENE), (SCENE + mm.PLAYER_ID, 1),
        (mm.ACTOR_MANAGER_PTR, MANAGER), (MANAGER + mm.ACTOR_COUNT, count),
        (MANAGER + mm.ACTOR_RECORDS, RECORDS),
        (RECORDS + player_slot * mm.ACTOR_STRIDE + mm.ACTOR_ID, 1),
        (RECORDS + player_slot * mm.ACTOR_STRIDE + mm.ACTOR_OBJECT, ACTOR),
        (RECORDS + player_slot * mm.ACTOR_STRIDE + mm.ACTOR_NODE, NODE),
        (NODE, mm.NODE_VTABLE),
    ):
        b.seed_u32(address, value)
    b.seed_floats(NODE + mm.NODE_POS, (*PLAYER.as_tuple(), 1))
    b.seed_floats(TARGET + mm.NODE_POS, (*NATIVE.target.as_tuple(), 1))
    b.seed_floats(CAM + mm.CAM_NATIVE_WORLD, RadiataStoriesAdapter._matrix(NATIVE))
    b.seed_floats(CAM + mm.CAM_FOV, [math.radians(mm.STOCK_FOV_DEG)])
    b.seed_floats(CAM + mm.CAM_FOV_SCALE_X, [xscale, yscale])
    b.seed_floats(CAM + mm.CAM_VIEWPORT_MIN_X, [0])
    b.seed_floats(CAM + mm.CAM_VIEWPORT_MAX_X, [640])
    b.seed_floats(CAM + mm.CAM_FOCAL, [320 * xscale * yscale / math.tan(math.radians(mm.STOCK_FOV_DEG) / 2)])
    for address, stock, _, _, _ in caves.RESOURCES:
        for i, word in enumerate(stock):
            b.seed_u32(address + 4 * i, word)
    return b


@pytest.fixture
def be():
    return seed_field(FakeBackend())


def active_bank(b):
    return mm.MOD_BLOCK + mm.SLOTS[b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def assert_stock(b):
    for address, stock, _, _, _ in caves.RESOURCES:
        assert caves.read_words(b, address, 2) == stock


class CaveMachine:
    """Tiny R5900 subset with inverse/tan/frustum/forward represented as stubs."""
    def __init__(self, backend, camera=CAM):
        self.b = backend
        self.regs = [0] * 32
        self.fpu = [0.0] * 32
        self.regs[m.SP], self.regs[m.S0] = 0x01F00000, camera
        self.regs[31] = (1 << 60) | 0x12345678
        self.calls = []

    def put(self, reg, value):
        if reg:
            self.regs[reg] = value & 0xFFFFFFFF

    def execute(self, word):
        op, rs, rt, rd = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        imm = word & 65535
        signed = imm - 65536 if imm & 32768 else imm
        addr = (self.regs[rs] + signed) & 0xFFFFFFFF
        r, b = self.regs, self.b
        if word == 0:
            return
        if op == 0:
            fn = word & 63
            if fn == 0: self.put(rd, r[rt] << ((word >> 6) & 31))
            elif fn == 2: self.put(rd, (r[rt] & 0xFFFFFFFF) >> ((word >> 6) & 31))
            elif fn in (0x21, 0x2D): self.put(rd, r[rs] + r[rt])
            elif fn == 0x24: self.put(rd, r[rs] & r[rt])
            elif fn == 0x2B: self.put(rd, int((r[rs] & 0xFFFFFFFF) < (r[rt] & 0xFFFFFFFF)))
            else: raise AssertionError(f"unmodelled integer instruction {word:08X}")
        elif op == 0x0F: self.put(rt, imm << 16)
        elif op == 9: self.put(rt, r[rs] + signed)
        elif op == 0x0D: self.put(rt, r[rs] | imm)
        elif op == 0x0C: self.put(rt, r[rs] & imm)
        elif op == 0x0B: self.put(rt, int((r[rs] & 0xFFFFFFFF) < (signed & 0xFFFFFFFF)))
        elif op == 0x23: self.put(rt, b.read_u32(addr))
        elif op == 0x25: self.put(rt, int.from_bytes(b.bytes_at(addr, 2), "little"))
        elif op == 0x2B: b.write_u32(addr, r[rt])
        elif op == 0x1E: r[rt] = int.from_bytes(b.bytes_at(addr, 16), "little")
        elif op == 0x1F: b.seed(addr, r[rt].to_bytes(16, "little"))
        elif op == 0x3F: b.seed(addr, (r[rt] & ((1 << 64) - 1)).to_bytes(8, "little"))
        elif op == 0x37: r[rt] = int.from_bytes(b.bytes_at(addr, 8), "little")
        elif op == 0x31: self.fpu[rt] = b.read_floats(addr, 1)[0]
        elif op == 0x39: b.write_float_block(addr, [self.fpu[rt]])
        elif op == 0x11 and rs == 16 and word & 63 == 0:
            fs, ft, fd = word >> 11 & 31, word >> 16 & 31, word >> 6 & 31
            self.fpu[fd] = struct.unpack("<f", struct.pack("<f", self.fpu[fs] + self.fpu[ft]))[0]
        else: raise AssertionError(f"unmodelled instruction {word:08X}")

    def native(self, target):
        if target == mm.FUN_INVERSE:
            self.calls.append(("inverse", self.regs[m.A0], self.regs[m.A1],
                               self.b.read_floats(self.regs[m.A1], 16)))
        elif target == mm.FUN_TAN:
            self.calls.append(("tan", self.fpu[12]))
            self.fpu[0] = math.tan(self.fpu[12])
        elif target == mm.FUN_FRUSTUM:
            self.calls.append(("frustum", self.regs[m.A0],
                               self.b.read_floats(self.regs[m.A0] + mm.CAM_NATIVE_WORLD, 16)))
        elif target == mm.FUN_FORWARD:
            matrix = self.b.read_floats(self.regs[m.A1] + mm.CAM_NATIVE_WORLD, 16)
            self.b.write_float_block(self.regs[m.A0], [matrix[2], matrix[6], matrix[10], 1])
            self.calls.append(("forward", self.regs[m.A1]))
        else:
            raise AssertionError(f"unexpected native boundary {target:08X}")

    def run(self, address):
        pc = address
        saved_ra = self.regs[31]
        for _ in range(2000):
            word = self.b.read_u32(pc)
            op = word >> 26
            if op in (2, 3, 4, 5) or word == 0x03E00008:
                rs, rt = word >> 21 & 31, word >> 16 & 31
                imm = word & 65535
                signed = imm - 65536 if imm & 32768 else imm
                dest = (word & 0x3FFFFFF) << 2 if op in (2, 3) else pc + 4 + 4 * signed
                take = self.regs[rs] == self.regs[rt] if op == 4 else self.regs[rs] != self.regs[rt]
                if op == 3: self.regs[31] = pc + 8
                self.execute(self.b.read_u32(pc + 4))
                if word == 0x03E00008:
                    assert self.regs[31] == saved_ra
                    return
                if op in (2, 3):
                    self.native(dest)
                    if op == 2: return
                    pc += 8
                else:
                    pc = dest if take else pc + 8
            else:
                self.execute(word)
                pc += 4
        raise AssertionError("generated cave did not finish")

    def view(self):
        self.regs[m.A0], self.regs[m.A1] = 0x01EF0000, self.regs[m.S0] + mm.CAM_NATIVE_WORLD
        self.run(mm.VIEW_CAVE)

    def tan(self, native_half=0.2):
        self.fpu[12] = native_half
        self.run(mm.FOV_CAVE)
        return self.calls[-1][1]

    def finish(self):
        self.regs[m.A0] = self.regs[m.S0]
        self.run(mm.FINISH_CAVE)

    def movement(self, record=RECORDS, camera=CAM):
        self.regs[m.A0], self.regs[m.A1], self.regs[m.S0] = 0x01EE0000, camera, record
        self.run(mm.MOVE_CAVE)
        return self.b.read_floats(self.regs[m.A0], 4)


@pytest.mark.parametrize("serial,crc,matched", [
    (mm.GAME_ID, mm.DISC_CRC, True),
    (" slpm-65800 ", " ac73005e ", True),
    (mm.GAME_ID, "DEADBEEF", False), ("SLPS-25377", mm.DISC_CRC, False), ("", "", False),
])
def test_identity_requires_both_verified_serial_and_crc(serial, crc, matched):
    b = FakeBackend(serial, crc)
    assert RadiataStoriesAdapter(b).identify().matched is matched
    assert not b.writes


def test_player_alias_lookup_follows_record_ownership_not_fixed_slot():
    b = seed_field(FakeBackend(), player_slot=3)
    adapter = RadiataStoriesAdapter(b)
    assert adapter.read_player().as_tuple() == pytest.approx(PLAYER.as_tuple())
    assert adapter._actor(SCENE)[:3] == (3, 1, NODE)
    assert not b.writes


@pytest.mark.parametrize("address,value", [
    (mm.FIELD_MANAGER_PTR, 0), (FIELD + mm.FIELD_OWNER, 0), (OWNER + mm.OWNER_CAMERA, 0),
    (CAM, 0x12345678), (TARGET, 0), (RENDERER + mm.RENDERER_CAMERA, CAM + 0x1000),
    (SCENE + 0x10, 1), (SCENE + 0x1C, 8), (SCENE + mm.PLAYER_ID, 0),
    (MANAGER + mm.ACTOR_COUNT, 0), (MANAGER + mm.ACTOR_COUNT, 197),
    (MANAGER + mm.ACTOR_RECORDS, 0), (RECORDS + mm.ACTOR_OBJECT, 0),
    (RECORDS + mm.ACTOR_NODE, 0), (NODE, 0),
    (RECORDS + mm.ACTOR_STRIDE + mm.ACTOR_ID, 1),
])
def test_host_scene_guard_refuses_unknown_ownership_flags_and_aliases_without_writes(be, address, value):
    be.seed_u32(address, value)
    adapter = RadiataStoriesAdapter(be)
    assert not adapter.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 1e7])
def test_invalid_actor_geometry_is_refused(be, bad):
    be.seed_floats(NODE + mm.NODE_POS, [bad, 950, -4200, 1])
    adapter = RadiataStoriesAdapter(be)
    assert not adapter.read_scene().valid
    with pytest.raises(caves.PatchConflict): adapter.set_patch(True)
    assert not be.writes


def test_homogeneous_position_and_duplicate_ids_are_not_trusted(be):
    be.seed_floats(NODE + mm.NODE_POS + 12, [0])
    assert not RadiataStoriesAdapter(be).read_scene().valid
    assert not be.writes


@pytest.mark.parametrize("xscale,yscale", [(1, 1), (.8, 1.2), (1.4, .75)])
def test_horizontal_fov_reads_actual_focal_and_converts_native_angle(xscale, yscale):
    b = seed_field(FakeBackend(), xscale=xscale, yscale=yscale)
    ad = RadiataStoriesAdapter(b)
    expected = math.degrees(2 * math.atan(math.tan(math.radians(mm.STOCK_FOV_DEG) / 2) / (xscale * yscale)))
    assert ad.read_fov_deg() == pytest.approx(expected, abs=1e-4)
    assert ad.capture_original_fov() == pytest.approx(expected, abs=1e-4)
    ad.write_fov_deg(60)
    assert b.read_floats(active_bank(b) + mm.SLOT_HALF_FOV, 1)[0] == pytest.approx(
        math.atan(xscale * yscale * math.tan(math.radians(30))))
    assert b.read_floats(CAM + mm.CAM_FOV, 1)[0] == pytest.approx(math.radians(mm.STOCK_FOV_DEG))


@pytest.mark.parametrize("address,values", [
    (CAM + mm.CAM_VIEWPORT_MAX_X, [0]), (CAM + mm.CAM_FOV_SCALE_X, [0]),
    (CAM + mm.CAM_FOV_SCALE_Y, [float("nan")]),
])
def test_invalid_lens_inputs_make_scene_invalid(be, address, values):
    be.seed_floats(address, values)
    assert not RadiataStoriesAdapter(be).read_scene().valid
    assert not be.writes


@pytest.mark.parametrize("yaw,pitch,distance", [(0, 20, 1500), (90, 35, 2000), (270, -20, 300), (720, 80, 5000)])
def test_orbit_bank_independent_offsets_do_not_subtract_a_stale_actor(be, yaw, pitch, distance):
    ad = RadiataStoriesAdapter(be)
    position, target = Vec3(40, 20, -30), Vec3(5, -90, 7)
    ad.write_orbit_params(Vec3(9000, 8000, 7000), yaw, pitch, distance,
                          pos_offset=position, target_offset=target)
    expected = orbit_pose(target, math.radians(yaw), math.radians(pitch), distance)
    pose = CameraPose(expected.eye + position, expected.target)
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == pytest.approx(ad._matrix(pose))
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 4) == pytest.approx((*target.as_tuple(), 1))
    assert be.read_u32(active_bank(be) + mm.SLOT_ACTOR_ID) == 1
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT


@pytest.mark.parametrize("yaw,pitch,distance,expected_pitch,expected_distance", [
    (0, -90, 1, -25, 150), (90, 95, 10000, 89.5, 6000),
])
def test_native_boundary_clamps_only_verified_pitch_distance_limits(be, yaw, pitch, distance, expected_pitch, expected_distance):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, yaw, pitch, distance, target_offset=Vec3(0, 0, 0))
    expected = orbit_pose(Vec3(0, 0, 0), math.radians(yaw), math.radians(expected_pitch), expected_distance)
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == pytest.approx(ad._matrix(expected))


@pytest.mark.parametrize("kind", ["centre", "position", "target", "yaw", "pitch", "distance", "fov"])
def test_nonfinite_requests_never_write_guest_memory(be, kind):
    ad = RadiataStoriesAdapter(be)
    vals = dict(centre=PLAYER, yaw_deg=0, pitch_deg=20, distance=1500,
                pos_offset=Vec3(0, 0, 0), target_offset=Vec3(0, -90, 0))
    if kind == "fov": call = lambda: ad.write_fov_deg(float("nan"))
    else:
        field = {"position": "pos_offset", "target": "target_offset", "yaw": "yaw_deg", "pitch": "pitch_deg"}.get(kind, kind)
        vals[field] = Vec3(float("nan"), 0, 0) if field in ("centre", "pos_offset", "target_offset") else float("inf")
        call = lambda: ad.write_orbit_params(**vals)
    with pytest.raises(ValueError): call()
    assert not be.writes


def test_generated_caves_fit_regions_keep_delays_and_resolve_all_branches():
    assert mm.VIEW_CAVE + 4 * len(caves.VIEW_WORDS) <= mm.FOV_CAVE
    assert mm.FOV_CAVE + 4 * len(caves.FOV_WORDS) <= mm.FINISH_CAVE
    assert mm.FINISH_CAVE + 4 * len(caves.FINISH_WORDS) <= mm.MOD_BLOCK
    assert mm.MOD_BLOCK + mm.BLOCK_SIZE <= mm.MOVE_CAVE
    assert mm.MOVE_CAVE + 4 * len(caves.MOVE_WORDS) <= 0xF2000
    assert mm.SLOTS[0] + 0x80 <= mm.SLOTS[1]
    assert mm.SLOTS[1] + 0x80 <= mm.BLOCK_SIZE
    for _, stock, hook, _, words in caves.RESOURCES:
        assert hook[1] == stock[1]
        for i, word in enumerate(words):
            if word >> 26 in (4, 5):
                off = word & 65535
                off = off - 65536 if off & 32768 else off
                assert 0 <= i + 1 + off < len(words)


@pytest.mark.parametrize("site", range(len(caves.RESOURCES)))
@pytest.mark.parametrize("resource", ["hook", "delay", "cave"])
def test_entire_hook_transaction_preflights_before_any_write(be, site, resource):
    address, _, _, cave, words = caves.RESOURCES[site]
    bad = address if resource == "hook" else address + 4 if resource == "delay" else cave + (len(words) - 1) * 4
    be.seed_u32(bad, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): RadiataStoriesAdapter(be).set_patch(True)
    assert not be.writes


@pytest.mark.parametrize("address", [mm.MOD_BLOCK, mm.MOD_BLOCK + mm.BLOCK_SIZE - 4])
def test_occupied_control_block_is_not_overwritten(be, address):
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): RadiataStoriesAdapter(be).set_patch(True)
    assert not be.writes


def test_partial_stock_reload_preflights_movement_cave_before_republishing(be):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 20, 1500)
    be.seed_u32(mm.MOVE_HOOK, mm.MOVE_STOCK[0])
    be.seed_u32(mm.MOVE_CAVE, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict, match="occupied"):
        ad.write_orbit_params(PLAYER, 180, 20, 1500)
    assert not be.writes


def test_bank_published_before_flags_and_cleanup_hook_connected_before_entry(be):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    writes = [a for a, _ in be.writes]
    slot_i = writes.index(mm.MOD_BLOCK + mm.MB_SLOT)
    flags_i = writes.index(mm.MOD_BLOCK + mm.MB_FLAGS)
    assert max(i for i, a in enumerate(writes) if active_bank(be) <= a < active_bank(be) + 0x60) < slot_i < flags_i
    assert writes.index(mm.FINISH_HOOK) < writes.index(mm.FOV_HOOK) < writes.index(mm.VIEW_HOOK)
    be.writes.clear()
    caves.install(be)
    assert not be.writes


def test_guest_uses_latest_actor_translation_and_finish_restores_native_matrix(be):
    ad = RadiataStoriesAdapter(be)
    target, position = Vec3(5, -90, 8), Vec3(30, 20, -10)
    ad.write_orbit_params(PLAYER, 90, 25, 1800, target_offset=target, pos_offset=position)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    fresh = PLAYER + Vec3(200, -50, 300)
    be.seed_floats(NODE + mm.NODE_POS, (*fresh.as_tuple(), 1))
    machine = CaveMachine(be)
    machine.view()
    expected = orbit_pose(target, math.radians(90), math.radians(25), 1800)
    pose = CameraPose(expected.eye + position + fresh, expected.target + fresh)
    assert machine.calls[-1][3] == pytest.approx(ad._matrix(pose))
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == CAM
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == pytest.approx(ad._matrix(pose))
    stack, ra = machine.regs[m.SP], machine.regs[31]
    machine.finish()
    assert machine.calls[-1][0] == "frustum"
    assert machine.calls[-1][2] == pytest.approx(ad._matrix(pose))
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert (machine.regs[m.SP], machine.regs[31]) == (stack, ra)


@pytest.mark.parametrize("address,value", [
    (SCENE + 0x10, 1), (SCENE + 0x1C, 8), (SCENE + mm.PLAYER_ID, 0),
    (SCENE + mm.PLAYER_ID, 2), (RENDERER + mm.RENDERER_CAMERA, CAM + 0x1000),
    (OWNER + mm.OWNER_CAMERA, CAM + 0x1000), (CAM, 0),
    (MANAGER + mm.ACTOR_COUNT, 0), (RECORDS + mm.ACTOR_ID, 9),
    (RECORDS + mm.ACTOR_OBJECT, 0), (RECORDS + mm.ACTOR_NODE, 0), (NODE, 0),
])
def test_guest_rejects_scene_or_stale_ownership_before_render_override(be, address, value):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    be.seed_u32(address, value)
    machine = CaveMachine(be)
    machine.view()
    assert machine.calls[-1][3] == native
    assert machine.tan(.123) == pytest.approx(.123)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == native


def test_fov_only_keeps_native_world_and_snapshots_bank_across_two_publications(be):
    ad = RadiataStoriesAdapter(be)
    ad.write_fov_deg(60)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    old_bank = active_bank(be)
    old_half = be.read_floats(old_bank + mm.SLOT_HALF_FOV, 1)[0]
    machine = CaveMachine(be)
    machine.view()
    assert machine.calls[-1][3] == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_LATCH) == mm.MOD_BLOCK + mm.MB_SNAPSHOT
    ad.write_fov_deg(80)
    assert active_bank(be) != old_bank
    ad.write_fov_deg(100)  # Reuses the original host bank, not the guest snapshot.
    assert active_bank(be) == old_bank
    assert machine.tan(.1) == pytest.approx(old_half)
    machine.finish()
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


@pytest.mark.parametrize('unstable', ['odd', 'changes_during_copy', 'bad_magic'])
def test_guest_rejects_incomplete_or_concurrently_reused_parameter_bank(be, unstable):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    bank = active_bank(be)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    if unstable == 'odd':
        be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif unstable == 'bad_magic':
        be.seed_u32(mm.MOD_BLOCK, 0)
    else:
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                be.seed_u32(address, value + 2)
            return value
        be.read_u32 = changed
    machine = CaveMachine(be)
    machine.view()
    assert machine.calls[-1][3] == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert machine.tan(.123) == pytest.approx(.123)


def test_flags_zero_is_native_pass_through_and_an_existing_transaction_is_not_overwritten(be):
    caves.prepare(be)
    machine = CaveMachine(be)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    machine.view()
    assert machine.calls[-1][3] == native
    RadiataStoriesAdapter(be).set_patch(True)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_PENDING, CAM + 0x1000)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_SAVED_WORLD, 0x12345678)
    machine.view()
    assert machine.calls[-1][3] == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == CAM + 0x1000
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_SAVED_WORLD) == 0x12345678


def test_orbit_fov_release_independently_and_final_restore_returns_all_four_sites(be):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    ad.set_patch(False)
    assert caves.site_state(be) == "applied"
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
    ad.restore_fov()
    assert_stock(be)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == native
    ad.set_patch(True)
    ad.write_fov_deg(60)
    ad.restore_fov()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
    ad.set_patch(False)
    assert_stock(be)


@pytest.mark.parametrize("site", range(len(caves.RESOURCES)))
def test_unknown_release_site_leaves_everything_untouched(be, site):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    be.seed_u32(caves.RESOURCES[site][0], 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict): ad.set_patch(False)
    assert not be.writes


def test_paused_transaction_refuses_cleanup_disconnect_until_the_guest_finishes(be):
    ad = RadiataStoriesAdapter(be)
    ad.set_patch(True)
    machine = CaveMachine(be)
    machine.view()
    with pytest.raises(caves.PatchConflict, match="paused"):
        ad.set_patch(False)
    assert caves.read_words(be, mm.VIEW_HOOK, 2) == mm.VIEW_STOCK
    assert caves.read_words(be, mm.FOV_HOOK, 2) == mm.FOV_STOCK
    assert caves.read_words(be, mm.FINISH_HOOK, 2) == caves.RESOURCES[2][2]
    machine.finish()
    ad.set_patch(False)
    assert_stock(be)


def test_stock_state_reload_republishes_requested_orbit_fov_and_owned_actor(be):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, 75, 35, 2000, target_offset=Vec3(0, -110, 0))
    ad.write_fov_deg(60)
    previous = be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16)
    be.mem = seed_field(FakeBackend(), player_slot=3).mem
    be.writes.clear()
    ad.set_patch(True)
    assert be.read_u32(active_bank(be) + mm.SLOT_ACTOR_INDEX) == 3
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == previous
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV
    ad.set_patch(False)
    ad.restore_fov()
    assert_stock(be)


def test_guarded_adapter_cannot_publish_or_restore_after_game_switch(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = RadiataStoriesAdapter(guard)
    ad.set_patch(True)
    be.serial, be.disc_crc = "SLPS-25377", "B476ED7A"
    assert guard.verify() == CHANGED
    be.writes.clear()
    with pytest.raises(WriteBlocked): ad.set_patch(True)
    with pytest.raises(WriteBlocked): ad.set_patch(False)
    assert not be.writes


def test_runtime_dispatch_restore_and_abandon_respect_real_adapter_boundaries(be):
    ad = RadiataStoriesAdapter(be)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, look_height=-90, distance=1500,
                                          pos_offset=[1, 2, 3], target_offset=[4, 5, 6]))
    rt._tick(.01, None)
    assert not rt.stats.last_error
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3) == [4, -85, 6]
    rt.restore()
    assert_stock(be)
    ad.set_patch(True)
    be.writes.clear()
    rt.abandon()
    assert not be.writes
    assert caves.site_state(be) == "applied"


@pytest.mark.parametrize("yaw", [0, 90, 180, -90, 45, -135])
@pytest.mark.parametrize("position", [Vec3(0, 0, 0), Vec3(700, -20, -450)])
def test_movement_getter_uses_actual_offset_forward_before_any_render(be, yaw, position):
    ad = RadiataStoriesAdapter(be)
    target = Vec3(40, -90, 25)
    ad.write_orbit_params(PLAYER, yaw, 30, 1500, pos_offset=position, target_offset=target)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    expected_pose = orbit_pose(target, math.radians(yaw), math.radians(30), 1500)
    expected_pose = CameraPose(expected_pose.eye + position, expected_pose.target)
    direction = expected_pose.target - expected_pose.eye
    forward = direction.scaled(1 / direction.length())
    machine = CaveMachine(be)
    # Getter must not depend on MB_APPLIED / a previous view transaction.
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    result = machine.movement()
    assert result == pytest.approx((*forward.as_tuple(), 1))
    assert not machine.calls  # no native getter, tan or render update
    assert be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16) == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    # Exactly the original consumer's atan2(z,x) -> 3pi/2-angle conversion.
    actual_yaw = (1.5 * math.pi - math.atan2(result[2], result[0])) % math.tau
    expected_yaw = (1.5 * math.pi - math.atan2(forward.z, forward.x)) % math.tau
    assert actual_yaw == pytest.approx(expected_yaw, abs=1e-6)


@pytest.mark.parametrize("address,value", [
    (mm.MOD_BLOCK, 0), (mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_FOV),
    (SCENE + 0x10, 1), (SCENE + 0x1C, 8), (SCENE + mm.PLAYER_ID, 0),
    (SCENE + mm.PLAYER_ID, 2), (mm.FIELD_MANAGER_PTR, 0),
    (FIELD + mm.FIELD_OWNER, 0), (OWNER + mm.OWNER_CAMERA, CAM + 0x1000),
    (CAM, 0), (mm.RENDERER_PTR, 0), (RENDERER + mm.RENDERER_CAMERA, CAM + 0x1000),
    (mm.ACTOR_MANAGER_PTR, 0), (MANAGER + mm.ACTOR_COUNT, 0),
    (MANAGER + mm.ACTOR_COUNT, mm.ACTOR_LIMIT + 1), (MANAGER + mm.ACTOR_RECORDS, 0),
    (RECORDS + mm.ACTOR_ID, 9), (RECORDS + mm.ACTOR_OBJECT, 0),
    (RECORDS + mm.ACTOR_NODE, 0), (NODE, 0),
])
def test_movement_getter_guards_fall_back_without_persistent_writes(be, address, value):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 20, 1500)
    native = be.read_floats(CAM + mm.CAM_NATIVE_WORLD, 16)
    be.seed_u32(address, value)
    be.writes.clear()
    machine = CaveMachine(be)
    assert machine.movement() == pytest.approx((native[2], native[6], native[10], 1))
    assert machine.calls == [("forward", CAM)]
    assert all(0x01EE0000 <= a < 0x01EE0010 for a, _ in be.writes)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


def test_movement_rejects_other_actor_and_accepts_relocated_player_record():
    b = seed_field(FakeBackend(), player_slot=3)
    ad = RadiataStoriesAdapter(b)
    ad.write_orbit_params(PLAYER, 90, 20, 1500)
    machine = CaveMachine(b)
    machine.movement(RECORDS)
    assert machine.calls == [("forward", CAM)]
    machine.calls.clear()
    result = machine.movement(RECORDS + 3 * mm.ACTOR_STRIDE)
    assert result[0] < -.9 and abs(result[2]) < 1e-6
    assert not machine.calls


@pytest.mark.parametrize("unstable", ["odd", "changed", "wrong_slot_id", "bad_index", "fov_bank", "disable_during_read"])
def test_movement_bank_is_consistent_or_falls_back_to_native(be, unstable):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 20, 1500)
    bank = active_bank(be)
    if unstable == "odd": be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif unstable == "wrong_slot_id": be.seed_u32(bank + mm.SLOT_ACTOR_ID, 2)
    elif unstable == "bad_index": be.seed_u32(bank + mm.SLOT_ACTOR_INDEX, 2)
    elif unstable == "fov_bank": be.seed_u32(bank + mm.SLOT_FLAGS, mm.FLAG_FOV)
    else:
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                if unstable == "changed": be.seed_u32(address, value + 2)
                else: be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
            return value
        be.read_u32 = changed
    machine = CaveMachine(be)
    machine.movement()
    assert machine.calls == [("forward", CAM)]


def test_movement_getter_preserves_arguments_saved_registers_ra_and_fpu(be):
    ad = RadiataStoriesAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 25, 1500)
    machine = CaveMachine(be)
    for reg in range(m.S0, m.S4 + 1):
        machine.regs[reg] = (1 << 100) | (reg << 60) | 0x12345678
    machine.regs[m.S0] = RECORDS
    machine.regs[m.A0], machine.regs[m.A1] = 0x01EE0000, CAM
    machine.fpu = [i + .125 for i in range(32)]
    before = list(machine.regs)
    fpu = list(machine.fpu)
    be.writes.clear()
    machine.run(mm.MOVE_CAVE)
    clobbered = set(range(m.T0, m.T7 + 1))
    assert all(value == before[i] for i, value in enumerate(machine.regs) if i not in clobbered)
    assert machine.fpu == fpu
    assert len(be.writes) == 4 and all(0x01EE0000 <= addr < 0x01EE0010 for addr, _ in be.writes)


def test_fov_only_and_orbit_release_use_native_movement_without_camera_mutation(be):
    ad = RadiataStoriesAdapter(be)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    machine.movement()
    assert machine.calls == [("forward", CAM)]
    ad.write_orbit_params(PLAYER, 90, 25, 1500)
    machine.calls.clear()
    machine.movement()
    assert not machine.calls
    ad.set_patch(False)
    assert caves.site_state(be) == "applied"  # FOV still owns the render hooks
    machine.movement()
    assert machine.calls == [("forward", CAM)]
    ad.restore_fov()
    assert_stock(be)


def test_metadata_and_native_input_noop_are_explicit(be):
    ad = RadiataStoriesAdapter(be)
    assert ad.name == "RADIATA" and ad.display_name_key == "game.radiata"
    assert ad.accepts_orbit_offsets and not ad.uses_offset_injection
    assert ad.features == dict(orbit=True, free_camera=False, fov=True,
                               position_offsets=True, target_offsets=True, per_frame_write=False)
    assert ad.PITCH_DISPLAY_SIGN == ad.PITCH_INPUT_SIGN == 1
    assert ad.default_settings() == dict(distance=1500, look_height=-90, pitch_deg=20,
                                         yaw_deg=180, fov_deg=mm.STOCK_FOV_DEG)
    ad.set_stick_block(True)
    ad.set_stick_block(False)
    assert not be.writes
