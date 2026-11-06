"""DQ5 contracts on synthetic sparse memory, never emulator or game data.

The small instruction runner reuses the Radiata R5900 subset and models only
DQ5's native render/pad call boundaries. It establishes publication, ownership,
ABI and restoration contracts, not real rendering, PS2 scheduling or scene coverage.
"""
from __future__ import annotations

import math

import pytest

from adapters.dragonquest5 import caves, memory_map as mm
from adapters.dragonquest5.adapter import DragonQuest5Adapter
from core import mips_asm as m
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT, MODE_ORIGINAL
from core.memory_backend.guard import CHANGED, GuardedBackend, WriteBlocked
from tests.test_druaga import FakeBackend as ByteBackend
from tests.test_radiata import CaveMachine as RadiataMachine

ACTOR, NODE = 0x01000000, 0x01001000
PAD, GP = 0x01002000, 0x01010000
PLAYER = Vec3(100.0, 30.0, -50.0)
NATIVE = orbit_pose(PLAYER + Vec3(0, 10, 0), math.radians(-147.73), math.radians(-32), 157.223)


class FakeBackend(ByteBackend):
    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)
        # No scheduler exists in sparse memory. One command poll may run the
        # emitted guest lifecycle, never a Python model that writes hook words.
        self.auto_guest_cleanup = True
        self._in_guest_cleanup = False
        self.before_guest_cleanup = None
        self.guest_cleanup_count = 0
        self.guest_install_count = 0

    def read_u32(self, address):
        value = super().read_u32(address)
        if (address == mm.MOD_BLOCK + mm.MB_COMMAND and value in (mm.CMD_UNINSTALL, mm.CMD_INSTALL)
                and self.auto_guest_cleanup and not self._in_guest_cleanup
                and super().read_u32(mm.RENDER_HOOK) == m.jal(mm.RENDER_CAVE)
                and super().read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0):
            self._in_guest_cleanup = True
            try:
                if value == mm.CMD_UNINSTALL:
                    self.guest_cleanup_count += 1
                else:
                    self.guest_install_count += 1
                if self.before_guest_cleanup is not None:
                    self.before_guest_cleanup(self)
                CaveMachine(self).render()
            finally:
                self._in_guest_cleanup = False
            value = super().read_u32(address)
        return value

    def title(self):
        return 'DRAGON QUEST V'

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]


def seed_projection(b, rad):
    """Invent the two native outputs consumed by the adapter, not a render model."""
    b.seed_floats(mm.CAM_PROJECTION, [math.cos(rad / 2)])
    b.seed_floats(mm.CAM_PROJECTION + 0x2C, [math.sin(rad / 2)])


def seed_field(b, *, node=NODE, player=PLAYER, lens=mm.STOCK_FOV_RAD):
    for address, value in mm.EXACT_GUARDS:
        b.seed_u32(address, value)
    for address in mm.ZERO_HALF_GUARDS:
        b.seed_u32(address & ~3, 0)
    b.seed_u32(mm.PLAYER_PTR, ACTOR)
    b.seed_u32(ACTOR + mm.PLAYER_NODE, node)
    b.seed_floats(node + mm.NODE_POSITION, (*player.as_tuple(), 1))
    b.seed_floats(mm.CAM_EYE, (*NATIVE.eye.as_tuple(), 1))
    b.seed_floats(mm.CAM_TARGET, (*NATIVE.target.as_tuple(), 1))
    b.seed_floats(mm.CAM_YAW, [0.75, -0.25, 150, 1])
    b.seed_floats(mm.WORLD, DragonQuest5Adapter._world(NATIVE))
    b.seed_floats(mm.CAM_FOV, [lens])
    seed_projection(b, lens)
    b.seed_u32(GP - 0x6788, PAD)
    b.seed_u32(PAD + 0x190, 0xFFFFFFC0)
    b.seed_u32(PAD + 0x194, 37)
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


class CaveMachine(RadiataMachine):
    """Reuse integer/FPU execution, with explicit synthetic DQ5 call boundaries."""
    def __init__(self, backend):
        super().__init__(backend)
        self.regs[28] = GP
        self.on_render = None
        self.on_pad = None

    def native(self, target):
        if target == mm.FUN_RENDER:
            self.calls.append(('render', self.regs[m.A0],
                               self.b.read_floats(mm.WORLD, 16), self.b.read_f32(mm.CAM_FOV)))
            if self.on_render is not None:
                self.on_render(self)
            seed_projection(self.b, self.b.read_f32(mm.CAM_FOV))
        elif target == mm.FUN_PAD_CAMERA:
            self.calls.append(('pad', self.regs[m.A0], self.b.read_u32(PAD + 0x190),
                               self.b.read_u32(PAD + 0x194)))
            if self.on_pad is not None:
                self.on_pad(self)
        else:
            raise AssertionError(f'unexpected DQ5 native boundary {target:08X}')
        # Native callees may overwrite caller-saved scratch and argument registers.
        for r in (*range(m.T0, m.T7 + 1), m.A0, m.A1, m.A2, m.A3):
            self.regs[r] = 0xBAD00000 | r

    def render(self, renderer=mm.RENDERER):
        self.regs[m.A0] = renderer
        self.run(mm.RENDER_CAVE)
        return self.calls[-1]

    def pad(self, camera=mm.CAM_EYE):
        self.regs[m.A0] = camera
        self.run(mm.PAD_CAVE)
        return self.calls[-1]


@pytest.mark.parametrize('serial,crc,matched', [
    (mm.GAME_ID, mm.DISC_CRC, True), (' slpm-65555 ', ' b64e9939 ', True),
    (mm.GAME_ID, 'DEADBEEF', False), (mm.GAME_ID, '', False),
    ('SLPM-65920', mm.DISC_CRC, False), ('', '', False),
])
def test_identity_requires_both_verified_serial_and_crc_without_writes(serial, crc, matched):
    b = FakeBackend(serial, crc)
    assert DragonQuest5Adapter(b).identify().matched is matched
    assert not b.writes


def test_identity_transport_failure_is_read_only(be):
    def broken():
        raise OSError('synthetic unavailable identity')
    be.crc = broken
    info = DragonQuest5Adapter(be).identify()
    assert not info.matched and 'PINE error' in info.reason
    assert not be.writes


def test_native_reads_metadata_and_defaults_never_write(be):
    ad = DragonQuest5Adapter(be)
    assert ad.read_player() == PLAYER
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(NATIVE.eye.as_tuple())
    assert ad.read_game_pose().target.as_tuple() == pytest.approx(NATIVE.target.as_tuple())
    assert ad.read_scene().valid and ad.is_field_like(ad.read_scene())
    assert ad.capture_original_fov() == pytest.approx(ad.read_fov_deg(), abs=1e-5)
    assert ad.name == 'DRAGONQUEST5' and ad.display_name_key == 'game.dragonquest5'
    assert ad.features == dict(orbit=True, free_camera=False, fov=True,
                               position_offsets=True, target_offsets=True, per_frame_write=False)
    assert ad.accepts_orbit_offsets and not ad.uses_offset_injection
    defaults = ad.default_settings()
    assert defaults['distance'] == mm.STOCK_DISTANCE
    assert defaults['look_height'] == ad.default_look_height() == 10
    assert defaults['pitch_deg'] < 0
    assert defaults['fov_deg'] == pytest.approx(ad.capture_original_fov())
    ad.set_stick_block(True)
    ad.set_stick_block(False)
    assert not be.writes


BAD_GUARDS = ([(a, v ^ 1) for a, v in mm.EXACT_GUARDS]
              + [(a, 1) for a in mm.ZERO_HALF_GUARDS])


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_host_scene_guard_rejects_before_any_write(be, address, value):
    be.seed_u32(address, value)
    ad = DragonQuest5Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    with pytest.raises(caves.PatchConflict): ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('address', mm.ZERO_HALF_GUARDS)
def test_host_halfword_guards_ignore_adjacent_high_halfword(be, address):
    be.seed_u32(address, 0xABCD0000)
    assert DragonQuest5Adapter(be).read_scene().valid
    assert not be.writes


@pytest.mark.parametrize('address', [mm.PLAYER_PTR, ACTOR + mm.PLAYER_NODE])
@pytest.mark.parametrize('pointer', [0, 0xFFFF0, 0x1000001, 0x1FFFFF0, 0x2000000])
def test_host_player_pointer_bounds_and_alignment_are_checked(be, address, pointer):
    be.seed_u32(address, pointer)
    ad = DragonQuest5Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('address', [NODE + mm.NODE_POSITION, mm.CAM_EYE, mm.CAM_TARGET, mm.CAM_FOV])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 1e7])
def test_invalid_native_geometry_and_lens_are_rejected_without_writes(be, address, bad):
    be.seed_floats(address, [bad])
    ad = DragonQuest5Adapter(be)
    assert not ad.read_scene().valid
    with pytest.raises(caves.PatchConflict): ad.set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('kind', ['centre', 'pos_offset', 'target_offset', 'yaw_deg', 'pitch_deg', 'distance', 'fov'])
def test_nonfinite_requests_are_rejected_without_writes(be, kind):
    ad = DragonQuest5Adapter(be)
    args = dict(centre=PLAYER, yaw_deg=0, pitch_deg=-30, distance=160,
                pos_offset=Vec3(0, 0, 0), target_offset=Vec3(0, 10, 0))
    if kind == 'fov':
        call = lambda: ad.write_fov_deg(float('nan'))
    else:
        args[kind] = Vec3(float('nan'), 0, 0) if kind in ('centre', 'pos_offset', 'target_offset') else float('inf')
        call = lambda: ad.write_orbit_params(**args)
    with pytest.raises(ValueError): call()
    assert not be.writes


@pytest.mark.parametrize('address', [mm.CAM_PROJECTION, mm.CAM_PROJECTION + 0x2C])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 0.0])
def test_rendered_projection_guard_rejects_invalid_lens_readback_without_writes(be, address, bad):
    be.seed_floats(address, [bad])
    ad = DragonQuest5Adapter(be)
    scene = ad.read_scene()
    assert not scene.valid and not ad.is_field_like(scene)
    assert 'projection' in scene.reason
    assert not be.writes


@pytest.mark.parametrize('field', [mm.MB_RENDER_EYE, mm.MB_RENDER_TARGET])
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 1e7])
def test_rendered_pose_guard_rejects_corrupt_owned_output_without_writes(be, field, bad):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    CaveMachine(be).render()
    be.seed_floats(mm.MOD_BLOCK + field, [bad])
    be.writes.clear()
    assert not ad.read_scene().valid
    assert not be.writes


@pytest.mark.parametrize('position', [Vec3(0, 0, -100), Vec3(0, 10, -100)])
def test_degenerate_or_vertical_offset_request_is_rejected_before_any_write(be, position):
    ad = DragonQuest5Adapter(be)
    with pytest.raises((ValueError, ZeroDivisionError)):
        ad.write_orbit_params(PLAYER, 0, 0, 100, pos_offset=position, target_offset=Vec3(0, 0, 0))
    assert not be.writes
    assert_stock(be)


def test_y_up_pitch_display_and_input_keep_internal_saved_convention(be):
    ad = DragonQuest5Adapter(be)
    assert ad.PITCH_DISPLAY_SIGN == ad.PITCH_INPUT_SIGN == -1
    assert ad.PITCH_POSITIVE_IS == 'above' and ad.LOOK_HEIGHT_POSITIVE_IS == 'up'
    assert ad.PITCH_RANGE == (-89.5, 25)
    internal = -32
    pose = orbit_pose(Vec3(0, 0, 0), 0, math.radians(internal), 100)
    assert pose.eye.y > 0 and internal * ad.PITCH_DISPLAY_SIGN > 0
    settings = CameraSettings(pitch_deg=internal, pitch_min_deg=-20, pitch_max_deg=85)
    rt = CameraRuntime(ad, settings)
    rt.set_stick(0, 1)
    rt._integrate(.01)
    assert settings.pitch_deg < internal
    settings.pitch_deg = -89
    rt._integrate(.1)
    assert settings.pitch_deg == -89.5
    settings.pitch_deg = internal
    settings.invert_y = True
    rt._integrate(.01)
    assert settings.pitch_deg > internal
    assert not be.writes


@pytest.mark.parametrize('yaw,pitch,distance', [(0, -30, 160), (90, 20, 200), (-135, -80, 60), (720, -89.5, 500)])
def test_world_basis_is_orthonormal_and_stores_eye_translation(be, yaw, pitch, distance):
    pose = orbit_pose(Vec3(7, 10, -3), math.radians(yaw), math.radians(pitch), distance)
    pose = CameraPose(pose.eye + Vec3(10, 20, -15), pose.target)
    matrix = DragonQuest5Adapter._world(pose)
    right, up, forward = [matrix[i:i + 3] for i in (0, 4, 8)]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    for axis in (right, up, forward):
        assert dot(axis, axis) == pytest.approx(1, abs=1e-10)
    assert dot(right, up) == pytest.approx(0, abs=1e-10)
    assert dot(right, forward) == pytest.approx(0, abs=1e-10)
    assert dot(up, forward) == pytest.approx(0, abs=1e-10)
    cross = (right[1] * up[2] - right[2] * up[1], right[2] * up[0] - right[0] * up[2],
             right[0] * up[1] - right[1] * up[0])
    assert cross == pytest.approx(forward)
    actual = (pose.target - pose.eye).scaled(1 / pose.distance())
    assert forward == pytest.approx(actual.as_tuple())
    assert matrix[12:15] == pose.eye.as_tuple()
    assert (matrix[3], matrix[7], matrix[11], matrix[15]) == (0, 0, 0, 1)
    assert not be.writes


@pytest.mark.parametrize('yaw,pitch,distance', [(0, -30, 160), (90, -60, 200), (-135, 15, 60)])
def test_relative_offsets_use_latest_guest_actor_and_preserve_native_rig(be, yaw, pitch, distance):
    ad = DragonQuest5Adapter(be)
    target, position = Vec3(4, 10, -3), Vec3(5, 7, -8)
    native_world = be.bytes_at(mm.WORLD, 64)
    native_rig = {a: be.bytes_at(a, 16) for a in (mm.CAM_EYE, mm.CAM_TARGET, mm.CAM_YAW)}
    ad.write_orbit_params(Vec3(9000, 8000, 7000), yaw, pitch, distance,
                          pos_offset=position, target_offset=target)
    relative = orbit_pose(target, math.radians(yaw), math.radians(pitch), distance)
    relative = CameraPose(relative.eye + position, relative.target)
    bank = active_bank(be)
    assert be.read_floats(bank + mm.SLOT_WORLD, 16) == pytest.approx(ad._world(relative))
    assert be.read_floats(bank + mm.SLOT_TARGET, 4) == pytest.approx((*target.as_tuple(), 1))
    fresh = PLAYER + Vec3(100, -20, 50)
    be.seed_floats(NODE + mm.NODE_POSITION, (*fresh.as_tuple(), 1))
    machine = CaveMachine(be)
    saved = {r: machine.regs[r] for r in (m.SP, 31, 28, *range(16, 24))}
    call = machine.render()
    expected = CameraPose(relative.eye + fresh, relative.target + fresh)
    assert call[0:2] == ('render', mm.RENDERER)
    assert call[2] == pytest.approx(ad._world(expected), abs=3e-5)
    assert ad.read_game_pose().eye.as_tuple() == pytest.approx(expected.eye.as_tuple(), abs=3e-5)
    assert ad.read_game_pose().target.as_tuple() == pytest.approx(expected.target.as_tuple(), abs=3e-5)
    assert ad.heartbeat_word() == 1
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert be.bytes_at(mm.WORLD, 64) == native_world
    assert all(be.bytes_at(a, 16) == data for a, data in native_rig.items())
    assert {r: machine.regs[r] for r in saved} == saved


@pytest.mark.parametrize('pitch,distance,expected_pitch,expected_distance', [
    (-120, 1, -89.5, 20), (90, 2000, 25, 600),
])
def test_orbit_native_boundary_clamps_pitch_and_distance(be, pitch, distance, expected_pitch, expected_distance):
    ad = DragonQuest5Adapter(be)
    target = Vec3(0, 10, 0)
    ad.write_orbit_params(PLAYER, 90, pitch, distance, target_offset=target)
    expected = orbit_pose(target, math.pi / 2, math.radians(expected_pitch), expected_distance)
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == pytest.approx(ad._world(expected))


@pytest.mark.parametrize('requested,clamped', [(1, 20), (40, 40), (80, 80), (150, 110)])
def test_fov_conversion_reads_rendered_projection_and_preserves_native_lens(be, requested, clamped):
    ad = DragonQuest5Adapter(be)
    native_lens = be.bytes_at(mm.CAM_FOV, 4)
    native_world = be.bytes_at(mm.WORLD, 64)
    original = ad.capture_original_fov()
    ad.set_patch(True)
    ad.write_fov_deg(requested)
    native_angle = 2 * math.atan(mm.PROJECTION_X_FACTOR * math.tan(math.radians(clamped) / 2))
    assert be.read_f32(active_bank(be) + mm.SLOT_FOV) == pytest.approx(native_angle)
    assert not ad.fov_in_sync(clamped)
    call = CaveMachine(be).render()
    assert call[3] == pytest.approx(native_angle)
    assert ad.read_fov_deg() == pytest.approx(clamped, abs=1e-5)
    assert ad.fov_in_sync(clamped)
    assert ad.capture_original_fov() == pytest.approx(original)
    assert be.bytes_at(mm.CAM_FOV, 4) == native_lens
    assert be.bytes_at(mm.WORLD, 64) == native_world
    ad.write_fov_deg(clamped)
    assert be.read_f32(active_bank(be) + mm.SLOT_FOV) == pytest.approx(native_angle)
    ad.restore_fov()
    CaveMachine(be).render()
    assert ad.read_fov_deg() == pytest.approx(original, abs=1e-5)
    ad.set_patch(False)
    assert_stock(be)


@pytest.mark.parametrize('invalid', ['flags', 'hook', 'projection'])
def test_fov_sync_does_not_trust_host_cache_without_active_owned_output(be, invalid):
    ad = DragonQuest5Adapter(be)
    ad.write_fov_deg(60)
    CaveMachine(be).render()
    assert ad.fov_in_sync(60)
    if invalid == 'flags': be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    elif invalid == 'hook': be.seed_u32(mm.RENDER_HOOK, 0xDEADBEEF)
    else: seed_projection(be, mm.STOCK_FOV_RAD)
    be.writes.clear()
    assert not ad.fov_in_sync(60)
    assert not be.writes


def test_fov_readback_uses_projection_not_the_native_control_angle(be):
    ad = DragonQuest5Adapter(be)
    seed_projection(be, ad._native_fov(75))
    assert ad.read_fov_deg() == pytest.approx(75, abs=1e-5)
    assert ad.capture_original_fov() != pytest.approx(75)
    assert not be.writes


@pytest.mark.parametrize('site', range(len(caves.RESOURCES)))
@pytest.mark.parametrize('resource', ['hook', 'delay', 'cave'])
@pytest.mark.parametrize('operation', ['orbit', 'fov'])
def test_all_resources_preflight_before_any_parameter_or_hook_write(be, site, resource, operation):
    address, _, _, cave, words = caves.RESOURCES[site]
    bad = address if resource == 'hook' else address + 4 if resource == 'delay' else cave + 4 * (len(words) - 1)
    be.seed_u32(bad, 0xDEADBEEF)
    ad = DragonQuest5Adapter(be)
    with pytest.raises(caves.PatchConflict):
        if operation == 'orbit': ad.set_patch(True)
        else: ad.write_fov_deg(60)
    assert not be.writes


@pytest.mark.parametrize('address', [mm.MOD_BLOCK, mm.MOD_BLOCK + mm.BLOCK_SIZE - 4])
def test_occupied_control_block_is_refused_without_any_writes(be, address):
    be.seed_u32(address, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict): DragonQuest5Adapter(be).set_patch(True)
    assert not be.writes


@pytest.mark.parametrize('site', range(len(caves.RESOURCES)))
@pytest.mark.parametrize('resource', ['hook', 'delay', 'cave'])
def test_active_resource_corruption_blocks_publish_and_release_without_writes(be, site, resource):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    address, _, _, cave, _ = caves.RESOURCES[site]
    bad = address if resource == 'hook' else address + 4 if resource == 'delay' else cave + 4
    be.seed_u32(bad, 0xDEADBEEF)
    be.writes.clear()
    with pytest.raises(caves.PatchConflict): ad.write_orbit_params(PLAYER, 90, -30, 160)
    with pytest.raises(caves.PatchConflict): ad.set_patch(False)
    assert not be.writes


@pytest.mark.parametrize('site', range(len(caves.RESOURCES)))
def test_zeroed_cave_with_owned_hook_is_refused_without_live_code_rebuilding(be, site):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    _, _, _, address, words = caves.RESOURCES[site]
    be.seed(address, bytes(4 * len(words)))
    be.writes.clear()
    with pytest.raises(caves.PatchConflict):
        ad.write_orbit_params(PLAYER, 90, -30, 160)
    with pytest.raises(caves.PatchConflict):
        ad.set_patch(False)
    assert not be.writes
    assert caves.read_words(be, address, len(words)) == (0,) * len(words)
    assert caves.site_state(be) == 'applied'


def test_publish_sequence_completes_inactive_bank_before_active_slot_and_flags(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    be.writes.clear()
    ad.write_orbit_params(PLAYER, 80, -30, 160)
    bank = active_bank(be)
    writes = [(a, int.from_bytes(data, 'little')) for a, data in be.writes]
    sequence = [(i, v) for i, (a, v) in enumerate(writes) if a == bank + mm.SLOT_SEQUENCE]
    flip = next(i for i, (a, _) in enumerate(writes) if a == mm.MOD_BLOCK + mm.MB_SLOT)
    flags = next(i for i, (a, _) in enumerate(writes) if a == mm.MOD_BLOCK + mm.MB_FLAGS)
    assert len(sequence) == 2
    assert sequence[0][1] & 1 and not sequence[1][1] & 1
    assert sequence[0][0] < sequence[1][0] < flip < flags
    assert all(bank <= a < bank + mm.SLOT_SIZE for a, _ in writes[:flip])
    assert all(a != address + 4 for a, _ in writes for address, _, _, _, _ in caves.RESOURCES)


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_guest_scene_guards_use_native_render_and_pad_after_host_publication(be, address, value):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    native = be.read_floats(mm.WORLD, 16)
    lens = be.read_f32(mm.CAM_FOV)
    be.seed_u32(address, value)
    machine = CaveMachine(be)
    call = machine.render()
    assert call[2] == native and call[3] == lens
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert machine.pad()[2] == 0xFFFFFFC0
    assert be.read_u32(PAD + 0x190) == 0xFFFFFFC0


@pytest.mark.parametrize('unstable', ['odd', 'changed', 'bad_magic', 'no_flags', 'slot_flags', 'wrong_node', 'bad_owner', 'other_renderer'])
def test_guest_rejects_unstable_bank_or_wrong_owner_without_modifying_native_camera(be, unstable):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    bank = active_bank(be)
    if unstable == 'odd': be.seed_u32(bank + mm.SLOT_SEQUENCE, 3)
    elif unstable == 'bad_magic': be.seed_u32(mm.MOD_BLOCK, 0)
    elif unstable == 'no_flags': be.seed_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    elif unstable == 'slot_flags': be.seed_u32(bank + mm.SLOT_FLAGS, 0)
    elif unstable == 'wrong_node': be.seed_u32(ACTOR + mm.PLAYER_NODE, NODE + 0x1000)
    elif unstable == 'bad_owner': be.seed_u32(mm.PLAYER_PTR, 0)
    elif unstable == 'changed':
        original = be.read_u32
        def changed(address):
            value = original(address)
            if address == bank + mm.SLOT_SEQUENCE: be.seed_u32(address, value + 2)
            return value
        be.read_u32 = changed
    native = be.bytes_at(mm.WORLD, 64)
    lens = be.bytes_at(mm.CAM_FOV, 4)
    machine = CaveMachine(be)
    call = machine.render(mm.RENDERER + 0x100 if unstable == 'other_renderer' else mm.RENDERER)
    assert call[2] == be.read_floats(mm.WORLD, 16)
    assert be.bytes_at(mm.WORLD, 64) == native and be.bytes_at(mm.CAM_FOV, 4) == lens
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert ad.heartbeat_word() == 0


def test_guest_snapshot_survives_two_host_publications_during_render_and_restores_native(be):
    ad = DragonQuest5Adapter(be)
    ad.write_orbit_params(PLAYER, 75, -35, 180, target_offset=Vec3(0, 10, 0))
    ad.write_fov_deg(60)
    native = be.bytes_at(mm.WORLD, 64)
    lens = be.bytes_at(mm.CAM_FOV, 4)
    first_bank = active_bank(be)
    requested = be.read_f32(first_bank + mm.SLOT_FOV)
    machine = CaveMachine(be)
    def republish(runner):
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)
        ad.write_orbit_params(PLAYER, -90, -10, 200)
        ad.write_fov_deg(90)
        assert active_bank(be) == first_bank
        assert be.read_f32(mm.CAM_FOV) == pytest.approx(requested)
        assert be.read_f32(mm.MOD_BLOCK + mm.MB_SNAPSHOT + mm.SLOT_FOV) == pytest.approx(requested)
    machine.on_render = republish
    call = machine.render()
    assert call[3] == pytest.approx(requested)
    assert be.bytes_at(mm.WORLD, 64) == native and be.bytes_at(mm.CAM_FOV, 4) == lens
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0
    assert ad.read_fov_deg() == pytest.approx(60, abs=1e-5)
    assert not ad.fov_in_sync(90)


def test_guest_fov_restore_preserves_a_new_native_lens_written_during_render(be):
    ad = DragonQuest5Adapter(be)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    machine.on_render = lambda runner: be.seed_floats(mm.CAM_FOV, [.75])
    machine.render()
    assert be.read_f32(mm.CAM_FOV) == .75


def test_guest_existing_transaction_is_not_overwritten(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_PENDING, 123)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_SAVED_WORLD, 0xDEADBEEF)
    native = be.read_floats(mm.WORLD, 16)
    assert CaveMachine(be).render()[2] == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 123
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_SAVED_WORLD) == 0xDEADBEEF


def test_scoped_pad_suppression_restores_processed_rx_and_keeps_other_axes(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    raw = b'invented raw left-right-buttons'
    be.seed(PAD, raw)
    machine = CaveMachine(be)
    saved = {r: machine.regs[r] for r in (m.SP, 31, 28, *range(16, 24))}
    call = machine.pad()
    assert call == ('pad', mm.CAM_EYE, 0, 37)
    assert be.read_u32(PAD + 0x190) == 0xFFFFFFC0
    assert be.read_u32(PAD + 0x194) == 37
    assert be.bytes_at(PAD, len(raw)) == raw
    assert {r: machine.regs[r] for r in saved} == saved
    assert CaveMachine(be).pad(mm.CAM_EYE + 0x100)[2] == 0xFFFFFFC0
    ad.set_patch(False)
    assert_stock(be)


def test_fov_only_render_and_pad_keep_native_camera_and_input(be):
    ad = DragonQuest5Adapter(be)
    native = be.read_floats(mm.WORLD, 16)
    lens = be.bytes_at(mm.CAM_FOV, 4)
    ad.write_fov_deg(60)
    machine = CaveMachine(be)
    call = machine.render()
    assert call[2] == native
    assert call[3] == pytest.approx(ad._native_fov(60))
    assert ad.read_fov_deg() == pytest.approx(60, abs=1e-5)
    assert not ad.patch_active()  # Orbit is off, but the FOV owner is active.
    assert ad.fov_in_sync(60)
    assert be.read_floats(mm.WORLD, 16) == native
    assert be.bytes_at(mm.CAM_FOV, 4) == lens
    assert machine.pad()[2] == 0xFFFFFFC0
    ad.restore_fov()
    assert_stock(be)


@pytest.mark.parametrize('order', ['orbit_first', 'fov_first'])
def test_orbit_fov_release_independently_and_restore_all_sites(be, order):
    ad = DragonQuest5Adapter(be)
    native = be.bytes_at(mm.WORLD, 64)
    lens = be.bytes_at(mm.CAM_FOV, 4)
    ad.set_patch(True)
    ad.write_fov_deg(60)
    CaveMachine(be).render()
    if order == 'orbit_first':
        ad.set_patch(False)
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_FOV
        assert caves.site_state(be) == 'applied'
        ad.restore_fov()
    else:
        ad.restore_fov()
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
        ad.set_patch(False)
    assert_stock(be)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_APPLIED) == 0
    assert be.bytes_at(mm.WORLD, 64) == native and be.bytes_at(mm.CAM_FOV, 4) == lens


def test_paused_transaction_keeps_cleanup_attached_until_guest_finishes(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_PENDING, mm.FLAG_ORBIT)
    with pytest.raises(caves.PatchConflict, match='paused'): ad.set_patch(False)
    assert caves.site_state(be) == 'applied'
    be.seed_u32(mm.MOD_BLOCK + mm.MB_PENDING, 0)
    ad.set_patch(False)
    assert_stock(be)


def test_stock_state_reload_republishes_saved_request_and_current_owned_node(be):
    ad = DragonQuest5Adapter(be)
    ad.write_orbit_params(PLAYER, 75, -35, 180, pos_offset=Vec3(1, 2, 3), target_offset=Vec3(4, 10, 6))
    ad.write_fov_deg(65)
    expected = be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16)
    fresh = seed_field(FakeBackend(), node=NODE + 0x1000, player=PLAYER + Vec3(10, 20, 30), lens=.7)
    be.mem = fresh.mem
    be.writes.clear()
    ad.set_patch(True)
    assert caves.site_state(be) == 'applied'
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == expected
    assert be.read_u32(active_bank(be) + mm.SLOT_NODE) == NODE + 0x1000
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV
    CaveMachine(be).render()
    assert be.read_f32(mm.CAM_FOV) == pytest.approx(.7)
    ad.set_patch(False)
    ad.restore_fov()
    assert_stock(be)
    assert be.read_f32(mm.CAM_FOV) == pytest.approx(.7)


def test_mixed_stock_owned_hooks_reinstall_idempotently_without_touching_delays(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    be.seed_u32(mm.PAD_HOOK, mm.PAD_STOCK[0])
    be.writes.clear()
    ad.set_patch(True)
    assert caves.site_state(be) == 'applied'
    assert all(a != address + 4 for a, _ in be.writes for address, _, _, _, _ in caves.RESOURCES)
    be.writes.clear()
    caves.install(be)
    assert not be.writes
    ad.set_patch(False)
    assert_stock(be)


def test_guarded_adapter_refuses_publish_and_restore_after_game_switch(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    ad = DragonQuest5Adapter(guard)
    ad.set_patch(True)
    be.serial, be.disc_crc = 'SLPM-65920', '2B9AF3C5'
    assert guard.verify() == CHANGED
    be.writes.clear()
    with pytest.raises(WriteBlocked): ad.set_patch(True)
    with pytest.raises(WriteBlocked): ad.set_patch(False)
    assert not be.writes


def test_runtime_dispatch_native_center_restore_and_abandon(be):
    ad = DragonQuest5Adapter(be)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, look_height=10, distance=160,
                                         pos_offset=[1, 2, 3], target_offset=[4, 5, 6],
                                         use_fov=True, fov_deg=60))
    rt._tick(.01, None)
    assert not rt.stats.last_error
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3) == [4, 15, 6]
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV
    assert all(a != 0x340B00 for a, _ in be.reads)
    rt.restore()
    assert rt.settings.mode == MODE_ORIGINAL and not rt.settings.use_fov
    assert_stock(be)
    assert rt.center_on_target()
    rt.restore()
    ad.set_patch(True)
    be.writes.clear()
    rt.abandon()
    assert not be.writes and caves.site_state(be) == 'applied'


def test_runtime_periodic_recheck_republishes_same_cached_request_after_stock_reload(be):
    ad = DragonQuest5Adapter(be)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, look_height=10, distance=160,
                                         pos_offset=[1, 2, 3], target_offset=[4, 5, 6],
                                         use_fov=True, fov_deg=65))
    rt._tick(.01, None)
    expected_world = be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16)
    cached = rt._last_orbit_key
    be.mem = seed_field(FakeBackend(), node=NODE + 0x1000, lens=.7).mem
    rt._patch_checked = rt._scene_time = rt._fov_checked = 0
    rt._tick(.01, None)
    assert not rt.stats.last_error
    assert caves.site_state(be) == 'applied'
    assert rt._last_orbit_key == cached
    assert be.read_floats(active_bank(be) + mm.SLOT_WORLD, 16) == expected_world
    assert be.read_u32(active_bank(be) + mm.SLOT_NODE) == NODE + 0x1000
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT | mm.FLAG_FOV
    rt.restore()
    assert_stock(be)
    assert be.read_f32(mm.CAM_FOV) == pytest.approx(.7)


@pytest.mark.parametrize('address,value', BAD_GUARDS)
def test_runtime_restore_releases_owned_hooks_even_after_scene_becomes_invalid(be, address, value):
    ad = DragonQuest5Adapter(be)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT, look_height=10, distance=160,
                                         use_fov=True, fov_deg=65))
    rt._tick(.01, None)
    be.seed_u32(address, value)
    rt.restore()
    assert not rt.stats.last_error
    assert_stock(be)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0


def test_native_center_uses_current_y_up_view_without_writing_camera_outputs(be):
    ad = DragonQuest5Adapter(be)
    native = {a: be.bytes_at(a, size) for a, size in ((mm.CAM_EYE, 16), (mm.CAM_TARGET, 16), (mm.WORLD, 64))}
    pose = ad.center_on_target(160, 12)
    assert pose.target == PLAYER + Vec3(0, 12, 0)
    assert pose.eye.y > pose.target.y
    assert pose.distance() == pytest.approx(160)
    assert be.read_floats(active_bank(be) + mm.SLOT_TARGET, 3) == [0, 12, 0]
    assert all(be.bytes_at(a, len(data)) == data for a, data in native.items())


def test_nested_render_does_not_replace_outer_transaction_backup(be):
    ad = DragonQuest5Adapter(be)
    ad.set_patch(True)
    native = be.bytes_at(mm.WORLD, 64)
    outer = CaveMachine(be)
    def nested_call(runner):
        backup = be.bytes_at(mm.MOD_BLOCK + mm.MB_SAVED_WORLD, 64)
        applied = be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING)
        nested = CaveMachine(be)
        nested.regs[m.SP] = runner.regs[m.SP]
        nested.render()
        assert be.bytes_at(mm.MOD_BLOCK + mm.MB_SAVED_WORLD, 64) == backup
        assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == applied
    outer.on_render = nested_call
    outer.render()
    assert be.bytes_at(mm.WORLD, 64) == native
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_PENDING) == 0


def test_generated_caves_banks_and_snapshots_fit_and_branches_resolve():
    assert mm.RENDER_CAVE + 4 * len(caves.RENDER_WORDS) <= mm.PAD_CAVE
    assert mm.PAD_CAVE + 4 * len(caves.PAD_WORDS) <= mm.MOD_BLOCK
    assert mm.MB_SNAPSHOT + mm.SLOT_SIZE <= mm.SLOTS[0]
    assert mm.SLOTS[0] + mm.SLOT_SIZE <= mm.SLOTS[1]
    assert mm.SLOTS[1] + mm.SLOT_SIZE <= mm.BLOCK_SIZE
    for _, stock, hook, _, words in caves.RESOURCES:
        assert stock[1] == hook[1]
        for i, word in enumerate(words):
            if word >> 26 in (4, 5):
                offset = word & 65535
                offset = offset - 65536 if offset & 32768 else offset
                assert 0 <= i + 1 + offset < len(words)
