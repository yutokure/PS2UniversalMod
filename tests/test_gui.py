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
from adapters.shiningforceexa import memory_map as ex_mm  # noqa: E402
from adapters.suikoden5 import memory_map as su_mm  # noqa: E402
from adapters.nightmaredruaga import memory_map as dr_mm  # noqa: E402
from adapters.radiatastories import caves as ra_caves, memory_map as ra_mm  # noqa: E402
from adapters.minstrelsong import caves as ms_caves, memory_map as ms_mm  # noqa: E402
from core.camera_math.orbit import Vec3, orbit_pose  # noqa: E402
from core.memory_backend.guard import WriteBlocked  # noqa: E402
from gui.camera_controller import app as gui  # noqa: E402
from tests.test_suikoden5 import FakeBackend  # noqa: E402
from tests.test_druaga import FakeBackend as DruagaFakeBackend, seed_field as seed_druaga_field  # noqa: E402
from tests.test_minstrelsong import (  # noqa: E402
    FakeBackend as MinstrelSongFakeBackend, active_bank as minstrelsong_bank,
    seed_field as seed_minstrelsong_field,
)


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


def seed_shining_field(backend, memory_map) -> None:
    """Synthetic field geometry and stock patch words; no emulator/game dump needed."""
    backend.write_floats(memory_map.PARTY_POS, [123.0, 200.0, 321.0])
    height = memory_map.STOCK_HEIGHT
    backend.write_floats(memory_map.CAM_FOCUS, [123.0, 200.0 + height, 321.0, 1.0])
    backend.write_floats(memory_map.CAM_EYE, [123.0, 700.0 + height, 1187.0254, 1.0])
    backend.write_floats(memory_map.CAM_DISTANCE, [1000.0])
    backend.write_floats(memory_map.CAM_HEIGHT, [height])
    backend.write_u32(memory_map.CAM_MODE, 0)
    backend.write_u32(memory_map.CAM_FOCUS_MODE, 0)
    backend.write_floats(memory_map.CAM_VP,
                         [3.6, 0, 0, 0, 0, 5.1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    backend.write_u32(memory_map.VP_LOAD_CALL, memory_map.VP_LOAD_WORD)
    backend.write_u32(memory_map.PAD_CALL_SITE, memory_map.PAD_CALL_WORD)
    backend.write_u32(memory_map.SMOOTH_GATE_WORD,
                      memory_map.SMOOTH_GATE_STOCK << memory_map.SMOOTH_GATE_SHIFT)
    if memory_map is ex_mm:
        backend.write_u32(ex_mm.CAM_ACTIVE_PTR, ex_mm.CAM_STRUCT)
        backend.write_u32(ex_mm.PARTY_ACTOR_PTR, ex_mm.PARTY_POS - ex_mm.PARTY_POS_OFFSET)
        backend.write_u32(ex_mm.CAM_FOV_WORD, 0x10000000)
        backend.write_floats(ex_mm.CAM_ASPECT, [ex_mm.PROJ_ASPECT])
        backend.write_u32(ex_mm.PAD_RX_LOAD, ex_mm.PAD_RX_WORD)
        backend.write_u32(ex_mm.PAD_RY_LOAD, ex_mm.PAD_RY_WORD)


class SFNeoBackend(GuiBackend):
    def __init__(self) -> None:
        super().__init__()
        self.gid, self.crcv, self.ttl = sf_mm.GAME_ID, sf_mm.DISC_CRC.lower(), "SF Neo"
        seed_shining_field(self, sf_mm)


EXA_GAME_ID, EXA_CRC = "SLPM-66646", "8B383FDF"


class SFExaBackend(GuiBackend):
    def __init__(self) -> None:
        super().__init__()
        self.gid, self.crcv, self.ttl = EXA_GAME_ID, EXA_CRC.lower(), "SF Exa"
        seed_shining_field(self, ex_mm)


class DruagaBackend(DruagaFakeBackend):
    """GUI transport contract over Druaga's synthetic byte-addressed field."""

    available = True
    connected = True

    def __init__(self):
        super().__init__(crc=dr_mm.DISC_CRC.lower())
        seed_druaga_field(self)

    def connect(self):
        pass

    def close(self):
        pass


RADIATA_GAME_ID, RADIATA_CRC = "SLPM-65800", "AC73005E"


class RadiataBackend(DruagaFakeBackend):
    """Synthetic field and transport for GUI integration; no emulator or game dump."""

    available = True
    connected = True

    def __init__(self):
        import math
        super().__init__(serial=RADIATA_GAME_ID, crc=RADIATA_CRC.lower())
        field, owner, camera, target = 0x1000000, 0x1002000, 0x1003000, 0x1004000
        scene, manager, records, actor, node, renderer = (
            0x1005000, 0x1006000, 0x1007000, 0x1008000, 0x1009000, 0x100A000)
        for address, value in (
            (ra_mm.FIELD_MANAGER_PTR, field), (field + ra_mm.FIELD_OWNER, owner),
            (owner + ra_mm.OWNER_CAMERA, camera), (owner + ra_mm.OWNER_TARGET, target),
            (camera, ra_mm.CAMERA_VTABLE), (target, ra_mm.NODE_VTABLE),
            (ra_mm.RENDERER_PTR, renderer), (renderer + ra_mm.RENDERER_CAMERA, camera),
            (ra_mm.SCENE_PTR, scene), (scene + ra_mm.PLAYER_ID, 1),
            (ra_mm.ACTOR_MANAGER_PTR, manager), (manager + ra_mm.ACTOR_COUNT, 1),
            (manager + ra_mm.ACTOR_RECORDS, records), (records + ra_mm.ACTOR_ID, 1),
            (records + ra_mm.ACTOR_OBJECT, actor), (records + ra_mm.ACTOR_NODE, node),
            (node, ra_mm.NODE_VTABLE),
        ):
            self.seed_u32(address, value)
        player = Vec3(100, 1000, -4000)
        pose = orbit_pose(player + Vec3(0, -90, 0), math.pi, math.radians(20), 1500)
        self.seed_floats(node + ra_mm.NODE_POS, (*player.as_tuple(), 1))
        self.seed_floats(target + ra_mm.NODE_POS, (*pose.target.as_tuple(), 1))
        self.seed_floats(camera + ra_mm.CAM_NATIVE_WORLD, gui.RadiataStoriesAdapter._matrix(pose))
        self.seed_floats(camera + ra_mm.CAM_FOV, [math.radians(ra_mm.STOCK_FOV_DEG)])
        self.seed_floats(camera + ra_mm.CAM_FOV_SCALE_X, [1, 1])
        self.seed_floats(camera + ra_mm.CAM_VIEWPORT_MIN_X, [0])
        self.seed_floats(camera + ra_mm.CAM_VIEWPORT_MAX_X, [640])
        self.seed_floats(camera + ra_mm.CAM_FOCAL, [320 / math.tan(math.radians(ra_mm.STOCK_FOV_DEG) / 2)])
        for address, stock, _, _, _ in ra_caves.RESOURCES:
            for i, word in enumerate(stock):
                self.seed_u32(address + 4 * i, word)

    def title(self):
        return "RADIATA STORIES"

    def connect(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def radiata_gui(monkeypatch):
    """Keep GUI/runtime stepping deterministic, but use real adapter methods on fake memory."""
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)


MINSTRELSONG_GAME_ID, MINSTRELSONG_CRC = "SLPM-65920", "2B9AF3C5"


class MinstrelSongBackend(MinstrelSongFakeBackend):
    """Real adapter on shared synthetic field memory, never a live PINE socket."""

    available = True
    connected = True

    def __init__(self):
        super().__init__(crc=MINSTRELSONG_CRC.lower())
        seed_minstrelsong_field(self)

    def connect(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def minstrelsong_gui(monkeypatch):
    """Step the real runtime explicitly instead of racing its background writer."""
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)


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
def test_exa_registration_is_distinct_from_neo():
    assert gui.ADAPTERS["SFEXA"] is gui.SFExaAdapter
    assert gui.ADAPTERS["SFNEO"] is gui.SFNeoAdapter
    assert gui.SFExaAdapter is not gui.SFNeoAdapter
    assert gui.ADAPTER_BY_GAME_ID[EXA_GAME_ID] is gui.SFExaAdapter
    assert gui.ADAPTER_BY_GAME_ID[sf_mm.GAME_ID] is gui.SFNeoAdapter
    assert EXA_GAME_ID in gui.SUPPORTED_IDS
    assert gui.SFExaAdapter(SFExaBackend()).identify().matched
    assert not gui.SFNeoAdapter(SFExaBackend()).identify().matched
    assert not gui.SFExaAdapter(SFNeoBackend()).identify().matched


@pytest.mark.parametrize("crc", [sf_mm.DISC_CRC, "DEADBEEF"])
def test_exa_serial_with_an_unverified_crc_is_read_only(env, crc):
    backend = SFExaBackend()
    backend.crcv = crc
    w = env.make(lambda: backend)
    assert w.runtime is None
    assert not w.guard.writes_allowed
    assert all(not getattr(w, g).isEnabled() for g in CAMERA_GROUPS)
    assert w.guard.expected == (EXA_GAME_ID, crc)


def test_exa_uses_its_own_limits_features_and_pitch_convention(env):
    w = env.make(SFExaBackend)
    assert type(w.adapter) is gui.SFExaAdapter
    assert w.adapter.name == "SFEXA"
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.rb_original.isChecked()
    assert w.guard.expected == (EXA_GAME_ID, EXA_CRC)
    assert w.sl_dist.spin.minimum() == w.adapter.DISTANCE_RANGE[0]
    assert w.sl_dist.spin.maximum() == w.adapter.DISTANCE_RANGE[1]
    assert w.sl_look.spin.minimum() == w.adapter.LOOK_HEIGHT_RANGE[0]
    assert w.sl_look.spin.maximum() == w.adapter.LOOK_HEIGHT_RANGE[1]
    lo, hi = sorted(v * w.adapter.PITCH_DISPLAY_SIGN for v in w.adapter.PITCH_RANGE)
    assert (w.sl_pitch.spin.minimum(), w.sl_pitch.spin.maximum()) == (lo, hi)
    assert not w.rb_free.isEnabled() and w.rb_free.toolTip()
    assert all(not sl.isEnabled() and sl.toolTip() for sl in w.off)
    assert w.lbl_look_hint.text() and w.lbl_pitch_hint.text()
    displayed_pitch = (lo + hi) / 2
    w.sl_pitch.spin.setValue(displayed_pitch)
    assert w.runtime.settings.pitch_deg == pytest.approx(
        w.sl_pitch.value() / w.adapter.PITCH_DISPLAY_SIGN)
    assert w.app_settings.game_id == EXA_GAME_ID


def test_exa_and_neo_saved_settings_and_presets_stay_separate(env):
    saved = {"games": {
        sf_mm.GAME_ID: {"distance": 1700.0, "look_height": 21.0, "pitch_deg": -31.0},
        EXA_GAME_ID: {"distance": 2300.0, "look_height": 47.0, "pitch_deg": -42.0,
                      "mode": "orbit"},
    }}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    backend = SFExaBackend()
    w = env.make(lambda: backend)
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.runtime.settings.distance == 2300.0
    assert w.runtime.settings.look_height == 47.0
    assert w.runtime.settings.pitch_deg == -42.0
    assert w.sl_pitch.value() == -42.0 * w.adapter.PITCH_DISPLAY_SIGN
    w.presets.save("exa-only", w.app_settings)
    w._persist()
    backend.gid, backend.crcv, backend.ttl = sf_mm.GAME_ID, sf_mm.DISC_CRC, "SF Neo"
    w._reconnect()
    assert type(w.adapter) is gui.SFNeoAdapter
    assert w.runtime.settings.distance == 1700.0
    assert w.runtime.settings.look_height == 21.0
    assert w.runtime.settings.pitch_deg == -31.0
    assert "exa-only" not in w.presets.list(sf_mm.GAME_ID)
    w.presets.save("neo-only", w.app_settings)
    backend.gid, backend.crcv, backend.ttl = EXA_GAME_ID, EXA_CRC, "SF Exa"
    w._reconnect()
    assert type(w.adapter) is gui.SFExaAdapter
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.runtime.settings.distance == 2300.0
    assert w.runtime.settings.look_height == 47.0
    assert w.runtime.settings.pitch_deg == -42.0
    assert "exa-only" in w.presets.list(EXA_GAME_ID)
    assert "neo-only" not in w.presets.list(EXA_GAME_ID)


def test_druaga_registration_uses_its_verified_adapter_and_identity():
    assert gui.ADAPTERS["DRUAGA"] is gui.DruagaAdapter
    assert gui.ADAPTER_BY_GAME_ID[dr_mm.GAME_ID] is gui.DruagaAdapter
    assert dr_mm.GAME_ID in gui.SUPPORTED_IDS
    assert gui.DruagaAdapter(DruagaBackend()).identify().matched
    assert not gui.DruagaAdapter(SFExaBackend()).identify().matched
    assert not gui.SFExaAdapter(DruagaBackend()).identify().matched


@pytest.mark.parametrize("crc", [ex_mm.DISC_CRC, "DEADBEEF", "", dr_mm.DISC_CRC[:-1] + "0"])
def test_druaga_serial_with_any_unverified_crc_is_read_only(env, crc):
    backend = DruagaBackend()
    backend.disc_crc = crc
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.DruagaAdapter
    assert window.runtime is None
    assert not window.guard.writes_allowed
    assert window.guard.expected == (dr_mm.GAME_ID, crc.upper())
    assert all(not getattr(window, group).isEnabled() for group in CAMERA_GROUPS)
    assert window.rb_original.isChecked()
    assert not backend.writes


def test_druaga_first_connection_uses_native_defaults_and_starts_in_original(env):
    backend = DruagaBackend()
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.DruagaAdapter
    assert window.app_settings.game_id == dr_mm.GAME_ID
    assert window.guard.expected == (dr_mm.GAME_ID, dr_mm.DISC_CRC)
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert all(getattr(window, group).isEnabled() for group in CAMERA_GROUPS)
    assert window.adapter.display_name in window.windowTitle()
    for key, value in window.adapter.default_settings().items():
        assert getattr(window.runtime.settings, key) == pytest.approx(value)
    assert not backend.writes


@pytest.mark.parametrize("saved_mode", [gui.MODE_ORBIT, gui.MODE_FREE])
def test_druaga_saved_mode_never_turns_the_mod_on_automatically(env, saved_mode):
    saved = {"games": {dr_mm.GAME_ID: {
        "game_id": dr_mm.GAME_ID, "mode": saved_mode, "distance": 35.0,
        "pitch_deg": -50.0, "look_height": 4.0, "pos_offset": [1.0, 2.0, 3.0],
        "target_offset": [4.0, 5.0, 6.0],
    }}}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    backend = DruagaBackend()
    window = env.make(lambda: backend)
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert window.runtime.settings.distance == 35.0
    assert window.runtime.settings.pitch_deg == -50.0
    assert window.runtime.settings.look_height == 4.0
    assert window.runtime.settings.pos_offset == [1, 2, 3]
    assert window.runtime.settings.target_offset == [4, 5, 6]
    assert not backend.writes


def test_druaga_gui_uses_its_limits_pitch_convention_and_six_supported_offsets(env):
    window = env.make(DruagaBackend)
    adapter = window.adapter
    assert (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == adapter.DISTANCE_RANGE
    assert (window.sl_look.spin.minimum(), window.sl_look.spin.maximum()) == adapter.LOOK_HEIGHT_RANGE
    displayed = tuple(sorted(value * adapter.PITCH_DISPLAY_SIGN for value in adapter.PITCH_RANGE))
    assert (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == displayed
    assert (window.runtime.settings.pitch_min_deg, window.runtime.settings.pitch_max_deg) == adapter.PITCH_RANGE
    assert window.lbl_pitch_hint.text() == gui.tr("hint.pitch_above")
    assert window.lbl_look_hint.text() == gui.tr("hint.look_up")
    assert not window.rb_free.isEnabled() and window.rb_free.toolTip()
    assert window.rb_orbit.isEnabled()
    assert not window.grp_zoom.isVisibleTo(window)
    # The advanced group is deliberately collapsed. Expand it before asking Qt
    # whether its descendants are enabled; a collapsed checkable parent disables them.
    window.grp_offsets.setChecked(True)
    assert len(window.off) == 6
    for slider in window.off:
        assert slider.isEnabled() and slider.spin.isEnabled()
        assert (slider.spin.minimum(), slider.spin.maximum()) == adapter.OFFSET_RANGE
        assert slider.toolTip() != gui.tr("tip.offsets_unsupported")
    window.sl_pitch.spin.setValue(42.0)
    assert window.runtime.settings.pitch_deg == window.app_settings.pitch_deg == -42.0
    for i, slider in enumerate(window.off):
        slider.spin.setValue(i + 0.25)
    assert window.runtime.settings.pos_offset == [0.25, 1.25, 2.25]
    assert window.runtime.settings.target_offset == [3.25, 4.25, 5.25]
    assert window.app_settings.pos_offset == [0.25, 1.25, 2.25]
    assert window.app_settings.target_offset == [3.25, 4.25, 5.25]
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL


def test_druaga_gui_enable_and_restore_manage_processed_right_input_not_raw(env):
    backend = DruagaBackend()
    raw = bytes([0, 255, 42, 201])
    backend.seed(dr_mm.PAD_RAW_AXES, raw)
    window = env.make(lambda: backend)
    assert tuple(backend.read_u32(dr_mm.PAD_AXIS_HOOK + i*4) for i in range(2)) == dr_mm.PAD_AXIS_STOCK
    assert not window.runtime.stats.last_error
    window.btn_enable.click()
    env.spin(0.25)
    assert window.runtime.settings.mode == gui.MODE_ORBIT
    assert backend.read_u32(dr_mm.PAD_AXIS_HOOK) != dr_mm.PAD_AXIS_STOCK[0]
    assert all(backend.read_u32(address) == neutral
               for (address, _), neutral in zip(dr_mm.PAD_ACTION_LOADS, dr_mm.PAD_NEUTRAL_WORDS))
    assert backend.bytes_at(dr_mm.PAD_RAW_AXES, len(raw)) == raw
    window.btn_restore.click()
    env.spin(0.15)
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert not window.runtime.stats.last_error
    assert tuple(backend.read_u32(dr_mm.PAD_AXIS_HOOK + i*4) for i in range(2)) == dr_mm.PAD_AXIS_STOCK
    assert all(backend.read_u32(address) == stock for address, stock in dr_mm.PAD_ACTION_LOADS)
    assert backend.bytes_at(dr_mm.PAD_RAW_AXES, len(raw)) == raw


def test_druaga_and_exa_saved_settings_and_presets_remain_isolated(env):
    saved = {"games": {
        dr_mm.GAME_ID: {"distance": 32.0, "look_height": 3.0, "pitch_deg": -50.0,
                        "pos_offset": [1.0, 2.0, 3.0], "target_offset": [4.0, 5.0, 6.0],
                        "mode": "orbit"},
        EXA_GAME_ID: {"distance": 2300.0, "look_height": 47.0, "pitch_deg": -42.0},
    }}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    # Keep both fake games behind a shared transport, just as PINE outlives a
    # real disc switch. Every read/write is delegated to the selected byte image.
    class SwitchingBackend:
        def __init__(self):
            self.inner = DruagaBackend()
        def __getattr__(self, name):
            return getattr(self.inner, name)
    backend = SwitchingBackend()
    window = env.make(lambda: backend)
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.runtime.settings.distance == 32.0
    assert window.runtime.settings.look_height == 3.0
    assert window.runtime.settings.pitch_deg == -50.0
    assert window.runtime.settings.pos_offset == [1, 2, 3]
    assert window.runtime.settings.target_offset == [4, 5, 6]
    window.presets.save("druaga-only", window.app_settings)
    window._persist()
    backend.inner = SFExaBackend()
    window._reconnect()
    assert type(window.adapter) is gui.SFExaAdapter
    assert window.runtime.settings.distance == 2300.0
    assert window.runtime.settings.look_height == 47.0
    assert window.runtime.settings.pitch_deg == -42.0
    window.presets.save("exa-only", window.app_settings)
    window._refresh_presets()
    assert window.cmb_preset.findText("druaga-only") == -1
    assert window.cmb_preset.findText("exa-only") >= 0
    backend.inner = DruagaBackend()
    window._reconnect()
    assert type(window.adapter) is gui.DruagaAdapter
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.runtime.settings.distance == 32.0
    assert window.runtime.settings.look_height == 3.0
    assert window.runtime.settings.pitch_deg == -50.0
    assert window.runtime.settings.pos_offset == [1, 2, 3]
    assert window.runtime.settings.target_offset == [4, 5, 6]
    assert window.cmb_preset.findText("druaga-only") >= 0
    assert window.cmb_preset.findText("exa-only") == -1
    window.sl_dist.spin.setValue(40.0)
    window.cmb_preset.setCurrentText("druaga-only")
    window.btn_load.click()
    assert window.runtime.settings.distance == 32.0
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()


def test_radiata_registration_uses_only_the_verified_adapter_and_identity():
    assert gui.ADAPTERS["RADIATA"] is gui.RadiataStoriesAdapter
    assert gui.ADAPTER_BY_GAME_ID[RADIATA_GAME_ID] is gui.RadiataStoriesAdapter
    assert RADIATA_GAME_ID in gui.SUPPORTED_IDS
    assert gui.RadiataStoriesAdapter(RadiataBackend()).identify().matched
    assert not gui.RadiataStoriesAdapter(DruagaBackend()).identify().matched
    assert not gui.DruagaAdapter(RadiataBackend()).identify().matched


@pytest.mark.parametrize("crc", [dr_mm.DISC_CRC, "DEADBEEF", "", RADIATA_CRC[:-1] + "0"])
def test_radiata_serial_with_an_unverified_crc_is_read_only(env, radiata_gui, crc):
    backend = RadiataBackend()
    backend.disc_crc = crc
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.RadiataStoriesAdapter
    assert window.runtime is None
    assert not window.guard.writes_allowed
    assert window.guard.expected == (RADIATA_GAME_ID, crc.upper())
    assert all(not getattr(window, group).isEnabled() for group in CAMERA_GROUPS)
    assert window.rb_original.isChecked()
    assert not backend.writes


@pytest.mark.parametrize("saved_mode", [None, gui.MODE_ORBIT, gui.MODE_FREE])
def test_radiata_uses_native_defaults_or_saved_values_but_always_starts_original(env, radiata_gui, saved_mode):
    if saved_mode is not None:
        saved = {"games": {RADIATA_GAME_ID: {
            "mode": saved_mode, "distance": 2200.0, "look_height": -110.0,
            "pitch_deg": 30.0, "pos_offset": [1, 2, 3], "target_offset": [4, 5, 6],
        }}}
        folder = env.tmp / "PS2UniversalCamera"
        folder.mkdir(parents=True)
        (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    backend = RadiataBackend()
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.RadiataStoriesAdapter
    assert window.app_settings.game_id == RADIATA_GAME_ID
    assert window.guard.expected == (RADIATA_GAME_ID, RADIATA_CRC)
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()
    if saved_mode is None:
        for key, value in window.adapter.default_settings().items():
            assert getattr(window.runtime.settings, key) == pytest.approx(value)
    else:
        assert window.runtime.settings.distance == 2200.0
        assert window.runtime.settings.pitch_deg == 30.0
        assert window.runtime.settings.look_height == -110.0
        assert window.runtime.settings.pos_offset == [1, 2, 3]
        assert window.runtime.settings.target_offset == [4, 5, 6]
    assert not backend.writes


@pytest.mark.parametrize("language", ["ja", "en"])
def test_radiata_limits_signs_features_and_independent_eye_tooltips(env, radiata_gui, language):
    window = env.make(RadiataBackend)
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData(language))
    adapter = window.adapter
    assert (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == (150, 6000)
    assert (window.sl_look.spin.minimum(), window.sl_look.spin.maximum()) == (-500, 500)
    assert (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == (-25, 89.5)
    assert window.runtime.settings.pitch_min_deg == -25
    assert window.runtime.settings.pitch_max_deg == 89.5
    assert window.lbl_pitch_hint.text() == gui.tr("hint.pitch_above")
    assert window.lbl_look_hint.text() == gui.tr("hint.look_down")
    assert not window.rb_free.isEnabled()
    assert window.rb_free.toolTip() == gui.tr("mode.free_unsupported")
    assert window.rb_orbit.isEnabled()
    assert not window.grp_zoom.isVisibleTo(window)
    assert gui.tr("game.radiata") in window.windowTitle()
    window.grp_offsets.setChecked(True)
    for i, slider in enumerate(window.off):
        assert slider.isEnabled()
        assert (slider.spin.minimum(), slider.spin.maximum()) == (-1500, 1500)
        key = "tip.cam_eye_offset" if i < 3 else "tip.tgt_offset"
        assert slider.toolTip() == window._offset_labels[i].toolTip() == gui.tr(key)
    window.sl_pitch.spin.setValue(42.0)
    assert window.runtime.settings.pitch_deg == window.app_settings.pitch_deg == 42.0
    for i, slider in enumerate(window.off):
        slider.spin.setValue(i + 0.25)
    assert window.runtime.settings.pos_offset == [0.25, 1.25, 2.25]
    assert window.runtime.settings.target_offset == [3.25, 4.25, 5.25]
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("ja"))


def test_radiata_enable_restore_updates_real_adapter_without_touching_native_input(env, radiata_gui):
    backend = RadiataBackend()
    window = env.make(lambda: backend)
    # Arbitrary fake native input state must never become part of this adapter's writes.
    input_address = 0x1100000
    backend.seed(input_address, b"right-left-buttons-untouched")
    before_input = backend.bytes_at(input_address, 27)
    native_camera = window.adapter._camera()[0]
    native_world = backend.read_floats(native_camera + ra_mm.CAM_NATIVE_WORLD, 16)
    window.btn_enable.click()
    window.runtime._tick(0.01, None)
    assert not window.runtime.stats.last_error
    assert window.runtime.settings.mode == gui.MODE_ORBIT
    assert window.adapter.patch_state() == "applied"
    assert backend.read_u32(ra_mm.MOD_BLOCK + ra_mm.MB_FLAGS) & ra_mm.FLAG_ORBIT
    assert backend.read_floats(native_camera + ra_mm.CAM_NATIVE_WORLD, 16) == native_world
    assert backend.bytes_at(input_address, 27) == before_input
    window.chk_fov.setChecked(True)
    window.sl_fov.spin.setValue(60)
    window.runtime._fov_checked = 0
    window.runtime._scene_time = 0
    window.runtime._tick(0.01, None)
    assert backend.read_u32(ra_mm.MOD_BLOCK + ra_mm.MB_FLAGS) & ra_mm.FLAG_FOV
    window.btn_restore.click()
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()
    assert window.adapter.patch_state() == "stock"
    assert backend.read_u32(ra_mm.MOD_BLOCK + ra_mm.MB_FLAGS) == 0
    assert backend.read_floats(native_camera + ra_mm.CAM_NATIVE_WORLD, 16) == native_world
    assert backend.bytes_at(input_address, 27) == before_input
    assert all(address != input_address for address, _ in backend.writes)


def test_radiata_and_druaga_settings_and_presets_stay_separate(env, radiata_gui):
    saved = {"games": {
        RADIATA_GAME_ID: {"distance": 2500.0, "look_height": -120.0, "pitch_deg": 35.0,
                          "pos_offset": [1, 2, 3], "target_offset": [4, 5, 6], "mode": "orbit"},
        dr_mm.GAME_ID: {"distance": 35.0, "look_height": 4.0, "pitch_deg": -50.0},
    }}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    class SwitchingBackend:
        def __init__(self): self.inner = RadiataBackend()
        def __getattr__(self, name): return getattr(self.inner, name)
    backend = SwitchingBackend()
    window = env.make(lambda: backend)
    assert window.runtime.settings.distance == 2500
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    window.presets.save("radiata-only", window.app_settings)
    window._persist()
    old_runtime = window.runtime
    backend.inner = DruagaBackend()
    window._reconnect()
    assert not old_runtime.running and not old_runtime.stats.connected
    assert type(window.adapter) is gui.DruagaAdapter
    assert window.runtime.settings.distance == 35
    assert window.runtime.settings.pitch_deg == -50
    assert window.cmb_preset.findText("radiata-only") == -1
    backend.inner = RadiataBackend()
    window._reconnect()
    assert type(window.adapter) is gui.RadiataStoriesAdapter
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.runtime.settings.distance == 2500
    assert window.runtime.settings.look_height == -120
    assert window.runtime.settings.pitch_deg == 35
    assert window.runtime.settings.pos_offset == [1, 2, 3]
    assert window.runtime.settings.target_offset == [4, 5, 6]
    window.sl_dist.spin.setValue(3000)
    window.cmb_preset.setCurrentText("radiata-only")
    window.btn_load.click()
    assert window.runtime.settings.distance == 2500
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL


def test_minstrelsong_registration_uses_only_its_verified_adapter_and_identity():
    assert gui.ADAPTERS["MINSTRELSONG"] is gui.MinstrelSongAdapter
    assert gui.ADAPTER_BY_GAME_ID[MINSTRELSONG_GAME_ID] is gui.MinstrelSongAdapter
    assert MINSTRELSONG_GAME_ID in gui.SUPPORTED_IDS
    assert (ms_mm.GAME_ID, ms_mm.DISC_CRC) == (MINSTRELSONG_GAME_ID, MINSTRELSONG_CRC)
    backend = MinstrelSongBackend()
    assert gui.MinstrelSongAdapter(backend).identify().matched
    assert not gui.MinstrelSongAdapter(RadiataBackend()).identify().matched
    assert not gui.MinstrelSongAdapter(DruagaBackend()).identify().matched
    assert not gui.RadiataStoriesAdapter(backend).identify().matched
    assert not gui.DruagaAdapter(backend).identify().matched
    assert not backend.writes


@pytest.mark.parametrize("crc", [ra_mm.DISC_CRC, dr_mm.DISC_CRC, "DEADBEEF", "", "2B9AF3C0"])
def test_minstrelsong_unverified_crc_stays_read_only(env, minstrelsong_gui, crc):
    backend = MinstrelSongBackend()
    backend.disc_crc = crc
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.MinstrelSongAdapter
    assert window.runtime is None
    assert window.guard.expected == (MINSTRELSONG_GAME_ID, crc.upper())
    assert not window.guard.writes_allowed
    assert all(not getattr(window, group).isEnabled() for group in CAMERA_GROUPS)
    assert window.rb_original.isChecked()
    assert window._conn_problem[0] == "notice.unsupported"
    assert not backend.writes


@pytest.mark.parametrize("saved_mode", [None, gui.MODE_ORBIT, gui.MODE_FREE])
def test_minstrelsong_defaults_and_saved_values_always_start_original(env, minstrelsong_gui, saved_mode):
    if saved_mode is not None:
        saved = {"games": {MINSTRELSONG_GAME_ID: {
            "mode": saved_mode, "distance": 12.0, "look_height": -2.0, "pitch_deg": 35.0,
            "pos_offset": [1, 2, 3], "target_offset": [4, 5, 6],
        }}}
        folder = env.tmp / "PS2UniversalCamera"
        folder.mkdir(parents=True)
        (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    backend = MinstrelSongBackend()
    window = env.make(lambda: backend)
    assert type(window.adapter) is gui.MinstrelSongAdapter
    assert window.adapter.backend is window.guard
    assert window.guard.expected == (MINSTRELSONG_GAME_ID, MINSTRELSONG_CRC)
    assert window.app_settings.game_id == MINSTRELSONG_GAME_ID
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.rb_original.isChecked()
    if saved_mode is None:
        for key, value in window.adapter.default_settings().items():
            assert getattr(window.runtime.settings, key) == pytest.approx(value)
    else:
        assert window.runtime.settings.distance == 12
        assert window.runtime.settings.look_height == -2
        assert window.runtime.settings.pitch_deg == 35
        assert window.runtime.settings.pos_offset == [1, 2, 3]
        assert window.runtime.settings.target_offset == [4, 5, 6]
    data = window.poller.poll_once()
    assert data["link"] and data["patch"] == "stock"
    assert data["fov"] == pytest.approx(window.adapter.capture_original_fov())
    assert not backend.writes


@pytest.mark.parametrize("language", ["ja", "en"])
def test_minstrelsong_limits_hints_translations_and_unsupported_free(env, minstrelsong_gui, language):
    window = env.make(MinstrelSongBackend)
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData(language))
    assert (window.sl_dist.spin.minimum(), window.sl_dist.spin.maximum()) == (1, 80)
    assert (window.sl_look.spin.minimum(), window.sl_look.spin.maximum()) == (-10, 10)
    assert (window.sl_pitch.spin.minimum(), window.sl_pitch.spin.maximum()) == (-25, 89.5)
    assert (window.runtime.settings.pitch_min_deg, window.runtime.settings.pitch_max_deg) == (-25, 89.5)
    assert window.lbl_pitch_hint.text() == gui.tr("hint.pitch_above")
    assert window.lbl_look_hint.text() == gui.tr("hint.look_down")
    expected_title = ("ロマンシング サガ -ミンストレルソング-" if language == "ja"
                      else "Romancing SaGa -Minstrel Song-")
    assert gui.tr("game.minstrelsong") == expected_title
    assert expected_title in window.windowTitle()
    assert window.rb_orbit.isEnabled()
    assert not window.rb_free.isEnabled()
    assert window.rb_free.toolTip() == gui.tr("mode.free_unsupported")
    assert window.sl_fov.isEnabled() and window.chk_fov.isEnabled()
    window._refresh_native_zoom(window.poller.poll_once())
    assert not window.grp_zoom.isVisibleTo(window)
    window.grp_offsets.setChecked(True)
    for i, slider in enumerate(window.off):
        assert slider.isEnabled()
        assert (slider.spin.minimum(), slider.spin.maximum()) == (-30, 30)
        key = "tip.cam_eye_offset" if i < 3 else "tip.tgt_offset"
        assert slider.toolTip() == window._offset_labels[i].toolTip() == gui.tr(key)
        slider.spin.setValue(i + .25)
    assert window.runtime.settings.pos_offset == [.25, 1.25, 2.25]
    assert window.runtime.settings.target_offset == [3.25, 4.25, 5.25]
    window.sl_pitch.spin.setValue(42)
    assert window.runtime.settings.pitch_deg == window.app_settings.pitch_deg == 42
    window.cmb_lang.setCurrentIndex(window.cmb_lang.findData("ja"))


def test_minstrelsong_gui_enable_fov_and_restore_use_real_adapter_without_touching_raw_input(env, minstrelsong_gui):
    backend = MinstrelSongBackend()
    window = env.make(lambda: backend)
    native = {address: backend.bytes_at(address, 16) for address in
              (ms_mm.CAM_EYE, ms_mm.CAM_TARGET, ms_mm.CAM_UP, ms_mm.CAM_TRANSLATE)}
    native_lens = backend.read_f32(ms_mm.CAM_NATIVE_FOCAL)
    raw_address = 0x01100000
    raw = b"raw-left-right-buttons-untouched"
    backend.seed(raw_address, raw)
    window.btn_enable.click()
    window.runtime._tick(.01, None)
    assert not window.runtime.stats.last_error
    assert window.runtime.settings.mode == gui.MODE_ORBIT
    assert window.adapter.patch_state() == "applied"
    assert backend.read_u32(ms_mm.MOD_BLOCK + ms_mm.MB_FLAGS) == ms_mm.FLAG_ORBIT
    window.sl_look.spin.setValue(-2)
    window.grp_offsets.setChecked(True)
    for slider, value in zip(window.off, [1, 2, 3, 4, 5, 6]):
        slider.spin.setValue(value)
    window.chk_fov.setChecked(True)
    window.sl_fov.spin.setValue(60)
    window.runtime._fov_checked = window.runtime._scene_time = 0
    window.runtime._tick(.01, None)
    assert not window.runtime.stats.last_error
    assert backend.read_u32(ms_mm.MOD_BLOCK + ms_mm.MB_FLAGS) == ms_mm.FLAG_ORBIT | ms_mm.FLAG_FOV
    bank = minstrelsong_bank(backend)
    assert backend.read_floats(bank + ms_mm.SLOT_TARGET, 3) == [4, 3, 6]
    assert backend.read_f32(bank + ms_mm.SLOT_FOCAL) == pytest.approx(window.adapter._focal(60))
    # This is a publish contract test: no guest/render loop runs on fake memory.
    assert backend.read_f32(ms_mm.CAM_NATIVE_FOCAL) == native_lens
    assert all(backend.bytes_at(address, 16) == data for address, data in native.items())
    window.btn_restore.click()
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert not window.runtime.settings.use_fov
    assert window.rb_original.isChecked()
    assert window.adapter.patch_state() == "stock"
    assert backend.read_u32(ms_mm.MOD_BLOCK + ms_mm.MB_FLAGS) == 0
    assert all(ms_caves.read_words(backend, address, 2) == stock
               for address, stock, _, _, _ in ms_caves.RESOURCES)
    assert all(backend.bytes_at(address, 16) == data for address, data in native.items())
    assert backend.bytes_at(raw_address, len(raw)) == raw
    assert not any(raw_address <= address < raw_address + len(raw) for address, _ in backend.writes)


def test_minstrelsong_and_radiata_settings_presets_and_active_switch_stay_isolated(env, minstrelsong_gui):
    saved = {"games": {
        MINSTRELSONG_GAME_ID: {"distance": 12.0, "look_height": -2.0, "pitch_deg": 35.0,
                              "pos_offset": [1, 2, 3], "target_offset": [4, 5, 6], "mode": "free"},
        RADIATA_GAME_ID: {"distance": 2500.0, "look_height": -120.0, "pitch_deg": 30.0},
    }}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")

    class SwitchingBackend:
        def __init__(self): self.inner = MinstrelSongBackend()
        def __getattr__(self, name): return getattr(self.inner, name)

    backend = SwitchingBackend()
    window = env.make(lambda: backend)
    assert window.runtime.settings.distance == 12
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    window.presets.save("minstrelsong-only", window.app_settings)
    window._persist()
    window.btn_enable.click()
    window.runtime._tick(.01, None)
    old_runtime, old_memory = window.runtime, backend.inner
    assert window.adapter.patch_active()
    old_memory.writes.clear()
    backend.inner = RadiataBackend()
    window._reconnect()
    assert not old_runtime.running and not old_runtime.stats.connected
    assert not old_memory.writes and not backend.inner.writes
    assert type(window.adapter) is gui.RadiataStoriesAdapter
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.runtime.settings.distance == 2500
    assert window.cmb_preset.findText("minstrelsong-only") == -1
    window.presets.save("radiata-separate", window.app_settings)
    window._persist()
    backend.inner = MinstrelSongBackend()
    window._reconnect()
    assert type(window.adapter) is gui.MinstrelSongAdapter
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert window.runtime.settings.distance == 12
    assert window.runtime.settings.look_height == -2
    assert window.runtime.settings.pos_offset == [1, 2, 3]
    assert window.runtime.settings.target_offset == [4, 5, 6]
    assert window.cmb_preset.findText("radiata-separate") == -1
    window.sl_dist.spin.setValue(20)
    window.cmb_preset.setCurrentText("minstrelsong-only")
    window.btn_load.click()
    assert window.runtime.settings.distance == 12
    assert window.runtime.settings.mode == gui.MODE_ORIGINAL
    assert not window.rb_free.isEnabled()
    assert not backend.inner.writes


def test_dragonquest5_registration_uses_only_its_verified_adapter_and_identity():
    assert gui.ADAPTERS["DRAGONQUEST5"] is gui.DragonQuest5Adapter
    assert gui.ADAPTER_BY_GAME_ID["SLPM-65555"] is gui.DragonQuest5Adapter
    assert "SLPM-65555" in gui.SUPPORTED_IDS
    backend = DruagaFakeBackend(serial="SLPM-65555", crc="b64e9939")
    adapter = gui.DragonQuest5Adapter(backend)
    assert adapter.name == "DRAGONQUEST5"
    assert adapter.display_name_key == "game.dragonquest5"
    assert adapter.identify().matched
    assert not gui.MinstrelSongAdapter(backend).identify().matched
    assert not gui.RadiataStoriesAdapter(backend).identify().matched
    assert not backend.writes


@pytest.mark.parametrize("serial,crc", [
    ("SLPM-65555", "DEADBEEF"), ("SLPM-65555", ""),
    ("SLPM-65920", "B64E9939"), ("SLPM-65800", "B64E9939"),
])
def test_dragonquest5_unverified_identity_is_not_a_match_or_a_write(serial, crc):
    backend = DruagaFakeBackend(serial=serial, crc=crc)
    assert not gui.DragonQuest5Adapter(backend).identify().matched
    assert not backend.writes


@pytest.mark.parametrize("language,expected", [
    ("ja", "ドラゴンクエストV 天空の花嫁"), ("en", "Dragon Quest V"),
])
def test_dragonquest5_title_translation_is_registered(language, expected):
    from gui.camera_controller.i18n import TEXT
    assert TEXT["game.dragonquest5"][language] == expected


RPG5_ID, RPG5_CRC = "SLPS-20143", "BB78C51D"


@pytest.fixture()
def rpg5_window(env, monkeypatch):
    """Real GUI selection and guard; no workers, live connection or gameplay fixture."""
    monkeypatch.setattr(gui.StatusPoller, "start", lambda self: None)
    monkeypatch.setattr(gui.CameraRuntime, "start", lambda self: None)
    monkeypatch.setattr(gui.MainWindow, "_setup_input", lambda self: None)

    def make(serial=RPG5_ID, crc=RPG5_CRC):
        backend = GuiBackend()
        backend.gid, backend.crcv, backend.ttl = serial, crc, "Disc title"
        return env.make(lambda: backend), backend

    return make


def test_rpgmaker5_registration_uses_its_own_adapter():
    from adapters.rpgmaker5.adapter import RPGMaker5Adapter
    assert gui.ADAPTERS["RPGMAKER5"] is RPGMaker5Adapter
    assert gui.ADAPTER_BY_GAME_ID[RPG5_ID] is RPGMaker5Adapter
    assert RPG5_ID in gui.SUPPORTED_IDS


@pytest.mark.parametrize("serial,crc", [(RPG5_ID, "DEADBEEF"), (RPG5_ID, ""), ("SLPS-00000", RPG5_CRC)])
def test_rpgmaker5_unverified_disc_stays_read_only(rpg5_window, serial, crc):
    w, backend = rpg5_window(serial, crc)
    assert w.runtime is None and not w.guard.writes_allowed
    assert not w.grp_mode.isEnabled() and not w.grp_lens.isEnabled()
    with pytest.raises(WriteBlocked):
        w.guard.write_u32(0, 1)
    assert backend.mem == {}


def test_rpgmaker5_features_and_translations_match_the_native_rig(rpg5_window):
    w, backend = rpg5_window(crc=RPG5_CRC.lower())
    assert type(w.adapter) is gui.RPGMaker5Adapter
    assert w.adapter.name == "RPGMAKER5" and w.adapter.backend is w.guard
    assert w.guard.expected == (RPG5_ID, RPG5_CRC) and w.guard.writes_allowed
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL and w.rb_original.isChecked()
    assert w.rb_orbit.isEnabled() and not w.rb_free.isEnabled()
    assert w.sl_fov.isEnabled() and w.chk_fov.isEnabled()
    for slider, limits in ((w.sl_dist, (200, 1600)), (w.sl_pitch, (20, 75)), (w.sl_fov, (20, 60))):
        assert (slider.spin.minimum(), slider.spin.maximum()) == limits
    w.grp_offsets.setChecked(True)
    assert not w.sl_look.isEnabled() and not any(sl.isEnabled() for sl in w.off)
    for lang, title in (("en", "RPG Maker 5"), ("ja", "RPGツクール5")):
        w.cmb_lang.setCurrentIndex(w.cmb_lang.findData(lang))
        assert title in w.windowTitle()
        reason = gui.tr("tip.look_height_unsupported")
        assert reason != "tip.look_height_unsupported"
        assert w.sl_look.toolTip() == w.lbl_look_hint.text() == reason
        assert w.chk_fov.toolTip() == w.sl_fov.toolTip() == gui.tr("tip.fov_orbit_only")
        assert all(sl.toolTip() == gui.tr("tip.offsets_unsupported") for sl in w.off)
    assert backend.mem == {}


def test_rpgmaker5_saved_settings_and_presets_cannot_override_native_look_height(rpg5_window):
    store = gui.SettingsStore()
    old = store.get(RPG5_ID)
    old.mode, old.look_height, old.distance = gui.MODE_FREE, 25.0, 810.0
    store.put(old)
    w, backend = rpg5_window()
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.runtime.settings.distance == 810.0
    assert w.sl_look.value() == w.runtime.settings.look_height == w.app_settings.look_height == 0
    old.look_height, old.distance = -15.0, 720.0
    w.presets.save("native-rig", old)
    w._refresh_presets()
    w.cmb_preset.setCurrentText("native-rig")
    w.btn_load.click()
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.runtime.settings.distance == 720.0
    assert w.sl_look.value() == w.runtime.settings.look_height == w.app_settings.look_height == 0
    w._persist()
    assert gui.SettingsStore().get(RPG5_ID).look_height == 0
    assert backend.mem == {}


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
    assert w.sl_look.isEnabled() and w.sl_look.toolTip() == gui.tr("tip.look_height")
    assert w.sl_fov.toolTip() == gui.tr("tip.fov")
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


@pytest.mark.parametrize(("saved_pitch", "internal_pitch"), [
    (-34.2, -34.2), (-120.0, -89.5), (60.0, 25.0),
])
def test_sfneo_saved_pitch_uses_display_sign_and_overrides_old_limits(env, saved_pitch, internal_pitch):
    saved = {"games": {sf_mm.GAME_ID: {
        "game_id": sf_mm.GAME_ID, "pitch_deg": saved_pitch,
        "pitch_min_deg": -25.0, "pitch_max_deg": 85.0,
    }}}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    w = env.make(SFNeoBackend)
    assert w.runtime is not None
    assert w.runtime.settings.pitch_deg == internal_pitch
    assert w.app_settings.pitch_deg == internal_pitch
    assert w.sl_pitch.value() == -internal_pitch
    assert (w.sl_pitch.spin.minimum(), w.sl_pitch.spin.maximum()) == (-25.0, 89.5)
    assert (w.runtime.settings.pitch_min_deg, w.runtime.settings.pitch_max_deg) == (-89.5, 25.0)
    assert (w.app_settings.pitch_min_deg, w.app_settings.pitch_max_deg) == (-89.5, 25.0)
    assert w.lbl_pitch_hint.text() == gui.tr("hint.pitch_above")
    w._persist()
    stored = json.loads((folder / "settings.json").read_text(encoding="utf-8"))["games"][sf_mm.GAME_ID]
    assert stored["pitch_deg"] == internal_pitch            # never persist the display convention
    assert (stored["pitch_min_deg"], stored["pitch_max_deg"]) == (-89.5, 25.0)


def test_sfneo_pitch_edits_convert_display_to_internal(env):
    w = env.make(SFNeoBackend)
    assert w.runtime is not None
    w.sl_pitch.spin.setValue(61.2)
    assert w.runtime.settings.pitch_deg == -61.2
    assert w.app_settings.pitch_deg == -61.2
    for raw, internal in ((895, -89.5), (-250, 25.0), (0, 0.0)):
        w.sl_pitch.slider.setValue(raw)
        assert w.runtime.settings.pitch_deg == internal
        assert w.app_settings.pitch_deg == internal
    w.sl_pitch.spin.setValue(48.3)
    w._persist()
    path = w.presets.save("sfneo-elevation", w.app_settings)
    assert json.loads(path.read_text(encoding="utf-8"))["settings"]["pitch_deg"] == -48.3


@pytest.mark.parametrize("internal_pitch", [-72.4, 18.2])
def test_sfneo_runtime_pitch_mirrors_in_display_convention(env, internal_pitch):
    w = env.make(SFNeoBackend)
    assert w.runtime is not None
    w.pump.stop()
    w.runtime.stop()
    w.runtime.settings.mode = gui.MODE_ORBIT
    w.runtime.settings.pitch_deg = internal_pitch
    w._refresh()
    assert w.sl_pitch.value() == -internal_pitch
    assert w.runtime.settings.pitch_deg == internal_pitch    # mirroring must not feed back


def test_suikoden_pitch_keeps_internal_display_and_saved_limits(env):
    saved = {"games": {su_mm.GAME_ID: {
        "game_id": su_mm.GAME_ID, "pitch_deg": -18.7,
        "pitch_min_deg": -31.0, "pitch_max_deg": 74.0,
    }}}
    folder = env.tmp / "PS2UniversalCamera"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    w = env.make(SuikodenBackend)
    assert w.runtime is not None
    assert w.sl_pitch.value() == w.runtime.settings.pitch_deg == -18.7
    assert (w.sl_pitch.spin.minimum(), w.sl_pitch.spin.maximum()) == (-31.0, 74.0)
    assert (w.runtime.settings.pitch_min_deg, w.runtime.settings.pitch_max_deg) == (-31.0, 74.0)
    w.sl_pitch.spin.setValue(28.4)
    assert w.runtime.settings.pitch_deg == w.app_settings.pitch_deg == 28.4
    w.pump.stop()
    w.runtime.stop()
    w.runtime.settings.mode = gui.MODE_ORBIT
    w.runtime.settings.pitch_deg = -11.3
    w._refresh()
    assert w.sl_pitch.value() == w.runtime.settings.pitch_deg == -11.3


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


@pytest.mark.parametrize(("preset_pitch", "internal_pitch"), [
    (-42.7, -42.7), (-120.0, -89.5), (70.0, 25.0),
])
def test_sfneo_preset_reapplies_adapter_limits_without_reinterpreting_pitch(env, preset_pitch, internal_pitch):
    w = env.make(SFNeoBackend)
    assert w.runtime is not None
    preset = {"name": "old-sfneo", "game_id": sf_mm.GAME_ID,
              "settings": {"game_id": sf_mm.GAME_ID, "mode": "orbit", "pitch_deg": preset_pitch,
                           "pitch_min_deg": -25.0, "pitch_max_deg": 85.0}}
    path = w.presets.dir / "old-sfneo.json"
    original = json.dumps(preset)
    path.write_text(original, encoding="utf-8")
    w._refresh_presets()
    w.cmb_preset.setCurrentText("old-sfneo")
    w.btn_load.click()
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.runtime.settings.pitch_deg == w.app_settings.pitch_deg == internal_pitch
    assert (w.runtime.settings.pitch_min_deg, w.runtime.settings.pitch_max_deg) == (-89.5, 25.0)
    assert (w.app_settings.pitch_min_deg, w.app_settings.pitch_max_deg) == (-89.5, 25.0)
    assert (w.sl_pitch.spin.minimum(), w.sl_pitch.spin.maximum()) == (-25.0, 89.5)
    assert w.sl_pitch.value() == -internal_pitch
    assert path.read_text(encoding="utf-8") == original      # loading leaves existing presets intact


def test_suikoden_preset_keeps_saved_pitch_bounds_and_sign(env):
    w = env.make(SuikodenBackend)
    assert w.runtime is not None
    preset = {"name": "su-pitch", "game_id": su_mm.GAME_ID,
              "settings": {"game_id": su_mm.GAME_ID, "pitch_deg": -19.6,
                           "pitch_min_deg": -32.0, "pitch_max_deg": 71.0}}
    (w.presets.dir / "su-pitch.json").write_text(json.dumps(preset), encoding="utf-8")
    w._refresh_presets()
    w.cmb_preset.setCurrentText("su-pitch")
    w.btn_load.click()
    assert w.runtime.settings.pitch_deg == w.app_settings.pitch_deg == w.sl_pitch.value() == -19.6
    assert (w.runtime.settings.pitch_min_deg, w.runtime.settings.pitch_max_deg) == (-32.0, 71.0)
    assert (w.app_settings.pitch_min_deg, w.app_settings.pitch_max_deg) == (-32.0, 71.0)
    assert (w.sl_pitch.spin.minimum(), w.sl_pitch.spin.maximum()) == (-32.0, 71.0)


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


@pytest.mark.parametrize("source, target, target_cls", [
    ((sf_mm.GAME_ID, sf_mm.DISC_CRC, "SF Neo"), (EXA_GAME_ID, EXA_CRC, "SF Exa"), gui.SFExaAdapter),
    ((EXA_GAME_ID, EXA_CRC, "SF Exa"), (sf_mm.GAME_ID, sf_mm.DISC_CRC, "SF Neo"), gui.SFNeoAdapter),
])
def test_neo_exa_switch_discards_the_old_runtime_without_restore(env, monkeypatch,
                                                                source, target, target_cls):
    shared = SwitchBackend()
    shared.gid, shared.crcv, shared.ttl = source
    source_map = sf_mm if source[0] == sf_mm.GAME_ID else ex_mm
    seed_shining_field(shared, source_map)
    w = env.make(lambda: shared)
    old_runtime, old_guard = w.runtime, w.guard
    assert old_runtime is not None
    w.btn_enable.click()
    env.spin(0.3)
    assert old_runtime.settings.mode == gui.MODE_ORBIT
    assert w.adapter.patch_active(), old_runtime.stats.last_error
    assert shared.log, "the source adapter never wrote"
    other_map = ex_mm if source_map is sf_mm else sf_mm
    other_control_words = {other_map.CAM_YAW_WORD, other_map.CAM_DISTANCE,
                           other_map.CAM_HEIGHT, other_map.SMOOTH_GATE_WORD,
                           other_map.VP_LOAD_CALL, other_map.PAD_CALL_SITE}
    if other_map is ex_mm:
        other_control_words.update((ex_mm.PAD_RX_LOAD, ex_mm.PAD_RY_LOAD))
    assert not other_control_words.intersection(shared.log), "wrote the other Shining game's controls"
    restored = []
    monkeypatch.setattr(old_runtime, "restore", lambda: restored.append(True))
    shared.gid, shared.crcv, shared.ttl = target
    # Explicit verification closes the documented lease window before checking writes.
    assert old_guard.verify() == gui.CHANGED
    env.spin(1.0)
    assert restored == []
    assert not old_runtime.running and old_guard.revoked
    assert w.runtime is not old_runtime and type(w.adapter) is target_cls
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.guard.expected == (target[0], target[1])
    count = len(shared.log)
    with pytest.raises(WriteBlocked):
        old_runtime.adapter.backend.write_u32(0x100, 1)
    assert len(shared.log) == count


def test_switching_from_active_suikoden_to_exa_selects_its_own_adapter(env):
    shared = SwitchBackend()
    w = orbit_running(env, shared)
    old_runtime = w.runtime
    shared.gid, shared.crcv, shared.ttl = EXA_GAME_ID, EXA_CRC.lower(), "SF Exa"
    t0 = time.monotonic()
    env.spin(1.6)
    assert type(w.adapter) is gui.SFExaAdapter
    assert w.runtime is not old_runtime and not old_runtime.running
    assert w.runtime.settings.mode == gui.MODE_ORIGINAL
    assert w.guard.expected == (EXA_GAME_ID, EXA_CRC)
    late = writes_after(shared, t0)
    assert not [a for a in late if a in SU_ADDRS or su_mm.MOD_BLOCK <= a < su_mm.CAVE_END]


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
