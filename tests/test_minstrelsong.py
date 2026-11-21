"""Minstrel Song contracts on synthetic sparse memory, never emulator/game data.

The tiny interpreter checks only emitted R5900 instructions and modeled native
call boundaries. It does not establish render correctness, PS2 scheduling, or
coverage of unverified gameplay scenes. FakeBackend and seed_field are shared
with GUI contract tests.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.minstrelsong import caves, memory_map as mm
from adapters.minstrelsong.adapter import MinstrelSongAdapter
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from tests.test_druaga import FakeBackend as ByteBackend

PLAYER = Vec3(10.0, 2.0, -5.0)
NATIVE = CameraPose(Vec3(8.0, -2.0, -12.0), Vec3(10.0, 0.5, -5.0))


class FakeBackend(ByteBackend):
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)

    def title(self):
        return "Romancing SaGa -Minstrel Song-"

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]


def seed_field(b):
    """Seed a verified-shape ordinary field with entirely invented geometry."""
    b.seed_u32(mm.CAM_MODE, 2)
    for address, value in (*mm.EXACT_GUARDS, *((p, 0) for p in mm.ZERO_GUARDS)):
        b.seed_u32(address, value)
    b.seed_floats(mm.PLAYER, (*PLAYER.as_tuple(), 1.0))
    b.seed_floats(mm.PLAYER_HEADING, (0.75,))
    b.seed_floats(mm.CAM_EYE, (*NATIVE.eye.as_tuple(), 0.0))
    b.seed_floats(mm.CAM_TARGET, (*NATIVE.target.as_tuple(), 2.0))
    b.seed_floats(mm.CAM_UP, (0.0, 1.0, 0.0, 0.0))
    b.seed_floats(mm.CAM_TRANSLATE, (0.0, 0.0, 0.0, 0.0))
    b.seed_floats(mm.CAM_NATIVE_FOCAL, (mm.STOCK_FOCAL,))
    b.seed_floats(mm.PROJECTION, (mm.STOCK_FOCAL,))
    b.seed_floats(mm.PROJECTION_Y, (mm.STOCK_FOCAL * mm.PROJECTION_Y_RATIO,))
    yaw, distance = native_angles(NATIVE)
    b.seed_floats(mm.CAM_YAW, (yaw, distance, yaw, distance))
    for address, stock, _, _, _ in caves.RESOURCES:
        for i, word in enumerate(stock):
            b.seed_u32(address + 4 * i, word)
    return b


def native_angles(pose):
    v = pose.eye - pose.target
    return math.atan2(v.x, v.z), v.length()


@pytest.fixture
def be():
    return seed_field(FakeBackend())


def active_bank(b):
    return mm.MOD_BLOCK + mm.SLOTS[b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


class CaveMachine:
    """Only emitted integer/FPU opcodes; native calls are explicit pure stubs."""
    def __init__(self, backend):
        self.b = backend
        self.regs = [0] * 32
        self.fpu = [0.0] * 32
        self.regs[m.SP] = 0x01F00000
        self.regs[31] = (1 << 60) | 0x12345678
        for r in range(16, 24):
            self.regs[r] = (1 << 100) | r
        self.regs[m.T0] = 0x12345678  # fifth argument, not available as cave scratch
        self.calls = []

    def put(self, reg, value):
        if reg:
            self.regs[reg] = value & 0xFFFFFFFF

    def execute(self, word):
        op, rs, rt, rd = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31
        imm = word & 65535
        signed = imm - 65536 if imm & 32768 else imm
        r, b = self.regs, self.b
        addr = (r[rs] + signed) & 0xFFFFFFFF
        if not word:
            return
        if op == 0:
            fn = word & 63
            if fn == 0: self.put(rd, r[rt] << (word >> 6 & 31))
            elif fn in (0x21, 0x2D): self.put(rd, r[rs] + r[rt])
            elif fn == 0x24: self.put(rd, r[rs] & r[rt])
            else: raise AssertionError(f'unmodeled integer {word:08X}')
        elif op == 0x0F: self.put(rt, imm << 16)
        elif op == 9: self.put(rt, r[rs] + signed)
        elif op == 0x0B: self.put(rt, int((r[rs] & 0xFFFFFFFF) < (signed & 0xFFFFFFFF)))
        elif op == 0x0D: self.put(rt, r[rs] | imm)
        elif op == 0x0C: self.put(rt, r[rs] & imm)
        elif op == 0x23: self.put(rt, b.read_u32(addr))
        elif op == 0x2B: b.write_u32(addr, r[rt])
        elif op == 0x3F: b.seed(addr, (r[rt] & ((1 << 64) - 1)).to_bytes(8, 'little'))
        elif op == 0x37: r[rt] = int.from_bytes(b.bytes_at(addr, 8), 'little')
        elif op == 0x31: self.fpu[rt] = b.read_floats(addr, 1)[0]
        elif op == 0x39: b.write_float_block(addr, [self.fpu[rt]])
        elif op == 0x11 and rs == 4:
            self.fpu[rd] = struct.unpack('<f', struct.pack('<I', r[rt] & 0xFFFFFFFF))[0]
        elif op == 0x11 and rs == 16:
            fs, ft, fd, fn = word >> 11 & 31, word >> 16 & 31, word >> 6 & 31, word & 63
            if fn == 0: self.fpu[fd] = f32(self.fpu[fs] + self.fpu[ft])
            elif fn == 2: self.fpu[fd] = f32(self.fpu[fs] * self.fpu[ft])
            else: raise AssertionError(f'unmodeled float {word:08X}')
        else:
            raise AssertionError(f'unmodeled opcode {word:08X}')

    def native(self, address):
        b, r = self.b, self.regs
        if address == mm.FUN_LOOK_AT:
            self.calls.append(('lookat', r[m.A0], r[m.A1], r[m.A2], r[m.A3], r[m.T0],
                               b.read_floats(r[m.A1], 4), b.read_floats(r[m.A2], 4)))
        elif address == mm.FUN_ANGLES:
            eye, target = b.read_floats(r[m.A0], 3), b.read_floats(r[m.A1], 3)
            pose = CameraPose(Vec3(*eye), Vec3(*target))
            yaw, distance = native_angles(pose)
            self.calls.append(('angles', tuple(eye), tuple(target), r[m.T0]))
            b.write_float_block(r[m.A0] + 0x14, [yaw])
            self.fpu[0] = f32(distance)
        elif address == mm.FUN_SET_PROJECTION:
            self.calls.append(('projection', r[m.A0], r[m.A1], r[m.A2], r[m.A3], r[m.T0],
                               b.read_f32(mm.PROJECTION), b.read_f32(mm.PROJECTION_Y)))
        else:
            raise AssertionError(f'unexpected native boundary {address:08X}')

    def run(self, address):
        pc, initial_ra = address, self.regs[31]
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
                    assert self.regs[31] == initial_ra
                    return
                if op in (2, 3):
                    self.native(dest)
                    if op == 2:
                        assert self.regs[31] == initial_ra
                        return
                    pc += 8
                else:
                    pc = dest if take else pc + 8
            else:
                self.execute(word)
                pc += 4
        raise AssertionError('cave did not return')

    def camera(self):
        self.regs[m.A0], self.regs[m.A1] = mm.CAM_VIEW, mm.CAM_EYE
        self.regs[m.A2], self.regs[m.A3] = mm.CAM_TARGET, mm.CAM_UP
        self.run(mm.CAMERA_CAVE)
        return self.calls[-1]

    def angles(self):
        temp = 0x01EF0000
        self.b.seed_floats(temp, self.b.read_floats(mm.CAM_EYE, 4))
        self.regs[m.A0], self.regs[m.A1] = temp, mm.CAM_TARGET
        self.run(mm.ANGLE_CAVE)
        # The verified stock caller stores these two outputs after cave return.
        yaw, distance = self.b.read_f32(temp + 0x14), self.fpu[0]
        self.b.write_float_block(mm.CAM_YAW, [yaw, distance])
        return yaw, distance

    def projection(self):
        self.regs[m.A0] = mm.PROJECTION
        self.regs[m.A1], self.regs[m.A2], self.regs[m.A3] = 0x1010, 0x2020, 0x3030
        self.run(mm.FOV_CAVE)
        return self.calls[-1]


def assert_stock(b):
    for address, stock, _, _, _ in caves.RESOURCES:
        assert caves.read_words(b, address, 2) == stock


@pytest.mark.parametrize('serial,crc,matched', [
    (mm.GAME_ID, mm.DISC_CRC, True), (' slpm-65920 ', ' 2b9af3c5 ', True),
    (mm.GAME_ID, 'DEADBEEF', False), ('SLPM-65800', mm.DISC_CRC, False), ('', '', False),
])
def test_identity_requires_serial_and_crc_without_writes(serial, crc, matched):
    b = FakeBackend(serial, crc)
    assert MinstrelSongAdapter(b).identify().matched is matched
    assert not b.writes


def test_seed_helper_reads_native_field_without_writes(be):
    ad = MinstrelSongAdapter(be)
    assert ad.read_player() == PLAYER
    assert ad.read_game_pose() == NATIVE
    assert ad.read_scene().valid
    assert ad.is_field_like(ad.read_scene())
    assert ad.capture_original_fov() == pytest.approx(math.degrees(2 * math.atan(256 / mm.STOCK_FOCAL)))
    assert ad.features['orbit'] and ad.features['fov'] and not ad.features['free_camera']
    assert not be.writes


BAD_GUARDS = ([(mm.CAM_MODE, v) for v in (0, 3, 4, 0x80000001, 0xFFFFFFFF)]
              + [(a, v ^ 1) for a, v in mm.EXACT_GUARDS] + [(a, 1) for a in mm.ZERO_GUARDS])


def seed_released_legacy(b, monkeypatch):
    # Reconstruct our own shipped mode-2-only assembler, not a state or game binary.
    def old_guard(a, reject):
        for addr, v in ((mm.CAM_MODE, 2), *mm.EXACT_GUARDS, *((p, 0) for p in mm.ZERO_GUARDS)):
            caves._addr(a.emit, m.T2, addr); a.emit(m.lw(m.T2, m.T2, 0))
            caves._addr(a.emit, m.T3, v); a.words.append(('bne', m.T2, m.T3, reject)); a.emit(m.NOP)
    with monkeypatch.context() as mp:
        mp.setattr(caves, '_guard', old_guard)
        for (_, _, _, addr, _), make in zip(caves.RESOURCES, (caves.camera_words, caves.angle_words, caves.fov_words)):
            for i, word in enumerate(make()): b.seed_u32(addr + i*4, word)
    b.seed_u32(mm.MOD_BLOCK, mm.MAGIC)
    b.seed_u32(mm.MOD_BLOCK + mm.MB_NATIVE_VALID, 1)


@pytest.mark.parametrize('mode', [1, 2])
def test_released_old_state_to_working_orbit_and_back(be, monkeypatch, mode):
    be.seed_u32(mm.CAM_MODE, mode)
    seed_released_legacy(be, monkeypatch)
    ad = MinstrelSongAdapter(be)
    assert ad.read_scene().valid
    ad.restore_fov(); ad.set_patch(False)
    assert not be.writes
    ad.write_orbit_params(PLAYER, 80, 25, 12)
    ad.write_fov_deg(70)
    machine = CaveMachine(be)
    assert machine.camera()[2:4] == (mm.MOD_BLOCK+mm.MB_RENDER_EYE, mm.MOD_BLOCK+mm.MB_RENDER_TARGET)
    assert machine.angles() == pytest.approx((math.radians(80), 12))
    assert machine.projection()[-2] == pytest.approx(ad._focal(70))
    ad.restore_fov(); ad.set_patch(False)
    assert_stock(be)


@pytest.mark.parametrize('fault', ['hook', 'flags', 'applied', 'lens', 'mixed', 'empty', 'foreign', 'magic'])
def test_legacy_migration_rejects_active_incomplete_or_unowned_without_writes(be, monkeypatch, fault):
    seed_released_legacy(be, monkeypatch)
    _, _, hook, addr, words = caves.RESOURCES[0]
    if fault == 'hook': be.seed_u32(mm.CAMERA_HOOK, hook[0])
    elif fault == 'mixed': be.seed(addr, struct.pack(f'<{len(words)}I', *words))
    elif fault == 'empty': be.seed(addr, bytes(len(words)*4))
    elif fault == 'foreign': be.seed_u32(addr + 4, 0xDEADBEEF)
    elif fault == 'magic': be.seed_u32(mm.MOD_BLOCK, 0)
    else:
        off = {'flags': mm.MB_FLAGS, 'applied': mm.MB_APPLIED, 'lens': mm.MB_PROJ_OWNED}[fault]
        be.seed_u32(mm.MOD_BLOCK + off, 1)
    ad = MinstrelSongAdapter(be)
    for operation in (lambda: ad.set_patch(True), lambda: ad.set_patch(False), lambda: ad.write_fov_deg(60)):
        with pytest.raises(caves.PatchConflict): operation()
    assert not be.writes


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_host_field_guard_rejects_without_writes(be, address, value):
    be.seed_u32(address, value)
    ad = MinstrelSongAdapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    with pytest.raises(caves.PatchConflict): ad.write_fov_deg(70)
    assert not be.writes


@pytest.mark.parametrize('address', [mm.PLAYER, mm.CAM_EYE, mm.CAM_TARGET, mm.CAM_NATIVE_FOCAL])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 1e7])
def test_host_invalid_geometry_and_lens_rejected(be, address, bad):
    be.seed_floats(address, [bad])
    ad = MinstrelSongAdapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_controls_are_refused_before_memory_writes(be, bad):
    ad = MinstrelSongAdapter(be)
    with pytest.raises(ValueError): ad.write_fov_deg(bad)
    with pytest.raises(ValueError): ad.write_orbit_params(PLAYER, bad, 20, 10)
    with pytest.raises(ValueError): ad.write_orbit_params(PLAYER, 90, 20, 10, pos_offset=Vec3(bad, 0, 0))
    assert not be.writes


@pytest.mark.parametrize('yaw,pitch,distance', [(0, 20, 10), (90, -5, 18), (-135, 80, 30)])
def test_camera_uses_latest_actor_relative_offsets_without_touching_native(be, yaw, pitch, distance):
    ad = MinstrelSongAdapter(be)
    target_off, pos_off = Vec3(2, -1.5, 3), Vec3(1, 2, -3)
    ad.write_orbit_params(PLAYER, yaw, pitch, distance, pos_offset=pos_off, target_offset=target_off)
    native = be.bytes_at(mm.CAM_TARGET, 32)
    heading = be.bytes_at(mm.PLAYER_HEADING, 4)
    newest = PLAYER + Vec3(100, -20, 50)
    be.seed_floats(mm.PLAYER, (*newest.as_tuple(), 1))
    machine = CaveMachine(be)
    saved = {r: machine.regs[r] for r in (m.SP, 31, m.T0, *range(16, 24))}
    call = machine.camera()
    rel = orbit_pose(target_off, math.radians(yaw), math.radians(pitch), distance)
    assert call[1] == mm.CAM_VIEW and call[4] == mm.CAM_UP
    assert call[6] == pytest.approx((*(newest + rel.eye + pos_off).as_tuple(), 1), abs=2e-5)
    assert call[7] == pytest.approx((*(newest + target_off).as_tuple(), 1), abs=2e-5)
    assert {r: machine.regs[r] for r in saved} == saved
    assert be.bytes_at(mm.CAM_TARGET, 32) == native
    assert be.bytes_at(mm.PLAYER_HEADING, 4) == heading
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == mm.FLAG_ORBIT
    assert ad.heartbeat_word() == 1
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(call[6][:3])


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_guest_guards_pass_native_camera_angles_and_projection(be, address, value):
    ad = MinstrelSongAdapter(be)
    ad.write_orbit_params(PLAYER, 80, 25, 12)
    ad.write_fov_deg(70)
    be.seed_u32(address, value)
    machine = CaveMachine(be)
    call = machine.camera()
    assert (call[2], call[3]) == (mm.CAM_EYE, mm.CAM_TARGET)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert machine.angles() == pytest.approx(native_angles(NATIVE))
    assert len([c for c in machine.calls if c[0] == 'angles']) == 1
    result = machine.projection()
    assert result[-2:] == pytest.approx((mm.STOCK_FOCAL, mm.STOCK_FOCAL * mm.PROJECTION_Y_RATIO), abs=1e-4)


@pytest.mark.parametrize('unstable', ['odd', 'changes_during_copy', 'bad_magic', 'no_flags', 'slot_flags'])
def test_guest_rejects_unstable_bank_for_camera_and_fov(be, unstable):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(75)
    bank = active_bank(be)
    if unstable == 'odd': be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif unstable == 'bad_magic': be.seed_u32(mm.MOD_BLOCK, 0)
    elif unstable == 'no_flags': be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    elif unstable == 'slot_flags': be.seed_u32(bank + mm.SLOT_FLAGS, 0)
    else:
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE:
                be.seed_u32(address, value + 2)
            return value
        be.read_u32 = changed
    machine = CaveMachine(be)
    assert machine.camera()[2:4] == (mm.CAM_EYE, mm.CAM_TARGET)
    assert machine.projection()[-2] == pytest.approx(mm.STOCK_FOCAL)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0


def test_angle_uses_accepted_camera_snapshot_across_two_host_publications(be):
    ad = MinstrelSongAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 30, 12)
    machine = CaveMachine(be)
    call = machine.camera()
    accepted = CameraPose(Vec3(*call[6][:3]), Vec3(*call[7][:3]))
    ad.write_orbit_params(PLAYER, -90, 50, 30)
    ad.write_orbit_params(PLAYER, 0, 15, 20)
    # A separate FOV snapshot must not change this frame's accepted camera.
    ad.write_fov_deg(80)
    machine.projection()
    saved = {r: machine.regs[r] for r in (m.SP, 31, m.T0, *range(16, 24))}
    assert machine.angles() == pytest.approx(native_angles(accepted), abs=2e-6)
    calls = [c for c in machine.calls if c[0] == 'angles']
    assert len(calls) == 2
    assert calls[0][1:3] == (NATIVE.eye.as_tuple(), NATIVE.target.as_tuple())
    assert calls[1][1] == pytest.approx(accepted.eye.as_tuple())
    assert calls[1][2] == pytest.approx(accepted.target.as_tuple())
    assert {r: machine.regs[r] for r in saved} == saved
    assert be.read_f32(mm.MOD_BLOCK + mm.MB_NATIVE_YAW) == pytest.approx(native_angles(NATIVE)[0])
    assert be.read_f32(mm.MOD_BLOCK + mm.MB_NATIVE_DISTANCE) == pytest.approx(NATIVE.distance())
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_NATIVE_VALID) == 1
    assert ad._native_pose() == NATIVE


def test_angle_guard_change_after_camera_acceptance_returns_native(be):
    ad = MinstrelSongAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 30, 12)
    machine = CaveMachine(be)
    machine.camera()
    be.seed_u32(mm.ZERO_GUARDS[0], 1)
    assert machine.angles() == pytest.approx(native_angles(NATIVE))
    assert len([c for c in machine.calls if c[0] == 'angles']) == 1


@pytest.mark.parametrize('requested,clamped', [(10, 20), (60, 60), (140, 110)])
def test_fov_only_changes_projection_and_preserves_native_master(be, requested, clamped):
    ad = MinstrelSongAdapter(be)
    native = be.bytes_at(mm.CAM_TARGET, 32)
    ad.write_fov_deg(requested)
    machine = CaveMachine(be)
    assert machine.camera()[2:4] == (mm.CAM_EYE, mm.CAM_TARGET)
    saved = {r: machine.regs[r] for r in (m.SP, 31, m.T0, *range(16, 24))}
    result = machine.projection()
    focal = mm.HALF_WIDTH / math.tan(math.radians(clamped) / 2)
    assert result[1:6] == (mm.PROJECTION, 0x1010, 0x2020, 0x3030, saved[m.T0])
    assert result[-2:] == pytest.approx((focal, focal * mm.PROJECTION_Y_RATIO), rel=2e-7)
    assert {r: machine.regs[r] for r in saved} == saved
    assert be.read_f32(mm.CAM_NATIVE_FOCAL) == mm.STOCK_FOCAL
    assert be.bytes_at(mm.CAM_TARGET, 32) == native
    assert ad.fov_in_sync(clamped)
    ad.restore_fov()
    assert_stock(be)
    assert be.read_f32(mm.PROJECTION) == mm.STOCK_FOCAL
    assert be.read_f32(mm.PROJECTION_Y) == pytest.approx(mm.STOCK_FOCAL * mm.PROJECTION_Y_RATIO)


def test_projection_restores_own_previous_output_before_recapture(be):
    ad = MinstrelSongAdapter(be)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    machine.projection()
    machine.projection()
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_NATIVE_PROJ, 2) == pytest.approx(
        [mm.STOCK_FOCAL, mm.STOCK_FOCAL * mm.PROJECTION_Y_RATIO])
    # New native lens values supersede our output and become the restore target.
    be.seed_floats(mm.PROJECTION, [400])
    be.seed_floats(mm.PROJECTION_Y, [470])
    machine.projection()
    assert be.read_floats(mm.MOD_BLOCK + mm.MB_NATIVE_PROJ, 2) == [400, 470]
    ad.restore_fov()
    assert (be.read_f32(mm.PROJECTION), be.read_f32(mm.PROJECTION_Y)) == (400, 470)


def test_host_restore_does_not_overwrite_projection_replaced_by_native(be):
    ad = MinstrelSongAdapter(be)
    ad.write_fov_deg(60)
    CaveMachine(be).projection()
    be.seed_floats(mm.PROJECTION, [401])
    be.seed_floats(mm.PROJECTION_Y, [471])
    ad.restore_fov()
    assert (be.read_f32(mm.PROJECTION), be.read_f32(mm.PROJECTION_Y)) == (401, 471)


@pytest.mark.parametrize('order', ['orbit_first', 'fov_first'])
def test_orbit_and_fov_release_independently(be, order):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    machine.camera()
    machine.angles()
    machine.projection()
    if order == 'orbit_first':
        ad.set_patch(False)
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
        assert caves.site_state(be) == 'applied'
        assert CaveMachine(be).camera()[2:4] == (mm.CAM_EYE, mm.CAM_TARGET)
        ad.restore_fov()
    else:
        ad.restore_fov()
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
        ad.set_patch(False)
    assert_stock(be)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert ad._native_pose() == NATIVE


def test_publish_uses_odd_then_even_sequence_before_flipping_active_bank(be):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    be.writes.clear()
    ad.write_orbit_params(PLAYER, 40, 20, 10)
    bank = active_bank(be)
    writes = [(a, int.from_bytes(data, 'little')) for a, data in be.writes]
    sequence_writes = [(i, value) for i, (a, value) in enumerate(writes) if a == bank + mm.SLOT_SEQUENCE]
    assert len(sequence_writes) == 2
    assert sequence_writes[0][1] & 1 and not sequence_writes[1][1] & 1
    flip = next(i for i, (a, _) in enumerate(writes) if a == mm.MOD_BLOCK + mm.MB_SLOT)
    assert sequence_writes[0][0] < sequence_writes[1][0] < flip
    assert all(bank <= a < bank + mm.SLOT_SIZE for a, _ in writes[:flip])


@pytest.mark.parametrize('kind,index', [('hook', i) for i in range(3)] + [('cave', i) for i in range(3)] + [('magic', 0), ('block', 0)])
def test_unknown_resources_refuse_install_without_any_writes(be, kind, index):
    if kind == 'hook': address = caves.RESOURCES[index][0]
    elif kind == 'cave': address = caves.RESOURCES[index][3]
    elif kind == 'magic': address = mm.MOD_BLOCK
    else: address = mm.MOD_BLOCK + 0x80
    be.seed_u32(address, 0xDEADBEEF)
    ad = MinstrelSongAdapter(be)
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes
    with pytest.raises(caves.PatchConflict): ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('index', range(3))
def test_unknown_active_hook_refuses_release_without_any_writes(be, index):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    be.seed_u32(caves.RESOURCES[index][0], 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict): ad.set_patch(False)
    assert not be.writes


@pytest.mark.parametrize('index', range(3))
@pytest.mark.parametrize('operation', ['orbit', 'fov'])
def test_owned_cave_corruption_blocks_subsequent_publication_without_any_writes(be, index, operation):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    be.seed_u32(caves.RESOURCES[index][3] + 4, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        if operation == 'orbit': ad.write_orbit_params(PLAYER, 90, 20, 10)
        else: ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('index', range(3))
@pytest.mark.parametrize('operation', ['orbit', 'fov'])
def test_active_zeroed_cave_rebuilt_before_parameter_publication(be, index, operation):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    _, _, _, address, words = caves.RESOURCES[index]
    be.seed(address, bytes(len(words) * 4))
    be.writes.clear()
    if operation == 'orbit': ad.write_orbit_params(PLAYER, 90, 20, 10)
    else: ad.write_fov_deg(60)
    assert caves.read_words(be, address, len(words)) == tuple(words)
    assert caves.site_state(be) == 'applied'
    first_parameter = next(i for i, (a, _) in enumerate(be.writes)
                           if any(mm.MOD_BLOCK + slot <= a < mm.MOD_BLOCK + slot + mm.SLOT_SIZE
                                  for slot in mm.SLOTS))
    rebuilt = [(i, a) for i, (a, _) in enumerate(be.writes) if address <= a < address + len(words) * 4]
    assert len(rebuilt) == len(words)
    assert all(i < first_parameter for i, _ in rebuilt)
    machine = CaveMachine(be)
    assert machine.camera()[2] != mm.CAM_EYE
    machine.angles()
    machine.projection()
    ad.set_patch(False)
    if operation == 'fov': ad.restore_fov()
    assert_stock(be)


def test_mixed_stock_owned_hooks_reapply_without_overwriting_delay_slots(be):
    ad = MinstrelSongAdapter(be)
    ad.set_patch(True)
    site, stock, _, _, _ = caves.RESOURCES[1]
    be.seed_u32(site, stock[0])
    be.writes.clear()
    ad.write_orbit_params(PLAYER, 35, 15, 10)
    assert caves.site_state(be) == 'applied'
    assert all(a != address + 4 for a, _ in be.writes for address, _, _, _, _ in caves.RESOURCES)
    ad.set_patch(False)
    assert_stock(be)


def test_orbit_limits_and_eye_offset_do_not_modify_target(be):
    ad = MinstrelSongAdapter(be)
    target = Vec3(3, -2, 4)
    offset = Vec3(1, 2, 3)
    ad.write_orbit_params(PLAYER, 45, 120, 100, pos_offset=offset, target_offset=target)
    expected = orbit_pose(target, math.radians(45), math.radians(ad.PITCH_RANGE[1]), ad.DISTANCE_RANGE[1])
    bank = active_bank(be)
    assert be.read_floats(bank + mm.SLOT_EYE, 3) == pytest.approx((expected.eye + offset).as_tuple())
    assert be.read_floats(bank + mm.SLOT_TARGET, 3) == pytest.approx(target.as_tuple())


def test_restore_native_angles_recomputes_current_rig_not_saved_pose(be):
    ad = MinstrelSongAdapter(be)
    ad.write_orbit_params(PLAYER, 90, 30, 12)
    machine = CaveMachine(be)
    machine.camera()
    machine.angles()
    fresh = CameraPose(Vec3(20, -5, 35), Vec3(18, 0, 45))
    be.seed_floats(mm.CAM_EYE, fresh.eye.as_tuple())
    be.seed_floats(mm.CAM_TARGET, fresh.target.as_tuple())
    ad.set_patch(False)
    yaw, distance = native_angles(fresh)
    assert be.read_floats(mm.CAM_YAW, 4) == pytest.approx([yaw, distance, yaw, distance])
    assert_stock(be)


def test_stock_state_reload_reapplies_preserved_orbit_and_fov(be):
    ad = MinstrelSongAdapter(be)
    ad.write_orbit_params(PLAYER, 75, 35, 12, target_offset=Vec3(0, -1.5, 0))
    ad.write_fov_deg(65)
    expected = be.read_floats(active_bank(be), mm.SLOT_SIZE // 4)[:9]
    be.mem = seed_field(FakeBackend()).mem
    be.writes.clear()
    ad.set_patch(True)
    assert caves.site_state(be) == 'applied'
    assert be.read_floats(active_bank(be), mm.SLOT_SIZE // 4)[:9] == expected
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV
    assert CaveMachine(be).camera()[2] != mm.CAM_EYE
    ad.set_patch(False)
    ad.restore_fov()
    assert_stock(be)


def test_guarded_backend_blocks_publish_and_restore_after_game_change(be):
    from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = MinstrelSongAdapter(guard)
    ad.set_patch(True)
    be.serial, be.disc_crc = 'SLPM-65800', 'AC73005E'
    assert guard.verify() == CHANGED
    be.writes.clear()
    with pytest.raises(WriteBlocked): ad.set_patch(True)
    with pytest.raises(WriteBlocked): ad.set_patch(False)
    assert not be.writes


def test_runtime_dispatch_restore_and_abandon_use_guarded_contract(be):
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT
    ad = MinstrelSongAdapter(be)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, look_height=-1.5, distance=12,
                                        pos_offset=[1, 2, 3], target_offset=[4, 5, 6]))
    rt._tick(.01, None)
    assert not rt.stats.last_error
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3) == [4, 3.5, 6]
    rt.restore()
    assert_stock(be)
    ad.set_patch(True)
    be.writes.clear()
    rt.abandon()
    assert not be.writes
    assert caves.site_state(be) == 'applied'
