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
