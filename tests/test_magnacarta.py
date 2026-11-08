"""Magna Carta offline adapter/lifecycle self-tests on synthetic guarded memory.

The tiny shared R5900 interpreter executes generated bootstrap instructions;
native render entry is a stub, not an EE/PCSX2 timing or visual verification.
Optional local RAM checks only compare stock hook words against supplied states.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import struct

import pytest

from adapters.magnacarta.adapter import MagnaCartaAdapter
from adapters.magnacarta import caves, memory_map as mm, directions
from core.camera_math.orbit import Vec3
from core.camera_runtime.engine import CameraSettings
from core.config.settings import AppSettings
from core.memory_backend.guard import GuardedBackend, CHANGED
from tests.test_druaga import FakeBackend as ByteBackend
from tests.test_radiata import CaveMachine as BaseMachine

ACTOR, OWNER, STATE = 0x1900000, 0x1800000, 0x1700000
MAGI, SCRIPT_FRAME, SCRIPT_STATE = 0x1600000, 0x1500000, 0x1400000


class BootMachine(BaseMachine):
    def native(self, target):
        assert target == mm.BOOT_NATIVE
        self.calls.append(target)


class FakeBackend(ByteBackend):
    available = connected = True

    def __init__(self, serial=mm.GAME_ID, crc=mm.DISC_CRC):
        super().__init__(serial, crc)
        self.host_writes = []
        self.in_guest = False
        self.auto_guest = True
        self.before_guest = None
        self.guest_count = 0

    def title(self): return 'MAGNACARTA'
    def connect(self): pass
    def close(self): pass
    def read_f32(self, address): return self.read_floats(address, 1)[0]

    def write_u32(self, address, value):
        if not self.in_guest:
            self.host_writes.append((address, value & 0xFFFFFFFF))
        super().write_u32(address, value)
        if (self.auto_guest and not self.in_guest and address == mm.BOOT_SITE
                and value == mm.BOOT_CAVE):
            self.in_guest = True
            try:
                if self.before_guest:
                    self.before_guest(self)
                machine = BootMachine(self)
                before = tuple(machine.regs)
                machine.run(mm.BOOT_CAVE)
                assert tuple(machine.regs) == before
                self.guest_count += 1
            finally:
                self.in_guest = False


def seed_field(b=None):
    b = b or FakeBackend()
    for address, value in ((mm.PLAYER_GLOBAL, ACTOR), (mm.FIELD_OWNER_GLOBAL, OWNER),
                           (OWNER + mm.STATE_POINTER, STATE), (STATE + 0x90, 2 << 8),
                           (mm.MAGI_GLOBAL, MAGI), (MAGI + 0x0C, SCRIPT_FRAME),
                           (SCRIPT_FRAME + 0x18, SCRIPT_STATE), (SCRIPT_STATE + 0x20, 0x31CC),
                           (mm.BOOT_SITE, mm.BOOT_NATIVE)):
        b.seed_u32(address, value)
    b.seed_floats(ACTOR + mm.PLAYER_POSITION, (100, 200, 30))
    b.seed_floats(mm.CAMERA_EYE, (100, -1000, 700))
    b.seed_floats(mm.VIEW_MATRIX, (1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1))
    for site, stock, _ in caves.resources():
        for i, word in enumerate(stock):
            b.seed_u32(site + i * 4, word)
    return b


@pytest.mark.parametrize('yaw', [0, 45, 90, 135, 180, 225, 270, 315, -90, 450])
@pytest.mark.parametrize('pitch,pos_offset', [
    (-25, Vec3(0, 0, 0)), (20, Vec3(130, -20, 70)), (89.5, Vec3(0, 0, 0)),
])
def test_published_movement_and_render_yaw_follow_actual_view(yaw, pitch, pos_offset):
    b = seed_field(); a = MagnaCartaAdapter(b)
    a.write_orbit_params(a.read_player(), yaw, pitch, 1600,
                         pos_offset=pos_offset, target_offset=Vec3(0, -100, 0))
    bank = mm.MOD_BLOCK + mm.SLOTS[b.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]
    eye = b.read_floats(bank + mm.SLOT_EYE, 3)
    target = b.read_floats(bank + mm.SLOT_TARGET, 3)
    fx, fy = target[0] - eye[0], target[1] - eye[1]
    length = math.hypot(fx, fy)
    fx, fy = fx / length, fy / length
    render_yaw = b.read_u32(bank + mm.SLOT_ROT_YAW)
    movement_yaw = b.read_u32(bank + mm.SLOT_YAW)
    # Pad up uses forward, not forward + pi. Pin to the actual eye/target too,
    # so changing both yaw fields to the same wrong value cannot pass.
    # Only the <=8-unit native singularity guard may separate the two fields.
    difference = (movement_yaw - render_yaw + 32768) % 65536 - 32768
    assert abs(difference) <= 8
    render_angle = render_yaw * (2 * math.pi / 65536)
    assert (math.cos(render_angle), math.sin(render_angle)) == pytest.approx((fx, fy), abs=1e-4)
    angle = movement_yaw * (2 * math.pi / 65536)
    assert (math.cos(angle), math.sin(angle)) == pytest.approx((fx, fy), abs=9e-4)
    # Native Unreal XY/Z-up uses screen right = (-forward.y, forward.x).
    # Check cardinal/diagonal directions independent of GUI Orbit yaw.
    for right, up in ((0, 1), (0, -1), (-1, 0), (1, 0),
                      (-1, 1), (1, 1), (-1, -1), (1, -1)):
        actual = (up * math.cos(angle) - right * math.sin(angle),
                  up * math.sin(angle) + right * math.cos(angle))
        expected = (up * fx - right * fy, up * fy + right * fx)
        assert actual == pytest.approx(expected, abs=1.8e-3)


def test_movement_yaw_avoids_native_axis_singularity_without_half_turn():
    # Exhaust the 16-bit circle, including wraparound and the 4-unit lookup bins.
    for yaw in range(65536):
        movement = MagnaCartaAdapter._movement_yaw(yaw)
        assert 0 <= movement <= 65535
        assert 8 <= movement % 16384 <= 16376
        difference = (movement - yaw + 32768) % 65536 - 32768
        assert abs(difference) <= 8
        if 8 <= yaw % 16384 <= 16376:
            assert movement == yaw


def test_center_uses_parameter_path_not_native_output_writes():
    b=seed_field(); a=MagnaCartaAdapter(b)
    pose=a.center_on_target(1500,-100)
    assert pose.distance()==pytest.approx(1500)
    assert not any(mm.CAMERA_EYE<=address<mm.CAMERA_EYE+12 for address,_ in b.host_writes)


@pytest.fixture
def be(): return seed_field()


@pytest.fixture
def adapter(be): return MagnaCartaAdapter(be)


@pytest.mark.parametrize('serial,crc,matched', [
    (mm.GAME_ID, mm.DISC_CRC, True), (' slps-25401 ', ' eb925207 ', True),
    (mm.GAME_ID, 'DEADBEEF', False), ('SLPS-25400', mm.DISC_CRC, False),
    ('', '', False),
])
def test_identify_requires_serial_and_crc(serial, crc, matched):
    b = seed_field(FakeBackend(serial, crc))
    assert MagnaCartaAdapter(b).identify().matched is matched
    assert b.writes == []


@pytest.mark.parametrize('address,value', [
    (mm.PLAYER_GLOBAL, 0), (mm.PLAYER_GLOBAL, ACTOR + 1),
    (mm.FIELD_OWNER_GLOBAL, 0), (mm.FIELD_OWNER_GLOBAL, 0x2000000),
    (OWNER + mm.STATE_POINTER, 0), (OWNER + mm.STATE_POINTER, STATE + 1),
    (STATE + 0x90, 0), (STATE + 0x90, 3 << 8), (STATE + 0x90, 255 << 8),
])
def test_scene_owner_rejection_never_writes(be, adapter, address, value):
    be.seed_u32(address, value)
    scene = adapter.read_scene()
    assert not scene.valid and scene.reason
    with pytest.raises(caves.PatchConflict):
        adapter.set_patch(True)
    assert be.writes == []


@pytest.mark.parametrize('mode,script_name', [(1, 0x31D3), (2, 0x31CC)])
def test_walking_running_and_coordinate_boundary(be, adapter, mode, script_name):
    be.seed_u32(STATE + 0x90, mode << 8)
    be.seed_u32(SCRIPT_STATE + 0x20, script_name)
    assert adapter.read_player() == Vec3(100, -30, 200)
    assert adapter.is_field_like(adapter.read_scene())
    assert adapter._native(Vec3(100, -30, 200)) == (100, 200, 30)
    assert be.writes == []


@pytest.mark.parametrize('address,value', [
    (0x56DB1C, 0), (0x56DB1C, MAGI + 1), (0x56DB1C, 0x2000000),
    (MAGI + 0x0C, 0), (MAGI + 0x0C, SCRIPT_FRAME + 4),
    (MAGI + 0x0C, 0x2000000), (SCRIPT_FRAME + 0x18, 0),
    (SCRIPT_FRAME + 0x18, SCRIPT_STATE + 1), (SCRIPT_FRAME + 0x18, 0x2000000),
    (SCRIPT_STATE + 0x20, 0), (SCRIPT_STATE + 0x20, 0x1234),
    (SCRIPT_STATE + 0x20, 0x131CC), (SCRIPT_STATE + 0x20, 0x131D3),
])
def test_original_scene_rejects_unknown_active_script_without_writes(be, adapter, address, value):
    # Selector remains a valid field mode, as it does in observed battles.
    assert be.read_u32(STATE + 0x90) >> 8 & 255 in mm.FIELD_MODES
    be.seed_u32(address, value)
    scene = adapter.read_scene()
    assert not scene.valid and 'script' in scene.reason
    with pytest.raises(caves.PatchConflict, match='script'):
        adapter.read_player()
    with pytest.raises(caves.PatchConflict, match='script'):
        adapter.set_patch(True)
    assert not adapter._orbit
    assert be.writes == []


def test_script_transition_revokes_previous_render_acceptance(be, adapter):
    adapter.set_patch(True)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED, ACTOR)
    be.seed_u32(SCRIPT_STATE + 0x20, 0x1234)
    assert not adapter.read_scene().valid
    adapter.copy_stock_params()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == 0


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf'), 1000001])
def test_invalid_actor_position_rejected(be, adapter, bad):
    be.seed_floats(ACTOR + mm.PLAYER_POSITION, (bad, 200, 30))
    assert not adapter.read_scene().valid
    assert be.writes == []


@pytest.mark.parametrize('field,bad', [('yaw', float('nan')), ('pitch', float('inf')),
                                       ('distance', -float('inf')), ('centre', float('nan'))])
def test_nonfinite_orbit_rejected_without_writes(be, adapter, field, bad):
    args = dict(centre=Vec3(100, -130, 200), yaw_deg=20, pitch_deg=15, distance=1500)
    args[{'yaw': 'yaw_deg', 'pitch': 'pitch_deg'}.get(field, field)] = Vec3(bad, 0, 0) if field == 'centre' else bad
    with pytest.raises(ValueError): adapter.write_orbit_params(**args)
    assert be.writes == []


@pytest.mark.parametrize('pitch,distance,expected_pitch,expected_distance', [
    (-999, -1, -25, 150), (999, 99999, 89.5, 6000),
])
def test_orbit_clamps_finite_parameters_and_publishes_even_bank(adapter, be, pitch, distance, expected_pitch, expected_distance):
    adapter.write_orbit_params(Vec3(100, -130, 200), 20, pitch, distance)
    assert adapter._relative.distance() == pytest.approx(expected_distance)
    _, actual_pitch = adapter._relative.yaw_pitch()
    assert math.degrees(actual_pitch) == pytest.approx(expected_pitch)
    bank = mm.MOD_BLOCK + mm.SLOTS[be.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]
    assert be.read_u32(bank) & 1 == 0
    assert be.read_u32(bank + mm.SLOT_PLAYER) == ACTOR
    assert caves.ready(be)


@pytest.mark.parametrize('fov,expected', [(-1, 20), (80, 80), (999, 110)])
def test_fov_clamps_but_original_never_installs_camera(adapter, be, fov, expected):
    adapter.write_fov_deg(fov)
    assert adapter._fov == expected
    assert be.writes == []
    adapter.set_patch(True)
    bank = mm.MOD_BLOCK + mm.SLOTS[be.read_u32(mm.MOD_BLOCK + mm.MB_SLOT) & 1]
    assert be.read_f32(bank + mm.SLOT_FOV) == expected


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_fov_rejected_without_writes(adapter, be, bad):
    with pytest.raises(ValueError): adapter.write_fov_deg(bad)
    assert be.writes == []


def test_two_toggles_are_independent_and_camera_restore_retains_them(adapter, be):
    adapter.set_wide_view_running(True)
    assert adapter.wide_view_running() and not adapter.no_encounters()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_WIDE
    adapter.set_no_encounters(True)
    assert adapter.wide_view_running() and adapter.no_encounters()
    adapter.set_patch(True)
    adapter.write_fov_deg(80)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 15
    adapter.restore()
    assert adapter.wide_view_running() and adapter.no_encounters()
    assert not adapter.patch_active()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 12
    adapter.set_wide_view_running(False)
    assert not adapter.wide_view_running() and adapter.no_encounters()
    adapter.set_no_encounters(False)
    assert caves.ready(be)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 0
    assert caves.site_state(be) == 'stock'
    assert be.read_u32(mm.BOOT_SITE) == mm.BOOT_NATIVE


def test_guest_bootstrap_applies_and_restores_every_exact_pair_no_host_code_writes(adapter, be):
    adapter.set_patch(True)
    assert be.guest_count == 1
    assert caves.matches(be, mm.FLAG_ORBIT)
    adapter.restore()
    assert be.guest_count == 2
    assert caves.matches(be, 0)
    sites = {site + off for site, _, _ in caves.resources() for off in (0, 4)}
    assert sites.isdisjoint(address for address, _ in be.host_writes)
    assert any(address == mm.BOOT_SITE and value == mm.BOOT_CAVE for address, value in be.host_writes)
    assert all(not (0x100000 <= address < 0x490000) for address, _ in be.host_writes)


@pytest.mark.parametrize('damage', ['site', 'delay', 'boot', 'cave', 'control', 'nonempty-control'])
def test_unknown_preflight_has_no_writes(be, damage):
    site, stock, _ = caves.resources()[0]
    if damage == 'site': be.seed_u32(site, 0xDEADBEEF)
    elif damage == 'delay': be.seed_u32(site + 4, 0xDEADBEEF)
    elif damage == 'boot': be.seed_u32(mm.BOOT_SITE, 0xDEADBEEF)
    elif damage == 'cave': be.seed_u32(mm.RENDER_CAVE + 4, 0xDEADBEEF)
    elif damage == 'control': be.seed_u32(mm.MOD_BLOCK, 0xDEADBEEF)
    else: be.seed_u32(mm.MOD_BLOCK + 0x3FC, 1)
    with pytest.raises(caves.PatchConflict): caves.sync(be, 1)
    assert be.writes == []


@pytest.mark.parametrize('field', ['pos_offset', 'target_offset'])
def test_nonfinite_offsets_rejected_without_writes(adapter, be, field):
    with pytest.raises(ValueError):
        adapter.write_orbit_params(Vec3(100, -130, 200), 20, 15, 1500,
                                   **{field: Vec3(float('nan'), 0, 0)})
    assert be.writes == []


def test_rejected_scene_passthrough_revokes_prior_movement_acceptance(adapter, be):
    adapter.set_patch(True)
    be.seed_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED, ACTOR)
    be.seed_u32(STATE + 0x90, 3 << 8)
    adapter.copy_stock_params()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_ACCEPTED) == 0


def test_active_cave_corruption_refuses_publication_no_writes(adapter, be):
    adapter.set_patch(True)
    be.seed_u32(mm.RENDER_CAVE + 4, 0xDEADBEEF)
    before = list(be.writes)
    with pytest.raises(caves.PatchConflict): adapter.set_patch(True)
    assert be.writes == before


def test_guest_race_conflict_refuses_all_hook_writes_and_restores_callback(be):
    site, _, _ = caves.resources()[-1]
    be.before_guest = lambda b: b.seed_u32(site + 4, 0xDEADBEEF)
    with pytest.raises(caves.PatchConflict, match='unknown hook'):
        caves.sync(be, 1)
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_CONFLICT
    assert be.read_u32(mm.BOOT_SITE) == mm.BOOT_NATIVE
    for address, stock, _ in caves.resources()[:-1]:
        assert caves.read_words(be, address, 2) == stock


def test_guard_blocks_apply_before_any_memory_write(be):
    guard = GuardedBackend(be)
    guard.bind(mm.GAME_ID, mm.DISC_CRC)
    adapter = MagnaCartaAdapter(guard)
    be.serial = 'OTHER'
    assert guard.verify() == CHANGED
    with pytest.raises(Exception, match='write blocked'):
        adapter.set_patch(True)
    assert be.writes == []


def test_original_camera_and_fov_release_keep_gameplay_toggles(adapter, be):
    adapter.set_wide_view_running(True)
    adapter.set_no_encounters(True)
    adapter.set_patch(True)
    adapter.set_patch(False)
    adapter.restore_fov()
    assert adapter.wide_view_running() and adapter.no_encounters()
    assert be.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == 12


def test_shared_direction_contract_matches_parent_map():
    assert directions.CAVE == 0xF8000
    assert mm.SLOT_YAW == 0x38 and mm.SLOT_PLAYER == 12
    assert mm.MB_SNAPSHOT == 0x100 and mm.MB_ACCEPTED == 28
    assert (mm.MOD_BLOCK, mm.MAGIC, mm.PLAYER_GLOBAL) == (0xFF000, 0x4D434131, 0x53B868)
    assert len(caves.resources()) == 5
    ranges = [(a, a + 4 * len(words)) for a, words in caves.code_resources()]
    assert all(hi <= mm.MOD_BLOCK for _, hi in ranges)
    assert all(hi <= start or end <= lo for i, (lo, hi) in enumerate(ranges)
               for start, end in ranges[i + 1:])


def test_default_settings_keys_are_real_persisted_runtime_fields(adapter):
    known = set(AppSettings().__dict__) & set(CameraSettings().__dict__)
    assert set(adapter.default_settings()) <= known


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from gui.camera_controller import app as gui
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr(gui.StatusPoller, 'start', lambda self: None)
    monkeypatch.setattr(gui.CameraRuntime, 'start', lambda self: None)
    monkeypatch.setattr(gui.MainWindow, '_setup_input', lambda self: None)
    windows = []

    def make(serial=mm.GAME_ID, crc=mm.DISC_CRC):
        backend = seed_field(FakeBackend(serial, crc))
        monkeypatch.setattr(gui, 'PineBackend', lambda: backend)
        window = gui.MainWindow()
        window._timer.stop()
        windows.append(window)
        return window, backend

    yield make
    for window in windows: window.close()
    qapp.processEvents()


def test_registered_gui_starts_original_with_session_options_off_no_writes(make_window):
    window, backend = make_window()
    assert isinstance(window.adapter, MagnaCartaAdapter)
    assert isinstance(window.adapter.backend, GuardedBackend)
    assert window.adapter.backend is window.guard
    assert window.guard.expected == (mm.GAME_ID, mm.DISC_CRC)
    assert window.runtime.settings.mode == 'original'
    for name in ('wide_view_running', 'no_encounters'):
        assert getattr(window, f'chk_{name}').isEnabled()
        assert not getattr(window, f'chk_{name}').isChecked()
        assert not getattr(window.runtime.settings, name)
    assert not window.rb_free.isEnabled()
    assert backend.writes == []


@pytest.mark.parametrize('serial,crc', [(mm.GAME_ID, 'DEADBEEF'), ('SLPS-00000', mm.DISC_CRC)])
def test_registered_gui_unverified_disc_never_writable(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert window.runtime is None
    assert not window.guard.writes_allowed
    assert not window.chk_wide_view_running.isEnabled()
    assert not window.chk_no_encounters.isEnabled()
    assert backend.writes == []


def test_registered_gui_original_preserves_both_options_disable_all_restores(make_window):
    window, backend = make_window()
    window.chk_wide_view_running.setChecked(True)
    window.chk_no_encounters.setChecked(True)
    assert backend.writes == []  # checkbox callbacks are requests, not adapter writes
    window.runtime._tick(0, None)
    assert window.adapter.wide_view_running() and window.adapter.no_encounters()
    data = window.poller.poll_once()
    assert data['wide_view_running'] and data['no_encounters']
    assert data['scale'] == pytest.approx(320 / math.tan(math.radians(55) / 2))
    window._on_mode('original')
    assert window.adapter.wide_view_running() and window.adapter.no_encounters()
    window._restore()
    assert not window.adapter.wide_view_running() and not window.adapter.no_encounters()
    assert caves.matches(backend, 0)


@pytest.mark.parametrize('state', ['walking_base', 'walking_base_only_wait',
                                   'walking_base_chara_and_camera_move', 'running_base'])
def test_optional_local_states_have_stock_hook_pairs_and_empty_caves(state):
    path = Path('C:/PS2CameraLab/work/magnacarta/states') / state / 'eeMemory.bin'
    if not path.is_file(): pytest.skip('optional private local RAM state unavailable')
    ram = path.read_bytes()
    magi = struct.unpack_from('<I', ram, mm.MAGI_GLOBAL)[0]
    frame = struct.unpack_from('<I', ram, magi + 0x0C)[0]
    script_state = struct.unpack_from('<I', ram, frame + 0x18)[0]
    script_name = struct.unpack_from('<I', ram, script_state + 0x20)[0]
    assert script_name == (0x31D3 if state == 'running_base' else 0x31CC)
    assert script_name in mm.FIELD_SCRIPT_NAMES  # exact u32, not truncated FName
    assert struct.unpack_from('<I', ram, mm.BOOT_SITE)[0] == mm.BOOT_NATIVE
    for site, stock, _ in caves.resources():
        assert struct.unpack_from('<2I', ram, site) == stock
    for address, words in caves.code_resources():
        assert not any(ram[address:address + 4 * len(words)])
