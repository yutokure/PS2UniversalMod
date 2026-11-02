"""PS2 Universal Camera Controller — PySide6 desktop application.

The GUI is a thin client: it owns no game knowledge at all.  It talks to

* the ``FFX2Adapter`` (game specific addresses)
* the ``CameraRuntime`` (per-frame writer thread)

through plain dataclasses, so adding a new game means adding an adapter and
registering it in ``ADAPTERS`` below.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import Qt, QTimer, Signal, QObject  # noqa: E402
    from PySide6.QtGui import QAction, QFont, QKeySequence  # noqa: E402
    from PySide6.QtWidgets import (  # noqa: E402
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
        QRadioButton, QSlider, QSpinBox, QStatusBar, QVBoxLayout, QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - startup diagnostics
    if "PySide6" not in str(exc):
        raise
    sys.stderr.write(
        "PySide6 is not installed for this interpreter:\n"
        f"  {sys.executable}\n\n"
        "Either start the app through the bundled launcher, which picks the right\n"
        "interpreter automatically:\n"
        "  PS2UniversalCamera.bat            (double-click, or run from a shell)\n"
        "  python run_gui.py                 (works with any Python)\n\n"
        "or install the dependency into this interpreter:\n"
        "  python -m pip install PySide6\n"
    )
    raise SystemExit(2) from None

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from adapters.shiningforceneo.adapter import SFNeoAdapter  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_math.orbit import FOV_MAX_DEG, FOV_MIN_DEG, scale_to_fov_deg  # noqa: E402
from core.camera_runtime.engine import (  # noqa: E402
    MODE_FREE, MODE_ORBIT, MODE_ORIGINAL, CameraRuntime, CameraSettings,
)
from core.config.settings import (  # noqa: E402
    APP_NAME, APP_VERSION, AppSettings, PresetStore, SettingsStore,
)
from core.controller.sources import (  # noqa: E402
    CompositeSource, InputPump, KeyboardSource, ScriptedSource, XInputSource,
)
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

try:  # run as a module (python -m gui.camera_controller.app)
    from gui.camera_controller.i18n import (  # noqa: E402
        LANGUAGES, current_language, set_language, tr,
    )
except ImportError:  # run as a script (python gui/camera_controller/app.py)
    from i18n import LANGUAGES, current_language, set_language, tr  # noqa: E402

ADAPTERS = {"FFX2": FFX2Adapter, "SFNEO": SFNeoAdapter, "SUIKODEN5": Suikoden5Adapter}
#: adapter class per game serial, chosen when the GUI connects
ADAPTER_BY_GAME_ID = {"SLPS-25250": FFX2Adapter, "SLPM-65908": SFNeoAdapter,
                      "SLPM-66286": Suikoden5Adapter}
#: ids the current adapters actually verify.  Each adapter matches on serial *and*
#: CRC (FFX-2 ``8A6D7F14``, Shining Force Neo ``64F241D2``, Suikoden V ``7380A572``), which only the Japanese
#: releases satisfy, so the US/EU serials are deliberately NOT listed here:
#: advertising them would promise support the adapters would then refuse.
SUPPORTED_IDS = {"SLPS-25250", "SLPM-65908", "SLPM-66286"}


class FloatSlider(QWidget):
    """Slider + numeric box kept in sync, emitting one float value."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float,
                 decimals: int = 1, step: float = 1.0) -> None:
        super().__init__()
        self._scale = 10 ** decimals
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(minimum * self._scale), int(maximum * self._scale))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setFixedWidth(96)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.set_value(value)

    def _from_slider(self, raw: int) -> None:
        v = raw / self._scale
        if abs(self.spin.value() - v) > 1e-9:
            self.spin.blockSignals(True)
            self.spin.setValue(v)
            self.spin.blockSignals(False)
        self.valueChanged.emit(v)

    def _from_spin(self, v: float) -> None:
        raw = int(round(v * self._scale))
        if self.slider.value() != raw:
            self.slider.blockSignals(True)
            self.slider.setValue(raw)
            self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def set_value(self, v: float) -> None:
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(int(round(v * self._scale)))
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def set_range(self, minimum: float, maximum: float) -> None:
        """Change the limits (a game may need a wider range than the default one)."""
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setRange(int(minimum * self._scale), int(maximum * self._scale))
        self.spin.setRange(minimum, maximum)
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def value(self) -> float:
        return self.spin.value()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{tr('app.title')}  v{APP_VERSION}")
        # 1180x860 does not fit a 1366x768 laptop, and a clipped window hides the
        # Controls/Debug rows, so clamp to the available desktop.
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(min(1180, avail.width() - 80), min(860, avail.height() - 120))
        else:
            self.resize(1180, 860)
        self.store = SettingsStore()
        self.presets = PresetStore()
        self.backend: PineBackend | None = None
        self.adapter = None
        self.runtime: CameraRuntime | None = None
        self.pump: InputPump | None = None
        self.scripted = ScriptedSource()
        self.app_settings = self.store.get("SLPS-25250")
        self._updating = False
        #: (widget, property, key) triples re-applied when the language changes
        self._i18n: list[tuple[object, str, str]] = []
        #: messages that must stay on screen (connection errors etc.)
        self._last_problem = ""
        set_language(getattr(self.app_settings, "language", "ja"))
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(80)
        self._reconnect()

    # ------------------------------------------------------------- i18n
    def _t(self, key: str, **fmt) -> str:
        return tr(key, **fmt)

    def _reg(self, widget, prop: str, key: str) -> None:
        self._i18n.append((widget, prop, key))

    def _label(self, key: str) -> "QLabel":
        w = QLabel(tr(key))
        self._reg(w, "text", key)
        return w

    def _group(self, key: str) -> "QGroupBox":
        b = QGroupBox(tr(key))
        self._reg(b, "title", key)
        return b

    def _btn(self, key: str) -> "QPushButton":
        b = QPushButton(tr(key))
        self._reg(b, "text", key)
        return b

    def _chk(self, key: str) -> "QCheckBox":
        c = QCheckBox(tr(key))
        self._reg(c, "text", key)
        return c

    def _radio(self, key: str) -> "QRadioButton":
        r = QRadioButton(tr(key))
        self._reg(r, "text", key)
        return r

    def _row(self, form, key: str, widget) -> None:
        form.addRow(self._label(key), widget)

    def _retranslate(self) -> None:
        for widget, prop, key in self._i18n:
            if prop == "title":
                widget.setTitle(tr(key))          # type: ignore[attr-defined]
            else:
                widget.setText(tr(key))           # type: ignore[attr-defined]
        self.setWindowTitle(f"{tr('app.title')}  v{APP_VERSION}")
        if getattr(self, "_ln", None) is not None:
            self._ln.setText(self._t("conn.language"))
        if getattr(self, "_tip_preset", False):
            self.cmb_preset.setToolTip(tr("ctl.preset_tip"))
        self.lbl_patch.setToolTip(tr("ctl.patch_tip"))
        self._refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        grid = QGridLayout(central)
        grid.setSpacing(10)

        grid.addWidget(self._build_connection(), 0, 0, 1, 2)
        grid.addWidget(self._build_mode(), 1, 0)
        grid.addWidget(self._build_controls(), 1, 1)
        grid.addWidget(self._build_rotation(), 2, 0)
        grid.addWidget(self._build_position(), 2, 1)
        grid.addWidget(self._build_lens(), 3, 0)
        grid.addWidget(self._build_debug(), 3, 1)
        self.grp_zoom = self._build_native_zoom()
        grid.addWidget(self.grp_zoom, 4, 0, 1, 2)
        self.grp_zoom.setVisible(False)       # shown for adapters with a native zoom

        self.setStatusBar(QStatusBar())
        self._status("Ready")

    def _build_connection(self) -> QGroupBox:
        box = self._group("group.connection")
        lay = QGridLayout(box)
        self.lbl_pcsx2 = QLabel(self._t("state.disconnected"))
        self.lbl_game = QLabel("-")
        self.lbl_serial = QLabel("-")
        self.lbl_adapter = QLabel("-")
        self.lbl_runtime = QLabel(self._t("state.stopped"))
        self.lbl_patch = QLabel("-")
        self.lbl_patch.setToolTip(self._t("ctl.patch_tip"))
        self.lbl_patch.setWordWrap(True)
        self.btn_reconnect = self._btn("btn.reconnect")
        self.btn_reconnect.clicked.connect(self._reconnect)
        lay.addWidget(self._label("conn.pcsx2"), 0, 0)
        lay.addWidget(self.lbl_pcsx2, 0, 1)
        lay.addWidget(self._label("conn.game"), 0, 2)
        lay.addWidget(self.lbl_game, 0, 3)
        lay.addWidget(self._label("conn.serial"), 1, 0)
        lay.addWidget(self.lbl_serial, 1, 1)
        lay.addWidget(self._label("conn.adapter"), 1, 2)
        lay.addWidget(self.lbl_adapter, 1, 3)
        lay.addWidget(self._label("conn.runtime"), 2, 0)
        lay.addWidget(self.lbl_runtime, 2, 1)
        lay.addWidget(self.btn_reconnect, 2, 3)
        # the game patch is what lets the orbit turn the view at all, so it gets a
        # first-class status row and buttons to load or remove it by hand
        lay.addWidget(self._label("conn.patch"), 3, 0)
        lay.addWidget(self.lbl_patch, 3, 1, 1, 3)
        self.btn_patch_load = self._btn("btn.patch_load")
        self.btn_patch_remove = self._btn("btn.patch_remove")
        self.btn_patch_load.clicked.connect(lambda: self._on_patch(True))
        self.btn_patch_remove.clicked.connect(lambda: self._on_patch(False))
        lay.addWidget(self.btn_patch_load, 4, 1)
        lay.addWidget(self.btn_patch_remove, 4, 2)
        self._ln = self._label("conn.language")
        self.cmb_lang = QComboBox()
        for code, native in LANGUAGES.items():
            self.cmb_lang.addItem(native, code)
        idx = self.cmb_lang.findData(current_language())
        self.cmb_lang.setCurrentIndex(max(0, idx))
        self.cmb_lang.currentIndexChanged.connect(self._on_language)
        lay.addWidget(self._ln, 5, 0)
        lay.addWidget(self.cmb_lang, 5, 1, 1, 3)
        return box

    def _build_mode(self) -> QGroupBox:
        box = self._group("group.mode")
        lay = QVBoxLayout(box)
        self.rb_original = self._radio("mode.original")
        self.rb_orbit = self._radio("mode.orbit")
        self.rb_free = self._radio("mode.free")
        for rb, mode in ((self.rb_original, MODE_ORIGINAL), (self.rb_orbit, MODE_ORBIT),
                         (self.rb_free, MODE_FREE)):
            rb.toggled.connect(lambda on, m=mode: self._on_mode(m) if on else None)
            lay.addWidget(rb)
        self.rb_original.setChecked(True)
        self.chk_auto_center = self._chk("mode.autocenter")
        self.chk_auto_center.setChecked(True)
        lay.addWidget(self.chk_auto_center)
        hint = QLabel(self._t("mode.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        self._reg(hint, "text", "mode.hint")
        lay.addWidget(hint)
        return box

    def _build_controls(self) -> QGroupBox:
        box = self._group("group.controls")
        lay = QGridLayout(box)
        self.btn_enable = self._btn("btn.enable")
        self.btn_disable = self._btn("btn.disable")
        self.btn_center = self._btn("btn.center")
        self.btn_reset = self._btn("btn.reset")
        self.btn_restore = self._btn("btn.restore")
        self.btn_save = self._btn("btn.save")
        self.btn_load = self._btn("btn.load")
        self.btn_enable.clicked.connect(lambda: self._on_mode(MODE_ORBIT))
        self.btn_disable.clicked.connect(lambda: self._on_mode(MODE_ORIGINAL))
        self.btn_center.clicked.connect(self._center_on_yuna)
        self.btn_reset.clicked.connect(self._reset_params)
        self.btn_restore.clicked.connect(self._restore)
        self.btn_save.clicked.connect(self._save_preset)
        self.btn_load.clicked.connect(self._load_preset)
        self.cmb_preset = QComboBox()
        self.cmb_preset.setToolTip(self._t("ctl.preset_tip"))
        self._tip_preset = True
        for i, b in enumerate((self.btn_enable, self.btn_disable, self.btn_center,
                               self.btn_reset, self.btn_restore, self.btn_load,
                               self.btn_save, self.cmb_preset)):
            lay.addWidget(b, i // 2, i % 2)
        return box

    def _build_rotation(self) -> QGroupBox:
        box = self._group("group.rotation")
        form = QFormLayout(box)
        # Yaw wraps: the runtime accumulates a continuous angle, so a -180..180
        # slider would clamp and silently fight the stick once the camera has
        # been turned past half a revolution.  Give it two full turns.
        self.sl_yaw = FloatSlider(-720, 720, 0, 1)
        # keep the slider range identical to the runtime clamp, otherwise the
        # widget can display values the engine will never produce
        self.sl_pitch = FloatSlider(-90, 90, 40.9, 1)
        self.sl_speed = FloatSlider(10, 400, 150, 0, 5)
        self.sl_sens = FloatSlider(0.1, 4.0, 1.0, 2, 0.05)
        self.sl_dead = FloatSlider(0.0, 0.6, 0.12, 2, 0.01)
        self.sl_yaw.valueChanged.connect(lambda v: self._set(yaw_deg=v))
        self.sl_pitch.valueChanged.connect(lambda v: self._set(pitch_deg=v))
        self.sl_speed.valueChanged.connect(lambda v: self._set(rotate_speed_deg=v))
        self.sl_sens.valueChanged.connect(lambda v: self._set(sensitivity=v))
        self.sl_dead.valueChanged.connect(lambda v: self._set(deadzone=v))
        self._row(form, "rot.yaw", self.sl_yaw)
        self._row(form, "rot.pitch", self.sl_pitch)
        self._row(form, "rot.speed", self.sl_speed)
        self._row(form, "rot.sens", self.sl_sens)
        self._row(form, "rot.deadzone", self.sl_dead)
        row = QHBoxLayout()
        self.chk_invx = self._chk("rot.invert_x")
        self.chk_invy = self._chk("rot.invert_y")
        self.chk_invx.toggled.connect(lambda v: self._set(invert_x=v))
        self.chk_invy.toggled.connect(lambda v: self._set(invert_y=v))
        row.addWidget(self.chk_invx)
        row.addWidget(self.chk_invy)
        w = QWidget()
        w.setLayout(row)
        self._row(form, "rot.invert", w)
        self.cmb_input = QComboBox()
        self.cmb_input.addItems(["auto", "xinput", "keyboard", "scripted"])
        self.cmb_input.currentTextChanged.connect(self._on_input_changed)
        self._row(form, "rot.input", self.cmb_input)
        return box

    def _build_position(self) -> QGroupBox:
        box = self._group("group.position")
        form = QFormLayout(box)
        self.sl_dist = FloatSlider(1.0, 200.0, 28.7, 1, 0.5)
        self.sl_dist.valueChanged.connect(lambda v: self._set(distance=v))
        self._row(form, "pos.distance", self.sl_dist)
        # how far above the party anchor (i.e. towards -Y) the camera looks.
        # This is the control that decides whether Yuna sits in the middle of
        # the frame, so it is exposed directly instead of being folded into the
        # target offsets.
        self.sl_look = FloatSlider(-40.0, 40.0, -6.0, 2, 0.5)
        self.sl_look.valueChanged.connect(lambda v: self._set(look_height=v))
        self._row(form, "pos.look_height", self.sl_look)

        self.off = []
        names = ["pos.cam_x", "pos.cam_y", "pos.cam_z",
                 "pos.tgt_x", "pos.tgt_y", "pos.tgt_z"]
        for i, nm in enumerate(names):
            sl = FloatSlider(-80, 80, 0.0, 2, 0.25)
            if i < 3:
                sl.valueChanged.connect(lambda v, k=i: self._set_pos_offset(k, v))
            else:
                sl.valueChanged.connect(lambda v, k=i - 3: self._set_target_offset(k, v))
            self.off.append(sl)
            self._row(form, nm, sl)
        return box

    def _build_lens(self) -> QGroupBox:
        box = self._group("group.lens")
        form = QFormLayout(box)
        self.sl_fov = FloatSlider(FOV_MIN_DEG, FOV_MAX_DEG, 54.68, 2, 0.5)
        self.sl_fov.valueChanged.connect(self._on_fov)
        self.chk_fov = self._chk("lens.apply")
        self.chk_fov.toggled.connect(self._on_fov_enable)
        self.lbl_fov_now = QLabel(self._t("lens.current_none"))
        self.btn_fov_reset = self._btn("lens.reset")
        self.btn_fov_reset.clicked.connect(self._reset_fov)
        self._row(form, "lens.fov", self.sl_fov)
        form.addRow(self.chk_fov)
        self._row(form, "lens.live", self.lbl_fov_now)
        form.addRow(self.btn_fov_reset)
        return box

    def _build_native_zoom(self) -> QGroupBox:
        """The game's own zoom (Suikoden V: three stages on R1 / the right stick)."""
        box = self._group("group.zoom")
        form = QFormLayout(box)
        self.lbl_zoom_now = QLabel("-")
        self._row(form, "zoom.live", self.lbl_zoom_now)
        row = QHBoxLayout()
        self.btn_zoom_stage: list[QPushButton] = []
        for n in range(3):
            b = QPushButton(self._t("zoom.stage", n=n + 1))
            b.clicked.connect(lambda _c=False, n=n: self._on_zoom_stage(n))
            self.btn_zoom_stage.append(b)
            row.addWidget(b)
        form.addRow(self._label("zoom.stages"), row)
        self.chk_zoom_follow = self._chk("zoom.follow")
        self.chk_zoom_follow.setChecked(True)
        form.addRow(self.chk_zoom_follow)
        self.lbl_zoom_note = self._label("zoom.note")
        self.lbl_zoom_note.setWordWrap(True)
        form.addRow(self.lbl_zoom_note)
        self._zoom_last: int | None = None
        return box

    def _on_zoom_stage(self, stage: int) -> None:
        """Orbit mode: use the distance of that native stage and keep the game's stage in step."""
        ad = self.adapter
        if self.runtime is None or not hasattr(ad, "set_zoom_stage"):
            return
        dist = ad.set_zoom_stage(stage)
        if dist is not None and self.runtime.settings.mode != MODE_ORIGINAL:
            self._set(distance=dist)
            self.sl_dist.set_value(dist)

    def _refresh_native_zoom(self) -> None:
        ad = self.adapter
        has = ad is not None and bool(getattr(ad, "features", {}).get("native_zoom"))
        self.grp_zoom.setVisible(has)
        if not has or self.runtime is None:
            return
        try:
            stage = ad.read_zoom_stage()
            native = ad.native_distance()
        except Exception:  # noqa: BLE001
            stage, native = None, None
        if stage is None:
            self.lbl_zoom_now.setText(self._t("zoom.none"))
            return
        self.lbl_zoom_now.setText(self._t("zoom.current", n=stage + 1, d=native or 0.0))
        orbit = self.runtime.settings.mode != MODE_ORIGINAL
        for b in self.btn_zoom_stage:
            b.setEnabled(orbit)
        # R1 / the game's zoom steps the orbit distance when "follow" is on
        if (orbit and self.chk_zoom_follow.isChecked() and self._zoom_last is not None
                and stage != self._zoom_last):
            dist = ad.stage_distance(stage)
            self._set(distance=dist)
            self.sl_dist.set_value(dist)
        self._zoom_last = stage

    def _build_debug(self) -> QGroupBox:
        box = self._group("group.debug")
        form = QFormLayout(box)
        self.lbl_cam = QLabel("-")
        self.lbl_aim = QLabel("-")
        self.lbl_player = QLabel("-")
        self.lbl_rate = QLabel("-")
        self.lbl_last = QLabel("-")
        self.lbl_err = QLabel("-")
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setStyleSheet("color:#a00;")
        for key, w in (("dbg.eye", self.lbl_cam), ("dbg.aim", self.lbl_aim),
                       ("dbg.player", self.lbl_player),
                       ("dbg.rate", self.lbl_rate), ("dbg.last", self.lbl_last),
                       ("dbg.warn", self.lbl_err)):
            self._row(form, key, w)
        return box

    # --------------------------------------------------------------- state
    def _set(self, **kwargs) -> None:
        if self.runtime is None or self._updating:
            return
        st = self.runtime.settings
        for k, v in kwargs.items():
            setattr(st, k, v)
        self.app_settings.__dict__.update({k: v for k, v in kwargs.items()})
        self._persist_later()

    def _set_pos_offset(self, index: int, value: float) -> None:
        if self.runtime is None:
            return
        self.runtime.settings.pos_offset[index] = value
        self.app_settings.pos_offset[index] = value
        self._persist_later()

    def _set_target_offset(self, index: int, value: float) -> None:
        if self.runtime is None:
            return
        self.runtime.settings.target_offset[index] = value
        self.app_settings.target_offset[index] = value
        self._persist_later()

    def _persist_later(self) -> None:
        if getattr(self, "_persist_timer", None) is None:
            self._persist_timer = QTimer(self)
            self._persist_timer.setSingleShot(True)
            self._persist_timer.timeout.connect(self._persist)
        self._persist_timer.start(800)

    def _persist(self) -> None:
        if self.runtime is None:
            return
        st = self.runtime.snapshot()
        self.app_settings.__dict__.update(st.__dict__)
        self.store.put(self.app_settings)

    # ------------------------------------------------------------ lifecycle
    def _reconnect(self) -> None:
        self._teardown()
        try:
            backend = PineBackend()
            backend.connect()
            adapter_cls = ADAPTER_BY_GAME_ID.get(backend.game_id().strip().upper(), FFX2Adapter)
            adapter = adapter_cls(backend)
            info = adapter.identify()
        except Exception as exc:  # noqa: BLE001
            self.lbl_pcsx2.setText(self._t("state.disconnected"))
            self.lbl_runtime.setText(self._t("state.stopped"))
            self._last_problem = self._t("status.pine_failed", err=exc)
            self._status(self._last_problem)
            self.lbl_err.setText(self._last_problem)
            return
        self.backend = backend
        self.adapter = adapter
        self.lbl_pcsx2.setText(self._t("state.connected"))
        self.lbl_game.setText(info.title or "-")
        self.lbl_serial.setText(f"{info.game_id} / {info.crc}")
        self.lbl_adapter.setText(adapter.name if info.matched else "-")
        if not info.matched:
            self._last_problem = self._t("status.unsupported", gid=info.game_id, crc=info.crc)
            self._status(self._last_problem)
            return
        # settings are kept per game, so FFX-2 values never reach this game; a game seen
        # for the first time starts from the adapter's own stock framing
        gid = info.game_id.strip().upper()
        self.app_settings = self.store.get(gid)
        defaults = getattr(adapter, "default_settings", None)
        if callable(defaults) and gid not in self.store.data:
            for key, value in defaults().items():
                setattr(self.app_settings, key, value)
        self._apply_adapter_limits(adapter)
        settings = CameraSettings(**{k: v for k, v in self.app_settings.__dict__.items()
                                     if k in CameraSettings().__dict__})
        self.runtime = CameraRuntime(adapter, settings)
        self.runtime.capture_original_fov()
        self._sync_widgets_from(settings)
        # the persisted mode must be reflected in the radio group: otherwise the
        # window says "Original" while the runtime is already driving the camera,
        # which is both confusing and unsafe
        self._sync_mode_radios(settings.mode)
        self.runtime.start()
        self._setup_input()
        self._refresh_presets()
        self._last_problem = ""
        self._status(self._t("status.connected"))

    def _apply_adapter_limits(self, adapter) -> None:
        """Slider ranges for this game; FFX-2 keeps the ranges the sliders were built with."""
        lo, hi = getattr(adapter, "DISTANCE_RANGE", (1.0, 200.0))
        self.sl_dist.set_range(lo, hi)
        lo, hi = getattr(adapter, "LOOK_HEIGHT_RANGE", (-40.0, 40.0))
        self.sl_look.set_range(lo, hi)

    def _sync_mode_radios(self, mode: str) -> None:
        """Select the radio that matches ``mode`` without firing _on_mode."""
        for rb, m in ((self.rb_original, MODE_ORIGINAL), (self.rb_orbit, MODE_ORBIT),
                      (self.rb_free, MODE_FREE)):
            blocked = rb.blockSignals(True)
            rb.setChecked(m == mode)
            rb.blockSignals(blocked)

    def _teardown(self) -> None:
        if self.pump:
            self.pump.stop()
            self.pump = None
        if self.runtime:
            # stop first: a tick still in flight could switch the orbit back on
            # after restore() has handed the projection to the area
            self.runtime.stop()
            self.runtime.restore()
            self.runtime = None
        if self.backend:
            self.backend.close()
            self.backend = None
        self.adapter = None

    def _setup_input(self) -> None:
        if self.runtime is None:
            return
        choice = self.cmb_input.currentText()
        sources = []
        if choice in ("auto", "xinput"):
            xi = XInputSource()
            if xi.available:
                sources.append(xi)
        if choice in ("auto", "keyboard"):
            sources.append(KeyboardSource())
        if choice in ("auto", "scripted"):
            sources.append(self.scripted)
        src = CompositeSource(sources) if len(sources) > 1 else (sources[0] if sources else self.scripted)
        if self.pump:
            self.pump.stop()
        self.pump = InputPump(self.runtime, src, hz=120)
        self.pump.start()

    def _on_input_changed(self, _text: str) -> None:
        self._setup_input()

    # ------------------------------------------------------------- actions
    def _on_language(self, _index: int) -> None:
        code = self.cmb_lang.currentData() or "ja"
        set_language(code)
        self.app_settings.language = code
        self._persist_later()
        self._retranslate()
        self._status(self._t("status.language", name=LANGUAGES.get(code, code)))

    def _mode_name(self, mode: str) -> str:
        return self._t(f"mode.short.{mode}" if mode in ("original", "orbit", "free")
                       else "mode.short.original")

    def _on_mode(self, mode: str) -> None:
        if self.runtime is None:
            return
        self._updating = True
        self.rb_original.setChecked(mode == MODE_ORIGINAL)
        self.rb_orbit.setChecked(mode == MODE_ORBIT)
        self.rb_free.setChecked(mode == MODE_FREE)
        self._updating = False
        if mode == MODE_ORIGINAL:
            self.runtime.restore()
            self.lbl_runtime.setText(self._t("state.stopped_original"))
            return
        if mode == MODE_ORBIT:
            # "move onto Yuna first, then rotate": re-centre whenever the mod is
            # (re)enabled so a field whose own camera does not look at the party
            # starts from a centred view.
            if self.runtime.stats.mode != MODE_ORBIT or self.chk_auto_center.isChecked():
                self.runtime.center_on_target()
                self._sync_widgets_from(self.runtime.snapshot())
        if mode == MODE_FREE and self.runtime.stats.applied_pose:
            eye, tgt = self.runtime.stats.applied_pose
            self.runtime.settings.free_eye = list(eye)
            self.runtime.settings.free_target = list(tgt)
        self.runtime.settings.mode = mode
        self.lbl_runtime.setText(f"{self._t('state.running')} ({self._mode_name(mode)})")

    def _center_on_yuna(self) -> None:
        if self.runtime is None:
            return
        if self.runtime.center_on_target():
            self._sync_widgets_from(self.runtime.snapshot())
            self.runtime.settings.mode = MODE_ORBIT
            self._sync_mode_radios(MODE_ORBIT)
            self.lbl_runtime.setText(f"{self._t('state.running')} ({self._mode_name(MODE_ORBIT)})")
            self._status(self._t("status.centered"))
        else:
            self._status(self._t("status.center_failed", err=self.runtime.stats.last_error))

    def _reset_params(self) -> None:
        if self.runtime is None:
            return
        self.runtime.sync_to_game()
        st = self.runtime.settings
        st.pos_offset = [0.0, 0.0, 0.0]
        st.target_offset = [0.0, 0.0, 0.0]
        self._sync_widgets_from(st)

    def _restore(self) -> None:
        if self.runtime is None:
            return
        self.runtime.restore()
        self._sync_mode_radios(MODE_ORIGINAL)
        self.lbl_runtime.setText(self._t("state.stopped_original"))
        self._status(self._t("status.restored"))

    def _on_patch(self, load: bool) -> None:
        """Load or remove the game patch by hand.  The next camera mode change hands it back."""
        if self.runtime is None:
            self._status(self._t("status.patch_need_connection"))
            return
        self.runtime.set_patch_override(load)
        if not self.runtime.running:
            self.runtime.start()
        self._status(self._t("status.patch_loaded" if load else "status.patch_removed"))
        self._slow_poll = 0.0  # show the new state on the next refresh

    def _on_fov(self, value: float) -> None:
        if self.runtime is None:
            return
        self.runtime.settings.fov_deg = value
        self.app_settings.fov_deg = value
        if self.chk_fov.isChecked():
            self.runtime.settings.use_fov = True
        self._persist_later()

    def _on_fov_enable(self, on: bool) -> None:
        if self.runtime is None:
            return
        self.runtime.settings.use_fov = on
        if not on:
            self.runtime.adapter.restore_fov()

    def _reset_fov(self) -> None:
        if self.runtime is None:
            return
        self.runtime.adapter.restore_fov()
        self.runtime.settings.use_fov = False
        self._updating = True
        self.chk_fov.setChecked(False)
        self._updating = False
        fov = self.runtime.adapter.read_fov_deg()
        self.sl_fov.set_value(fov)

    def _save_preset(self) -> None:
        if self.runtime is None:
            return
        name, ok = _prompt(self, self._t("dlg.preset_title"), self._t("dlg.preset_label"),
                           "orbit-default")
        if not ok or not name.strip():
            return
        path = self.presets.save(name.strip(), self.app_settings)
        self._refresh_presets()
        self._status(self._t("status.preset_saved", name=path.name))

    def _load_preset(self) -> None:
        if self.runtime is None:
            return
        name = self.cmb_preset.currentText()
        if not name:
            return
        st = self.presets.load(name, self.app_settings.game_id)
        if st is None:
            self._status(self._t("status.preset_missing", name=name))
            return
        self.app_settings = st
        self.runtime.settings = CameraSettings(**{k: v for k, v in st.__dict__.items()
                                                  if k in CameraSettings().__dict__})
        self._sync_widgets_from(self.runtime.settings)
        self._sync_mode_radios(self.runtime.settings.mode)
        self._status(self._t("status.preset_loaded", name=name))

    def _refresh_presets(self) -> None:
        gid = self.app_settings.game_id
        self.cmb_preset.clear()
        self.cmb_preset.addItems(self.presets.list(gid))

    def _sync_widgets_from(self, st) -> None:
        self._updating = True
        self.sl_yaw.set_value(st.yaw_deg)
        self.sl_pitch.set_value(st.pitch_deg)
        self.sl_dist.set_value(st.distance)
        self.sl_look.set_value(st.look_height)
        self.sl_speed.set_value(st.rotate_speed_deg)
        self.sl_sens.set_value(st.sensitivity)
        self.sl_dead.set_value(st.deadzone)
        self.sl_fov.set_value(st.fov_deg)
        self.chk_invx.setChecked(st.invert_x)
        self.chk_invy.setChecked(st.invert_y)
        self.chk_fov.setChecked(st.use_fov)
        for i in range(3):
            self.off[i].set_value(st.pos_offset[i])
            self.off[i + 3].set_value(st.target_offset[i])
        self._updating = False

    # -------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        if self.runtime is None:
            self.lbl_runtime.setText("Stopped")
            return
        st = self.runtime.stats
        mode = self.runtime.settings.mode
        self.lbl_runtime.setText(
            f"{self._t('state.running')} ({self._mode_name(mode)})"
            if mode != MODE_ORIGINAL else self._t("state.stopped_original"))
        # Both of these cost a PINE round trip, and the runtime thread is using
        # the same socket; polling them at the 80 ms UI tick added needless
        # contention, so they are refreshed a few times per second instead.
        now = time.monotonic()
        if now - getattr(self, "_slow_poll", 0.0) >= 0.4:
            self._slow_poll = now
            try:
                state = self.adapter.patch_state()
            except Exception:  # noqa: BLE001
                state = "unreadable"
            key, style = PATCH_TEXT.get(state, ("patch.missing", "color:#c60;"))
            self.lbl_patch.setText(self._t(key))
            self.lbl_patch.setStyleSheet(style)
            self._refresh_native_zoom()
            try:
                fov = self.adapter.read_fov_deg()
                reader = getattr(self.adapter, "read_fov_scale", None)
                scale = (reader() if callable(reader)
                         else self.adapter.backend.read_floats(0x340B00, 1)[0])
                self.lbl_fov_now.setText(self._t("lens.current", fov=fov, scale=scale))
            except Exception:  # noqa: BLE001
                self.lbl_fov_now.setText(self._t("lens.current_none"))
        if st.applied_pose:
            e, t = st.applied_pose
            self.lbl_cam.setText(f"({e[0]:.2f}, {e[1]:.2f}, {e[2]:.2f})")
            self.lbl_aim.setText(f"({t[0]:.2f}, {t[1]:.2f}, {t[2]:.2f})")
        if st.player:
            p = st.player
            self.lbl_player.setText(f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})")
        self.lbl_rate.setText(self._t("dbg.rate_value", n=st.writes_per_sec))
        self.lbl_last.setText(time.strftime("%H:%M:%S") if st.total_writes else "-")
        problem = self._last_problem or st.last_error
        self.lbl_err.setText(problem or "-")
        # mirror runtime-driven values back into the widgets while the stick moves
        if mode != MODE_ORIGINAL and not self._updating:
            cur = self.runtime.settings
            self._updating = True
            try:
                if abs(self.sl_yaw.value() - cur.yaw_deg) > 0.05:
                    self.sl_yaw.set_value(cur.yaw_deg)
                if abs(self.sl_pitch.value() - cur.pitch_deg) > 0.05:
                    self.sl_pitch.set_value(cur.pitch_deg)
                if abs(self.sl_dist.value() - cur.distance) > 0.05:
                    self.sl_dist.set_value(cur.distance)
            finally:
                self._updating = False

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._persist()
            self._teardown()
        finally:
            event.accept()


#: how the game-patch status row is shown, per adapter.patch_state()
PATCH_TEXT = {
    "applied": ("patch.active", "color:#070;"),
    "stock": ("patch.stock", "color:#666;"),
    "partial": ("patch.partial", "color:#c60;"),
    "unknown": ("patch.unknown", "color:#c00;"),
}


def _prompt(parent, title, label, default):
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getText(parent, title, label, QLineEdit.Normal, default)


def main() -> int:
    # --screenshot PATH renders the window offscreen and exits; used to produce
    # the evidence images in reports/ without needing a visible desktop session.
    shot = None
    if "--screenshot" in sys.argv:
        i = sys.argv.index("--screenshot")
        if i + 1 < len(sys.argv):
            shot = sys.argv[i + 1]
            del sys.argv[i:i + 2]
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)
    win = MainWindow()
    win.show()
    if shot:
        from PySide6.QtCore import QTimer

        def _demo() -> None:
            # drive the GUI itself so the capture shows a live orbit rather than
            # an idle window: this is a real GUI -> runtime -> memory round trip
            if "--demo" in sys.argv:
                win.rb_orbit.setChecked(True)
                win.sl_yaw.set_value(35.0)

        def _grab() -> None:
            try:
                win.grab().save(shot)
                print(f"PS2UniversalCamera: wrote {shot}")
            finally:
                app.quit()

        QTimer.singleShot(1200, _demo)
        QTimer.singleShot(3200, _grab)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
