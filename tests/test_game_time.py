"""Generic clock-only runtime/GUI integration on synthetic guarded memory; no emulator."""
from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

import pytest

from core.camera_runtime import engine
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT, MODE_ORIGINAL
from core.config.settings import AppSettings
from core.memory_backend.guard import CHANGED, GuardedBackend


class ClockBackend:
    available = connected = True

    def __init__(self):
        self.gid, self.crcv = "TEST-CLOCK", "12345678"
        self.word = 7
        self.writes = []

    def connect(self):
        pass

    def close(self):
        pass

    def game_id(self):
        return self.gid

    def crc(self):
        return self.crcv

    def read_u32(self, address):
        return self.word

    def write_u32(self, address, value):
        self.writes.append((address, value, threading.current_thread().name))
        self.word = value


class ClockAdapter:
    """Contract fake; the address and words are synthetic, not game data."""
    features = {"game_time_pause": True}
    uses_offset_injection = False
    name = "TEST"

    def __init__(self, backend=None):
        self.backend = backend or ClockBackend()
        self.calls = []
        self.fail = False
        self.bad_readback = False
        self.camera_error = False
        self.status_error = False

    def identify(self):
        return SimpleNamespace(game_id=self.backend.game_id(), crc=self.backend.crc(),
                               title="Test clock", matched=True)

    def default_settings(self):
        # Even a bad adapter default must not enable a session-only clock setting.
        return {"pause_game_time": True}

    def set_time_paused(self, on):
        self.calls.append(bool(on))
        if self.fail:
            raise OSError("clock write failed")
        want = 0 if on else 7
        if self.backend.read_u32(0x100) != want:
            self.backend.write_u32(0x100, want)
        if self.bad_readback or self.backend.read_u32(0x100) != want:
            raise RuntimeError("clock readback mismatch")

    def time_paused(self):
        if self.status_error:
            raise OSError("clock status failed")
        return self.backend.read_u32(0x100) == 0

    def read_game_time(self):
        if self.status_error:
            raise OSError("clock status failed")
        return "12:34"

    def read_scene(self):
        return None

    def is_field_like(self, scene):
        return False

    def capture_original_fov(self):
        return 55.0

    def restore_fov(self):
        if self.camera_error:
            raise OSError("camera cleanup failed")

    def patch_state(self):
        return "stock"

    def read_fov_deg(self):
        return 55.0

    def read_fov_scale(self):
        return 1024.0


@pytest.fixture
def clock(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(engine.time, "perf_counter", lambda: now[0])
    ad = ClockAdapter()
    rt = CameraRuntime(ad)
    return now, ad, rt


def test_clock_setting_is_runtime_only_and_defaults_off():
    assert CameraSettings().pause_game_time is False
    assert "pause_game_time" not in AppSettings().__dict__


def test_unsupported_runtime_never_calls_clock_api(clock):
    _, ad, rt = clock
    ad.features = {}
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    rt.restore()
    assert ad.calls == []
    assert "not supported" in rt.stats.game_time_error


@pytest.mark.parametrize("mode", [MODE_ORIGINAL, MODE_ORBIT])
def test_clock_independent_of_mode_and_invalid_camera(clock, mode):
    now, ad, rt = clock
    rt.settings.mode = mode
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    assert ad.calls == [True]
    assert ad.backend.word == 0
    rt.settings.pause_game_time = False
    now[0] += 0.25
    rt._tick(0, None)
    assert ad.calls == [True, False]
    assert ad.backend.word == 7


def test_clock_is_serviced_even_while_camera_frozen(clock):
    _, ad, rt = clock
    rt.settings.mode = MODE_ORBIT
    rt.freeze(True)
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    assert ad.calls == [True]


def test_clock_checks_at_most_four_hz_and_reapplies_state_load(clock):
    now, ad, rt = clock
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    for _ in range(24):
        now[0] += 0.01
        rt._tick(0, None)
    assert ad.calls == [True]
    ad.backend.word = 7  # stock savestate load
    now[0] = 10.25
    rt._tick(0, None)
    assert ad.calls == [True, True]
    assert ad.backend.word == 0
    rt.settings.pause_game_time = False
    now[0] = 10.26
    rt._tick(0, None)
    assert ad.calls == [True, True]  # toggles do not bypass rate limit


@pytest.mark.parametrize("readback", [False, True])
def test_clock_failure_surfaces_and_retries(clock, readback):
    now, ad, rt = clock
    ad.fail, ad.bad_readback = not readback, readback
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    assert "clock" in rt.stats.game_time_error
    now[0] += 0.5
    rt._tick(0, None)
    assert len(ad.calls) == 1
    ad.fail = ad.bad_readback = False
    now[0] += 0.5
    rt._tick(0, None)
    assert ad.calls == [True, True]
    assert rt.stats.game_time_error == ""
    assert rt.stats.last_error == ""


def test_failed_partial_apply_still_restores_on_disable(clock):
    now, ad, rt = clock
    ad.bad_readback = True
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    assert ad.backend.word == 0
    rt.settings.pause_game_time = False
    ad.bad_readback = False
    now[0] += 1
    rt._tick(0, None)
    assert ad.calls == [True, False]
    assert ad.backend.word == 7


def test_restore_clock_even_when_camera_cleanup_fails(clock):
    _, ad, rt = clock
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    ad.camera_error = True
    rt.restore()
    assert not rt.settings.pause_game_time
    assert ad.calls == [True, False]
    assert ad.backend.word == 7
    assert "camera cleanup" in rt.stats.last_error


def test_restore_explicitly_releases_even_without_recorded_ownership(clock):
    _, ad, rt = clock
    ad.backend.word = 0
    rt.restore()
    assert ad.calls == [False]
    assert ad.backend.word == 7


def test_restore_failure_is_retained_and_retried(clock):
    now, ad, rt = clock
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    ad.fail = True
    rt.restore()
    assert not rt.settings.pause_game_time
    assert "clock write failed" in rt.stats.game_time_error
    ad.fail = False
    now[0] += 1
    rt._tick(0, None)
    assert ad.backend.word == 7
    assert not rt.stats.game_time_error


def test_original_camera_selection_can_preserve_clock(clock):
    _, ad, rt = clock
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    rt.restore(release_game_time=False)
    assert rt.settings.mode == MODE_ORIGINAL
    assert rt.settings.pause_game_time
    assert ad.calls == [True]


def test_abandon_is_write_free_and_cannot_restart(clock):
    _, ad, rt = clock
    rt.settings.pause_game_time = True
    rt._tick(0, None)
    before = list(ad.backend.writes)
    rt.abandon()
    rt.restore()
    rt.stop()
    rt.start()
    rt._tick(0, None)
    assert not rt.settings.pause_game_time
    assert not rt.running
    assert ad.backend.writes == before
    assert ad.calls == [True]


def test_running_worker_handles_toggle_and_disable_all_writes():
    applied, released = threading.Event(), threading.Event()

    class WorkerAdapter(ClockAdapter):
        def set_time_paused(self, on):
            super().set_time_paused(on)
            (applied if on else released).set()

    ad = WorkerAdapter()
    rt = CameraRuntime(ad, poll_hz=100)
    rt.settings.pause_game_time = True
    rt.start()
    try:
        assert applied.wait(1.0)
        rt.restore()  # live disable-all must queue, not write from this thread
        assert not rt.settings.pause_game_time
        assert released.wait(1.5)
        assert [name for _, _, name in ad.backend.writes] == ["camera-runtime", "camera-runtime"]
    finally:
        rt.stop()
        rt.restore()


@pytest.mark.parametrize("notice,clock_error", [
    ("", ""),
    ("patch: unknown hook word", ""),
    ("patch: write blocked: waiting for the game to be identified", ""),
    ("game clock: write blocked: waiting for the game to be identified",
     "game clock: write blocked: waiting for the game to be identified"),
    ("", "game clock: clock restore failed"),
])
def test_loop_recovery_clears_only_exact_loop_owned_error(monkeypatch, notice, clock_error):
    class PatchConflict(RuntimeError):
        pass

    class RecoveringAdapter(ClockAdapter):
        ticks = 0

        def tick(self, runtime):
            self.ticks += 1
            if self.ticks == 1:
                raise PatchConflict("stock state needs reapply")
            assert runtime.stats.last_error == "PatchConflict: stock state needs reapply"
            if notice:
                runtime.stats.last_error = notice
            runtime.stats.game_time_error = clock_error
            runtime._stop.set()  # successful recovery completes this deterministic loop

    ad = RecoveringAdapter()
    rt = CameraRuntime(ad)
    monkeypatch.setattr(rt, "_tick", lambda dt, pose: ad.tick(rt))
    monkeypatch.setattr(engine.time, "sleep", lambda delay: None)
    rt._loop()
    assert ad.ticks == 2
    assert rt.stats.connected
    assert rt.stats.last_error == notice
    assert rt.stats.game_time_error == clock_error


def test_loop_success_does_not_clear_handled_error_without_prior_exception(monkeypatch):
    rt = CameraRuntime(ClockAdapter())
    notice = "patch: write blocked: waiting for the game to be identified"

    def tick(dt, pose):
        rt.stats.last_error = notice
        rt._stop.set()

    monkeypatch.setattr(rt, "_tick", tick)
    monkeypatch.setattr(engine.time, "sleep", lambda delay: None)
    rt._loop()
    assert rt.stats.last_error == notice


def test_clock_uses_guard_for_apply_and_restore():
    be = ClockBackend()
    guard = GuardedBackend(be)
    guard.bind(be.game_id(), be.crc())
    ad = ClockAdapter(guard)
    rt = CameraRuntime(ad)
    rt.settings.pause_game_time = True
    rt._service_game_time()
    assert be.word == 0
    be.gid = "OTHER-GAME"
    assert guard.verify() == CHANGED
    before = list(be.writes)
    rt.restore()
    assert "write blocked" in rt.stats.game_time_error
    assert be.writes == before
    rt.abandon()
    assert be.writes == before


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from gui.camera_controller import app as gui

    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(gui, "PineBackend", ClockBackend)
    monkeypatch.setitem(gui.ADAPTER_BY_GAME_ID, "TEST-CLOCK", ClockAdapter)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)
    w = gui.MainWindow()
    w._timer.stop()
    yield w, gui, qapp
    w.close()


def test_gui_supported_startup_reconnect_and_persistence(window):
    w, _, _ = window
    assert isinstance(w.adapter.backend, GuardedBackend)
    assert w.chk_game_time.isEnabled()
    assert not w.chk_game_time.isChecked()
    assert not w.runtime.settings.pause_game_time
    assert "pause_game_time" not in w.app_settings.__dict__
    assert w.adapter.calls == []
    w.chk_game_time.setChecked(True)
    assert w.runtime.settings.pause_game_time
    assert w.adapter.calls == []  # GUI only sets a flag
    w.runtime._tick(0, None)
    assert w.adapter.calls == [True]
    w._persist()
    saved = json.loads(w.store.path.read_text(encoding="utf-8"))
    assert "pause_game_time" not in saved["games"]["TEST-CLOCK"]
    old = w.adapter
    w._reconnect()
    assert old.calls[-1] is False
    assert not w.chk_game_time.isChecked()
    assert not w.runtime.settings.pause_game_time
    assert w.adapter.calls == []


def test_gui_unsupported_adapter_disables_and_explains(window):
    w, _, _ = window
    w.adapter.features = {}
    w._apply_feature_gates()
    assert not w.chk_game_time.isEnabled()
    assert w.lbl_game_time_reason.text()
    assert w.chk_game_time.toolTip() == w.lbl_game_time_reason.text()
    w._on_game_time(True)
    assert not w.runtime.settings.pause_game_time
    assert w.adapter.calls == []


def test_gui_preset_never_enables_clock(window, monkeypatch):
    w, _, _ = window
    st = AppSettings(game_id="TEST-CLOCK", mode=MODE_ORBIT, yaw_deg=18)
    st.pause_game_time = True  # defense even against future/foreign preset values
    monkeypatch.setattr(w.presets, "load", lambda *a: st)
    w.cmb_preset.addItem("test")
    w._load_preset()
    assert w.runtime.settings.yaw_deg == 18
    assert w.runtime.settings.mode == MODE_ORIGINAL
    assert not w.runtime.settings.pause_game_time
    assert not w.chk_game_time.isChecked()
    assert w.adapter.calls == []


def test_gui_checkbox_resume_runs_only_on_runtime_tick(window):
    w, _, _ = window
    w.chk_game_time.setChecked(True)
    w.runtime._tick(0, None)
    w.chk_game_time.setChecked(False)
    assert not w.runtime.settings.pause_game_time
    assert w.adapter.calls == [True]
    w.runtime._time_checked_at = float("-inf")
    w.runtime._tick(0, None)
    assert w.adapter.calls == [True, False]


def test_gui_original_and_disable_all_are_distinct(window):
    w, _, _ = window
    w.chk_game_time.setChecked(True)
    w.runtime._tick(0, None)
    w._on_mode(MODE_ORIGINAL)
    assert w.runtime.settings.pause_game_time
    assert w.chk_game_time.isChecked()
    assert w.adapter.calls == [True]
    w._restore()
    assert not w.runtime.settings.pause_game_time
    assert not w.chk_game_time.isChecked()
    assert w.adapter.calls == [True, False]


def test_gui_clock_error_visible_in_original_and_clears_on_retry(window):
    w, _, _ = window
    w.adapter.fail = True
    w.chk_game_time.setChecked(True)
    w.runtime._tick(0, None)
    data = w.poller.poll_once()
    w._flash_msg = None
    text, level = w._compute_notice(data)
    assert "clock write failed" in text and level == "warn"
    w.adapter.fail = False
    w.runtime._time_retry_at = 0
    w.runtime._time_checked_at = float("-inf")
    w.runtime._tick(0, None)
    assert w._compute_notice(w.poller.poll_once()) == ("", "")


def test_gui_poller_reads_optional_clock_and_reports_failure(window):
    w, _, _ = window
    data = w.poller.poll_once()
    assert data["game_time"] == "12:34"
    assert data["time_paused"] is False
    w.adapter.status_error = True
    data = w.poller.poll_once()
    assert data["link"]
    assert "clock status failed" in data["game_time_error"]
    assert "clock status failed" in w._compute_notice(data)[0]


def test_gui_teardown_restores_clock_despite_camera_failure(window):
    w, _, _ = window
    w.chk_game_time.setChecked(True)
    w.runtime._tick(0, None)
    ad = w.adapter
    ad.camera_error = True
    w._teardown()
    assert ad.calls == [True, False]
    assert ad.backend.read_u32(0x100) == 7
    assert not w.chk_game_time.isChecked()


def test_gui_game_change_abandons_clock_without_write(window):
    w, _, _ = window
    w.chk_game_time.setChecked(True)
    w.runtime._tick(0, None)
    be, ad, rt = w.backend, w.adapter, w.runtime
    before = list(be.writes)
    be.gid = "OTHER-GAME"
    w._teardown()
    assert be.writes == before
    assert ad.calls == [True]
    assert not rt.settings.pause_game_time
    assert not w.chk_game_time.isChecked()


def test_gui_translations_explain_clock_not_emulator_pause(window):
    w, gui, _ = window
    for language, text in (("ja", "ゲーム内時間を停止"), ("en", "Pause in-game clock")):
        gui.set_language(language)
        w._retranslate()
        assert w.chk_game_time.text() == text
        assert "PCSX2" in w.chk_game_time.toolTip()
