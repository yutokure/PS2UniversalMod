"""Grandia II GUI contracts on synthetic memory; never connect to PCSX2.

Workers/input pumps are disabled. Explicit guest callbacks use only the small
interpreter from test_grandia2, not a live renderer or packet-budget simulation.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.dragonquest5 import adapter as dq5  # noqa: E402
from adapters.grandia2 import Grandia2Adapter, memory_map as mm  # noqa: E402
from core.camera_runtime.engine import MODE_ORIGINAL, MODE_ORBIT, CameraSettings  # noqa: E402
from core.config.settings import AppSettings, SettingsStore  # noqa: E402
from core.memory_backend.guard import GuardedBackend, WriteBlocked  # noqa: E402
from gui.camera_controller import app as gui  # noqa: E402
from tests.test_grandia2 import CaveMachine, FakeBackend, seed_field  # noqa: E402


class GuiBackend(FakeBackend):
    """Only the fake transport lifecycle; no socket, emulator or worker."""
    available = connected = True

    def connect(self):
        pass

    def close(self):
        pass


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    previous_language = gui.current_language()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)
    windows = []

    def make(serial=mm.GAME_ID, crc=mm.DISC_CRC, *, saved_fov=None):
        if saved_fov is not None:
            SettingsStore().put(AppSettings(game_id=mm.GAME_ID, mode=MODE_ORBIT,
                                            fov_deg=saved_fov, use_fov=True))
        backend = seed_field(GuiBackend(serial, crc))
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


def test_grandia2_registration_and_fov_budget_are_exact():
    assert gui.ADAPTERS["GRANDIA2"] is Grandia2Adapter
    assert gui.ADAPTER_BY_GAME_ID["SLPM-65081"] is Grandia2Adapter
    assert "SLPM-65081" in gui.SUPPORTED_IDS
    assert (mm.GAME_ID, mm.DISC_CRC) == ("SLPM-65081", "B6AB7BC2")
    assert Grandia2Adapter.FOV_RANGE == (20, 60)


@pytest.mark.parametrize("serial,crc", [
    ("SLPM-65081", "B6AB7BC2"), (" slpm-65081 ", " b6ab7bc2 "),
])
def test_verified_disc_starts_original_without_clock_or_writes(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert isinstance(window.adapter, Grandia2Adapter)
    assert window.adapter.info.matched
    assert isinstance(window.adapter.backend, GuardedBackend)
    assert window.adapter.backend is window.guard
    assert window.guard.expected == (mm.GAME_ID, mm.DISC_CRC)
    assert window.guard.writes_allowed
    assert window.runtime.settings.mode == MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert not window.runtime.settings.pause_game_time
    assert not window.chk_game_time.isChecked()
    assert not window.chk_game_time.isEnabled()
    assert backend.writes == []


@pytest.mark.parametrize("serial,crc", [
    ("SLPM-65081", "DEADBEEF"), ("SLPM-00000", "B6AB7BC2"),
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


@pytest.mark.parametrize("language,title", [("ja", "グランディアII"), ("en", "Grandia II")])
def test_bilingual_features_ranges_and_unsupported_reasons(make_window, language, title):
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    window.grp_offsets.setChecked(True)
    assert title in window.windowTitle()
    assert not window.rb_free.isEnabled()
    assert window.rb_free.toolTip() == window._t("mode.free_unsupported")
    assert not window.chk_game_time.isEnabled()
    assert window.chk_game_time.toolTip() == window._t("time.unsupported")
    for control in (window.sl_fov, window.chk_fov, window.btn_fov_reset):
        assert control.isEnabled()
        assert control.toolTip() != window._t("lens.unsupported")
    assert (window.sl_fov.spin.minimum(), window.sl_fov.spin.maximum()) == (20, 60)
    assert window.sl_fov.value() == mm.STOCK_FOV_DEG
    assert (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == (100, 10000)
    assert (window.sl_look.spin.minimum(), window.sl_look.spin.maximum()) == (-1000, 1000)
    assert (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == (-25, 89.5)
    assert window.lbl_look_hint.text() == window._t("hint.look_up")
    assert window.lbl_pitch_hint.text() == window._t("hint.pitch_above")
    for control in window.off:
        assert control.isEnabled()
        assert (control.spin.minimum(), control.spin.maximum()) == (-3000, 3000)
    assert backend.writes == []


@pytest.mark.parametrize("saved,expected", [(110, 60), (10, 20), (45, 45)])
def test_saved_lens_is_clamped_in_runtime_settings_and_widgets_without_enabling(make_window, saved, expected):
    window, backend = make_window(saved_fov=saved)
    assert window.runtime.settings.fov_deg == window.app_settings.fov_deg == expected
    assert window.sl_fov.value() == expected
    assert window.runtime.settings.use_fov and window.chk_fov.isChecked()
    assert window.runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
    assert not window.adapter.patch_active()
    window._persist()
    assert window.store.get(mm.GAME_ID).fov_deg == expected
    assert backend.writes == []


@pytest.mark.parametrize("language", ["ja", "en"])
def test_wide_preset_clamps_to_60_preserves_original_and_game_scoped_settings(make_window, language):
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    window.store.put(AppSettings(game_id="SLPM-65555", fov_deg=110, use_fov=True))
    preset = AppSettings(game_id=mm.GAME_ID, mode=MODE_ORBIT, fov_deg=110, use_fov=True,
                         language="en" if language == "ja" else "ja")
    window.presets.save("old-wide-lens", preset)
    window._refresh_presets()
    window.cmb_preset.setCurrentText("old-wide-lens")
    window._load_preset()
    assert window.runtime.settings.fov_deg == window.app_settings.fov_deg == 60
    assert window.sl_fov.value() == 60 and window.chk_fov.isChecked()
    assert window.runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
    assert gui.current_language() == language
    assert not window.adapter.patch_active()
    window._persist()
    assert window.store.get(mm.GAME_ID).fov_deg == 60
    assert window.store.get("SLPM-65555").fov_deg == 110
    assert backend.writes == []
    restarted, restarted_backend = make_window()
    assert restarted.runtime.settings.fov_deg == restarted.app_settings.fov_deg == 60
    assert restarted.sl_fov.value() == 60
    assert restarted.runtime.settings.mode == MODE_ORIGINAL
    assert restarted_backend.writes == []


def test_optional_range_resets_to_existing_default_for_other_adapters(make_window):
    window, backend = make_window()
    assert window.sl_fov.spin.maximum() == 60
    # Exercise the generic GUI boundary with an existing real adapter that has
    # no custom FOV_RANGE; no game memory is read or written by limit application.
    legacy = dq5.DragonQuest5Adapter(window.guard)
    assert not hasattr(legacy, "FOV_RANGE")
    settings = CameraSettings(fov_deg=110, use_fov=True)
    window._apply_adapter_limits(legacy, settings)
    window._sync_widgets_from(settings)
    assert settings.fov_deg == window.app_settings.fov_deg == 110
    assert (window.sl_fov.spin.minimum(), window.sl_fov.spin.maximum()) == (20, 110)
    assert window.sl_fov.value() == 110
    window._apply_adapter_limits(window.adapter, settings)
    window._sync_widgets_from(settings)
    assert settings.fov_deg == window.app_settings.fov_deg == 60
    assert window.sl_fov.value() == 60
    assert backend.writes == []


def test_adapter_caps_direct_wide_request_and_gui_reset_keeps_orbit_view(make_window):
    window, backend = make_window()
    native = backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    window._on_mode(MODE_ORBIT)
    window.adapter.write_fov_deg(110)  # external callers cannot bypass the GUI cap
    machine = CaveMachine(backend)
    machine.render()
    machine.finish()
    assert window.adapter.fov_in_sync(110)
    assert window.adapter.read_fov_deg() == pytest.approx(60, abs=1e-4)
    pose = window.adapter.read_game_pose()
    data = window.poller.poll_once()
    assert data["fov"] == pytest.approx(60, abs=1e-4)
    assert not data.get("time_paused", False)
    window.btn_fov_reset.click()
    machine = CaveMachine(backend)
    machine.render()
    machine.finish()
    assert window.adapter.patch_active()
    assert window.adapter.read_game_pose() == pose
    assert window.adapter.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-4)
    assert backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    window._restore()
    assert not window.adapter.patch_active()
    assert window.rb_original.isChecked()
    assert backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
