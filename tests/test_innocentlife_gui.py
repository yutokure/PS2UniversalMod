"""Registered Innocent Life GUI integration on synthetic memory, never PCSX2."""
from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.innocentlife import InnocentLifeAdapter, caves, memory_map as mm  # noqa: E402
from core.camera_runtime.engine import MODE_ORIGINAL, MODE_ORBIT  # noqa: E402
from core.memory_backend.guard import GuardedBackend, WriteBlocked  # noqa: E402
from gui.camera_controller import app as gui  # noqa: E402
from tests.test_innocentlife import CaveMachine, FakeBackend, seed_field  # noqa: E402


class GuiBackend(FakeBackend):
    """Only the fake transport lifecycle; all memory and guest work is synthetic."""
    available = connected = True

    def connect(self):
        pass

    def close(self):
        pass


@pytest.fixture
def make_window(tmp_path, monkeypatch):
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)
    windows = []

    def make(serial=mm.GAME_ID, crc=mm.DISC_CRC):
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


def test_innocentlife_registration_is_exact():
    assert gui.ADAPTERS["INNOCENTLIFE"] is InnocentLifeAdapter
    assert gui.ADAPTER_BY_GAME_ID["SLPS-25763"] is InnocentLifeAdapter
    assert "SLPS-25763" in gui.SUPPORTED_IDS
    assert (mm.GAME_ID, mm.DISC_CRC) == ("SLPS-25763", "9AC21F92")


@pytest.mark.parametrize("serial,crc", [
    ("SLPS-25763", "9AC21F92"), (" slps-25763 ", " 9ac21f92 "),
])
def test_registered_verified_disc_starts_original_clock_off_and_no_writes(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert isinstance(window.adapter, InnocentLifeAdapter)
    assert window.adapter.info.matched
    assert isinstance(window.adapter.backend, GuardedBackend)
    assert window.adapter.backend is window.guard
    assert window.guard.expected == (mm.GAME_ID, mm.DISC_CRC)
    assert window.guard.writes_allowed
    assert window.runtime.settings.mode == MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert not window.runtime.settings.pause_game_time
    assert not window.chk_game_time.isChecked()
    assert window.chk_game_time.isEnabled()
    assert backend.writes == []


@pytest.mark.parametrize("serial,crc", [
    ("SLPS-25763", "DEADBEEF"), ("SLPS-00000", "9AC21F92"),
])
def test_unverified_serial_or_crc_is_read_only_in_gui(make_window, serial, crc):
    window, backend = make_window(serial, crc)
    assert window.runtime is None
    assert not window.guard.writes_allowed
    assert not window.chk_game_time.isEnabled()
    assert not window.grp_mode.isEnabled()
    assert not window.grp_lens.isEnabled()
    assert backend.writes == []
    with pytest.raises(WriteBlocked):
        window.guard.write_u32(mm.CLOCK_HOOK, mm.CLOCK_PAUSED)
    window._flash_msg = None
    text, level = window._compute_notice(window.poller.data)
    assert serial in text and crc in text and level == "error"
    assert backend.writes == []


def test_innocentlife_fov_enabled_and_only_free_has_bilingual_unsupported_reason(make_window):
    window, backend = make_window()
    window.grp_offsets.setChecked(True)  # unchecked advanced group disables its children
    for language in ("ja", "en"):
        gui.set_language(language)
        window._retranslate()
        assert not window.rb_free.isEnabled()
        assert window.rb_free.toolTip() == window._t("mode.free_unsupported")
        for control in (window.sl_fov, window.chk_fov, window.btn_fov_reset):
            assert control.isEnabled()
            assert control.toolTip() != window._t("lens.unsupported")
        assert window.sl_fov.value() == pytest.approx(mm.STOCK_FOV_DEG, abs=.01)
        assert all(control.isEnabled() for control in window.off)
        assert window.chk_game_time.isEnabled()
        assert "PCSX2" in window.chk_game_time.toolTip()
    assert backend.writes == []


@pytest.mark.parametrize("language", ["ja", "en"])
def test_supported_fov_saved_values_and_presets_remain_game_scoped_without_enabling_camera(make_window, language):
    from core.config.settings import AppSettings
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    window.chk_fov.setChecked(True)
    window.sl_fov.set_value(85)
    window._on_fov(85)
    window.app_settings.use_fov = True
    window._apply_adapter_limits(window.adapter, window.runtime.settings)
    assert window.runtime.settings.use_fov and window.app_settings.use_fov
    window._persist()
    stored = window.store.get(mm.GAME_ID)
    assert stored.use_fov and stored.fov_deg == 85
    assert not window.store.get("SLPS-00000").use_fov
    preset = AppSettings(game_id=mm.GAME_ID, mode="orbit", use_fov=True, fov_deg=60,
                         language="en" if language == "ja" else "ja")
    window.presets.save("horizontal-fov", preset)
    window._refresh_presets()
    window.cmb_preset.setCurrentText("horizontal-fov")
    window._load_preset()
    assert window.runtime.settings.use_fov and window.app_settings.use_fov
    assert window.runtime.settings.fov_deg == window.app_settings.fov_deg == 60
    assert window.chk_fov.isChecked() and window.chk_fov.isEnabled()
    assert window.sl_fov.value() == 60
    assert window.runtime.settings.mode == MODE_ORIGINAL and window.rb_original.isChecked()
    assert gui.current_language() == language
    run_runtime_tick_on_worker(window.runtime)
    assert not window.adapter.patch_active()  # Original does not service FOV-only
    assert backend.writes == []
    # Loading persisted lens values in another window still starts in Original.
    window._persist()
    restarted, restarted_backend = make_window()
    assert restarted.runtime.settings.use_fov
    assert restarted.runtime.settings.fov_deg == 60
    assert restarted.runtime.settings.mode == MODE_ORIGINAL
    assert restarted.chk_fov.isChecked() and restarted.chk_fov.isEnabled()
    assert restarted_backend.writes == []


@pytest.mark.parametrize("language", ["ja", "en"])
def test_gui_orbit_fov_actual_readback_reset_and_disable_keep_clock_independent(make_window, language):
    window, backend = make_window()
    gui.set_language(language)
    window._retranslate()
    native = backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    window._on_mode(MODE_ORBIT)
    window.chk_fov.setChecked(True)
    window.sl_fov.set_value(60)
    window._on_fov(60)
    window.chk_game_time.setChecked(True)
    window.runtime._scene_time = window.runtime._fov_checked = 0
    run_runtime_tick_on_worker(window.runtime)
    CaveMachine(backend).render()
    assert window.adapter.fov_in_sync(60) and window.adapter.time_paused()
    data = window.poller.poll_once()
    assert data["fov"] == pytest.approx(60, abs=1e-5)
    assert data["scale"] == pytest.approx(443.405, abs=.001)
    assert backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native
    window.btn_fov_reset.click()
    CaveMachine(backend).render()
    assert not window.runtime.settings.use_fov and not window.chk_fov.isChecked()
    assert window.adapter.read_fov_deg() == pytest.approx(mm.STOCK_FOV_DEG, abs=1e-5)
    assert window.adapter.patch_active() and window.adapter.time_paused()
    window._on_mode(MODE_ORIGINAL)
    assert not window.adapter.patch_active() and window.adapter.time_paused()
    assert caves.matches(backend, mm.FLAG_TIME)
    window._restore()
    assert caves.matches(backend, 0)
    assert backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native


def run_runtime_tick_on_worker(runtime):
    errors = []

    def run():
        try:
            runtime._tick(0, None)
        except Exception as exc:  # test surfaces worker failures in the main thread
            errors.append(exc)

    worker = threading.Thread(target=run, name="test-clock-runtime-worker")
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive(), "synthetic clock tick did not finish"
    assert errors == []


def test_registered_original_clock_toggle_writes_only_on_worker(make_window):
    window, backend = make_window()
    # Collect actual fake transport writes, including the simulated guest lifecycle.
    writers = []
    backend.on_write = lambda address, data: writers.append(threading.current_thread().name)
    native_camera = backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE)
    window.chk_game_time.setChecked(True)
    assert window.runtime.settings.pause_game_time
    assert window.runtime.settings.mode == MODE_ORIGINAL
    assert backend.writes == []  # UI callback is only a runtime settings request
    run_runtime_tick_on_worker(window.runtime)
    assert not window.runtime.stats.game_time_error
    assert window.adapter.time_paused()
    assert backend.read_u32(mm.CLOCK_HOOK) == mm.CLOCK_PAUSED
    assert not window.adapter.patch_active()  # no Orbit merely because clock is stopped
    assert backend.bytes_at(mm.CAMERA, mm.CAMERA_SIZE) == native_camera
    assert writers and set(writers) == {"test-clock-runtime-worker"}
    data = window.poller.poll_once()
    assert data["game_time"] == "08:09:07"
    assert data["time_paused"] is True
    before = list(backend.writes)
    window.chk_game_time.setChecked(False)
    assert not window.runtime.settings.pause_game_time
    assert backend.writes == before
    window.runtime._time_checked_at = float("-inf")
    run_runtime_tick_on_worker(window.runtime)
    assert not window.adapter.time_paused()
    assert backend.read_u32(mm.CLOCK_HOOK) == mm.CLOCK_STOCK
    assert caves.matches(backend, 0)
    assert set(writers) == {"test-clock-runtime-worker"}


def test_registered_original_selection_preserves_clock_disable_all_releases(make_window):
    window, backend = make_window()
    window.chk_game_time.setChecked(True)
    run_runtime_tick_on_worker(window.runtime)
    window._on_mode(MODE_ORIGINAL)
    assert window.runtime.settings.pause_game_time
    assert window.chk_game_time.isChecked()
    assert window.adapter.time_paused()
    window._restore()
    assert not window.runtime.settings.pause_game_time
    assert not window.chk_game_time.isChecked()
    assert window.rb_original.isChecked()
    assert not window.adapter.time_paused()
    assert caves.matches(backend, 0)
