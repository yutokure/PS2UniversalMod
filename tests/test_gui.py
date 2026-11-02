"""GUI behaviour without an emulator: offscreen window on a fake PINE backend (see docs/gui/GUI_AUDIT_2026-11-02.md)."""
from __future__ import annotations

import json
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.shiningforceneo import memory_map as sf_mm  # noqa: E402
from adapters.suikoden5 import memory_map as su_mm  # noqa: E402
from gui.camera_controller import app as gui  # noqa: E402
from tests.test_suikoden5 import FakeBackend  # noqa: E402


class GuiBackend(FakeBackend):
    """The fake backend plus what the GUI asks of a PINE backend."""

    available = True
    connected = True

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


class DeadBackend:
    """PCSX2 not running."""

    available = False
    connected = False

    def connect(self) -> None:
        raise OSError("PCSX2 is not reachable")

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def env(tmp_path, monkeypatch, qapp):
    """Settings and presets in a temp folder, and a way to choose what PINE connects to."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    state = {"backend": DeadBackend}
    monkeypatch.setattr(gui, "PineBackend", lambda *a, **k: state["backend"]())
    windows = []

    def make(backend_cls=DeadBackend):
        state["backend"] = backend_cls
        w = gui.MainWindow()
        windows.append(w)
        return w

    def spin(secs=0.5):
        end = time.time() + secs
        while time.time() < end:
            qapp.processEvents()
            time.sleep(0.01)

    yield type("Env", (), {"make": staticmethod(make), "spin": staticmethod(spin), "tmp": tmp_path})
    for w in windows:
        w.close()
    spin(0.1)


def suikoden_backend():
    b = GuiBackend()
    b.stock()
    b.write_floats(su_mm.G_FOCUS, [65.6, 14.4, 5.1])
    b.write_floats(su_mm.G_EYE, [415.9, 104.4, 176.0])
    b.write_floats(su_mm.G_PITCH, [13.0]); b.write_floats(su_mm.G_YAW, [244.0])
    b.write_floats(su_mm.G_DISTANCE, [400.0]); b.write_floats(su_mm.G_FOV, [20.0])
    return b


class SuikodenBackend(GuiBackend):
    def __init__(self) -> None:
        super().__init__()
        self.mem = suikoden_backend().mem


class SFNeoBackend(GuiBackend):
    def __init__(self) -> None:
        super().__init__()
        self.gid, self.crcv, self.ttl = sf_mm.GAME_ID, sf_mm.DISC_CRC.lower(), "SF Neo"


class UnsupportedBackend(GuiBackend):
    def __init__(self) -> None:
        super().__init__()
        self.crcv = "deadbeef"


CAMERA_GROUPS = ("grp_mode", "grp_controls", "grp_rotation", "grp_position", "grp_lens")


# --- no game ----------------------------------------------------------------------------------
def test_no_game_disables_the_controls_and_explains(env):
    w = env.make(DeadBackend)
    env.spin(0.3)
    assert w.runtime is None
    assert all(not getattr(w, g).isEnabled() for g in CAMERA_GROUPS)
    assert w.lbl_notice.isVisibleTo(w)
    assert "PCSX2" in w.lbl_notice.text()
    assert w.rb_original.isChecked()


def test_unsupported_game_is_refused_with_its_id(env):
    w = env.make(UnsupportedBackend)
    env.spin(0.3)
    assert w.runtime is None
    assert all(not getattr(w, g).isEnabled() for g in CAMERA_GROUPS)
    assert "deadbeef" in w.lbl_notice.text().lower() or "DEADBEEF" in w.lbl_notice.text()


# --- a supported game ---------------------------------------------------------------------------
def test_connected_game_enables_controls_and_uses_the_game_limits(env):
    w = env.make(SuikodenBackend)
    env.spin(0.5)
    assert w.runtime is not None
    assert all(getattr(w, g).isEnabled() for g in CAMERA_GROUPS)
    assert "Suikoden V" in w.windowTitle()
    assert (w.sl_dist.spin.minimum(), w.sl_dist.spin.maximum()) == (50.0, 1500.0)
    assert w.off[0].spin.maximum() == 200.0
    assert (w.sl_yaw.spin.minimum(), w.sl_yaw.spin.maximum()) == (-180.0, 180.0)
    assert w.sl_pitch.spin.minimum() < 0 < w.sl_pitch.spin.maximum()
    assert w.lbl_look_hint.text() and w.lbl_pitch_hint.text()
    assert not w.rb_free.isEnabled()                       # no detached camera for this game
    assert w.grp_zoom.isVisibleTo(w)


def test_the_window_always_starts_in_original_whatever_was_saved(env):
    saved = {"games": {"SLPM-66286": {"game_id": "SLPM-66286", "mode": "orbit", "distance": 300.0}}}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    w = env.make(SuikodenBackend)
    env.spin(0.4)
    assert w.runtime.settings.mode == "original"
    assert w.rb_original.isChecked()
    assert w.runtime.settings.distance == 300.0            # the values are kept, only the mode is not


def test_offsets_are_disabled_when_the_adapter_cannot_use_them(env):
    w = env.make(SFNeoBackend)
    env.spin(0.4)
    assert w.runtime is not None
    assert all(not sl.isEnabled() for sl in w.off)
    assert "adapter" in w.off[0].toolTip().lower() or w.off[0].toolTip()
    assert w.lbl_look_hint.text() != ""
    assert not w.rb_free.isEnabled()


def test_offsets_group_is_folded_and_flags_when_in_use(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    assert not w.grp_offsets.isChecked()
    before = w.grp_offsets.title()
    w.off[0].spin.setValue(12.0)
    assert w.grp_offsets.title() != before
    w.off[0].spin.setValue(0.0)
    assert w.grp_offsets.title() == before


# --- buttons and presets ----------------------------------------------------------------------------
def test_one_button_turns_the_mod_off(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    assert not hasattr(w, "btn_disable")
    w.btn_enable.click()
    env.spin(0.4)
    assert w.runtime.settings.mode == "orbit"
    w.btn_restore.click()
    env.spin(0.4)
    assert w.runtime.settings.mode == "original" and w.rb_original.isChecked()


def test_loading_a_preset_never_changes_the_mode(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    preset = {"name": "p1", "game_id": "SLPM-66286",
              "settings": {"game_id": "SLPM-66286", "mode": "orbit", "distance": 275.0, "yaw_deg": 33.0,
                           "language": "en"}}
    (w.presets.dir / "p1.json").write_text(json.dumps(preset), encoding="utf-8")
    w._refresh_presets()
    w.cmb_preset.setCurrentText("p1")
    w.btn_load.click()
    assert w.runtime.settings.distance == 275.0 and w.runtime.settings.yaw_deg == 33.0
    assert w.runtime.settings.mode == "original"
    assert w.rb_original.isChecked()
    assert gui.current_language() == "ja"                  # a preset does not switch the language either


def test_overwriting_a_preset_asks_first(env, monkeypatch):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    w.presets.save("mine", w.app_settings)
    asked = []
    monkeypatch.setattr(gui, "_prompt", lambda *a: ("mine", True))
    monkeypatch.setattr(gui.QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(1) or gui.QMessageBox.No))
    before = (w.presets.dir / "mine.json").read_text(encoding="utf-8")
    w.sl_dist.spin.setValue(333.0)
    w.btn_save.click()
    assert asked and (w.presets.dir / "mine.json").read_text(encoding="utf-8") == before   # "No" kept it


# --- language ------------------------------------------------------------------------------------------
def test_language_switch_translates_every_registered_text(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    ja_stage, ja_restore = w.btn_zoom_stage[0].text(), w.btn_restore.text()
    en = w.cmb_lang.findData("en")
    w.cmb_lang.setCurrentIndex(en)
    env.spin(0.2)
    assert w.btn_zoom_stage[0].text() == "Stage 1" != ja_stage
    assert w.btn_restore.text() != ja_restore
    assert "Suikoden V" in w.windowTitle()
    assert w.btn_enable.toolTip().startswith("Turn the camera mod on")
    w.cmb_lang.setCurrentIndex(w.cmb_lang.findData("ja"))


# --- robustness --------------------------------------------------------------------------------------
def test_a_failing_game_write_becomes_a_message_not_an_exception(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)

    def boom():
        raise RuntimeError("PCSX2 went away")

    w.runtime.adapter.restore_fov = boom
    w.chk_fov.setChecked(True)
    w.chk_fov.setChecked(False)                            # restore_fov raises inside the slot
    env.spin(0.2)
    assert "PCSX2 went away" in w.lbl_notice.text()


def test_the_wheel_does_not_move_an_unfocused_slider(env, qapp):
    w = env.make(SuikodenBackend)
    env.spin(0.2)
    start = w.sl_dist.value()
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    w.sl_dist.slider.wheelEvent(ev)
    assert not ev.isAccepted()
    assert w.sl_dist.value() == start


def test_lost_link_disables_the_controls_then_they_come_back(env):
    w = env.make(SuikodenBackend)
    env.spin(0.6)
    assert w.grp_position.isEnabled()
    w.backend.available = False                           # PCSX2 "disappears": the poller reports no link
    env.spin(1.0)
    assert not w.grp_position.isEnabled()
    assert w.lbl_notice.isVisibleTo(w)
    w.backend.available = True
    env.spin(1.2)
    assert w.grp_position.isEnabled()


def test_zoom_follow_is_remembered_per_game(env):
    w = env.make(SuikodenBackend)
    env.spin(0.3)
    w.chk_zoom_follow.setChecked(False)
    w._persist()
    saved = json.loads((env.tmp / "PS2UniversalCamera" / "settings.json").read_text(encoding="utf-8"))
    assert saved["games"]["SLPM-66286"]["zoom_follow"] is False


def test_no_unregistered_hardcoded_english_in_the_main_labels(env):
    w = env.make(DeadBackend)
    env.spin(0.2)
    assert w.lbl_runtime.text() == gui.tr("state.stopped")
    assert w.statusBar().currentMessage() in ("", gui.tr("status.ready"), gui.tr("status.connected"))


def test_every_translation_key_used_by_the_window_exists():
    """A mistyped key shows up as the raw key on screen; catch it here."""
    import re
    from pathlib import Path
    from gui.camera_controller.i18n import TEXT
    src = Path(gui.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r"(?:_t|tr|_label|_btn|_chk|_radio|_group|_tip|_row)\(\s*(?:form,\s*|self\.\w+,\s*)?\"([a-z_]+\.[a-z_0-9]+)\"", src))
    keys |= set(re.findall(r"\(\"([a-z_]+\.[a-z_0-9]+)\",\s*\"color", src))
    keys |= set(re.findall(r"\"(tip\.[a-z_]+)\"|\"(notice\.[a-z_]+)\"|\"(hint\.[a-z_]+)\"", src) and
                [k for t in re.findall(r"\"(tip\.[a-z_]+)\"|\"(notice\.[a-z_]+)\"|\"(hint\.[a-z_]+)\"", src) for k in t if k])
    missing = sorted(k for k in keys if k not in TEXT)
    assert not missing, missing
    assert all(set(v) == {"en", "ja"} for v in TEXT.values())


# --- the running game changes under a live connection (review finding P1) --------------------------------
class SwitchBackend(SuikodenBackend):
    """One PINE connection that outlives the game: the test changes ``gid`` / ``crcv`` underneath it."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[int] = []
        self.times: list[float] = []

    def write_u32(self, a: int, v: int) -> None:
        self.log.append(a)
        self.times.append(time.monotonic())
        super().write_u32(a, v)

    write_float_block = None

    def write_floats(self, a, vals) -> None:
        for i, v in enumerate(vals):
            import struct
            self.write_u32(a + 4 * i, struct.unpack("<I", struct.pack("<f", float(v)))[0])

    write_float_block = write_floats


SU_ADDRS = (su_mm.CAM_HOOK, su_mm.CAM_HOOK + 4, su_mm.ZOOM_HOOK, su_mm.ZOOM_HOOK + 4)


#: the longest an unnoticed game change may still be written to (identity lease 0.25 s + margin)
DETECTION_BOUND = 0.6


def writes_after(be, t0: float, bound: float = DETECTION_BOUND) -> list[int]:
    """Writes later than ``bound`` seconds after ``t0``: none are allowed once the change is noticed."""
    return [a for a, t in zip(be.log, be.times) if t > t0 + bound]


def su_writes(be, since: int = 0) -> list[int]:
    return [a for a in be.log[since:]
            if a in SU_ADDRS or su_mm.MOD_BLOCK <= a < su_mm.CAVE_END]


def orbit_running(env, shared):
    w = env.make(lambda: shared)
    env.spin(0.4)
    w.btn_enable.click()
    env.spin(0.6)
    assert w.runtime.settings.mode == "orbit"
    assert su_writes(shared), "the orbit never wrote to the game"
    return w


def test_same_game_keeps_its_runtime_and_the_orbit(env):
    """TEST-P1-01: several identity checks pass and nothing is torn down or re-applied."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    runtime, guard = w.runtime, w.guard
    env.spin(1.6)                                           # four polls
    assert w.runtime is runtime and w.guard is guard and not guard.revoked
    assert w.runtime.settings.mode == "orbit" and w.runtime.running


def test_switching_to_an_unsupported_game_stops_all_writes(env):
    """TEST-P1-02 / 03 / 05: same socket, another disc.  Nothing may reach it, restore included."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    old_runtime = w.runtime
    shared.gid, shared.crcv, shared.ttl = "SLUS-20000", "cafef00d", "Some Other Game"
    t0 = time.monotonic()
    env.spin(1.6)
    assert writes_after(shared, t0) == [], "the old adapter or its restore wrote into the new game"
    assert w.runtime is None and not old_runtime.running
    assert all(not getattr(w, g).isEnabled() for g in CAMERA_GROUPS)
    assert "SLUS-20000" in w.lbl_notice.text() and "CAFEF00D" in w.lbl_notice.text().upper()
    t1 = time.monotonic()
    w.btn_reconnect.click()                                 # a manual reconnect on the new game is quiet as well
    env.spin(0.3)
    assert writes_after(shared, t1, 0.0) == []


def test_switching_between_supported_games_selects_the_new_adapter(env):
    """TEST-P1-04: Suikoden V -> Shining Force Neo -> Suikoden V on one connection."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    first = w.runtime
    shared.gid, shared.crcv, shared.ttl = sf_mm.GAME_ID, sf_mm.DISC_CRC.lower(), "SF Neo"
    t0 = time.monotonic()
    env.spin(1.6)
    assert type(w.adapter).__name__ == "SFNeoAdapter" and w.runtime is not first
    assert not first.running and w.runtime.settings.mode == "original"
    late = [a for a, t in zip(shared.log, shared.times) if t > t0 + DETECTION_BOUND]
    assert [a for a in late if a in SU_ADDRS or su_mm.MOD_BLOCK <= a < su_mm.CAVE_END] == [],         "Suikoden V addresses were written after the game changed"
    assert w.grp_mode.isEnabled()
    assert w.guard.expected == (sf_mm.GAME_ID.upper(), sf_mm.DISC_CRC.upper())
    # and back: the Suikoden adapter is chosen again
    shared.gid, shared.crcv, shared.ttl = su_mm.GAME_ID, su_mm.DISC_CRC.lower(), "Suikoden V"
    env.spin(1.6)
    assert type(w.adapter).__name__ == "Suikoden5Adapter" and w.runtime.settings.mode == "original"


def test_unsupported_game_is_noticed_when_a_supported_one_starts(env):
    shared = SwitchBackend()
    shared.crcv = "deadbeef"
    w = env.make(lambda: shared)
    env.spin(0.4)
    assert w.runtime is None and w.guard is not None and not w.guard.writes_allowed
    shared.crcv = su_mm.DISC_CRC.lower()
    env.spin(1.6)
    assert w.runtime is not None and w.grp_mode.isEnabled()


def test_closing_after_a_silent_game_switch_does_not_restore_into_the_new_game(env):
    """The window is closed (teardown + restore) before the poller has noticed the switch."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    w.poller.stop()                                         # no poll will notice; teardown must check itself

    shared.gid, shared.crcv = "SLUS-20000", "cafef00d"
    w.guard._verified_at -= 5.0                             # the next write must re-check the game
    time.sleep(0.05)
    t0 = time.monotonic()
    w.close()
    assert writes_after(shared, t0, 0.0) == []


def test_pcsx2_restart_with_another_game_does_not_restore_into_it(env):
    """TEST-P1-06: PCSX2 goes away and comes back running something else."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    shared.available = False
    env.spin(0.9)
    assert not w.grp_position.isEnabled()
    shared.gid, shared.crcv = "SLUS-20000", "cafef00d"
    t0 = time.monotonic()
    shared.available = True
    env.spin(1.6)
    assert writes_after(shared, t0) == [] and w.runtime is None


def test_pcsx2_restart_with_the_same_game_keeps_working(env):
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    runtime = w.runtime
    shared.available = False
    env.spin(0.9)
    shared.available = True
    env.spin(1.2)
    assert w.runtime is runtime and w.grp_position.isEnabled() and runtime.running


def test_the_status_poller_checks_the_game_without_touching_the_camera_loop(env):
    """TEST-P1-07: identity costs a handful of reads per second, not one per camera tick."""
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    reads = {"n": 0}
    orig = shared.game_id

    def counting():
        reads["n"] += 1
        return orig()
    shared.game_id = counting
    env.spin(2.0)
    # the poller (every 0.4 s) and the lease renewal (every ~0.15 s) only: nowhere near the camera tick rate
    assert 3 <= reads["n"] <= 25


# --- teardown restores only after a positive SAME (fail closed) -----------------------------------------
def hook_is_stock(be) -> bool:
    return be.read_u32(su_mm.CAM_HOOK) == su_mm.CAM_HOOK_WORDS[0]


def fresh_lease(w) -> None:
    w.poller.stop()                                         # nobody else renews it
    w.guard._verified_at = time.monotonic()                 # the last good check is moments old


def test_teardown_restores_the_camera_when_the_game_is_confirmed_the_same(env):
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    assert not hook_is_stock(shared)
    fresh_lease(w)
    w._teardown()
    assert hook_is_stock(shared) and w.runtime is None      # TEST-01 / 05: the normal way out still restores


def test_teardown_does_not_restore_when_the_game_cannot_be_identified(env):
    """UNKNOWN, even though the lease is still valid: no restore."""
    for how in ("error", "empty"):
        shared = SwitchBackend()
        w = orbit_running(env, shared)
        fresh_lease(w)
        if how == "error":
            def boom():
                raise OSError("PCSX2 busy")
            shared.game_id = boom
        else:
            shared.gid, shared.crcv = "", ""
        old = w.runtime
        w._teardown()
        n = len(shared.log)
        assert not hook_is_stock(shared), f"restored into an unidentified game ({how})"
        assert not old.running and w.runtime is None and w.guard is None
        time.sleep(0.2)
        assert len(shared.log) == n                         # and nothing else was written either


def test_teardown_does_not_restore_when_pcsx2_is_unreachable(env):
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    fresh_lease(w)
    shared.available = False
    old = w.runtime
    w._teardown()
    assert not hook_is_stock(shared) and not old.running and w.runtime is None


def test_teardown_does_not_restore_after_the_game_changed_or_the_guard_was_revoked(env):
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    fresh_lease(w)
    shared.gid, shared.crcv = "SLUS-20000", "cafef00d"
    w._teardown()
    assert not hook_is_stock(shared)
    shared2 = SwitchBackend()
    w2 = orbit_running(env, shared2)
    fresh_lease(w2)
    w2.guard.revoke("test")
    w2._teardown()
    assert not hook_is_stock(shared2)
