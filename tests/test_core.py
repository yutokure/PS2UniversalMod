"""Unit tests for the game-independent core (no emulator required)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.camera_math.orbit import (  # noqa: E402
    CameraPose, FOV_MAX_DEG, FOV_MIN_DEG, Vec3, clamp, default_fov_deg,
    fov_deg_to_scale, orbit_pose, scale_to_fov_deg,
)
from core.config.settings import AppSettings, PresetStore, SettingsStore  # noqa: E402
from core.controller.sources import ScriptedSource, deadzone_apply  # noqa: E402


# --- orbit math -----------------------------------------------------------
def test_orbit_distance_is_preserved():
    target = Vec3(10.0, -5.0, 3.0)
    for yaw in (-180, -90, 0, 45, 90, 179):
        for pitch in (-20, 0, 30, 80):
            pose = orbit_pose(target, math.radians(yaw), math.radians(pitch), 25.0)
            assert pose.distance() == pytest.approx(25.0, abs=1e-9)


def test_orbit_yaw_pitch_round_trip():
    target = Vec3(1.0, 2.0, 3.0)
    for yaw_deg in (-120.0, -30.0, 0.0, 75.0, 170.0):
        for pitch_deg in (-15.0, 0.0, 35.0, 70.0):
            pose = orbit_pose(target, math.radians(yaw_deg), math.radians(pitch_deg), 18.0)
            yaw, pitch = pose.yaw_pitch()
            assert math.degrees(yaw) == pytest.approx(yaw_deg, abs=1e-6)
            assert math.degrees(pitch) == pytest.approx(pitch_deg, abs=1e-6)


def test_positive_pitch_puts_camera_above_target_in_y_down_space():
    """FFX-2 stores +Y downwards, so "above" means a smaller Y."""
    target = Vec3(0.0, 0.0, 0.0)
    pose = orbit_pose(target, 0.0, math.radians(30.0), 10.0)
    assert pose.eye.y < target.y


def test_orbit_default_matches_the_game_camera():
    """The stock field camera resolves to these parameters (measured)."""
    target = Vec3(-0.7377, -7.2519, 110.2479)
    eye = Vec3(-1.3086, -26.0506, 131.9051)
    pose = CameraPose(eye=eye, target=target)
    yaw, pitch = pose.yaw_pitch()
    assert math.degrees(yaw) == pytest.approx(-1.51, abs=0.05)
    assert math.degrees(pitch) == pytest.approx(40.95, abs=0.05)
    assert pose.distance() == pytest.approx(28.69, abs=0.05)


def test_clamp():
    assert clamp(5, 0, 1) == 1
    assert clamp(-5, 0, 1) == 0
    assert clamp(0.5, 0, 1) == 0.5


# --- FOV ------------------------------------------------------------------
def test_fov_scale_round_trip():
    for deg in (20.0, 40.0, 54.68, 80.0, 110.0):
        scale = fov_deg_to_scale(deg)
        assert scale_to_fov_deg(scale) == pytest.approx(deg, abs=1e-9)


def test_fov_clamps_are_enforced():
    assert fov_deg_to_scale(1.0) == fov_deg_to_scale(FOV_MIN_DEG)
    assert fov_deg_to_scale(179.0) == fov_deg_to_scale(FOV_MAX_DEG)


def test_fov_reference_value():
    """619.0 is the stock field projection scale -> 54.68 deg horizontal."""
    assert scale_to_fov_deg(619.0) == pytest.approx(54.68, abs=0.01)
    assert default_fov_deg() == pytest.approx(54.68, abs=0.01)
    assert fov_deg_to_scale(80.0) == pytest.approx(381.36, abs=0.02)


# --- input ----------------------------------------------------------------
def test_deadzone():
    assert deadzone_apply(0.05, 0.0, 0.12) == (0.0, 0.0)
    x, y = deadzone_apply(1.0, 0.0, 0.12)
    assert x == pytest.approx(1.0)
    assert y == pytest.approx(0.0)


def test_scripted_source():
    s = ScriptedSource()
    assert s.poll() == (0.0, 0.0)
    s.set(0.5, -0.25)
    assert s.poll() == (0.5, -0.25)


# --- settings -------------------------------------------------------------
def test_settings_store_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    st = store.get("SLPS-25250")
    st.yaw_deg = 42.0
    st.fov_deg = 61.5
    st.pos_offset = [1.0, 2.0, 3.0]
    store.put(st)

    reloaded = SettingsStore(path)
    again = reloaded.get("SLPS-25250")
    assert again.yaw_deg == 42.0
    assert again.fov_deg == 61.5
    assert again.pos_offset == [1.0, 2.0, 3.0]


def test_settings_are_separated_per_game(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    a = store.get("SLPS-25250")
    a.yaw_deg = 10.0
    store.put(a)
    b = store.get("SLUS-20672")
    b.yaw_deg = 90.0
    store.put(b)
    assert store.get("SLPS-25250").yaw_deg == 10.0
    assert store.get("SLUS-20672").yaw_deg == 90.0


def test_presets(tmp_path):
    store = PresetStore(tmp_path / "presets")
    st = AppSettings()
    st.game_id = "SLPS-25250"
    st.pitch_deg = 12.5
    store.save("night orbit", st)
    assert "night orbit" in store.list("SLPS-25250")
    loaded = store.load("night orbit", "SLPS-25250")
    assert loaded is not None and loaded.pitch_deg == 12.5
    assert store.load("missing", "SLPS-25250") is None


# --- adapter guard --------------------------------------------------------
def test_field_guard_rejects_loading_and_battle():
    from adapters.ffx2.adapter import FFX2Adapter, SceneState

    class DummyBackend:
        pass

    ad = FFX2Adapter(DummyBackend())
    good = SceneState(player=Vec3(1, -12, 110),
                      game_pose=CameraPose(Vec3(0.4, -26, 131.9), Vec3(-0.7, -7.2, 110.2)),
                      fov_deg=54.7, max_dist_game=28.7)
    assert ad.is_field_like(good)

    loading = SceneState(player=Vec3(0, 0, 0),
                         game_pose=CameraPose(Vec3(0, 0, 5), Vec3(0, 0, 0)),
                         fov_deg=54.7, max_dist_game=5.0)
    assert not ad.is_field_like(loading)

    far = SceneState(player=Vec3(1, -12, 110),
                     game_pose=CameraPose(Vec3(0, -200, 900), Vec3(0, 0, 0)),
                     fov_deg=54.7, max_dist_game=1000.0)
    assert not ad.is_field_like(far)


def test_field_guard_accepts_camera_switch_geometry():
    """Regression: the camera-switch savestate parks the stock eye ~170 units behind
    the party.  The old 120-unit limit made the mod silent there."""
    from adapters.ffx2.adapter import FFX2Adapter, SceneState

    ad = FFX2Adapter(object())
    switched = SceneState(player=Vec3(-0.97, -11.25, 133.01),
                          game_pose=CameraPose(Vec3(12.9, -23.23, 301.7), Vec3(-0.97, -17.25, 133.01)),
                          fov_deg=54.7, max_dist_game=169.7)
    assert ad.is_field_like(switched)


# --- XInput slot detection -------------------------------------------------
class _Gamepad:
    def __init__(self, rx=0, ry=0):
        self.sThumbRX = rx
        self.sThumbRY = ry


def _xinput_with(connected: dict[int, _Gamepad]):
    from core.controller.sources import XInputSource

    src = XInputSource.__new__(XInputSource)
    src.index = None
    src.active_slot = None
    src._dll = object()  # only checked for "not None" by poll()
    src._read_slot = lambda slot: connected.get(slot)
    return src


def test_xinput_finds_pad_in_slot_one():
    """Regression: the pad answered on XInput slot 1 while the mod read slot 0."""
    src = _xinput_with({1: _Gamepad(rx=16384, ry=-32767)})
    x, y = src.poll()
    assert src.active_slot == 1
    assert x == pytest.approx(0.5, abs=1e-3)
    assert y == pytest.approx(-1.0, abs=1e-3)


def test_xinput_prefers_last_working_slot_and_recovers_after_unplug():
    pads = {2: _Gamepad(rx=32767)}
    src = _xinput_with(pads)
    src.poll()
    assert src.active_slot == 2
    pads.clear()
    assert src.poll() == (0.0, 0.0)
    assert src.active_slot is None
    pads[0] = _Gamepad(ry=32767)
    assert src.poll() == (0.0, pytest.approx(1.0, abs=1e-3))
    assert src.active_slot == 0


def test_xinput_pinned_slot_ignores_others():
    src = _xinput_with({1: _Gamepad(rx=32767)})
    src.index = 0
    assert src.poll() == (0.0, 0.0)
    assert src.active_slot is None


# --- scene-change resync ----------------------------------------------------
class _FakeBackend:
    def __init__(self):
        self.mem = {}
        self.writes = []

    def read_floats(self, addr, n):
        return [self.mem.get(addr + 4 * i, 0.0) for i in range(n)]

    def write_float_block(self, addr, values):
        self.writes.append((addr, tuple(values)))
        for i, v in enumerate(values):
            self.mem[addr + 4 * i] = v


class _FakeAdapter:
    CAM_EYE_OFFSET_ADDR = 0x3403E0
    CAM_TARGET_ADDR = 0x33FC40

    def __init__(self, backend):
        self.backend = backend


def test_resync_republishes_when_game_clears_offset():
    from core.camera_runtime.engine import CameraRuntime

    backend = _FakeBackend()
    rt = CameraRuntime(_FakeAdapter(backend))
    offset, aim = (1.0, 2.0, 3.0), (4.0, 5.0, 6.0)
    rt._last_published = (offset, aim)
    for i, v in enumerate(offset):
        backend.mem[0x3403E0 + 4 * i] = v
    for i, v in enumerate(aim):
        backend.mem[0x33FC40 + 4 * i] = v

    rt._verify_published()
    assert rt._last_published == (offset, aim)
    assert rt.stats.resyncs == 0

    backend.mem[0x3403E0] = 0.0  # the game cleared our offset on a scene change
    rt._verify_published()
    assert rt._last_published is None
    assert rt.stats.resyncs == 1


def test_resync_is_noop_before_first_publish():
    from core.camera_runtime.engine import CameraRuntime

    rt = CameraRuntime(_FakeAdapter(_FakeBackend()))
    rt._verify_published()
    assert rt.stats.resyncs == 0


# --- stock camera hook ------------------------------------------------------
class _HookBackend:
    """Floats and raw words in one fake EE memory (only what the hook touches)."""

    def __init__(self):
        self.f = {}
        self.u = {}
        self.writes = []
        self.u_writes = []

    def read_floats(self, addr, n):
        return [self.f.get(addr + 4 * i, 0.0) for i in range(n)]

    def read_u32(self, addr):
        return self.u.get(addr, 0)

    def write_u32(self, addr, value):
        self.u_writes.append((addr, value))
        self.u[addr] = value

    def write_float_block(self, addr, values):
        self.writes.append((addr, tuple(values)))
        for i, v in enumerate(values):
            self.f[addr + 4 * i] = v


def _patch_backend(applied: bool):
    """Fake EE memory with the look-at and stock-hook words applied or stock."""
    from adapters.ffx2 import memory_map as mm

    b = _HookBackend()
    for addr, stock, patched in mm.PATCH_WORDS:
        b.u[addr] = patched if applied else stock
    b.u[mm.PROJ_SOURCE_LOAD] = mm.PROJ_SOURCE_STOCK
    b.u[mm.LOOKAT_LOAD_SITE] = mm.LOOKAT_LOAD_STOCK
    b.u[mm.LOOKAT_CALL + 4] = mm.LOOKAT_CALL_DELAY
    if applied:
        from adapters.ffx2.lookat_cave import cave_words
        for i, word in enumerate(cave_words()):
            b.u[mm.LOOKAT_CAVE + 4 * i] = word
    return b


def _hooked_backend():
    return _patch_backend(applied=True)


def test_hook_detection_needs_all_patched_words():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _hooked_backend()
    assert FFX2Adapter(b).hook_active()
    b.u[mm.HOOK_CHECK[0][0]] = 0xC62C0060  # stock load back in place
    assert not FFX2Adapter(b).hook_active()


def test_orbit_params_map_to_eye_routine_slots():
    import math
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _hooked_backend()
    FFX2Adapter(b).write_orbit_params(Vec3(1.0, -6.0, 3.0), yaw_deg=30.0,
                                      pitch_deg=20.0, distance=28.7)
    assert b.f[mm.ORBIT_CENTRE] == pytest.approx(1.0)
    assert b.f[mm.ORBIT_CENTRE + 4] == pytest.approx(-6.0)
    assert b.f[mm.ORBIT_YAW_SLOT] == pytest.approx(math.radians(mm.ORBIT_YAW_OFFSET_DEG - 30.0))
    assert b.f[mm.ORBIT_NPITCH_SLOT] == pytest.approx(-math.radians(20.0))
    assert b.f[mm.ORBIT_DIST_SLOT] == pytest.approx(28.7)


def test_stock_yaw_is_reproduced_by_slot_mapping():
    """Calibration: the stock yaw 90.65 deg gives an eye angle of about -0.8 deg."""
    import math
    from adapters.ffx2 import memory_map as mm

    stock_slot_deg = 90.65  # measured yaw slot when the stock eye was -0.8 deg
    eye_angle_deg = mm.ORBIT_YAW_OFFSET_DEG - stock_slot_deg
    assert eye_angle_deg == pytest.approx(-0.8, abs=0.05)


def test_copy_stock_params_mirrors_blend_and_centre():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _hooked_backend()
    b.f[mm.STOCK_YAW_OUT], b.f[mm.STOCK_NPITCH_OUT], b.f[mm.STOCK_DIST_OUT] = 1.58, -0.48, 63.6
    b.u[mm.STOCK_CENTRE_PTR] = 0x0033FC50
    for i, v in enumerate((-0.44, -0.07, 66.1, 0.0)):
        b.f[0x0033FC50 + 4 * i] = v
    FFX2Adapter(b).copy_stock_params()
    assert b.f[mm.ORBIT_YAW_SLOT] == pytest.approx(1.58)
    assert b.f[mm.ORBIT_NPITCH_SLOT] == pytest.approx(-0.48)
    assert b.f[mm.ORBIT_DIST_SLOT] == pytest.approx(63.6)
    assert b.read_floats(mm.ORBIT_CENTRE, 4) == pytest.approx((-0.44, -0.07, 66.1, 0.0))


def test_runtime_passes_stock_values_through_when_patch_is_applied_in_original():
    """A manual load in the original camera keeps the slots at the stock values."""
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORIGINAL, CameraSettings

    b = _hooked_backend()
    b.f[mm.STOCK_YAW_OUT] = 1.58
    b.u[mm.STOCK_CENTRE_PTR] = 0x0033FC50
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORIGINAL))
    rt.set_patch_override(True)
    rt._tick(0.001, None)
    assert b.f[mm.ORBIT_YAW_SLOT] == pytest.approx(1.58)


def test_runtime_publishes_orbit_only_when_it_changes():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    b = _hooked_backend()
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT, yaw_deg=10.0))
    centre = Vec3(0.0, -6.0, 40.0)
    rt._publish_orbit((centre.x, centre.y, centre.z), 10.0, 40.0, 28.7)
    rt._publish_orbit((centre.x, centre.y, centre.z), 10.0, 40.0, 28.7)
    slot_writes = [w for w in b.writes if w[0] == mm.ORBIT_YAW_SLOT]
    assert len(slot_writes) == 1


def test_orbit_writes_walk_target_at_centre():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _hooked_backend()
    FFX2Adapter(b).write_walk_target(Vec3(3.0, -6.0, 40.0))
    assert b.f[mm.WALK_TARGET] == pytest.approx(3.0)
    assert b.f[mm.WALK_TARGET + 8] == pytest.approx(40.0)


def test_walk_direction_is_away_from_orbit_eye():
    """target (= centre) - eye is -(sin yaw, cos yaw): the forward for any orbit yaw."""
    import math

    for yaw_deg in (0.0, 90.0, -90.0, 135.0):
        yaw, cp, d = math.radians(yaw_deg), math.cos(math.radians(40.0)), 28.7
        centre = (0.0, 0.0, 0.0)
        eye = (math.sin(yaw) * cp * d, -math.sin(math.radians(40.0)) * d, math.cos(yaw) * cp * d)
        fx, fz = centre[0] - eye[0], centre[2] - eye[2]
        n = math.hypot(fx, fz)
        assert fx / n == pytest.approx(-math.sin(yaw), abs=1e-9)
        assert fz / n == pytest.approx(-math.cos(yaw), abs=1e-9)


def test_walk_target_gives_centre_minus_eye_for_any_base():
    """target - base == centre - eye, whatever base the game currently has."""
    from core.camera_math.orbit import walk_target

    centre, eye = Vec3(-44.0, -56.0, 12.0), Vec3(-30.0, -70.0, 40.0)
    for base in (Vec3(-44.0, -60.0, 40.0), Vec3(-59.9, -121.5, -126.2), eye):
        t = walk_target(centre, base, eye)
        d = t - base
        e = centre - eye
        assert (d.x, d.y, d.z) == pytest.approx((e.x, e.y, e.z))


def test_capture_original_fov_keeps_requested_fov():
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings
    from adapters.ffx2 import memory_map as mm

    b = _HookBackend()
    b.f[mm.CAM_PROJ_SCALE] = 1024.0  # the area's own zoom (34.7 deg)
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT, fov_deg=40.0, use_fov=True))
    rt.capture_original_fov()
    assert rt.settings.fov_deg == pytest.approx(40.0)
    assert rt._orig_fov == pytest.approx(34.71, abs=0.05)


def test_projection_centre_is_held_while_orbiting_and_restored():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    b = _HookBackend()
    b.f[mm.CAM_PROJ_SCALE] = 1024.0
    b.f[mm.CAM_PROJ_CENTRE] = 900.0  # other_area_base: image shifted off-centre
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT))
    rt._hold_projection()
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(mm.STOCK_PROJ_CENTRE)
    assert b.f[mm.CAM_PROJ_SCALE] == pytest.approx(619.0)  # stock field framing by default
    assert rt.stats.projection_fixes == 2
    rt._release_projection(restore=True)
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(900.0)
    assert b.f[mm.CAM_PROJ_SCALE] == pytest.approx(1024.0)  # the area's own zoom comes back


def test_projection_hold_drops_saved_values_when_guard_fails():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    b = _HookBackend()
    b.f[mm.CAM_PROJ_SCALE] = 619.0
    b.f[mm.CAM_PROJ_CENTRE] = 900.0
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT))
    rt._hold_projection()
    rt._release_projection(restore=False)  # guard failed: do not put anything back
    assert rt._proj_saved is None
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(mm.STOCK_PROJ_CENTRE)


def test_projection_source_follows_the_orbit_and_is_restored():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    b = _HookBackend()
    b.u[mm.PROJ_SOURCE_LOAD] = mm.PROJ_SOURCE_STOCK
    b.f[mm.CAM_PROJ_SCALE] = 1024.0
    b.f[mm.CAM_PROJ_CENTRE] = 900.0  # other_area_base
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT, use_fov=True, fov_deg=54.68))
    rt._set_projection_redirect(True)
    rt._set_projection_redirect(True)  # answered from the cache: no second write
    assert b.u[mm.PROJ_SOURCE_LOAD] == mm.PROJ_SOURCE_REDIRECT
    assert len(b.u_writes) == 1
    rt._hold_projection()
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(mm.STOCK_PROJ_CENTRE)
    rt._leave_orbit_projection(force=True)
    assert b.u[mm.PROJ_SOURCE_LOAD] == mm.PROJ_SOURCE_STOCK
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(900.0)  # the area's own centre comes back
    assert len(b.u_writes) == 2


def test_restore_puts_the_stock_projection_back():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, MODE_ORIGINAL, CameraSettings

    b = _patch_backend(applied=True)
    b.f[mm.CAM_PROJ_SCALE] = 1024.0
    b.f[mm.CAM_PROJ_CENTRE] = 900.0
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT, use_fov=True, fov_deg=54.68))
    rt._set_projection_redirect(True)
    rt._hold_projection()
    assert b.u[mm.PROJ_SOURCE_LOAD] == mm.PROJ_SOURCE_REDIRECT
    rt.restore()
    assert rt.settings.mode == MODE_ORIGINAL
    assert rt.stats.last_error == ""
    assert b.u[mm.PROJ_SOURCE_LOAD] == mm.PROJ_SOURCE_STOCK
    assert b.f[mm.CAM_PROJ_CENTRE] == pytest.approx(900.0)
    assert all(b.u[addr] == stock for addr, stock, _ in mm.PATCH_WORDS)


def test_patch_words_apply_from_stock_and_go_back_to_stock():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _patch_backend(applied=False)
    ad = FFX2Adapter(b)
    ad.set_patch(True)
    assert ad.patch_state() == "applied"
    from adapters.ffx2.lookat_cave import cave_words
    count = len(mm.PATCH_WORDS) + len(cave_words())
    assert len(b.u_writes) == count
    assert b.u_writes[:len(cave_words())] == [
        (mm.LOOKAT_CAVE + 4 * i, word) for i, word in enumerate(cave_words())
    ]  # publish the complete cave before attaching the call site
    ad.set_patch(True)  # already applied: nothing to write
    assert len(b.u_writes) == count
    ad.set_patch(False)
    assert ad.patch_state() == "stock"
    assert len(b.u_writes) == count + len(mm.PATCH_WORDS)
    assert b.u[mm.LOOKAT_LOAD_SITE] == mm.LOOKAT_LOAD_STOCK


def test_patch_refuses_unknown_words_and_writes_nothing():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter, PatchConflict

    b = _patch_backend(applied=False)
    b.u[mm.PATCH_WORDS[5][0]] = 0x12345678  # foreign code at a patched address
    ad = FFX2Adapter(b)
    assert ad.patch_state() == "unknown"
    with pytest.raises(PatchConflict):
        ad.set_patch(True)
    assert b.u_writes == []


def test_patch_state_reports_partial_application():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _patch_backend(applied=True)
    b.u[mm.PATCH_WORDS[0][0]] = mm.PATCH_WORDS[0][1]  # look-at word back to stock only
    assert FFX2Adapter(b).patch_state() == "partial"


def test_projection_source_refuses_unknown_word():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter, PatchConflict

    b = _HookBackend()
    b.u[mm.PROJ_SOURCE_LOAD] = 0x12345678
    with pytest.raises(PatchConflict):
        FFX2Adapter(b).set_projection_source(True)
    assert b.u_writes == []


def test_orbit_applies_the_patch_and_original_removes_it():
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, MODE_ORIGINAL, CameraSettings

    b = _patch_backend(applied=False)  # a stock camera, as after a savestate load
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT))
    rt._tick(0.001, None)  # no field scene in the fake memory: the guard path
    assert FFX2Adapter(b).patch_state() == "applied"

    rt.settings.mode = MODE_ORIGINAL
    rt._tick(0.001, None)
    assert FFX2Adapter(b).patch_state() == "stock"
    assert not rt.stats.last_error.startswith("patch")


def test_override_loads_the_patch_in_original_and_keeps_the_aim_current():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORIGINAL, CameraSettings

    b = _patch_backend(applied=False)
    for i, v in enumerate((1.0, 2.0, 3.0)):
        b.f[mm.CAM_AIM + 4 * i] = v  # the game's own look-at point
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORIGINAL))
    rt.set_patch_override(True)
    rt._tick(0.001, None)
    assert FFX2Adapter(b).patch_state() == "applied"
    assert [b.f[mm.CAM_AIM_SLOT + 4 * i] for i in range(3)] == [1.0, 2.0, 3.0]


def test_override_is_dropped_when_the_mode_changes():
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_FREE, MODE_ORBIT, CameraSettings

    b = _patch_backend(applied=False)
    rt = CameraRuntime(FFX2Adapter(b), CameraSettings(mode=MODE_ORBIT))
    rt._tick(0.001, None)
    assert FFX2Adapter(b).patch_state() == "applied"
    rt.set_patch_override(False)
    rt._tick(0.001, None)
    assert FFX2Adapter(b).patch_state() == "stock"
    rt.settings.mode = MODE_FREE  # the override belonged to the orbit, so the free camera wants the patch
    rt._tick(0.001, None)
    assert FFX2Adapter(b).patch_state() == "applied"


def test_failed_patch_write_waits_before_retrying():
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    class _FlakyBackend(_HookBackend):
        def __init__(self):
            super().__init__()
            self.fail_next = True

        def write_u32(self, addr, value):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("pine busy")
            super().write_u32(addr, value)

    flaky = _FlakyBackend()
    flaky.u = dict(_patch_backend(applied=False).u)
    ad = FFX2Adapter(flaky)
    attempts = []
    real_set_patch = ad.set_patch
    ad.set_patch = lambda on: (attempts.append(on), real_set_patch(on))[1]
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT))
    rt._tick(0.001, None)
    assert rt.stats.last_error == "patch: pine busy"
    rt._tick(0.001, None)
    rt._tick(0.001, None)
    assert len(attempts) == 1  # no retry on every tick
    rt._retry_at = 0.0  # the backoff has passed
    rt._tick(0.001, None)
    assert len(attempts) == 2
    assert ad.patch_state() == "applied"


# --- FFX-2 scripted-camera anchor height ------------------------------------
def _ffx2_field_backend(actor=Vec3(-0.73772, -12.25185, 110.24788), camera_height=5.0):
    """The actor stays put while the scripted camera changes its subject height.

    The protected base / camera-switch states measure camera_height = 5 / 1;
    other_area_base measures 10.  0x3312D0 is independent of those offsets.
    """
    from adapters.ffx2 import memory_map as mm

    b = _patch_backend(applied=False)
    b.write_float_block(0x3312D0, (*actor.as_tuple(), 1.0))
    b.write_float_block(mm.CAM_TARGET, (actor.x, actor.y + camera_height, actor.z, 0.0))
    b.write_float_block(mm.CAM_EYE_BASE, (actor.x, actor.y - 15.0, actor.z + 25.0, 1.0))
    b.write_float_block(mm.CAM_AIM, (actor.x, actor.y + camera_height, actor.z, 0.0))
    b.write_float_block(mm.CAM_BASIS_FWD, (0.0, 0.5, -math.sqrt(0.75), 0.0))
    b.f[mm.CAM_PROJ_SCALE] = 619.0
    b.f[mm.CAM_PROJ_CENTRE] = mm.STOCK_PROJ_CENTRE
    return b


@pytest.mark.parametrize("camera_height", [5.0, 1.0, 10.0, -3.0])
def test_ffx2_player_anchor_is_independent_of_scripted_camera_height(camera_height):
    from adapters.ffx2.adapter import FFX2Adapter

    ad = FFX2Adapter(_ffx2_field_backend(camera_height=camera_height))
    # Keep the normal-field reference (+5) so existing look_height settings do
    # not change framing, but never inherit the script's variable height.
    assert ad.read_player().as_tuple() == pytest.approx((-0.73772, -7.25185, 110.24788))


@pytest.mark.parametrize("hook", [True, False])
def test_ffx2_orbit_height_stays_fixed_across_camera_switch_and_tracks_actor(hook):
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, MODE_ORBIT, CameraSettings

    actor = Vec3(-0.73772, -12.25185, 110.24788)
    b = _ffx2_field_backend(actor)
    s = CameraSettings(mode=MODE_ORBIT, look_height=-6.0, target_offset=[2.0, -1.5, 3.0])
    rt = CameraRuntime(FFX2Adapter(b), s)
    if not hook:
        rt.set_patch_override(False)  # exercise offset injection without the stock hook
    rt.scene_refresh_ms = 0.0
    rt._tick(0.001, None)
    before = rt.stats.applied_pose
    assert before[1] == pytest.approx((actor.x + 2.0, actor.y - 2.5, actor.z + 3.0))

    # Same actor, new scripted camera and stock eye (the measured cut moves it
    # ~170 units away).  No orbit input or settings change.
    b.write_float_block(mm.CAM_TARGET, (actor.x, actor.y + 1.0, actor.z, 0.0))
    b.write_float_block(mm.CAM_AIM, (actor.x, actor.y + 1.0, actor.z, 0.0))
    b.write_float_block(mm.CAM_EYE_BASE, (12.9, -23.23, 301.7, 1.0))
    rt._tick(0.001, None)
    assert rt.stats.applied_pose == before
    if hook:
        assert b.read_floats(mm.ORBIT_CENTRE, 3) == pytest.approx(before[1])
    assert b.read_floats(mm.CAM_AIM_SLOT, 3) == pytest.approx(before[1])
    base = Vec3(*b.read_floats(mm.CAM_EYE_BASE, 3))
    offset = Vec3(*b.read_floats(mm.CAM_EYE_OFFSET, 3))
    assert (base + offset).as_tuple() == pytest.approx(before[0])

    # Do not freeze world Y as a workaround: real elevation and X/Z movement
    # must still translate the whole orbit, even in the switched camera.
    delta = Vec3(2.0, -8.0, 4.0)
    moved = actor + delta
    b.write_float_block(0x3312D0, (*moved.as_tuple(), 1.0))
    b.write_float_block(mm.CAM_TARGET, (moved.x, moved.y + 1.0, moved.z, 0.0))
    rt._tick(0.001, None)
    for old, new in zip(before, rt.stats.applied_pose):
        assert new == pytest.approx((Vec3(*old) + delta).as_tuple())
    if hook:
        assert b.read_floats(mm.ORBIT_CENTRE, 3) == pytest.approx(rt.stats.applied_pose[1])
    assert b.read_floats(mm.CAM_AIM_SLOT, 3) == pytest.approx(rt.stats.applied_pose[1])


@pytest.mark.parametrize("actor", [Vec3(0.0, 0.0, 0.0), Vec3(0.01, -0.02, 0.03)])
def test_ffx2_anchor_compensation_does_not_bypass_loading_guard(actor):
    from adapters.ffx2.adapter import FFX2Adapter

    ad = FFX2Adapter(_ffx2_field_backend(actor, camera_height=10.0))
    scene = ad.read_scene()
    assert scene.player == actor
    assert not ad.is_field_like(scene)


def test_ffx2_center_uses_the_same_stable_anchor_as_orbit():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, CameraSettings

    b = _ffx2_field_backend(camera_height=1.0)
    s = CameraSettings(look_height=-4.0, target_offset=[1.0, 2.0, 3.0])
    rt = CameraRuntime(FFX2Adapter(b), s)
    assert rt.center_on_target()
    assert b.read_floats(mm.CAM_AIM_SLOT, 3) == pytest.approx((0.26228, -9.25185, 113.24788))


# --- main-only look-at hook / minimap isolation -----------------------------
@pytest.mark.parametrize("output,eye,target,redirect", [
    (0x33F620, 0x340360, 0x33FC10, True),
    (0x33F620, 0x3413B0, 0x340C60, False),  # another camera bank
    (0x4FE3B0, 0x3403A0, 0x33FC50, False),  # alternate camera branch
    (0x5FF000, 0x5FF010, 0x5FF020, False),  # stack-local wrapper target
    (0x33F620, 0x340360, 0x33FC50, False),  # only target differs
    (0x33F620, 0x3403A0, 0x33FC10, False),  # only eye differs
    (0x33F7E0, 0x340360, 0x33FC10, False),  # only output differs
])
def test_ffx2_lookat_cave_redirects_only_main_camera(output, eye, target, redirect):
    """Execute the emitted MIPS subset, including branch delay slots and tail jump.

    Check argument isolation, not merely that a dictionary received a word.
    """
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.lookat_cave import cave_words
    from core import mips_asm as m

    words = cave_words()
    regs = [0x12340000 + i for i in range(32)]
    regs[0], regs[m.A0], regs[m.A1], regs[m.A2] = 0, output, eye, target
    regs[31] = mm.LOOKAT_CALL + 8
    before = list(regs)
    pc, steps, reached_builder = 0, 0, False
    while pc < len(words):
        steps += 1
        assert steps <= len(words)
        word = words[pc]
        op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
        imm = word & 0xFFFF
        signed = imm - 0x10000 if imm & 0x8000 else imm
        if op == 15:
            regs[rt] = imm << 16
        elif op == 13:
            regs[rt] = regs[rs] | imm
        elif op == 9:
            regs[rt] = (regs[rs] + signed) & 0xFFFFFFFF
        elif op == 5:
            assert words[pc + 1] == m.NOP
            if regs[rs] != regs[rt]:
                pc += 1 + signed
                continue
        elif op == 2:
            assert (word & 0x03FFFFFF) << 2 == mm.FN_LOOKAT_BUILD
            assert words[pc + 1] == m.NOP
            reached_builder = True
            break
        else:
            assert word == m.NOP
        pc += 1
    assert reached_builder
    assert regs[m.A2] == target + (0x30 if redirect else 0)
    for i in range(32):
        if i not in (m.V0, m.A2):
            assert regs[i] == before[i]  # especially ra and every other argument
    assert 4 * len(words) <= 0x100
    assert mm.LOOKAT_CALL_PATCHED == m.jal(mm.LOOKAT_CAVE)
    assert mm.LOOKAT_CALL_DELAY == m.addiu(m.A2, m.A2, 0x50)


@pytest.mark.parametrize("on", [True, False])
def test_ffx2_migrates_legacy_global_lookat_without_touching_auxiliary_calls(on):
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter

    b = _patch_backend(applied=False)
    b.u[mm.LOOKAT_LOAD_SITE] = mm.LOOKAT_LOAD_PATCHED
    ad = FFX2Adapter(b)
    assert not ad.patch_active()
    assert ad.patch_state() == "partial"
    ad.set_patch(on)
    assert b.u[mm.LOOKAT_LOAD_SITE] == mm.LOOKAT_LOAD_STOCK
    assert ad.patch_state() == ("applied" if on else "stock")
    assert ad.patch_active() == on
    assert b.u[mm.LOOKAT_CALL + 4] == mm.LOOKAT_CALL_DELAY
    untouched = {0x1AE0B0, 0x1AE03C, 0x1959E0}
    assert not untouched.intersection(a for a, _ in b.u_writes)


@pytest.mark.parametrize("where", ["legacy", "delay", "cave", "call"])
def test_ffx2_scoped_hook_preflights_every_word_before_writing(where):
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter, PatchConflict

    b = _patch_backend(applied=False)
    addr = {"legacy": mm.LOOKAT_LOAD_SITE, "delay": mm.LOOKAT_CALL + 4,
            "cave": mm.LOOKAT_CAVE + 8, "call": mm.LOOKAT_CALL}[where]
    b.u[addr] = 0xDEADBEEF
    with pytest.raises(PatchConflict):
        FFX2Adapter(b).set_patch(True)
    assert b.u_writes == []
    assert b.u[addr] == 0xDEADBEEF
    if where != "cave":
        with pytest.raises(PatchConflict):
            FFX2Adapter(b).set_patch(False)
        assert b.u_writes == []
    else:
        # A damaged cave may be detached by restoring our known call word;
        # do not overwrite the unknown cave as part of cleanup.
        b.u[mm.LOOKAT_CALL] = mm.LOOKAT_CALL_PATCHED
        FFX2Adapter(b).set_patch(False)
        assert b.u[mm.LOOKAT_CALL] == mm.LOOKAT_CALL_STOCK
        assert b.u[addr] == 0xDEADBEEF
        assert b.u_writes == [(mm.LOOKAT_CALL, mm.LOOKAT_CALL_STOCK)]


def test_ffx2_scoped_hook_reinstalls_after_savestate_and_restores_stock():
    from adapters.ffx2 import memory_map as mm
    from adapters.ffx2.adapter import FFX2Adapter
    from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT

    b = _ffx2_field_backend()
    ad = FFX2Adapter(b)
    rt = CameraRuntime(ad, CameraSettings(mode=MODE_ORBIT))
    rt.scene_refresh_ms = 0.0
    rt._tick(0.001, None)
    assert ad.patch_active()
    b.u = dict(_patch_backend(applied=False).u)  # a stock savestate replaces code + cave
    rt._patch_checked = 0.0
    rt._tick(0.001, None)
    assert ad.patch_active()
    rt.restore()
    assert ad.patch_state() == "stock"
    assert b.u[mm.LOOKAT_CALL] == mm.LOOKAT_CALL_STOCK
    assert b.u[mm.LOOKAT_LOAD_SITE] == mm.LOOKAT_LOAD_STOCK
