"""Druaga adapter tests on a sparse byte backend; no emulator or game binary.

The tiny instruction interpreter models this adapter's generated cave and the two
matrix-builder call boundaries. It checks argument/ownership/branch behaviour,
not rendered output, PS2 timing, or unverified gameplay scenes.
"""
from __future__ import annotations

import math
import struct

import pytest

from adapters.nightmaredruaga import caves, memory_map as mm
from adapters.nightmaredruaga.adapter import DruagaAdapter
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked


ROOT = 0x01F00000
CAM = ROOT + mm.CAMERA_OFFSET
PLAYER_SLOT = 1
PLAYER_RECORD = mm.ENTITY_TABLE + PLAYER_SLOT * mm.ENTITY_STRIDE
PLAYER = Vec3(10.0, 2.0, -5.0)
NATIVE = orbit_pose(PLAYER, math.radians(165.631), math.radians(-40.925), mm.STOCK_DISTANCE)
DUNGEON_ROOT = 0x01E00000
DUNGEON_CAM = DUNGEON_ROOT + mm.DUNGEON_CAMERA_OFFSET
DUNGEON_ACTOR = 0x0072D560
DUNGEON_PLAYER = Vec3(14.0, 50.0, -24.0)
DUNGEON_NATIVE = CameraPose(Vec3(14.0, 57.899, -31.0), Vec3(14.0, 51.5, -24.0))
DUNGEON_COLLISION = Vec3(0.0, 2.598, 4.0)


class FakeBackend:
    """Byte-addressed memory, including unaligned halfwords and write ordering."""

    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        self.mem: dict[int, int] = {}
        self.writes: list[tuple[int, bytes]] = []
        self.reads: list[tuple[int, int]] = []
        self.serial, self.disc_crc = serial, crc
        self.on_write = None

    def game_id(self): return self.serial
    def crc(self): return self.disc_crc
    def title(self): return "THE NIGHTMARE OF DRUAGA"

    def seed(self, address, data):
        self.mem.update((address + i, byte) for i, byte in enumerate(data))

    def bytes_at(self, address, length):
        self.reads.append((address, length))
        return bytes(self.mem.get(address + i, 0) for i in range(length))

    def seed_u32(self, address, value):
        self.seed(address, struct.pack("<I", value & 0xFFFFFFFF))

    def seed_floats(self, address, values):
        values = tuple(values)
        self.seed(address, struct.pack(f"<{len(values)}f", *values))

    def read_u32(self, address):
        return struct.unpack("<I", self.bytes_at(address, 4))[0]

    def write_u32(self, address, value):
        data = struct.pack("<I", value & 0xFFFFFFFF)
        self.writes.append((address, data))
        self.seed(address, data)
        if self.on_write:
            self.on_write(address, data)

    def read_floats(self, address, count):
        return list(struct.unpack(f"<{count}f", self.bytes_at(address, count * 4)))

    def write_float_block(self, address, values):
        for i, value in enumerate(values):
            self.write_u32(address + i * 4, struct.unpack("<I", struct.pack("<f", value))[0])

    write_floats = write_float_block


def projection_for(backend, rad, xscale=1.0, *, cam=CAM):
    """Synthetic native projection builder input/output, not a render test."""
    projection = [0.0] * 16
    projection[0] = 1.0 / math.tan(rad / 2.0)
    projection[11] = 1.0
    backend.seed_floats(cam + mm.CAM_PROJECTION, projection)
    backend.seed_floats(cam + mm.CAM_ASPECT_SCALE_X, [xscale])


def seed_field(backend, *, native_fov_deg=25.0, player_slot=PLAYER_SLOT):
    backend.seed_u32(mm.ROOT_PTR, ROOT)
    backend.seed_u32(mm.CAMERA_PTR, CAM)
    backend.seed_u32(ROOT, mm.ROOT_VTABLE)
    backend.seed_u32(ROOT + 4, 0x00010002)
    backend.seed_u32(CAM, mm.CAMERA_VTABLE)
    backend.seed_u32(mm.GAME_STATE, 2)
    backend.seed_u32(mm.GAME_FLAGS_WORD, 0)
    backend.seed_u32(mm.EVENT_ACTIVE, 0)
    backend.seed_u32(CAM + mm.CAM_MODE, 0)
    backend.seed_u32(ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, CAM + mm.CAM_VIEW)
    record = mm.ENTITY_TABLE + player_slot * mm.ENTITY_STRIDE
    backend.seed_u32(record, 1)
    backend.seed_u32(record + 8, (mm.PLAYER_ID << 16) | 7)
    backend.seed_u32(record + mm.ENTITY_RENDERER, ROOT + mm.RENDERER_OFFSET)
    backend.seed_floats(record + mm.ENTITY_POS, (*PLAYER.as_tuple(), 1.0))
    for offset in (0x230, mm.CAM_NATIVE_EYE, 0x250):
        backend.seed_floats(CAM + offset, (*NATIVE.eye.as_tuple(), 1.0))
    for offset in (0x270, mm.CAM_NATIVE_TARGET, 0x290):
        backend.seed_floats(CAM + offset, (*NATIVE.target.as_tuple(), 1.0))
    forward = (NATIVE.target - NATIVE.eye).scaled(1.0 / NATIVE.distance())
    matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
              *forward.as_tuple(), 0.0, *NATIVE.eye.as_tuple(), 1.0]
    backend.seed_floats(CAM + mm.CAM_WORLD, matrix)
    backend.seed_floats(CAM + mm.CAM_NATIVE_FOV_DEG, [native_fov_deg])
    backend.seed_floats(CAM + mm.CAM_FOV_RAD, [math.radians(native_fov_deg)])
    projection_for(backend, math.radians(native_fov_deg))
    for address, stock, _, _, _ in caves.RESOURCES + caves.MOVEMENT_RESOURCES:
        for i, word in enumerate(stock):
            backend.seed_u32(address + 4 * i, word)
    # Right-input patch sites, when present, are unrelated to the camera hook.
    for site, word in mm.PAD_ACTION_LOADS:
        backend.seed_u32(site, word)
    for i, word in enumerate(mm.PAD_AXIS_STOCK):
        backend.seed_u32(mm.PAD_AXIS_HOOK + i * 4, word)
    return backend


def seed_dungeon_field(backend, *, native_fov_deg=40.0, player_slot=0):
    """Separate root class and native actor ownership, never town's ID1000."""
    seed_field(backend)
    # A fresh dungeon record table need not preserve any town entity identity.
    for slot in range(mm.ENTITY_COUNT):
        backend.seed(mm.ENTITY_TABLE + slot * mm.ENTITY_STRIDE, bytes(mm.ENTITY_STRIDE))
    backend.seed_u32(mm.ROOT_PTR, DUNGEON_ROOT)
    backend.seed_u32(mm.CAMERA_PTR, DUNGEON_CAM)
    backend.seed_u32(DUNGEON_ROOT, mm.DUNGEON_ROOT_VTABLE)
    backend.seed_u32(DUNGEON_ROOT + 4, 0x00020003)
    backend.seed_u32(DUNGEON_CAM, mm.DUNGEON_CAMERA_VTABLE)
    backend.seed_u32(mm.GAME_STATE, 1)
    backend.seed_u32(DUNGEON_CAM + mm.CAM_MODE, 1)
    backend.seed_u32(DUNGEON_CAM + 0x2DC, 0x00000101)  # transition halfword +2DE stays zero
    backend.seed_u32(DUNGEON_ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, DUNGEON_CAM + mm.CAM_VIEW)
    record = mm.ENTITY_TABLE + player_slot * mm.ENTITY_STRIDE
    backend.seed_u32(record, 1)
    backend.seed_u32(record + 8, (mm.DUNGEON_PLAYER_ID << 16) | 0)
    backend.seed_u32(record + mm.ENTITY_RENDERER, DUNGEON_ROOT + mm.RENDERER_OFFSET)
    backend.seed_floats(record + mm.ENTITY_POS, (*DUNGEON_PLAYER.as_tuple(), 1.0))
    backend.seed_u32(mm.DUNGEON_ACTOR_PTR, DUNGEON_ACTOR)
    backend.seed_u32(DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, record + mm.ENTITY_RENDERER)
    backend.seed_floats(DUNGEON_ACTOR + 0x650, (*DUNGEON_PLAYER.as_tuple(), 1.0))
    for offset in (0x230, mm.CAM_NATIVE_EYE):
        backend.seed_floats(DUNGEON_CAM + offset, (*DUNGEON_NATIVE.eye.as_tuple(), 1.0))
    render_eye = DUNGEON_NATIVE.eye + DUNGEON_COLLISION
    backend.seed_floats(DUNGEON_CAM + 0x250, (*render_eye.as_tuple(), 1.0))
    backend.seed_floats(DUNGEON_CAM + 0x2F0, (*DUNGEON_COLLISION.as_tuple(), 1.0))
    for offset in (0x270, mm.CAM_NATIVE_TARGET, 0x290):
        backend.seed_floats(DUNGEON_CAM + offset, (*DUNGEON_NATIVE.target.as_tuple(), 1.0))
    forward = (DUNGEON_NATIVE.target - render_eye)
    forward = forward.scaled(1.0 / forward.length())
    backend.seed_floats(DUNGEON_CAM + mm.CAM_WORLD,
                        [1, 0, 0, 0, 0, 1, 0, 0, *forward.as_tuple(), 0, *render_eye.as_tuple(), 1])
    backend.seed_floats(DUNGEON_CAM + mm.CAM_NATIVE_FOV_DEG, [native_fov_deg])
    backend.seed_floats(DUNGEON_CAM + mm.CAM_FOV_RAD, [math.radians(native_fov_deg)])
    projection_for(backend, math.radians(native_fov_deg), cam=DUNGEON_CAM)
    return backend


@pytest.fixture
def be():
    return seed_field(FakeBackend())


@pytest.fixture
def dungeon_be():
    return seed_dungeon_field(FakeBackend())


def active_bank(backend):
    return mm.MOD_BLOCK + mm.SLOTS[backend.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]


def cave_frame(backend, *, dungeon=False):
    """Execute generated integer/FPU instructions and model native builder calls.

    Town's hook delay slot loads native eye into t0; f0 holds the native
    degree-to-radian conversion. Dungeon reaches its hook after computing the
    native FOV and loading native eye + collision delta into t0 from a stack
    temporary; its delay slot sets a0. R5900 lq/sq preserve all 128 register
    bits. Native calls return immediately after recording a1.
    """
    regs = [0] * 32
    fpu = [0.0] * 32
    regs[m.SP] = 0x001E0000
    saved_s2, saved_s3 = (1 << 110) | 0x1234, (1 << 107) | 0x5678
    regs[18], regs[19] = saved_s2, saved_s3
    cam = DUNGEON_CAM if dungeon else CAM
    regs[m.S1] = cam
    regs[m.V0], regs[m.V1] = cam + 0x240, cam + 0x250
    if dungeon:
        # Before 4B9C04, the native collision-adjusted eye was loaded from the
        # stack. The hook delay slot (addiu a0,s1,10) also executes beforehand.
        regs[m.T0] = int.from_bytes(backend.bytes_at(cam + 0x250, 16), "little")
        regs[m.A0] = cam + mm.CAM_WORLD
        fpu[0] = 12345.0  # dungeon must reload native +1AC, not reuse this scratch
    else:
        regs[m.T0] = int.from_bytes(backend.bytes_at(regs[m.V0], 16), "little")
        fpu[0] = math.radians(backend.read_floats(cam + mm.CAM_NATIVE_FOV_DEG, 1)[0])
    calls = []

    def put(reg, value):
        if reg:
            regs[reg] = value & 0xFFFFFFFF

    def execute(word):
        op, rs, rt, rd = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        imm = word & 65535
        signed = imm - 65536 if imm & 32768 else imm
        address = (regs[rs] + signed) & 0xFFFFFFFF
        if word == 0:
            return
        if op == 0:
            fn = word & 63
            if fn == 0:
                put(rd, regs[rt] << ((word >> 6) & 31))
            elif fn == 2:
                put(rd, (regs[rt] & 0xFFFFFFFF) >> ((word >> 6) & 31))
            elif fn in (0x21, 0x2D):
                put(rd, regs[rs] + regs[rt])
            elif fn in (0x23, 0x2F):
                put(rd, regs[rs] - regs[rt])
            elif fn == 0x24:
                put(rd, regs[rs] & regs[rt])
            elif fn == 0x25:
                put(rd, regs[rs] | regs[rt])
            else:
                raise AssertionError(f"unmodelled R5900 instruction {word:08X}")
        elif op == 0x0F:
            put(rt, imm << 16)
        elif op in (9, 0x19):
            put(rt, regs[rs] + signed)
        elif op == 0x0D:
            put(rt, regs[rs] | imm)
        elif op == 0x0C:
            put(rt, regs[rs] & imm)
        elif op == 0x0B:
            put(rt, int((regs[rs] & 0xFFFFFFFF) < (signed & 0xFFFFFFFF)))
        elif op == 0x23:
            put(rt, backend.read_u32(address))
        elif op == 0x25:
            put(rt, int.from_bytes(backend.bytes_at(address, 2), "little"))
        elif op == 0x2B:
            backend.write_u32(address, regs[rt])
        elif op == 0x1E:
            regs[rt] = int.from_bytes(backend.bytes_at(address, 16), "little")
        elif op == 0x1F:
            backend.seed(address, regs[rt].to_bytes(16, "little"))
        elif op == 0x31:
            fpu[rt] = backend.read_floats(address, 1)[0]
        elif op == 0x39:
            backend.write_float_block(address, [fpu[rt]])
        elif op == 0x11 and ((word >> 21) & 31) == 16 and (word & 63) == 0:
            fs, ft, fd = (word >> 11) & 31, (word >> 16) & 31, (word >> 6) & 31
            fpu[fd] = struct.unpack("<f", struct.pack("<f", fpu[fs] + fpu[ft]))[0]
        else:
            raise AssertionError(f"unmodelled R5900 instruction {word:08X}")

    pc = mm.DUNGEON_CAVE if dungeon else mm.CAVE
    for _ in range(1000):
        word = backend.read_u32(pc)
        op = word >> 26
        if op in (2, 3, 4, 5):
            rs, rt = (word >> 21) & 31, (word >> 16) & 31
            imm = word & 65535
            signed = imm - 65536 if imm & 32768 else imm
            take = (regs[rs] == regs[rt]) if op == 4 else (regs[rs] != regs[rt])
            destination = ((word & 0x3FFFFFF) << 2) if op in (2, 3) else pc + 4 + 4 * signed
            execute(backend.read_u32(pc + 4))
            if op == 3:
                args = tuple(backend.read_floats(regs[m.A1], 4))
                calls.append((destination, regs[m.A0], regs[m.A1], args))
                if destination == mm.FUN_TRANSLATE:
                    backend.seed_floats(regs[m.A0] + 0x30, args)
                elif destination == mm.FUN_LOOK_AT:
                    eye = Vec3(*backend.read_floats(regs[m.A0] + 0x30, 3))
                    delta = Vec3(*args[:3]) - eye
                    backend.seed_floats(regs[m.A0] + 0x20,
                                        (*delta.scaled(1 / delta.length()).as_tuple(), 0.0))
                else:
                    raise AssertionError(f"unexpected cave call {destination:08X}")
                pc += 8
            elif op == 2:
                assert destination == (mm.DUNGEON_RETURN if dungeon else mm.CAM_RETURN)
                assert regs[m.SP] == 0x001E0000
                assert (regs[18], regs[19]) == (saved_s2, saved_s3)
                return calls
            else:
                pc = destination if take else pc + 8
        else:
            execute(word)
            pc += 4
    raise AssertionError("generated cave did not return")


@pytest.mark.parametrize("serial,crc,matched", [
    (mm.GAME_ID, mm.DISC_CRC, True),
    (f" {mm.GAME_ID.lower()} ", f" {mm.DISC_CRC.lower()} ", True),
    (mm.GAME_ID, "DEADBEEF", False),
    ("SLPS-00000", mm.DISC_CRC, False),
    ("", "", False),
])
def test_identify_requires_the_verified_serial_and_crc(serial, crc, matched):
    backend = FakeBackend(serial, crc)
    info = DruagaAdapter(backend).identify()
    assert info.matched is matched
    assert not backend.writes


def test_identify_transport_failure_is_read_only(be):
    def fail():
        raise OSError("synthetic disconnect")
    be.crc = fail
    info = DruagaAdapter(be).identify()
    assert not info.matched and "disconnect" in info.reason
    assert not be.writes


@pytest.mark.parametrize("address,value", [
    (mm.ROOT_PTR, 0), (mm.ROOT_PTR, 0x1FFFFFF), (mm.ROOT_PTR, ROOT + 1),
    (mm.CAMERA_PTR, CAM + 0x10), (ROOT, 0), (CAM, 0),
    (ROOT + 4, 1), (mm.GAME_STATE, 0), (mm.GAME_FLAGS_WORD, 0x40000000),
    (mm.EVENT_ACTIVE, 1), (CAM + mm.CAM_MODE, 1),
    (ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, CAM + mm.CAM_VIEW + 0x10),
    (PLAYER_RECORD, 0), (PLAYER_RECORD + 8, (1001 << 16) | 7),
    (PLAYER_RECORD + mm.ENTITY_RENDERER, 0),
])
def test_scene_guard_refuses_unverified_allocations_and_scenes_without_writes(be, address, value):
    be.seed_u32(address, value)
    adapter = DruagaAdapter(be)
    scene = adapter.read_scene()
    assert not scene.valid and scene.reason
    assert not adapter.is_field_like(scene)
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(True)
    assert not be.writes


def test_scene_geometry_and_actor_homogeneous_coordinate_are_validated(be):
    adapter = DruagaAdapter(be)
    assert adapter.is_field_like(adapter.read_scene())
    be.seed_floats(PLAYER_RECORD + mm.ENTITY_POS + 12, [0.0])
    assert not adapter.read_scene().valid
    assert not be.writes


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_geometry_is_invalid(be, bad):
    be.seed_floats(CAM + mm.CAM_WORLD + 0x30, [bad])
    assert not DruagaAdapter(be).read_scene().valid
    assert not be.writes


def test_actor_lookup_is_by_id_not_fixed_slot():
    backend = seed_field(FakeBackend(), player_slot=23)
    adapter = DruagaAdapter(backend)
    assert adapter.read_player().as_tuple() == pytest.approx(PLAYER.as_tuple())
    adapter.set_patch(True)
    assert backend.read_u32(active_bank(backend) + mm.SLOT_ANCHOR) == 23


def test_generated_cave_regions_branches_and_displaced_words_are_consistent():
    assert mm.CAVE + len(caves.WORDS) * 4 <= mm.CAVE_END <= mm.DUNGEON_CAVE
    assert mm.DUNGEON_CAVE + len(caves.DUNGEON_WORDS) * 4 <= mm.DUNGEON_CAVE_END <= mm.MOD_BLOCK
    assert mm.SLOTS[0] + 0x40 <= mm.SLOTS[1]
    assert mm.SLOTS[1] + 0x40 <= mm.BLOCK_SIZE
    assert caves.HOOK == (m.j(mm.CAVE), mm.CAM_HOOK_WORDS[1])
    assert caves.DUNGEON_HOOK == (m.j(mm.DUNGEON_CAVE), mm.DUNGEON_HOOK_WORDS[1])
    assert mm.CAM_HOOK_WORDS == (0xE62001AC, 0x78480000)
    assert mm.DUNGEON_HOOK_WORDS == (0x7C680000, 0x26240010)
    for words, return_address in ((caves.WORDS, mm.CAM_RETURN), (caves.DUNGEON_WORDS, mm.DUNGEON_RETURN)):
        assert words[0] == 0x7C680000  # native eye -> mirror, not mod eye
        assert m.swc1(0, m.S1, mm.CAM_FOV_RAD) in words
        assert m.jal(mm.FUN_TRANSLATE) in words
        assert m.jal(mm.FUN_LOOK_AT) in words
        assert words[-2] == m.j(return_address)
        for i, word in enumerate(words):
            if word >> 26 in (4, 5):
                offset = word & 65535
                offset = offset - 65536 if offset & 32768 else offset
                assert 0 <= i + 1 + offset < len(words)


@pytest.mark.parametrize("corrupt", ["hook", "delay", "cave", "dungeon_hook", "dungeon_delay", "dungeon_cave", "magic", "dirty_block"])
def test_all_patch_resources_are_preflighted_before_any_write(be, corrupt):
    if corrupt == "hook": be.seed_u32(mm.CAM_HOOK, 0x12345678)
    if corrupt == "delay": be.seed_u32(mm.CAM_HOOK + 4, 0x12345678)
    if corrupt == "cave": be.seed_u32(mm.CAVE + 4 * (len(caves.WORDS) - 1), 1)
    if corrupt == "dungeon_hook": be.seed_u32(mm.DUNGEON_HOOK, 0x12345678)
    if corrupt == "dungeon_delay": be.seed_u32(mm.DUNGEON_HOOK + 4, 0x12345678)
    if corrupt == "dungeon_cave": be.seed_u32(mm.DUNGEON_CAVE + 4 * (len(caves.DUNGEON_WORDS) - 1), 1)
    if corrupt == "magic": be.seed_u32(mm.MOD_BLOCK, 0xBADCAFE)
    if corrupt == "dirty_block": be.seed_u32(mm.MOD_BLOCK + mm.BLOCK_SIZE - 4, 1)
    with pytest.raises(caves.PatchConflict):
        DruagaAdapter(be).set_patch(True)
    assert not be.writes


def test_preparing_is_disconnected_install_is_idempotent_and_release_restores_stock(be):
    caves.prepare(be)
    assert caves.site_state(be) == "stock"
    assert tuple(be.read_u32(mm.CAVE + 4*i) for i in range(len(caves.WORDS))) == tuple(caves.WORDS)
    before = len(be.writes)
    caves.prepare(be)
    assert len(be.writes) == before
    caves.install(be)
    assert caves.site_state(be) == "applied"
    assert be.writes[-1][0] == mm.DUNGEON_HOOK
    before = len(be.writes)
    caves.install(be)
    assert len(be.writes) == before
    caves.uninstall(be)
    assert caves.site_state(be) == "stock"
    assert be.read_u32(mm.CAM_HOOK + 4) == mm.CAM_HOOK_WORDS[1]


@pytest.mark.parametrize("yaw,pitch,distance", [(0, -35, 22), (90, -35, 22),
    (180, -60, 40), (270, 10, 5), (-90, -89, 3), (720, 25, 100)])
def test_orbit_relative_math_keeps_eye_and_target_offsets_independent(be, yaw, pitch, distance):
    adapter = DruagaAdapter(be)
    target_offset, position_offset = Vec3(1.0, 2.5, -3.0), Vec3(-2.0, 1.0, 4.0)
    # The explicit offset boundary must not subtract this deliberately stale centre.
    adapter.write_orbit_params(Vec3(900, 800, 700), yaw, pitch, distance,
                               pos_offset=position_offset, target_offset=target_offset)
    bank = active_bank(be)
    expected = orbit_pose(target_offset, math.radians(yaw), math.radians(pitch), distance)
    assert be.read_floats(bank + mm.SLOT_EYE, 3) == pytest.approx((expected.eye + position_offset).as_tuple())
    assert be.read_floats(bank + mm.SLOT_TARGET, 3) == pytest.approx(target_offset.as_tuple())
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
    assert be.read_floats(CAM + mm.CAM_NATIVE_EYE, 3) == pytest.approx(NATIVE.eye.as_tuple())
    assert be.read_floats(CAM + mm.CAM_NATIVE_TARGET, 3) == pytest.approx(NATIVE.target.as_tuple())


@pytest.mark.parametrize("pitch,distance,clamped_pitch,clamped_distance", [
    (-100, -10, -89.5, 2), (90, 1000, 25, 100),
])
def test_adapter_clamps_pitch_and_distance_at_its_native_boundary(be, pitch, distance, clamped_pitch, clamped_distance):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 0, pitch, distance, target_offset=Vec3(0, 0, 0))
    expected = orbit_pose(Vec3(0, 0, 0), 0, math.radians(clamped_pitch), clamped_distance)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 3) == pytest.approx(expected.eye.as_tuple(), abs=1e-5)


@pytest.mark.parametrize("kind", ["centre", "yaw", "pitch", "distance", "position", "target", "fov"])
def test_non_finite_inputs_are_refused_without_guest_writes(be, kind):
    adapter = DruagaAdapter(be)
    kwargs = dict(centre=PLAYER, yaw_deg=90.0, pitch_deg=-35.0, distance=22.0,
                  pos_offset=Vec3(0, 0, 0), target_offset=Vec3(0, 0, 0))
    if kind == "fov":
        action = lambda: adapter.write_fov_deg(math.nan)
    else:
        key = {"centre": "centre", "yaw": "yaw_deg", "pitch": "pitch_deg", "distance": "distance",
               "position": "pos_offset", "target": "target_offset"}[kind]
        kwargs[key] = Vec3(math.nan, 0, 0) if kind in ("centre", "position", "target") else math.nan
        action = lambda: adapter.write_orbit_params(**kwargs)
    with pytest.raises(ValueError):
        action()
    assert not be.writes


def test_guest_adds_latest_actor_position_and_preserves_native_current_goals(be):
    adapter = DruagaAdapter(be)
    offset, pos = Vec3(1, 3, -2), Vec3(4, -1, 2)
    adapter.write_orbit_params(PLAYER + offset, 90, -35, 22, pos_offset=pos, target_offset=offset)
    native_before = be.bytes_at(CAM + 0x230, 0x70)
    moved = Vec3(-12.0, 7.0, 3.0)
    be.seed_floats(PLAYER_RECORD + mm.ENTITY_POS, (*moved.as_tuple(), 1.0))
    calls = cave_frame(be)
    expected = orbit_pose(offset, math.radians(90), math.radians(-35), 22)
    assert calls[0][0:3] == (mm.FUN_TRANSLATE, CAM + mm.CAM_WORLD, mm.MOD_BLOCK + mm.MB_EYE)
    assert calls[1][0:3] == (mm.FUN_LOOK_AT, CAM + mm.CAM_WORLD, mm.MOD_BLOCK + mm.MB_TARGET)
    assert calls[0][3][:3] == pytest.approx((moved + expected.eye + pos).as_tuple(), abs=3e-6)
    assert calls[1][3][:3] == pytest.approx((moved + offset).as_tuple())
    assert be.bytes_at(CAM + 0x230, 0x70) == native_before
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 1
    pose = adapter.read_game_pose()
    assert pose.eye.as_tuple() == pytest.approx(calls[0][3][:3])
    assert pose.target.as_tuple() == pytest.approx(calls[1][3][:3])


@pytest.mark.parametrize("address,value", [(mm.EVENT_ACTIVE, 1), (CAM + mm.CAM_MODE, 1),
    (mm.CAMERA_PTR, CAM + 0x10), (ROOT, 0), (ROOT + 4, 1), (mm.GAME_STATE, 1),
    (mm.GAME_FLAGS_WORD, 0x40000000),
    (ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, CAM + mm.CAM_VIEW + 0x10),
    (PLAYER_RECORD, 0), (PLAYER_RECORD + 8, 999 << 16), (PLAYER_RECORD + mm.ENTITY_RENDERER, 0)])
def test_guest_rechecks_scene_and_uses_native_builders_on_rejection(be, address, value):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    be.seed_u32(address, value)
    calls = cave_frame(be)
    assert calls[0][2] == CAM + mm.CAM_NATIVE_EYE
    assert calls[1][2] == CAM + mm.CAM_NATIVE_TARGET
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0


@pytest.mark.parametrize("xscale", [0.5, 1.0, 1.7])
def test_fov_conversion_uses_native_vertical_projection_and_horizontal_gui_units(be, xscale):
    adapter = DruagaAdapter(be)
    be.seed_floats(CAM + mm.CAM_ASPECT_SCALE_X, [xscale])
    original = adapter.capture_original_fov()
    assert original == pytest.approx(math.degrees(2 * math.atan(math.tan(math.radians(25)/2) / (0.7*xscale))))
    adapter.write_fov_deg(60)
    rad = be.read_floats(active_bank(be) + mm.SLOT_FOV, 1)[0]
    assert rad == pytest.approx(2 * math.atan(0.7*xscale*math.tan(math.radians(60)/2)))
    assert be.read_floats(CAM + mm.CAM_NATIVE_FOV_DEG, 1) == [25.0]
    cave_frame(be)
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(rad)
    projection_for(be, rad, xscale)
    assert adapter.read_fov_deg() == pytest.approx(60, abs=2e-5)
    assert adapter.fov_in_sync(60)
    assert not adapter.fov_in_sync(45)


def test_double_buffer_is_filled_before_slot_flags_and_hook_are_published(be):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    old_bank = active_bank(be)
    old_payload = be.bytes_at(old_bank, 0x28)
    be.writes.clear()
    at_flip = []
    def observe(address, data):
        if address == mm.MOD_BLOCK + mm.MB_SLOT:
            bank = active_bank(be)
            at_flip.append((bank, be.read_floats(bank + mm.SLOT_EYE, 3),
                            be.read_floats(bank + mm.SLOT_TARGET, 3),
                            be.read_floats(bank + mm.SLOT_FOV, 1)[0], be.read_u32(bank + mm.SLOT_ANCHOR)))
    be.on_write = observe
    adapter.write_fov_deg(70)
    assert len(at_flip) == 1 and at_flip[0][0] != old_bank
    assert at_flip[0][4] == PLAYER_SLOT
    assert at_flip[0][3] == pytest.approx(2 * math.atan(0.7*math.tan(math.radians(70)/2)))
    assert be.bytes_at(old_bank, 0x28) == old_payload
    addresses = [a for a, _ in be.writes]
    flip = addresses.index(mm.MOD_BLOCK + mm.MB_SLOT)
    flag = addresses.index(mm.MOD_BLOCK + mm.MB_FLAGS)
    assert addresses[0] == mm.MOD_BLOCK + mm.MB_MOVE_SEQ
    assert all(a in range(at_flip[0][0], at_flip[0][0]+0x3C) for a in addresses[1:flip])
    assert addresses[-1] == mm.MOD_BLOCK + mm.MB_MOVE_SEQ
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_MOVE_SEQ) % 2 == 0
    assert flip < flag


def test_first_hook_is_connected_only_after_a_complete_bank_and_flags(be):
    DruagaAdapter(be).write_fov_deg(60)
    addresses = [a for a, _ in be.writes]
    assert addresses.index(mm.MOD_BLOCK + mm.MB_SLOT) < addresses.index(mm.MOD_BLOCK + mm.MB_FLAGS) < addresses.index(mm.CAM_HOOK)


def test_fov_and_orbit_release_independently_and_final_restore_keeps_native_state(be):
    adapter = DruagaAdapter(be)
    native_before = be.bytes_at(CAM + 0x230, 0x70)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    adapter.write_fov_deg(60)
    cave_frame(be)
    adapter.set_patch(False)
    assert caves.site_state(be) == "applied"
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
    adapter.restore_fov()
    assert caves.site_state(be) == "stock"
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(25))
    assert be.bytes_at(CAM + 0x230, 0x70) == native_before


def test_unknown_hook_on_release_is_not_overwritten(be):
    adapter = DruagaAdapter(be)
    adapter.set_patch(True)
    be.seed_u32(mm.CAM_HOOK, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(False)
    assert not be.writes


def test_restore_does_not_overwrite_projection_no_longer_owned(be):
    adapter = DruagaAdapter(be)
    adapter.write_fov_deg(60)
    be.seed_floats(CAM + mm.CAM_FOV_RAD, [0.75])  # a new native camera writer won
    adapter.restore_fov()
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1) == [0.75]
    assert caves.site_state(be) == "stock"


def test_state_reload_republishes_last_orbit_and_fov_and_restores_new_native_baseline(be):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, pos_offset=Vec3(1, 2, 3), target_offset=Vec3(0, 4, 0))
    adapter.write_fov_deg(60)
    expected_eye = be.read_floats(active_bank(be) + mm.SLOT_EYE, 3)
    expected_target = be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3)
    loaded = seed_field(FakeBackend(), native_fov_deg=40.0, player_slot=12)
    be.mem = loaded.mem
    be.writes.clear()
    adapter.set_patch(True)  # the runtime calls this even if the settings key is unchanged
    assert caves.site_state(be) == "applied"
    bank = active_bank(be)
    assert be.read_floats(bank + mm.SLOT_EYE, 3) == pytest.approx(expected_eye)
    assert be.read_floats(bank + mm.SLOT_TARGET, 3) == pytest.approx(expected_target)
    assert be.read_u32(bank + mm.SLOT_ANCHOR) == 12
    cave_frame(be)
    adapter.set_patch(False)
    adapter.restore_fov()
    assert caves.site_state(be) == "stock"
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(40))
    assert be.read_floats(CAM + mm.CAM_NATIVE_FOV_DEG, 1) == [40.0]


def test_runtime_dispatches_eye_and_target_offsets_from_the_same_anchor():
    class Spy:
        accepts_orbit_offsets = True
        def __init__(self): self.calls = []
        def write_orbit_params(self, *args, **kwargs): self.calls.append((args, kwargs))
    adapter = Spy()
    settings = CameraSettings(mode=MODE_ORBIT, look_height=3.0,
                              pos_offset=[1.0, 2.0, 3.0], target_offset=[4.0, 5.0, 6.0])
    runtime = CameraRuntime(adapter, settings)
    centre = (104.0, 208.0, 306.0)
    assert runtime._publish_orbit(centre, 90, -35, 22)
    args, kwargs = adapter.calls[0]
    assert args[0].as_tuple() == centre
    assert args[1:] == (90, -35, 22)
    assert kwargs["pos_offset"].as_tuple() == (1, 2, 3)
    assert kwargs["target_offset"].as_tuple() == (4, 8, 6)
    assert not runtime._publish_orbit(centre, 90, -35, 22)
    settings.pos_offset[0] = 2.0
    assert runtime._publish_orbit(centre, 90, -35, 22)


def test_runtime_tick_and_restore_use_the_native_orbit_boundary(be):
    adapter = DruagaAdapter(be)
    settings = CameraSettings(mode=MODE_ORBIT, yaw_deg=90, pitch_deg=-35, distance=22,
                              look_height=2.0, pos_offset=[1, 2, 3], target_offset=[4, 5, 6])
    runtime = CameraRuntime(adapter, settings)
    runtime._tick(0.01, None)
    assert not runtime.stats.last_error
    assert caves.site_state(be) == "applied"
    expected = orbit_pose(Vec3(4, 7, 6), math.radians(90), math.radians(-35), 22)
    assert be.read_floats(active_bank(be) + mm.SLOT_EYE, 3) == pytest.approx((expected.eye + Vec3(1, 2, 3)).as_tuple())
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3) == pytest.approx((4, 7, 6))
    runtime.restore()
    assert caves.site_state(be) == "stock"
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert all(be.read_u32(address) == word for address, word in mm.PAD_ACTION_LOADS)


def assert_pad_stock(backend):
    assert caves.read_words(backend, mm.PAD_AXIS_HOOK, 2) == mm.PAD_AXIS_STOCK
    assert all(backend.read_u32(address) == word for address, word in mm.PAD_ACTION_LOADS)


def test_right_block_changes_only_axis_hook_cave_and_derived_direction_loads(be):
    raw = bytes([0xFF, 0x79, 0xA5, 0x5A, 0, 255, 38, 192])
    raw_address = mm.PAD_RAW_AXES - 4
    be.seed(raw_address, raw)
    adapter = DruagaAdapter(be)
    adapter.set_stick_block(True)
    expected = {a for a, _ in mm.PAD_ACTION_LOADS} | {mm.PAD_AXIS_HOOK}
    expected |= {mm.PAD_CAVE + 4*i for i in range(len(caves.PAD_WORDS))}
    assert {a for a, _ in be.writes} == expected
    assert caves.read_words(be, mm.PAD_AXIS_HOOK, 2) == caves.PAD_HOOK
    assert all(be.read_u32(a) == neutral for (a, _), neutral in zip(mm.PAD_ACTION_LOADS, mm.PAD_NEUTRAL_WORDS))
    assert be.bytes_at(raw_address, len(raw)) == raw
    before = len(be.writes)
    adapter.set_stick_block(True)
    assert len(be.writes) == before
    adapter.set_stick_block(False)
    assert_pad_stock(be)
    assert be.bytes_at(raw_address, len(raw)) == raw
    assert caves.read_words(be, mm.PAD_CAVE, len(caves.PAD_WORDS)) == tuple(caves.PAD_WORDS)
    before = len(be.writes)
    adapter.set_stick_block(False)
    assert len(be.writes) == before


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("unknown_index", range(len(mm.PAD_ACTION_LOADS)))
def test_right_block_preflights_every_derived_site_before_any_write(be, on, unknown_index):
    if not on:
        DruagaAdapter(be).set_stick_block(True)
    be.seed_u32(mm.PAD_ACTION_LOADS[unknown_index][0], 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        DruagaAdapter(be).set_stick_block(on)
    assert not be.writes


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("hook_applied", [False, True])
def test_right_block_normalizes_known_mixed_sites(be, on, hook_applied):
    address, _ = mm.PAD_ACTION_LOADS[1]
    be.seed_u32(address, mm.PAD_NEUTRAL_WORDS[1])
    if hook_applied:
        for i, word in enumerate(caves.PAD_WORDS):
            be.seed_u32(mm.PAD_CAVE + 4*i, word)
        be.seed_u32(mm.PAD_AXIS_HOOK, caves.PAD_HOOK[0])
    DruagaAdapter(be).set_stick_block(on)
    assert all(be.read_u32(a) == (neutral if on else stock)
               for (a, stock), neutral in zip(mm.PAD_ACTION_LOADS, mm.PAD_NEUTRAL_WORDS))
    assert caves.read_words(be, mm.PAD_AXIS_HOOK, 2) == (caves.PAD_HOOK if on else mm.PAD_AXIS_STOCK)


def test_existing_unknown_hook_refuses_republication_without_mod_block_writes(be):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    be.seed_u32(mm.CAM_HOOK, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        adapter.write_orbit_params(PLAYER, 45, -30, 15, target_offset=Vec3(0, 1, 0))
    assert not be.writes


def test_fov_only_cave_leaves_camera_builders_native_and_flags_zero_is_pass_through(be):
    adapter = DruagaAdapter(be)
    adapter.write_fov_deg(60)
    calls = cave_frame(be)
    assert [call[2] for call in calls] == [CAM + mm.CAM_NATIVE_EYE, CAM + mm.CAM_NATIVE_TARGET]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    calls = cave_frame(be)
    assert [call[2] for call in calls] == [CAM + mm.CAM_NATIVE_EYE, CAM + mm.CAM_NATIVE_TARGET]
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(25))
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_HEARTBEAT) == 2


@pytest.mark.parametrize("address,value", [(mm.EVENT_ACTIVE, 1), (mm.GAME_STATE, 1),
    (mm.GAME_FLAGS_WORD, 0x40000000), (CAM + mm.CAM_MODE, 1),
    (ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, 0)])
def test_guest_rejection_does_not_apply_stale_fov_override(be, address, value):
    adapter = DruagaAdapter(be)
    adapter.write_fov_deg(60)
    be.seed_u32(address, value)
    cave_frame(be)
    assert be.read_floats(CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(25))


@pytest.mark.parametrize("index", [64, 0xFFFFFFFF])
def test_guest_rejects_out_of_bounds_actor_indices(be, index):
    adapter = DruagaAdapter(be)
    adapter.set_patch(True)
    be.seed_u32(active_bank(be) + mm.SLOT_ANCHOR, index)
    calls = cave_frame(be)
    assert [call[2] for call in calls] == [CAM + mm.CAM_NATIVE_EYE, CAM + mm.CAM_NATIVE_TARGET]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0


def test_cave_keeps_the_original_native_eye_and_target_mirror_stores(be):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(1, 2, 3))
    be.seed_floats(CAM + 0x250, [101, 102, 103, 1])
    be.seed_floats(CAM + 0x290, [201, 202, 203, 1])
    cave_frame(be)
    assert be.read_floats(CAM + 0x250, 4) == be.read_floats(CAM + mm.CAM_NATIVE_EYE, 4)
    assert be.read_floats(CAM + 0x290, 4) == be.read_floats(CAM + mm.CAM_NATIVE_TARGET, 4)
    assert be.read_floats(CAM + 0x250, 3) != be.read_floats(mm.MOD_BLOCK + mm.MB_EYE, 3)
    assert be.read_floats(CAM + 0x290, 3) != be.read_floats(mm.MOD_BLOCK + mm.MB_TARGET, 3)


def test_guarded_adapter_cannot_publish_or_restore_into_a_changed_game(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    adapter = DruagaAdapter(guard)
    adapter.set_patch(True)
    be.serial, be.disc_crc = "SLPS-00000", "BADCAFE0"
    assert guard.verify() == CHANGED
    be.writes.clear()
    with pytest.raises(WriteBlocked):
        adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    with pytest.raises(WriteBlocked):
        adapter.set_patch(False)
    assert not be.writes


def test_runtime_abandon_is_no_write_even_with_an_active_druaga_hook(be):
    adapter = DruagaAdapter(be)
    runtime = CameraRuntime(adapter, CameraSettings(mode=MODE_ORBIT))
    adapter.set_patch(True)
    be.writes.clear()
    runtime.abandon()
    assert not be.writes
    assert caves.site_state(be) == "applied"


def assert_both_hook_states(backend, *, applied):
    for address, stock, hook, _, _ in caves.RESOURCES:
        expected = hook if applied else stock
        assert tuple(backend.read_u32(address + 4 * i) for i in range(2)) == expected


def test_dungeon_fixture_uses_separate_root_class_and_native_actor_ownership(dungeon_be):
    adapter = DruagaAdapter(dungeon_be)
    scene = adapter.read_scene()
    assert scene.valid and adapter.is_field_like(scene)
    assert scene.player.as_tuple() == pytest.approx(DUNGEON_PLAYER.as_tuple())
    assert dungeon_be.read_u32(mm.GAME_STATE) == 1
    assert dungeon_be.read_u32(DUNGEON_ROOT) == mm.DUNGEON_ROOT_VTABLE
    assert dungeon_be.read_u32(DUNGEON_CAM) == mm.DUNGEON_CAMERA_VTABLE
    assert adapter.CAM_EYE_ADDR == DUNGEON_CAM + mm.CAM_WORLD + 0x30
    assert not any(dungeon_be.read_u32(mm.ENTITY_TABLE+i*mm.ENTITY_STRIDE+8) >> 16 == mm.PLAYER_ID
                   for i in range(mm.ENTITY_COUNT))
    assert not dungeon_be.writes


@pytest.mark.parametrize("player_slot", [0, 7, 63])
def test_dungeon_lookup_follows_actor_owned_record_not_id_or_fixed_slot(player_slot):
    backend = seed_dungeon_field(FakeBackend(), player_slot=player_slot)
    record = mm.ENTITY_TABLE + player_slot * mm.ENTITY_STRIDE
    # Ownership, not an assumed dungeon ID0 or town ID1000, selects the anchor.
    backend.seed_u32(record + 8, (141 << 16) | 27)
    adapter = DruagaAdapter(backend)
    assert adapter.read_player().as_tuple() == pytest.approx(DUNGEON_PLAYER.as_tuple())
    adapter.set_patch(True)
    assert backend.read_u32(active_bank(backend) + mm.SLOT_ANCHOR) == player_slot
    calls = cave_frame(backend, dungeon=True)
    assert calls[0][2] == mm.MOD_BLOCK + mm.MB_EYE
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 1


@pytest.mark.parametrize("address,value", [
    (mm.ROOT_PTR, 0), (mm.CAMERA_PTR, DUNGEON_CAM + 0x10),
    (DUNGEON_ROOT, mm.ROOT_VTABLE), (DUNGEON_CAM, mm.CAMERA_VTABLE),
    (DUNGEON_ROOT + 4, 0x00020002), (mm.GAME_STATE, 2),
    (DUNGEON_CAM + mm.CAM_MODE, 0), (DUNGEON_CAM + 0x2DC, 0x00010101),
    (mm.EVENT_ACTIVE, 1), (mm.GAME_FLAGS_WORD, 0x40000000),
    (DUNGEON_ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, 0),
    (mm.DUNGEON_ACTOR_PTR, 0), (mm.DUNGEON_ACTOR_PTR, DUNGEON_ACTOR + 1),
    (mm.DUNGEON_ACTOR_PTR, 0x02000000),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, 0),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, mm.ENTITY_TABLE),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, mm.ENTITY_TABLE + mm.ENTITY_RENDERER + 1),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, mm.ENTITY_TABLE + mm.ENTITY_RENDERER + mm.ENTITY_COUNT*mm.ENTITY_STRIDE),
    (mm.ENTITY_TABLE, 0), (mm.ENTITY_TABLE + mm.ENTITY_RENDERER, ROOT + mm.RENDERER_OFFSET),
])
def test_dungeon_host_rejects_invalid_scene_or_actor_ownership_without_write(dungeon_be, address, value):
    dungeon_be.seed_u32(address, value)
    adapter = DruagaAdapter(dungeon_be)
    assert not adapter.read_scene().valid
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(True)
    assert not dungeon_be.writes


def test_town_id1000_record_does_not_replace_missing_dungeon_owned_actor(dungeon_be):
    record = mm.ENTITY_TABLE + mm.ENTITY_STRIDE
    dungeon_be.seed_u32(record, 1)
    dungeon_be.seed_u32(record + 8, mm.PLAYER_ID << 16)
    dungeon_be.seed_u32(record + mm.ENTITY_RENDERER, DUNGEON_ROOT + mm.RENDERER_OFFSET)
    dungeon_be.seed_floats(record + mm.ENTITY_POS, (6, 50, -4, 1))
    dungeon_be.seed_u32(DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, 0)
    adapter = DruagaAdapter(dungeon_be)
    assert not adapter.read_scene().valid
    assert not dungeon_be.writes


@pytest.mark.parametrize("address,value", [
    (mm.GAME_STATE, 2), (DUNGEON_ROOT + 4, 2), (DUNGEON_CAM + mm.CAM_MODE, 0),
    (DUNGEON_CAM + 0x2DC, 0x00010101), (mm.EVENT_ACTIVE, 1),
    (mm.GAME_FLAGS_WORD, 0x40000000),
    (DUNGEON_ROOT + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, 0),
    (mm.DUNGEON_ACTOR_PTR, 0), (mm.DUNGEON_ACTOR_PTR, DUNGEON_ACTOR + 1),
    (mm.DUNGEON_ACTOR_PTR, 0x02000000),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, 0),
    (DUNGEON_ACTOR + mm.ACTOR_ENTITY_PTR, mm.ENTITY_TABLE + mm.ENTITY_RENDERER + mm.ENTITY_STRIDE),
    (mm.ENTITY_TABLE, 0), (mm.ENTITY_TABLE + mm.ENTITY_RENDERER, 0),
])
def test_dungeon_guest_rejects_transition_and_stale_actor_anchor(dungeon_be, address, value):
    adapter = DruagaAdapter(dungeon_be)
    adapter.write_orbit_params(DUNGEON_PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    collision_eye = dungeon_be.bytes_at(DUNGEON_CAM + 0x250, 16)
    dungeon_be.seed_u32(address, value)
    calls = cave_frame(dungeon_be, dungeon=True)
    assert [call[2] for call in calls] == [DUNGEON_CAM + 0x250, DUNGEON_CAM + 0x290]
    assert dungeon_be.bytes_at(DUNGEON_CAM + 0x250, 16) == collision_eye
    assert dungeon_be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert dungeon_be.read_floats(DUNGEON_CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(40))


def test_dungeon_guest_adds_fresh_owned_actor_and_keeps_native_collision_output(dungeon_be):
    adapter = DruagaAdapter(dungeon_be)
    target, position = Vec3(1, 3, -2), Vec3(4, -1, 2)
    adapter.write_orbit_params(DUNGEON_PLAYER + target, 90, -35, 22, pos_offset=position, target_offset=target)
    before = dungeon_be.bytes_at(DUNGEON_CAM + 0x230, 0x70)
    moved = Vec3(16.0, 51.0, -22.0)
    dungeon_be.seed_floats(mm.ENTITY_TABLE + mm.ENTITY_POS, (*moved.as_tuple(), 1.0))
    calls = cave_frame(dungeon_be, dungeon=True)
    expected = orbit_pose(target, math.radians(90), math.radians(-35), 22)
    assert calls[0][0:3] == (mm.FUN_TRANSLATE, DUNGEON_CAM + mm.CAM_WORLD, mm.MOD_BLOCK + mm.MB_EYE)
    assert calls[1][0:3] == (mm.FUN_LOOK_AT, DUNGEON_CAM + mm.CAM_WORLD, mm.MOD_BLOCK + mm.MB_TARGET)
    assert calls[0][3][:3] == pytest.approx((moved + expected.eye + position).as_tuple(), abs=3e-6)
    assert calls[1][3][:3] == pytest.approx((moved + target).as_tuple())
    assert dungeon_be.bytes_at(DUNGEON_CAM + 0x230, 0x70) == before
    assert dungeon_be.read_floats(DUNGEON_CAM + 0x250, 3) == pytest.approx((DUNGEON_NATIVE.eye + DUNGEON_COLLISION).as_tuple())
    assert dungeon_be.read_floats(DUNGEON_CAM + 0x290, 4) == dungeon_be.read_floats(DUNGEON_CAM + 0x280, 4)
    assert dungeon_be.read_u32(mm.MOD_BLOCK + mm.MB_CAMERA) == DUNGEON_CAM


@pytest.mark.parametrize("xscale", [0.5, 1.0, 1.7])
def test_dungeon_fov_uses_native_radian_field_and_independent_parameter_bank(dungeon_be, xscale):
    adapter = DruagaAdapter(dungeon_be)
    dungeon_be.seed_floats(DUNGEON_CAM + mm.CAM_ASPECT_SCALE_X, [xscale])
    adapter.write_fov_deg(60)
    expected = 2 * math.atan(0.7*xscale*math.tan(math.radians(60)/2))
    native_eye = dungeon_be.bytes_at(DUNGEON_CAM + 0x250, 16)
    calls = cave_frame(dungeon_be, dungeon=True)
    assert [call[2] for call in calls] == [DUNGEON_CAM + 0x250, DUNGEON_CAM + 0x290]
    assert dungeon_be.read_floats(mm.MOD_BLOCK + mm.MB_NATIVE_FOV, 1)[0] == pytest.approx(math.radians(40))
    assert dungeon_be.read_floats(DUNGEON_CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(expected)
    assert dungeon_be.read_floats(DUNGEON_CAM + mm.CAM_NATIVE_FOV_DEG, 1) == [40.0]
    assert dungeon_be.bytes_at(DUNGEON_CAM + 0x250, 16) == native_eye
    projection_for(dungeon_be, expected, xscale, cam=DUNGEON_CAM)
    assert adapter.read_fov_deg() == pytest.approx(60, abs=2e-5)
    adapter.restore_fov()
    assert_both_hook_states(dungeon_be, applied=False)
    assert dungeon_be.read_floats(DUNGEON_CAM + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(40))


@pytest.mark.parametrize("dungeon", [False, True])
@pytest.mark.parametrize("already_applied", [0, 1])
def test_known_mixed_hooks_apply_and_remove_both_sites(be, dungeon, already_applied):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else be
    caves.prepare(backend)
    address, _, hook, _, _ = caves.RESOURCES[already_applied]
    backend.seed_u32(address, hook[0])
    adapter = DruagaAdapter(backend)
    adapter.set_patch(True)
    assert_both_hook_states(backend, applied=True)
    adapter.set_patch(False)
    assert_both_hook_states(backend, applied=False)


@pytest.mark.parametrize("start_dungeon,end_dungeon", [(False, True), (True, False), (True, True)])
def test_state_reload_reselects_scene_owned_actor_and_reinstalls_both_hooks(start_dungeon, end_dungeon):
    backend = seed_dungeon_field(FakeBackend()) if start_dungeon else seed_field(FakeBackend())
    adapter = DruagaAdapter(backend)
    target, position = Vec3(1, 2, 3), Vec3(4, -1, 2)
    adapter.write_orbit_params(Vec3(0, 0, 0), 90, -35, 22, pos_offset=position, target_offset=target)
    adapter.write_fov_deg(60)
    old_eye = backend.read_floats(active_bank(backend) + mm.SLOT_EYE, 3)
    loaded = (seed_dungeon_field(FakeBackend(), native_fov_deg=42, player_slot=11) if end_dungeon
              else seed_field(FakeBackend(), native_fov_deg=28, player_slot=11))
    backend.mem = loaded.mem
    backend.writes.clear()
    adapter.set_patch(True)
    assert_both_hook_states(backend, applied=True)
    assert backend.read_floats(active_bank(backend) + mm.SLOT_EYE, 3) == pytest.approx(old_eye)
    assert backend.read_u32(active_bank(backend) + mm.SLOT_ANCHOR) == 11
    calls = cave_frame(backend, dungeon=end_dungeon)
    player = DUNGEON_PLAYER if end_dungeon else PLAYER
    assert calls[0][3][:3] == pytest.approx((player + Vec3(*old_eye)).as_tuple())
    assert calls[1][3][:3] == pytest.approx((player + target).as_tuple())
    adapter.set_patch(False)
    adapter.restore_fov()
    assert_both_hook_states(backend, applied=False)
    cam = DUNGEON_CAM if end_dungeon else CAM
    assert backend.read_floats(cam + mm.CAM_FOV_RAD, 1)[0] == pytest.approx(math.radians(42 if end_dungeon else 28))


@pytest.mark.parametrize("dungeon", [False, True])
@pytest.mark.parametrize("site_index", [0, 1])
def test_unknown_site_prevents_release_of_either_hook(dungeon, site_index):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else seed_field(FakeBackend())
    adapter = DruagaAdapter(backend)
    adapter.set_patch(True)
    address = caves.RESOURCES[site_index][0]
    backend.seed_u32(address, 0xDEADBEEF)
    backend.writes.clear()
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(False)
    assert not backend.writes


@pytest.mark.parametrize("dungeon", [False, True])
@pytest.mark.parametrize("already_applied", [0, 1])
def test_fov_only_publication_repairs_both_known_mixed_hooks(be, dungeon, already_applied):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else be
    caves.prepare(backend)
    address, _, hook, _, _ = caves.RESOURCES[already_applied]
    backend.seed_u32(address, hook[0])
    adapter = DruagaAdapter(backend)
    adapter.write_fov_deg(60)
    assert_both_hook_states(backend, applied=True)
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
    adapter.restore_fov()
    assert_both_hook_states(backend, applied=False)


@pytest.mark.parametrize("dungeon", [False, True])
@pytest.mark.parametrize("rejection", ["event", "process", "mode", "suspended", "renderer"])
def test_runtime_restore_with_fov_releases_owned_hooks_even_when_scene_became_invalid(dungeon, rejection):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else seed_field(FakeBackend())
    cam, root = (DUNGEON_CAM, DUNGEON_ROOT) if dungeon else (CAM, ROOT)
    adapter = DruagaAdapter(backend)
    runtime = CameraRuntime(adapter, CameraSettings(mode=MODE_ORBIT, use_fov=True, fov_deg=60))
    adapter.set_patch(True)
    adapter.write_fov_deg(60)
    runtime._sync_stick_block(True)
    cave_frame(backend, dungeon=dungeon)
    if rejection == "event": backend.seed_u32(mm.EVENT_ACTIVE, 1)
    elif rejection == "process": backend.seed_u32(mm.GAME_STATE, 0)
    elif rejection == "mode": backend.seed_u32(cam + mm.CAM_MODE, 2)
    elif rejection == "suspended": backend.seed_u32(mm.GAME_FLAGS_WORD, 0x40000000)
    else: backend.seed_u32(root + mm.RENDERER_OFFSET + mm.RENDER_CAMERA, 0)
    assert not adapter.read_scene().valid
    runtime.restore()
    assert not runtime.stats.last_error
    assert_both_hook_states(backend, applied=False)
    assert backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert all(backend.read_u32(address) == stock for address, stock in mm.PAD_ACTION_LOADS)
    # If the same camera still owns its last override, release may restore its
    # native FOV; otherwise the next stock update owns the pending projection.
    assert backend.read_floats(cam + mm.CAM_NATIVE_FOV_DEG, 1) == [40.0 if dungeon else 25.0]
    assert_pad_stock(backend)


def pad_axis_sample(backend, axis, *, blocked):
    """Run the emitted pad cave's integer instructions, including delay slots.

    Native normalization resumes at a3=raw-127; the patch must preserve that
    exact signed input for LX/LY while replacing RX/RY with zero. The helper
    deliberately does not emulate unrelated pad-library deadzone/timer logic.
    """
    regs = [0x11110000 + i for i in range(32)]
    regs[m.ZERO] = 0
    regs[m.V1] = mm.PAD_RAW_AXES - 4 + axis
    regs[m.T0] = axis
    regs[m.A0] = 0xDEADBEEF
    regs[m.A3] = (regs[m.A0] - 127) & 0xFFFFFFFF  # original hook delay slot
    saved = list(regs)
    before = dict(backend.mem)

    def put(register, value):
        if register:
            regs[register] = value & 0xFFFFFFFF

    def execute(word):
        op, rs, rt = word >> 26, word >> 21 & 31, word >> 16 & 31
        immediate = word & 65535
        signed = immediate - 65536 if immediate & 32768 else immediate
        if word == 0:
            return
        if op == 0x24:
            put(rt, backend.bytes_at((regs[rs] + signed) & 0xFFFFFFFF, 1)[0])
        elif op == 9:
            put(rt, regs[rs] + signed)
        elif op == 0x0B:
            put(rt, int((regs[rs] & 0xFFFFFFFF) < (signed & 0xFFFFFFFF)))
        else:
            raise AssertionError(f"unmodelled pad instruction {word:08X}")

    if not blocked:
        for word in mm.PAD_AXIS_STOCK:
            execute(word)
    else:
        pc = mm.PAD_CAVE
        for _ in range(30):
            word = backend.read_u32(pc)
            op = word >> 26
            if op in (2, 4, 5):
                rs, rt = word >> 21 & 31, word >> 16 & 31
                immediate = word & 65535
                signed = immediate - 65536 if immediate & 32768 else immediate
                take = (regs[rs] == regs[rt]) if op == 4 else (regs[rs] != regs[rt])
                destination = (word & 0x3FFFFFF) << 2 if op == 2 else pc + 4 + signed * 4
                execute(backend.read_u32(pc + 4))
                if op == 2:
                    assert destination == mm.PAD_AXIS_RETURN
                    break
                pc = destination if take else pc + 8
            else:
                execute(word)
                pc += 4
        else:
            raise AssertionError("pad cave never returned")
    assert backend.mem == before  # in particular, never edit raw packet bytes
    assert all(regs[i] == saved[i] for i in range(32) if i not in (m.A0, m.A3))
    signed_input = regs[m.A3] - 0x100000000 if regs[m.A3] & 0x80000000 else regs[m.A3]
    return regs[m.A0], signed_input


def test_pad_cave_layout_branches_and_unchanged_hook_delay_are_safe():
    assert mm.CAVE_END <= mm.DUNGEON_CAVE
    assert mm.DUNGEON_CAVE_END <= mm.PAD_CAVE
    assert mm.PAD_CAVE + len(caves.PAD_WORDS)*4 <= mm.PAD_CAVE_END <= mm.MOD_BLOCK
    assert caves.PAD_HOOK == (m.j(mm.PAD_CAVE), mm.PAD_AXIS_STOCK[1])
    assert caves.PAD_WORDS[0] == mm.PAD_AXIS_STOCK[0]
    assert mm.PAD_AXIS_STOCK[1] in caves.PAD_WORDS
    assert caves.PAD_WORDS[-2:] == [m.j(mm.PAD_AXIS_RETURN), m.NOP]
    for i, word in enumerate(caves.PAD_WORDS):
        if word >> 26 in (4, 5):
            offset = word & 65535
            offset = offset - 65536 if offset & 32768 else offset
            assert 0 <= i + 1 + offset < len(caves.PAD_WORDS)


@pytest.mark.parametrize("axis", range(4))
@pytest.mark.parametrize("raw", [0, 1, 126, 127, 128, 254, 255])
def test_generated_pad_cave_neutralizes_only_processed_right_axis_input(be, axis, raw):
    be.seed(mm.PAD_RAW_AXES, bytes([raw]*4))
    DruagaAdapter(be).set_stick_block(True)
    sample, signed = pad_axis_sample(be, axis, blocked=True)
    assert sample == (127 if axis < 2 else raw)
    assert signed == (0 if axis < 2 else raw - 127)
    stock_sample, stock_signed = pad_axis_sample(be, axis, blocked=False)
    assert (stock_sample, stock_signed) == (raw, raw - 127)


def test_processed_right_axes_and_direction_bits_are_zero_while_left_and_buttons_remain(be):
    raw = bytes([0, 255, 38, 192])
    packet = bytes([0, 0x79, 0xA5, 0x5A]) + raw
    be.seed(mm.PAD_RAW_AXES - 4, packet)
    adapter = DruagaAdapter(be)
    adapter.set_stick_block(True)
    for axis in range(4):
        _, signed = pad_axis_sample(be, axis, blocked=True)
        be.seed_u32(mm.PAD_RIGHT_X + axis*4, signed)
    assert [be.read_u32(mm.PAD_RIGHT_X + i*4) for i in range(2)] == [0, 0]
    assert be.read_u32(mm.PAD_RIGHT_X + 8) == (38 - 127) & 0xFFFFFFFF
    assert be.read_u32(mm.PAD_RIGHT_X + 12) == 192 - 127
    # Each directional threshold load is independently replaced by raw centre.
    samples = []
    for (address, stock), neutral in zip(mm.PAD_ACTION_LOADS, mm.PAD_NEUTRAL_WORDS):
        assert be.read_u32(address) == neutral
        assert neutral >> 26 == 9 and neutral >> 21 & 31 == m.ZERO
        assert neutral >> 16 & 31 == stock >> 16 & 31
        samples.append(neutral & 65535)
    assert samples == [127, 127, 127, 127]
    deadzone = 30
    right_direction_bits = sum(1 << i for i, sample in enumerate(samples)
                               if sample < 127-deadzone or sample > 127+deadzone)
    assert right_direction_bits == 0
    assert be.bytes_at(mm.PAD_RAW_AXES - 4, len(packet)) == packet
    adapter.set_stick_block(False)
    assert_pad_stock(be)
    assert [pad_axis_sample(be, i, blocked=False)[1] for i in range(4)] == [-127, 128, -89, 65]


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("corrupt", ["axis_hook", "axis_delay"])
def test_pad_axis_unknown_hook_or_delay_preflights_before_every_write(be, on, corrupt):
    if not on:
        DruagaAdapter(be).set_stick_block(True)
    be.seed_u32(mm.PAD_AXIS_HOOK + (4 if corrupt == "axis_delay" else 0), 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        DruagaAdapter(be).set_stick_block(on)
    assert not be.writes


def test_pad_occupied_cave_is_not_overwritten_and_known_hook_can_still_be_released(be):
    be.seed_u32(mm.PAD_CAVE + 4*(len(caves.PAD_WORDS)-1), 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict):
        DruagaAdapter(be).set_stick_block(True)
    assert not be.writes
    be.seed_u32(mm.PAD_AXIS_HOOK, caves.PAD_HOOK[0])
    for (address, _), neutral in zip(mm.PAD_ACTION_LOADS, mm.PAD_NEUTRAL_WORDS):
        be.seed_u32(address, neutral)
    DruagaAdapter(be).set_stick_block(False)
    assert_pad_stock(be)
    assert be.read_u32(mm.PAD_CAVE + 4*(len(caves.PAD_WORDS)-1)) == 0xDEADBEEF


def test_pad_cave_is_filled_before_single_word_hook_and_state_reload_reapplies(be):
    adapter = DruagaAdapter(be)
    adapter.set_stick_block(True)
    addresses = [address for address, _ in be.writes]
    hook_index = addresses.index(mm.PAD_AXIS_HOOK)
    assert all(address in range(mm.PAD_CAVE, mm.PAD_CAVE + len(caves.PAD_WORDS)*4)
               for address in addresses[:hook_index])
    assert mm.PAD_AXIS_HOOK + 4 not in addresses
    loaded = seed_field(FakeBackend())
    be.mem = loaded.mem
    be.writes.clear()
    adapter.set_stick_block(True)
    assert caves.read_words(be, mm.PAD_AXIS_HOOK, 2) == caves.PAD_HOOK
    assert all(be.read_u32(address) == neutral
               for (address, _), neutral in zip(mm.PAD_ACTION_LOADS, mm.PAD_NEUTRAL_WORDS))
    adapter.set_stick_block(False)
    assert_pad_stock(be)
    assert mm.PAD_AXIS_HOOK + 4 not in [address for address, _ in be.writes]


def movement_frame(backend, *, dungeon=False, local=(0.0, 0.25, 1.0, 1.0),
                   caller=0x0045598C, controller=None, manager=None, site=0,
                   on_step=None):
    """Execute the emitted movement wrapper, including unchanged hook delay.

    Stops at native fallback or the verified continuation; it deliberately does
    not model gameplay, native sector math, tile legality, or PS2 scheduling.
    """
    regs = [(1 << (70+i)) | (0x1000+i) for i in range(32)]
    regs[0] = 0
    regs[m.SP] = stack = 0x001E0000
    regs[m.S0] = ROOT+mm.TOWN_CONTROLLER_OFFSET if controller is None else controller
    regs[m.S2] = mm.DUNGEON_MANAGER if manager is None else manager
    regs[m.A0] = regs[m.S2]
    regs[31] = mm.DUNGEON_MOVE_SITES[site]+8 if dungeon else 0x0051B0A4
    fpu = [0x3E800000+i for i in range(32)]
    backend.seed_floats(stack+0x70, local)
    backend.seed_u32(stack+0x40, caller)
    config = 0x001A0000
    backend.seed_u32(regs[m.S0]+0xC, config)
    before_regs = list(regs)
    before_fpu = list(fpu)
    before = dict(backend.mem)

    def put(reg, value):
        if reg: regs[reg] = value & 0xFFFFFFFF

    def execute(word):
        op, rs, rt, rd = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31
        imm = word & 65535
        signed = imm-65536 if imm & 32768 else imm
        address = (regs[rs]+signed) & 0xFFFFFFFF
        if not word: return
        if op == 0:
            fn, shift = word & 63, word >> 6 & 31
            if fn == 0: put(rd, regs[rt] << shift)
            elif fn == 2: put(rd, (regs[rt] & 0xFFFFFFFF) >> shift)
            elif fn in (0x21, 0x2D): put(rd, regs[rs]+regs[rt])
            elif fn == 0x23: put(rd, regs[rs]-regs[rt])
            elif fn == 0x2B: put(rd, int((regs[rs] & 0xFFFFFFFF) < (regs[rt] & 0xFFFFFFFF)))
            else: raise AssertionError(f'unmodelled movement R {word:08X}')
        elif op == 0xF: put(rt, imm << 16)
        elif op == 9: put(rt, regs[rs]+signed)
        elif op == 0xD: put(rt, regs[rs] | imm)
        elif op == 0xC: put(rt, regs[rs] & imm)
        elif op == 0xB: put(rt, int((regs[rs] & 0xFFFFFFFF) < (signed & 0xFFFFFFFF)))
        elif op == 0x23: put(rt, backend.read_u32(address))
        elif op == 0x25: put(rt, int.from_bytes(backend.bytes_at(address, 2), 'little'))
        elif op == 0x1E: regs[rt] = int.from_bytes(backend.bytes_at(address, 16), 'little')
        elif op == 0x1F: backend.seed(address, regs[rt].to_bytes(16, 'little'))
        elif op == 0x31: fpu[rt] = backend.read_u32(address)
        elif op == 0x39: backend.seed_u32(address, fpu[rt])
        elif op == 0x11 and rs == 16:
            fs, ft, fd, fn = word >> 11 & 31, word >> 16 & 31, word >> 6 & 31, word & 63
            x, z = (struct.unpack('<f', struct.pack('<I', fpu[r]))[0] for r in (fs, ft))
            value = x+z if fn == 0 else x-z if fn == 1 else x*z if fn == 2 else None
            assert value is not None, f'unmodelled FPU {word:08X}'
            fpu[fd] = struct.unpack('<I', struct.pack('<f', value))[0]
        else: raise AssertionError(f'unmodelled movement instruction {word:08X}')

    execute(mm.DUNGEON_MOVE_STOCK[1] if dungeon else mm.TOWN_MOVE_STOCK[1])
    pc = mm.DUNGEON_MOVE_CAVE if dungeon else mm.TOWN_MOVE_CAVE
    for _ in range(500):
        word = backend.read_u32(pc)
        if on_step: on_step(pc, word)
        op = word >> 26
        if op in (2, 4, 5) or (op == 0 and word & 63 == 8):
            rs, rt = word >> 21 & 31, word >> 16 & 31
            imm = word & 65535
            signed = imm-65536 if imm & 32768 else imm
            dest = (word & 0x3FFFFFF) << 2 if op == 2 else regs[rs] if op == 0 else pc+4+signed*4
            take = regs[rs] == regs[rt] if op == 4 else regs[rs] != regs[rt]
            execute(backend.read_u32(pc+4))
            if op in (0, 2):
                assert regs[m.SP] == stack
                assert fpu == before_fpu
                except_regs = (m.V0,) if dungeon else (m.V0, m.V1)
                assert all(regs[i] == before_regs[i] for i in range(32) if i not in except_regs)
                # No global pad/camera/actor writes: stack save and local XZ only.
                assert all(backend.mem.get(addr) == byte for addr, byte in before.items()
                           if not stack-0xA0 <= addr < stack+0x80
                           and not (on_step and mm.MOD_BLOCK+mm.MB_MOVE_SEQ <= addr < mm.MOD_BLOCK+mm.MB_MOVE_SEQ+4))
                return dest, tuple(backend.read_floats(stack+0x70, 4)), regs
            pc = dest if take else pc+8
        else:
            execute(word); pc += 4
    raise AssertionError('movement cave never returned')


@pytest.mark.parametrize('yaw', [0, 45, 90, 135, 180, 225, 270, -45])
@pytest.mark.parametrize('local', [(0, 0.25, 0, 1), (0, 0.25, 0.1, 1), (0.1, 0.25, 0, 1),
                                  (-0.06, 0.25, -0.08, 1)])
def test_town_generated_movement_uses_actual_basis_and_preserves_speed_y_w(be, yaw, local):
    adapter = DruagaAdapter(be)
    adapter.write_orbit_params(PLAYER, yaw, -89.5, 22, pos_offset=Vec3(2, 1, -3),
                               target_offset=Vec3(4, 2, 1))
    bank = active_bank(be)
    eye, target = (Vec3(*be.read_floats(bank+off, 3)) for off in (mm.SLOT_EYE, mm.SLOT_TARGET))
    delta = target-eye
    fx, fz = delta.x/math.hypot(delta.x, delta.z), delta.z/math.hypot(delta.x, delta.z)
    dest, got, regs = movement_frame(be, local=local)
    assert dest == mm.TOWN_MOVE_RETURN
    x, y, z, w = local
    assert got == pytest.approx((fz*x+fx*z, y, -fx*x+fz*z, w), abs=1e-7)
    assert math.hypot(got[0], got[2]) == pytest.approx(math.hypot(x, z), abs=1e-7)
    assert regs[m.V0] == 1  # stock hook delay slot kept


@pytest.mark.parametrize('address,value', [(mm.ROOT_PTR, 0), (mm.CAMERA_PTR, CAM+16),
    (ROOT, 0), (ROOT+4, 1), (CAM, 0), (CAM+mm.CAM_MODE, 1), (mm.GAME_STATE, 1),
    (mm.EVENT_ACTIVE, 1), (mm.GAME_FLAGS_WORD, 0x40000000),
    (ROOT+mm.RENDERER_OFFSET+mm.RENDER_CAMERA, 0), (PLAYER_RECORD, 0),
    (PLAYER_RECORD+8, 999 << 16), (PLAYER_RECORD+mm.ENTITY_RENDERER, 0),
    (mm.MOD_BLOCK+mm.MB_MAGIC, 0), (mm.MOD_BLOCK+mm.MB_FLAGS, mm.FLAG_FOV),
    (mm.MOD_BLOCK+mm.MB_MOVE_SEQ, 1)])
def test_town_movement_rejects_stale_scene_and_replays_displaced_lw(be, address, value):
    DruagaAdapter(be).write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    be.seed_u32(address, value)
    local = (0.03, 0.25, -0.04, 1.0)
    dest, got, regs = movement_frame(be, local=local)
    assert dest == mm.TOWN_MOVE_NATIVE and got == pytest.approx(local)
    assert regs[m.V1] == 0x001A0000 and regs[m.V0] == 1


@pytest.mark.parametrize('bad', ['controller', 'root', 'camera', 'anchor', 'valid', 'reserved'])
def test_town_movement_ownership_and_bank_validation(be, bad):
    DruagaAdapter(be).set_patch(True)
    bank = active_bank(be)
    if bad == 'root': be.seed_u32(bank+mm.SLOT_ROOT, ROOT+16)
    if bad == 'camera': be.seed_u32(bank+mm.SLOT_CAMERA, CAM+16)
    if bad == 'anchor': be.seed_u32(bank+mm.SLOT_ANCHOR, mm.ENTITY_COUNT)
    if bad == 'valid': be.seed_u32(bank+mm.SLOT_MOVE, 0)
    if bad == 'reserved': be.seed_u32(bank+mm.SLOT_MOVE, mm.MOVE_VALID | 8)
    dest, got, _ = movement_frame(be, controller=ROOT+mm.TOWN_CONTROLLER_OFFSET+(16 if bad=='controller' else 0))
    assert dest == mm.TOWN_MOVE_NATIVE
    assert got == (0, .25, 1, 1)


@pytest.mark.parametrize('back_yaw,sector', [(0, 1), (45, 5), (90, 2), (135, 4),
    (180, 0), (225, 7), (270, 3), (-45, 6), (22.49, 1), (22.51, 5), (-22.51, 6), (-22.49, 1)])
@pytest.mark.parametrize('site', [0, 1])
def test_dungeon_generated_movement_returns_native_quantized_sector(dungeon_be, back_yaw, sector, site):
    adapter = DruagaAdapter(dungeon_be)
    adapter.write_orbit_params(DUNGEON_PLAYER, back_yaw, -35, 22, target_offset=Vec3(0, 0, 0))
    assert dungeon_be.read_u32(active_bank(dungeon_be)+mm.SLOT_MOVE) == mm.MOVE_VALID | sector
    dest, _, regs = movement_frame(dungeon_be, dungeon=True, site=site)
    assert dest == mm.DUNGEON_MOVE_SITES[site]+8 and regs[m.V0] == sector


@pytest.mark.parametrize('caller,accepted', [(0x00452404, True), (0x0045598C, True),
                                           (0x0055F4D8, False), (0, False)])
def test_dungeon_movement_excludes_target_selection_ui(dungeon_be, caller, accepted):
    DruagaAdapter(dungeon_be).set_patch(True)
    dest, _, _ = movement_frame(dungeon_be, dungeon=True, caller=caller)
    assert dest == (mm.DUNGEON_MOVE_SITES[0]+8 if accepted else mm.DUNGEON_SECTOR_FUN)


@pytest.mark.parametrize('bad', ['manager', 'event', 'transition', 'actor', 'anchor', 'fov_only', 'town'])
def test_dungeon_movement_falls_back_native_for_scene_and_owner_mismatch(dungeon_be, bad):
    DruagaAdapter(dungeon_be).set_patch(True)
    if bad == 'event': dungeon_be.seed_u32(mm.EVENT_ACTIVE, 1)
    if bad == 'transition': dungeon_be.seed_u32(DUNGEON_CAM+0x2DC, 1 << 16)
    if bad == 'actor': dungeon_be.seed_u32(DUNGEON_ACTOR+mm.ACTOR_ENTITY_PTR, 0)
    if bad == 'anchor': dungeon_be.seed_u32(active_bank(dungeon_be)+mm.SLOT_ANCHOR, 64)
    if bad == 'fov_only': dungeon_be.seed_u32(mm.MOD_BLOCK+mm.MB_FLAGS, mm.FLAG_FOV)
    if bad == 'town': dungeon_be.seed_u32(DUNGEON_ROOT, mm.ROOT_VTABLE)
    dest, _, _ = movement_frame(dungeon_be, dungeon=True,
                                manager=mm.DUNGEON_MANAGER+(16 if bad=='manager' else 0))
    assert dest == mm.DUNGEON_SECTOR_FUN


@pytest.mark.parametrize('dungeon', [False, True])
def test_movement_seq_change_during_read_rejects_without_partial_local_write(dungeon):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else seed_field(FakeBackend())
    DruagaAdapter(backend).set_patch(True)
    fired = []
    def interleave(pc, word):
        if not fired and word == m.lw(m.T6, m.T0, mm.MB_MOVE_SEQ):
            fired.append(True)
            backend.seed_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ, backend.read_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ)+2)
    local = (.03, .25, .04, 1)
    dest, got, _ = movement_frame(backend, dungeon=dungeon, local=local, on_step=interleave)
    assert fired and got == pytest.approx(local)
    assert dest == (mm.DUNGEON_SECTOR_FUN if dungeon else mm.TOWN_MOVE_NATIVE)


@pytest.mark.parametrize('dungeon', [False, True])
def test_movement_degenerate_actual_horizontal_vector_falls_back_but_near_vertical_works(dungeon):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else seed_field(FakeBackend())
    adapter = DruagaAdapter(backend)
    adapter.write_orbit_params(PLAYER, 0, -89.5, 22, target_offset=Vec3(0, 0, 0))
    dest, _, _ = movement_frame(backend, dungeon=dungeon)
    assert dest == (mm.DUNGEON_MOVE_SITES[0]+8 if dungeon else mm.TOWN_MOVE_RETURN)
    # Cancel only horizontal eye offset exactly; there is no safe heading now.
    eye = adapter._last_orbit[0]
    adapter.write_orbit_params(PLAYER, 0, -89.5, 22, pos_offset=Vec3(0, 0, -eye.z), target_offset=Vec3(0, 0, 0))
    assert backend.read_u32(active_bank(backend)+mm.SLOT_MOVE) == 0
    dest, _, _ = movement_frame(backend, dungeon=dungeon)
    assert dest == (mm.DUNGEON_SECTOR_FUN if dungeon else mm.TOWN_MOVE_NATIVE)


@pytest.mark.parametrize('resource', range(3))
@pytest.mark.parametrize('kind', ['hook', 'delay', 'cave'])
def test_unknown_movement_resources_reject_activation_and_republish_with_zero_writes(be, resource, kind):
    address, _, _, cave, words = caves.MOVEMENT_RESOURCES[resource]
    target = address if kind == 'hook' else address+4 if kind == 'delay' else cave+len(words)*4-4
    be.seed_u32(target, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): DruagaAdapter(be).set_patch(True)
    assert not be.writes


def test_movement_install_restore_fov_only_and_stock_reload(be):
    adapter = DruagaAdapter(be)
    adapter.write_fov_deg(60)
    assert caves.movement_state(be) == 'stock'
    adapter.set_patch(True)
    assert caves.movement_state(be) == 'applied'
    addresses = [a for a, _ in be.writes]
    assert addresses.index(mm.MOD_BLOCK+mm.MB_MOVE_SEQ) < addresses.index(mm.TOWN_MOVE_HOOK)
    assert all(address+4 not in addresses for address, *_ in caves.MOVEMENT_RESOURCES)
    adapter.set_patch(False)
    assert caves.movement_state(be) == 'stock' and caves.site_state(be) == 'applied'
    adapter.restore_fov()
    assert caves.site_state(be) == 'stock'
    adapter.set_patch(True)
    be.mem = seed_field(FakeBackend()).mem
    adapter.set_patch(True)
    assert caves.movement_state(be) == 'applied'
    adapter.set_patch(False)
    assert caves.movement_state(be) == 'stock'


@pytest.mark.parametrize('resource', range(3))
def test_active_unknown_movement_site_blocks_republish_and_restore_without_writes(be, resource):
    adapter = DruagaAdapter(be)
    adapter.set_patch(True)
    be.seed_u32(caves.MOVEMENT_RESOURCES[resource][0], 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict): adapter.write_fov_deg(60)
    with pytest.raises(caves.PatchConflict): adapter.set_patch(False)
    assert not be.writes


def test_movement_known_mixed_reconnect_preflights_code_before_publish(be):
    adapter = DruagaAdapter(be)
    adapter.set_patch(True)
    be.seed_u32(mm.TOWN_MOVE_HOOK, mm.TOWN_MOVE_STOCK[0])
    be.seed_u32(mm.TOWN_MOVE_CAVE, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict): adapter.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('dungeon', [False, True])
def test_publish_odd_seq_rejects_each_partial_bank_and_slot_flags_transition(dungeon):
    backend = seed_dungeon_field(FakeBackend()) if dungeon else seed_field(FakeBackend())
    adapter = DruagaAdapter(backend)
    adapter.write_orbit_params(PLAYER, 0, -35, 22, target_offset=Vec3(0, 0, 0))
    seen = []
    def observe(address, data):
        if address not in range(mm.MOD_BLOCK, mm.MOD_BLOCK+mm.BLOCK_SIZE): return
        odd = backend.read_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ) & 1
        if not odd: return
        dest, local, _ = movement_frame(backend, dungeon=dungeon, local=(.03, .25, .04, 1))
        seen.append(address)
        assert dest == (mm.DUNGEON_SECTOR_FUN if dungeon else mm.TOWN_MOVE_NATIVE)
        assert local == pytest.approx((.03, .25, .04, 1))
    backend.on_write = observe
    adapter.write_orbit_params(PLAYER, 90, -35, 22, target_offset=Vec3(0, 0, 0))
    backend.on_write = None
    assert mm.MOD_BLOCK+mm.MB_SLOT in seen and mm.MOD_BLOCK+mm.MB_FLAGS in seen
    assert len(seen) >= 17
    dest, _, regs = movement_frame(backend, dungeon=dungeon)
    assert dest == (mm.DUNGEON_MOVE_SITES[0]+8 if dungeon else mm.TOWN_MOVE_RETURN)
    if dungeon: assert regs[m.V0] == 2


def test_dungeon_sector_uses_offset_eye_target_not_yaw_setting(dungeon_be):
    adapter = DruagaAdapter(dungeon_be)
    adapter.write_orbit_params(PLAYER, 0, -35, 2, pos_offset=Vec3(10, 1, -2),
                               target_offset=Vec3(4, 3, -7))
    # Original yaw0 gives native sector1. Offset moves actual back to near +X.
    dest, _, regs = movement_frame(dungeon_be, dungeon=True)
    assert dest == mm.DUNGEON_MOVE_SITES[0]+8 and regs[m.V0] == 2


def test_movement_cave_reservations_branch_targets_and_hook_delay_slots():
    assert mm.MOD_BLOCK+mm.BLOCK_SIZE <= mm.TOWN_MOVE_CAVE
    assert mm.TOWN_MOVE_CAVE+4*len(caves.TOWN_MOVE_WORDS) <= mm.TOWN_MOVE_CAVE_END <= mm.DUNGEON_MOVE_CAVE
    assert mm.DUNGEON_MOVE_CAVE+4*len(caves.DUNGEON_MOVE_WORDS) <= mm.DUNGEON_MOVE_CAVE_END < 0x400000
    assert caves.TOWN_MOVE_HOOK[1] == mm.TOWN_MOVE_STOCK[1]
    assert caves.DUNGEON_MOVE_HOOK[1] == mm.DUNGEON_MOVE_STOCK[1]
    for words in (caves.TOWN_MOVE_WORDS, caves.DUNGEON_MOVE_WORDS):
        for i, word in enumerate(words):
            if word >> 26 in (4, 5):
                off = word & 65535
                assert 0 <= i+1+(off-65536 if off & 32768 else off) < len(words)
