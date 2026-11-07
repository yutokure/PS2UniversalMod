"""Session-only game options on synthetic guarded memory; never connects to PCSX2."""
from __future__ import annotations

import json
import os
import threading
import pytest

from core.camera_runtime import engine
from core.camera_runtime.engine import CameraRuntime, CameraSettings, MODE_ORBIT, MODE_ORIGINAL
from core.config.settings import AppSettings, SESSION_ONLY_SETTINGS
from core.memory_backend.guard import CHANGED, GuardedBackend
from tests.test_game_time import ClockAdapter, ClockBackend

NAMES = ("wide_view_running", "no_encounters")


class ToggleBackend(ClockBackend):
    def __init__(self):
        super().__init__()
        self.gid = "TEST-TOGGLES"
        self.words = {0x200: 7, 0x204: 7}

    def read_u32(self, address):
        return self.words[address]

    def write_u32(self, address, value):
        self.writes.append((address, value, threading.current_thread().name))
        self.words[address] = value


class ToggleAdapter(ClockAdapter):
    features = {name: True for name in NAMES}

    def __init__(self, backend=None):
        super().__init__(backend or ToggleBackend())
        self.calls = {name: [] for name in NAMES}
        self.fail = set()
        self.bad_readback = set()
        self.status_error = set()

    def default_settings(self):
        return {name: True for name in SESSION_ONLY_SETTINGS}

    def _set(self, name, on):
        self.calls[name].append(bool(on))
        if name in self.fail:
            raise OSError(f"{name} write failed")
        address = 0x200 + NAMES.index(name) * 4  # synthetic, not game data
        want = 0 if on else 7
        if self.backend.read_u32(address) != want:
            self.backend.write_u32(address, want)
        if name in self.bad_readback or self.backend.read_u32(address) != want:
            raise RuntimeError(f"{name} readback mismatch")

    def _get(self, name):
        if name in self.status_error:
            raise OSError(f"{name} status failed")
        return self.backend.read_u32(0x200 + NAMES.index(name) * 4) == 0

    def set_wide_view_running(self, on):
        self._set("wide_view_running", on)

    def wide_view_running(self):
        return self._get("wide_view_running")

    def set_no_encounters(self, on):
        self._set("no_encounters", on)

    def no_encounters(self):
        return self._get("no_encounters")


@pytest.fixture
def toggles(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(engine.time, "perf_counter", lambda: now[0])
    adapter = ToggleAdapter()
    return now, adapter, CameraRuntime(adapter)


@pytest.mark.parametrize("name", NAMES)
def test_session_only_defaults_not_serialized(name):
    assert getattr(CameraSettings(), name) is False
    assert name not in AppSettings().__dict__
    assert name not in AppSettings().to_dict()


@pytest.mark.parametrize("mode", [MODE_ORIGINAL, MODE_ORBIT])
@pytest.mark.parametrize("name", NAMES)
def test_independent_of_camera_and_other_toggle(toggles, mode, name):
    now, ad, rt = toggles
    rt.settings.mode = mode
    rt.freeze(True)
    setattr(rt.settings, name, True)
    rt._tick(0, None)
    assert ad.calls[name] == [True]
    assert getattr(ad, name)()
    other = next(n for n in NAMES if n != name)
    assert ad.calls[other] == []
    rt.restore(release_game_time=False, release_game_toggles=False)
    assert getattr(rt.settings, name)
    assert ad.calls[name] == [True]
    setattr(rt.settings, name, False)
    now[0] += .25
    rt._tick(0, None)
    assert ad.calls[name] == [True, False]
    assert not getattr(ad, name)()


def test_rate_limit_state_load_and_retry_are_independent(toggles):
    now, ad, rt = toggles
    rt.settings.wide_view_running = rt.settings.no_encounters = True
    ad.fail.add("wide_view_running")
    rt._tick(0, None)
    assert rt.stats.wide_view_running_error
    assert ad.no_encounters()
    assert rt.stats.no_encounters_error == ""
    now[0] += .24
    rt._tick(0, None)
    assert all(len(ad.calls[n]) == 1 for n in NAMES)
    ad.backend.words[0x204] = 7  # synthetic stock savestate
    now[0] = 10.25
    rt._tick(0, None)
    assert ad.no_encounters()
    assert ad.calls["no_encounters"] == [True, True]
    assert ad.calls["wide_view_running"] == [True]
    ad.fail.clear()
    now[0] = 11
    rt._tick(0, None)
    assert ad.wide_view_running()
    assert not rt.stats.wide_view_running_error


@pytest.mark.parametrize("name", NAMES)
def test_partial_apply_disable_and_restore_retry(toggles, name):
    now, ad, rt = toggles
    ad.bad_readback.add(name)
    setattr(rt.settings, name, True)
    rt._tick(0, None)
    assert getattr(ad, name)()
    ad.bad_readback.clear()
    ad.fail.add(name)
    ad.camera_error = True
    rt.restore()
    assert not getattr(rt.settings, name)
    assert getattr(rt.stats, f"{name}_error")
    other = next(n for n in NAMES if n != name)
    assert ad.calls[other] == [False]  # one failure does not skip the other cleanup
    ad.fail.clear()
    now[0] += 1
    rt._tick(0, None)
    assert not getattr(ad, name)()
    assert not getattr(rt.stats, f"{name}_error")


def test_unsupported_and_missing_api_fail_closed(toggles):
    _, ad, rt = toggles
    ad.features = {"wide_view_running": True}
    ad.set_wide_view_running = None
    rt.settings.wide_view_running = rt.settings.no_encounters = True
    rt._tick(0, None)
    assert "missing set_wide_view_running" in rt.stats.wide_view_running_error
    assert "not supported" in rt.stats.no_encounters_error
    assert all(not calls for calls in ad.calls.values())


def test_guard_blocks_release_and_abandon_never_writes():
    be = ToggleBackend()
    guard = GuardedBackend(be)
    guard.bind(be.game_id(), be.crc())
    ad = ToggleAdapter(guard)
    rt = CameraRuntime(ad)
    rt.settings.wide_view_running = rt.settings.no_encounters = True
    rt._tick(0, None)
    be.gid = "OTHER"
    assert guard.verify() == CHANGED
    before = list(be.writes)
    rt.restore()
    assert "write blocked" in rt.stats.wide_view_running_error
    assert "write blocked" in rt.stats.no_encounters_error
    rt.abandon()
    rt.restore()
    rt.stop()
    rt.start()
    rt._tick(0, None)
    assert be.writes == before
    assert not rt.running
    assert not rt.settings.wide_view_running and not rt.settings.no_encounters


def test_live_worker_owns_apply_and_disable_all():
    applied, released = threading.Event(), threading.Event()

    class WorkerAdapter(ToggleAdapter):
        def set_no_encounters(self, on):
            super().set_no_encounters(on)
            (applied if on else released).set()

    ad = WorkerAdapter()
    rt = CameraRuntime(ad, poll_hz=100)
    rt.settings.wide_view_running = rt.settings.no_encounters = True
    rt.start()
    try:
        assert applied.wait(1)
        rt.restore()
        assert released.wait(1.5)
        assert len(ad.backend.writes) == 4
        assert {writer for _, _, writer in ad.backend.writes} == {"camera-runtime"}
    finally:
        rt.stop()
        rt.restore()


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from gui.camera_controller import app as gui
    qapp = QApplication.instance() or QApplication([])
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(gui, "PineBackend", ToggleBackend)
    monkeypatch.setitem(gui.ADAPTER_BY_GAME_ID, "TEST-TOGGLES", ToggleAdapter)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)
    w = gui.MainWindow()
    w._timer.stop()
    yield w, gui, qapp
    w.close()


def test_gui_startup_flags_only_original_disable_reconnect_and_no_persistence(window):
    w, _, _ = window
    assert isinstance(w.adapter.backend, GuardedBackend)
    for name in NAMES:
        checkbox = getattr(w, f"chk_{name}")
        assert checkbox.isEnabled() and not checkbox.isChecked()
        assert not getattr(w.runtime.settings, name)
        checkbox.setChecked(True)
        assert getattr(w.runtime.settings, name)
        assert ad_calls_empty(w.adapter)
    w.runtime._tick(0, None)
    w._on_mode(MODE_ORIGINAL)
    assert all(getattr(w.runtime.settings, n) for n in NAMES)
    w._persist()
    saved = json.loads(w.store.path.read_text(encoding="utf-8"))
    assert SESSION_ONLY_SETTINGS.isdisjoint(saved["games"]["TEST-TOGGLES"])
    preset = w.presets.save("session-not-saved", w.app_settings)
    assert SESSION_ONLY_SETTINGS.isdisjoint(json.loads(preset.read_text())["settings"])
    old = w.adapter
    w._reconnect()
    for name in NAMES:
        assert old.calls[name] == [True, False]
        assert not getattr(w, f"chk_{name}").isChecked()
        assert not getattr(w.runtime.settings, name)
    assert ad_calls_empty(w.adapter)
    for name in NAMES:
        getattr(w, f"chk_{name}").setChecked(True)
    w.runtime._tick(0, None)
    w._restore()
    assert all(w.adapter.calls[n] == [True, False] for n in NAMES)


def ad_calls_empty(adapter):
    return all(not calls for calls in adapter.calls.values())


@pytest.mark.parametrize("initial", [False, True])
def test_gui_preset_cannot_change_session_toggles(window, monkeypatch, initial):
    w, _, _ = window
    st = AppSettings(game_id="TEST-TOGGLES", yaw_deg=18)
    for name in NAMES:
        getattr(w, f"chk_{name}").setChecked(initial)
        setattr(st, name, not initial)
    monkeypatch.setattr(w.presets, "load", lambda *args: st)
    w.cmb_preset.addItem("foreign")
    w._load_preset()
    assert w.runtime.settings.yaw_deg == 18
    assert w.runtime.settings.mode == MODE_ORIGINAL
    assert all(getattr(w.runtime.settings, n) == initial for n in NAMES)
    assert all(getattr(w, f"chk_{n}").isChecked() == initial for n in NAMES)
    assert ad_calls_empty(w.adapter)


@pytest.mark.parametrize("name", NAMES)
def test_gui_feature_gate_bilingual_explanation_and_status_error(window, name):
    w, gui, _ = window
    for language in ("ja", "en"):
        gui.set_language(language)
        w._retranslate()
        checkbox = getattr(w, f"chk_{name}")
        assert checkbox.text() == w._t(f"toggle.{name}")
        assert checkbox.toolTip() == w._t(f"toggle.{name}.explanation")
        assert "Original" in w.chk_wide_view_running.toolTip()
        assert ("orange" if language == "en" else "オレンジ") in w.chk_no_encounters.toolTip()
    w.adapter.status_error.add(name)
    data = w.poller.poll_once()
    assert data["link"]
    assert f"{name} status failed" in data[f"{name}_error"]
    w._flash_msg = None
    assert f"{name} status failed" in w._compute_notice(data)[0]
    w.poller.data = data
    w._refresh()
    assert f"{name} status failed" in getattr(w, f"lbl_{name}").text()
    w.adapter.status_error.clear()
    w.adapter.fail.add(name)
    getattr(w, f"chk_{name}").setChecked(True)
    w.runtime._tick(0, None)
    assert f"{name} write failed" in w._compute_notice(w.poller.poll_once())[0]
    w.adapter.features = {}
    w._apply_feature_gates()
    assert not getattr(w, f"chk_{name}").isEnabled()
    assert getattr(w, f"lbl_{name}_reason").text() == w._t(f"toggle.{name}.unsupported")


def test_gui_game_change_abandons_without_cleanup_writes(window):
    w, _, _ = window
    for name in NAMES:
        getattr(w, f"chk_{name}").setChecked(True)
    w.runtime._tick(0, None)
    be, ad, rt = w.backend, w.adapter, w.runtime
    before = list(be.writes)
    be.gid = "OTHER"
    w._teardown()
    assert be.writes == before
    assert all(ad.calls[n] == [True] for n in NAMES)
    assert all(not getattr(rt.settings, n) for n in NAMES)
    assert all(not getattr(w, f"chk_{n}").isChecked() for n in NAMES)
