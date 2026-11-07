"""Symphonia GUI contracts on synthetic memory; no emulator or game dumps.

All PINE transport, status/runtime workers and input pumps are replaced before
window construction. These tests cover registration and host UI contracts, not
native camera rendering, cave execution, or unverified gameplay scenes.
"""
from __future__ import annotations

import math
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.talesofsymphonia.adapter import TalesOfSymphoniaAdapter  # noqa: E402
from adapters.talesofsymphonia import caves, memory_map as mm  # noqa: E402
from core.camera_runtime.engine import MODE_ORIGINAL, MODE_ORBIT  # noqa: E402
from core.config.settings import AppSettings, SettingsStore  # noqa: E402
from core.memory_backend.guard import GuardedBackend, WriteBlocked  # noqa: E402
from gui.camera_controller import app as gui  # noqa: E402
from tests.test_druaga import FakeBackend as ByteBackend  # noqa: E402


class GuiBackend(ByteBackend):
    """Sparse synthetic memory and identity, never a socket or live process."""
    available = connected = True

    def connect(self):
        pass

    def close(self):
        pass

    def title(self):
        return "TALES OF SYMPHONIA"

    def read_f32(self, address):
        return self.read_floats(address, 1)[0]


def seed_town(backend):
    """Independent synthetic Z-up geometry; no copied savestate payload."""
    player, eye, target = (100.0, 200.0, 10.0), (100.0, -1200.0, 800.0), (100.0, 200.0, 97.0)
    backend.seed_u32(mm.MODE, mm.TOWN_MODE)
    backend.seed_u32(mm.SUBMODE, 0)
    backend.seed_u32(mm.TOWN_ACTOR, 0x13BA20)
    backend.seed_floats(mm.TOWN_PLAYER, player)
    backend.seed_floats(mm.TOWN_EYE, eye)
    backend.seed_floats(mm.TOWN_TARGET, target)
    delta = [a - b for a, b in zip(eye, target)]
    length = math.sqrt(sum(x * x for x in delta))
    backward = [x / length for x in delta]
    right = [1.0, 0.0, 0.0]
    up = [0.0, backward[2], -backward[1]]
    backend.seed_floats(mm.CAMERA_WORLD, [*right, 0, *up, 0, *backward, 0, *eye, 1])
    view = [right[0], up[0], backward[0], 0,
            right[1], up[1], backward[1], 0,
            right[2], up[2], backward[2], 0,
            -sum(x * y for x, y in zip(eye, right)),
            -sum(x * y for x, y in zip(eye, up)),
            -sum(x * y for x, y in zip(eye, backward)), 1]
    backend.seed_floats(mm.VIEW, view)
    # Stock FOV comes from the selected 0x94-byte native rig, not the shared
    # projection matrix: late HUD rendering may already have replaced that.
    vertical = math.degrees(2 * math.atan(math.tan(math.radians(36) / 2) / (4 / 3)))
    backend.seed_u32(mm.TOWN_CAMERA_INDEX, 2)
    backend.seed_floats(mm.TOWN_CAMERA_BASE + 2 * 0x94 + 0x58, [vertical])
    backend.seed_floats(mm.TOWN_CAMERA_BASE + 0x58, [70])  # tempting unselected rig
    # Deliberately disagree with the native rig so a HUD-mirror regression fails.
    sx = 1 / math.tan(math.radians(70) / 2)
    backend.seed_floats(mm.PROJECTION,
                        [sx, 0, 0, 0, 0, sx * 4 / 3, 0, 0, 0, 0, -1.01, -1, 0, 0, -201, 0])
    for site, stock, _, _, _ in caves.RESOURCES:
        for index, word in enumerate(stock):
            backend.seed_u32(site + 4 * index, word)
    return backend


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    previous_language = gui.current_language()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)
    windows = []

    def make(serial=mm.GAME_ID, crc=mm.DISC_CRC, *, saved=None):
        if saved is not None:
            SettingsStore().put(AppSettings(game_id=mm.GAME_ID, mode=MODE_ORBIT, **saved))
        backend = seed_town(GuiBackend(serial, crc))
        monkeypatch.setattr(gui, "PineBackend", lambda: backend)
        window = gui.MainWindow()
        window._timer.stop()
        windows.append(window)
        return window, backend

    yield make
    for window in windows:
        window.close()
    qapp.processEvents()
    gui.set_language(previous_language)


def test_symphonia_registration_and_adapter_limits_are_exact():
    assert gui.ADAPTERS["TALESOFSYMPHONIA"] is TalesOfSymphoniaAdapter
    assert gui.ADAPTER_BY_GAME_ID["SLPS-25400"] is TalesOfSymphoniaAdapter
    assert "SLPS-25400" in gui.SUPPORTED_IDS
    assert (mm.GAME_ID, mm.DISC_CRC) == ("SLPS-25400", "830B6FB1")
    assert TalesOfSymphoniaAdapter.PITCH_RANGE == (-25, 89.5)
    assert TalesOfSymphoniaAdapter.PITCH_DISPLAY_SIGN == 1
    assert TalesOfSymphoniaAdapter.LOOK_HEIGHT_POSITIVE_IS == "down"
    assert TalesOfSymphoniaAdapter.DISTANCE_RANGE == (50, 6000)
    assert TalesOfSymphoniaAdapter.LOOK_HEIGHT_RANGE == (-1000, 1000)
    assert TalesOfSymphoniaAdapter.OFFSET_RANGE == (-3000, 3000)
    assert TalesOfSymphoniaAdapter.FOV_RANGE == (20, 110)


@pytest.mark.parametrize("serial,crc", [
    ("SLPS-25400", "830B6FB1"), (" slps-25400 ", " 830b6fb1 "),
])
def test_verified_disc_starts_original_guarded_without_writes(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert isinstance(window.adapter, TalesOfSymphoniaAdapter)
    assert window.adapter.info.matched
    assert isinstance(window.adapter.backend, GuardedBackend)
    assert window.adapter.backend is window.guard
    assert window.guard.expected == (mm.GAME_ID, mm.DISC_CRC)
    assert window.guard.writes_allowed
    assert window.adapter.is_field_like(window.adapter.read_scene())
    assert window.adapter.patch_state() == "stock"
    # Native half-angle conversion truncates 16-bit-turn units before trig;
    # allow one input step rather than expecting an unquantized 36 degrees.
    assert window.runtime._orig_fov == pytest.approx(36, abs=0.02)
    assert window.adapter.read_fov_deg() == pytest.approx(36, abs=0.02)
    defaults = window.adapter.default_settings()
    assert window.runtime.settings.distance == defaults["distance"] == window.sl_dist.value()
    assert window.runtime.settings.look_height == defaults["look_height"] == window.sl_look.value()
    assert window.runtime.settings.pitch_deg == defaults["pitch_deg"] == window.sl_pitch.value()
    assert window.runtime.settings.fov_deg == defaults["fov_deg"] == window.sl_fov.value()
    assert window.runtime.settings.mode == MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert not window.runtime.settings.pause_game_time
    assert not window.chk_game_time.isChecked()
    assert not window.chk_game_time.isEnabled()
    assert backend.writes == []


@pytest.mark.parametrize("serial,crc", [
    ("SLPS-25400", "DEADBEEF"), ("SLPS-00000", "830B6FB1"),
])
def test_unverified_disc_remains_read_only(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert window.runtime is None
    assert not window.guard.writes_allowed
    assert not window.grp_mode.isEnabled()
    assert not window.grp_lens.isEnabled()
    assert not window.chk_game_time.isEnabled()
    assert backend.writes == []
    with pytest.raises(WriteBlocked):
        window.guard.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, mm.FLAG_ORBIT)
    window._flash_msg = None
    text, level = window._compute_notice(window.poller.data)
    assert serial in text and crc in text and level == "error"
    assert backend.writes == []


@pytest.mark.parametrize("language,title", [
    ("ja", "テイルズ オブ シンフォニア"), ("en", "Tales of Symphonia"),
])
def test_bilingual_features_ranges_and_reasons(make_window, language, title):
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    window.grp_offsets.setChecked(True)
    assert title in window.windowTitle()
    assert window.rb_orbit.isEnabled()
    assert not window.rb_free.isEnabled()
    assert window.rb_free.toolTip() == window._t("mode.free_unsupported")
    assert not window.chk_game_time.isEnabled()
    assert window.chk_game_time.toolTip() == window._t("time.unsupported")
    for control in (window.sl_fov, window.chk_fov, window.btn_fov_reset):
        assert control.isEnabled()
        assert control.toolTip() != window._t("lens.unsupported")
    assert (window.sl_fov.spin.minimum(), window.sl_fov.spin.maximum()) == (20, 110)
    assert (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == (50, 6000)
    assert (window.sl_look.spin.minimum(), window.sl_look.spin.maximum()) == (-1000, 1000)
    assert (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == (-25, 89.5)
    assert window.lbl_look_hint.text() == window._t("hint.look_down")
    assert window.lbl_pitch_hint.text() == window._t("hint.pitch_above")
    for index, control in enumerate(window.off):
        assert control.isEnabled()
        assert (control.spin.minimum(), control.spin.maximum()) == (-3000, 3000)
        key = "tip.cam_eye_offset" if index < 3 else "tip.tgt_offset"
        assert control.toolTip() == window._t(key)
    assert backend.writes == []


@pytest.mark.parametrize("saved,expected", [(150, 110), (110, 110), (10, 20), (45, 45)])
def test_saved_lens_is_clamped_without_enabling(make_window, saved, expected):
    window, backend = make_window(saved={"fov_deg": saved, "use_fov": True})
    assert window.runtime.settings.fov_deg == window.app_settings.fov_deg == expected
    assert window.sl_fov.value() == expected
    assert window.runtime.settings.use_fov and window.chk_fov.isChecked()
    assert window.runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
    window._persist()
    assert window.store.get(mm.GAME_ID).fov_deg == expected
    assert backend.writes == []


@pytest.mark.parametrize("saved,expected", [(-90, -25), (90, 89.5), (42, 42)])
def test_pitch_limits_override_stale_settings_in_canonical_sign(make_window, saved, expected):
    window, backend = make_window(saved={"pitch_deg": saved, "pitch_min_deg": -90, "pitch_max_deg": 90})
    settings = window.runtime.settings
    assert (settings.pitch_min_deg, settings.pitch_max_deg) == (-25, 89.5)
    assert settings.pitch_deg == window.app_settings.pitch_deg == window.sl_pitch.value() == expected
    assert window._pitch_to_display(expected) == window._pitch_from_display(expected) == expected
    assert window.rb_original.isChecked()
    assert backend.writes == []


@pytest.mark.parametrize("language", ["ja", "en"])
def test_preset_stays_original_language_and_game_scoped(make_window, language):
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    window.store.put(AppSettings(game_id="SLPM-65081", fov_deg=100, use_fov=True))
    preset = AppSettings(game_id=mm.GAME_ID, mode=MODE_ORBIT, fov_deg=150, use_fov=True,
                         pitch_deg=120, pitch_min_deg=-90, pitch_max_deg=90,
                         language="en" if language == "ja" else "ja")
    window.presets.save("wide-lens", preset)
    window._refresh_presets()
    window.cmb_preset.setCurrentText("wide-lens")
    window._load_preset()
    assert window.runtime.settings.fov_deg == window.app_settings.fov_deg == window.sl_fov.value() == 110
    assert window.runtime.settings.pitch_deg == window.sl_pitch.value() == 89.5
    assert window.runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
    assert gui.current_language() == language
    window._persist()
    assert window.store.get(mm.GAME_ID).fov_deg == 110
    assert window.store.get("SLPM-65081").fov_deg == 100
    assert backend.writes == []
    restarted, restarted_backend = make_window()
    assert restarted.runtime.settings.fov_deg == restarted.app_settings.fov_deg == 110
    assert restarted.runtime.settings.mode == MODE_ORIGINAL
    assert restarted_backend.writes == []


def test_game_switch_abandons_without_restore_or_writes(make_window, monkeypatch):
    window, backend = make_window()
    monkeypatch.setattr(window.runtime, "restore", lambda: pytest.fail("restore after game switch"))
    backend.serial = "SLPM-65081"
    backend.disc_crc = "B6AB7BC2"
    window._teardown(restore=True)
    assert window.runtime is None and window.adapter is None and window.guard is None
    assert backend.writes == []
