"""PS2 Universal Camera Controller — PySide6 desktop application.

The GUI is a thin client: it owns no game knowledge.  It talks to

* a game adapter (``adapters/<game>/adapter.py``, chosen from the game's serial)
* the ``CameraRuntime`` (per-frame writer thread)

through plain dataclasses, so adding a game means adding an adapter and registering it in
``ADAPTERS`` / ``ADAPTER_BY_GAME_ID`` / ``SUPPORTED_IDS`` below.

Rules this module keeps (see docs/gui/GUI_AUDIT_2026-11-02.md):

* the GUI thread never waits on PINE: game state is read by ``StatusPoller``; actions that write to
  the game are wrapped so a failure becomes a message, never a traceback;
* the window always starts in Original (the user switches the mod on);
* controls are disabled when there is nothing to control (no game, lost link, unsupported game) and
  per control when the adapter cannot use it;
* the adapter writes through a ``GuardedBackend`` armed for the (serial, CRC) it was chosen for.
  ``StatusPoller`` re-checks the running game every poll; when it differs the guard refuses all
  writes at once, and the window drops the old runtime *without* restoring (a restore would write
  the old game's addresses into the new game) and connects again to pick the right adapter.
"""
from __future__ import annotations

import functools
import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QLockFile, QSettings, Qt, QTimer, Signal  # noqa: E402
    from PySide6.QtGui import QFont  # noqa: E402
    from PySide6.QtWidgets import (  # noqa: E402
        QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
        QRadioButton, QScrollArea, QSlider, QStatusBar, QVBoxLayout, QWidget,
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
from adapters.shiningforceexa.adapter import SFExaAdapter  # noqa: E402
from adapters.suikoden5.adapter import Suikoden5Adapter  # noqa: E402
from core.camera_math.orbit import FOV_MAX_DEG, FOV_MIN_DEG  # noqa: E402
from core.camera_runtime.engine import (  # noqa: E402
    MODE_FREE, MODE_ORBIT, MODE_ORIGINAL, CameraRuntime, CameraSettings,
)
from core.config.settings import (  # noqa: E402
    APP_NAME, APP_VERSION, AppSettings, PresetStore, SettingsStore, _config_home,
)
from core.controller.sources import (  # noqa: E402
    CompositeSource, InputPump, KeyboardSource, ScriptedSource, XInputSource,
)
from core.memory_backend.guard import CHANGED, SAME, GuardedBackend  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

try:  # run as a module (python -m gui.camera_controller.app)
    from gui.camera_controller.i18n import (  # noqa: E402
        LANGUAGES, current_language, set_language, tr,
    )
except ImportError:  # run as a script (python gui/camera_controller/app.py)
    from i18n import LANGUAGES, current_language, set_language, tr  # noqa: E402

log = logging.getLogger("ps2cam.gui")

ADAPTERS = {"FFX2": FFX2Adapter, "SFNEO": SFNeoAdapter, "SFEXA": SFExaAdapter,
            "SUIKODEN5": Suikoden5Adapter}
#: adapter class per game serial, chosen when the GUI connects
ADAPTER_BY_GAME_ID = {"SLPS-25250": FFX2Adapter, "SLPM-65908": SFNeoAdapter,
                      "SLPM-66646": SFExaAdapter, "SLPM-66286": Suikoden5Adapter}
#: ids the current adapters actually verify.  Each adapter matches on serial *and*
#: CRC (FFX-2 ``8A6D7F14``, Shining Force Neo ``64F241D2``, Shining Force Exa ``8B383FDF``,
#: Suikoden V ``7380A572``), which only the Japanese releases satisfy, so the US/EU serials
#: are deliberately NOT listed here: advertising them would promise support the adapters refuse.
SUPPORTED_IDS = {"SLPS-25250", "SLPM-65908", "SLPM-66646", "SLPM-66286"}

#: severity styles of the notice bar (explicit foreground *and* background: readable on any theme)
NOTICE_STYLE = {
    "info": "background:#e8f1fb;color:#123c69;border:1px solid #a9c6e8;border-radius:4px;padding:6px;",
    "warn": "background:#fff4ce;color:#5c4a00;border:1px solid #e6c84d;border-radius:4px;padding:6px;",
    "error": "background:#fde7e9;color:#7a1118;border:1px solid #e6a3a8;border-radius:4px;padding:6px;",
}
#: how the game-patch status row is shown, per adapter.patch_state()
PATCH_TEXT = {
    "applied": ("patch.active", "color:#0a6b22;"),
    "stock": ("patch.stock", "color:#555;"),
    "partial": ("patch.partial", "color:#a85b00;"),
    "unknown": ("patch.unknown", "color:#b00020;"),
}
NO_STYLE = ""


def safe_slot(fn):
    """Run a slot that may touch the game; a failure becomes a notice, not an uncaught exception."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("slot %s failed", fn.__name__)
            self._flash(self._t("notice.action_failed", err=exc), "warn")
            return None
    return wrapper


class _NoWheelSlider(QSlider):
    """A slider that ignores the mouse wheel unless it has the focus (scrolling the window must not move the camera)."""

    def __init__(self, *a) -> None:
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _NoWheelSpin(QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class FloatSlider(QWidget):
    """Slider + numeric box kept in sync, emitting one float value."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float,
                 decimals: int = 1, step: float = 1.0) -> None:
        super().__init__()
        self._scale = 10 ** decimals
        self.slider = _NoWheelSlider(Qt.Horizontal)
        self.slider.setRange(int(minimum * self._scale), int(maximum * self._scale))
        self.spin = _NoWheelSpin()
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
        """Change the limits (a game may need another range than the default one)."""
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setRange(int(minimum * self._scale), int(maximum * self._scale))
        self.spin.setRange(minimum, maximum)
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)

    def value(self) -> float:
        return self.spin.value()


class StatusPoller(threading.Thread):
    """Reads the slow-changing game state off the GUI thread.

    Every read is a PINE round trip.  When PCSX2 is closed or killed a request can block, and the
    80 ms window timer made the whole window freeze on it.  The GUI only reads the last result from
    ``data``; this thread does the reading, and it does nothing while the backend reports PCSX2 as
    unreachable (``PineBackend.available``).

    It also watches which game is running: every poll (about 0.4 s, two PINE reads) the window's
    ``GuardedBackend`` compares the live serial and CRC with the ones the adapter was chosen for.
    That check lives here, not in the camera loop, so the 1.2 kHz writer pays nothing for it.
    """

    def __init__(self, window: "MainWindow", period: float = 0.4) -> None:
        super().__init__(name="gui-status-poller", daemon=True)
        self.window = window
        self.period = period
        self._halt = threading.Event()
        #: link: True when the last poll could read the game; the rest is what was read
        self.data: dict = {"link": True, "patch": "unreadable", "fov": None, "scale": None,
                           "zoom_stage": None, "zoom_native": None}

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.wait(self.period):
            self.data = self.poll_once()

    def poll_once(self) -> dict:
        w = self.window
        ad, be = w.adapter, w.backend
        d: dict = {"link": False, "patch": "unreadable", "fov": None, "scale": None,
                   "zoom_stage": None, "zoom_native": None}
        if ad is None or be is None or not be.available:
            return d
        guard = getattr(w, "guard", None)
        if guard is not None and guard.verify() == CHANGED:
            # another game: say nothing about its memory, the window reconnects (see _refresh)
            d["link"] = True
            return d
        try:
            d["patch"] = ad.patch_state()
            d["fov"] = ad.read_fov_deg()
            reader = getattr(ad, "read_fov_scale", None)
            d["scale"] = reader() if callable(reader) else be.read_floats(0x340B00, 1)[0]
            d["link"] = True
        except Exception:  # noqa: BLE001
            return d
        if getattr(ad, "features", {}).get("native_zoom"):
            try:
                d["zoom_stage"] = ad.read_zoom_stage()
                d["zoom_native"] = ad.native_distance()
            except Exception:  # noqa: BLE001
                pass
        return d


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{tr('app.title')}  v{APP_VERSION}")
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(min(980, avail.width() - 80), min(820, avail.height() - 120))
        else:
            self.resize(980, 820)
        self.setMinimumSize(640, 420)
        self.store = SettingsStore()
        self.presets = PresetStore()
        self.backend: PineBackend | None = None
        #: what the adapter writes through; armed for the game that was identified at connect
        self.guard: GuardedBackend | None = None
        self.adapter = None
        self.runtime: CameraRuntime | None = None
        self.pump: InputPump | None = None
        self.scripted = ScriptedSource()
        self.app_settings = self.store.get("SLPS-25250")
        self._updating = False
        #: (widget, property, key, format arguments) re-applied when the language changes
        self._i18n: list[tuple[object, str, str, dict]] = []
        #: a connection-level problem that stays until the next successful connect: (key, level, args)
        self._conn_problem: tuple[str, str, dict] | None = None
        #: a short-lived message: (text, level, until)
        self._flash_msg: tuple[str, str, float] | None = None
        self._last_text: dict[int, str] = {}
        self._last_style: dict[int, str] = {}
        self._usable = False
        self._zoom_last: int | None = None
        set_language(getattr(self.app_settings, "language", "ja"))
        self._build_ui()
        self._restore_geometry()
        self._link_ok = True
        self.poller = StatusPoller(self)
        self.poller.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(80)
        self._reconnect()

    # ------------------------------------------------------------- i18n
    def _t(self, key: str, **fmt) -> str:
        return tr(key, **fmt)

    def _reg(self, widget, prop: str, key: str, **fmt) -> None:
        self._i18n.append((widget, prop, key, fmt))

    def _label(self, key: str) -> QLabel:
        w = QLabel(tr(key))
        self._reg(w, "text", key)
        return w

    def _group(self, key: str) -> QGroupBox:
        b = QGroupBox(tr(key))
        self._reg(b, "title", key)
        return b

    def _btn(self, key: str, tip: str | None = None) -> QPushButton:
        b = QPushButton(tr(key))
        self._reg(b, "text", key)
        if tip:
            self._tip(b, tip)
        return b

    def _chk(self, key: str, tip: str | None = None) -> QCheckBox:
        c = QCheckBox(tr(key))
        self._reg(c, "text", key)
        if tip:
            self._tip(c, tip)
        return c

    def _radio(self, key: str) -> QRadioButton:
        r = QRadioButton(tr(key))
        self._reg(r, "text", key)
        return r

    def _tip(self, widget, key: str) -> None:
        widget.setToolTip(tr(key))
        self._reg(widget, "tooltip", key)

    def _row(self, form, key: str, widget, tip: str | None = None) -> QLabel:
        lab = self._label(key)
        form.addRow(lab, widget)
        if tip:
            self._tip(lab, tip)
            self._tip(widget, tip)
        return lab

    def _retranslate(self) -> None:
        for widget, prop, key, fmt in self._i18n:
            text = tr(key, **fmt)
            if prop == "title":
                widget.setTitle(text)             # type: ignore[attr-defined]
            elif prop == "tooltip":
                widget.setToolTip(text)           # type: ignore[attr-defined]
            else:
                widget.setText(text)              # type: ignore[attr-defined]
        self._update_title()
        self._update_hints()
        self._update_offsets_title()
        self._last_text.clear()
        self._refresh()

    def _update_title(self) -> None:
        game = getattr(self.adapter, "display_name", "") if self.adapter is not None else ""
        base = f"{tr('app.title')}  v{APP_VERSION}"
        self.setWindowTitle(tr("title.game", app=base, game=game) if game else base)

    # --------------------------------------------------------- cached widget updates
    def _put(self, widget, text: str) -> None:
        """setText only when the text changed (the 80 ms refresh must not churn the widgets)."""
        if self._last_text.get(id(widget)) != text:
            self._last_text[id(widget)] = text
            widget.setText(text)

    def _style(self, widget, css: str) -> None:
        if self._last_style.get(id(widget)) != css:
            self._last_style[id(widget)] = css
            widget.setStyleSheet(css)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        grid = QGridLayout(central)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        grid.addWidget(self._build_connection(), 0, 0, 1, 2)
        self.lbl_notice = QLabel("")
        self.lbl_notice.setWordWrap(True)
        self.lbl_notice.setVisible(False)
        grid.addWidget(self.lbl_notice, 1, 0, 1, 2)
        self.grp_mode = self._build_mode()
        self.grp_controls = self._build_controls()
        self.grp_rotation = self._build_rotation()
        self.grp_position = self._build_position()
        self.grp_lens = self._build_lens()
        self.grp_zoom = self._build_native_zoom()
        grid.addWidget(self.grp_mode, 2, 0)
        grid.addWidget(self.grp_controls, 2, 1)
        grid.addWidget(self.grp_rotation, 3, 0)
        grid.addWidget(self.grp_position, 3, 1)
        grid.addWidget(self.grp_lens, 4, 0)
        grid.addWidget(self.grp_zoom, 4, 1)
        self.grp_zoom.setVisible(False)       # shown for adapters with a native zoom
        grid.addWidget(self._build_debug(), 5, 0, 1, 2)
        grid.setRowStretch(6, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(central)
        self._scroll = scroll
        self.setCentralWidget(scroll)
        self.setStatusBar(QStatusBar())
        self._status(self._t("status.ready"))
        self._set_usable(False)

    def _build_connection(self) -> QGroupBox:
        box = self._group("group.connection")
        lay = QGridLayout(box)
        self.lbl_pcsx2 = QLabel(self._t("state.disconnected"))
        self.lbl_game = QLabel("-")
        self.lbl_serial = QLabel("-")
        self.lbl_adapter = QLabel("-")
        self.lbl_runtime = QLabel(self._t("state.stopped"))
        self.lbl_patch = QLabel("-")
        self._tip(self.lbl_patch, "ctl.patch_tip")
        self.lbl_patch.setWordWrap(True)
        self.btn_reconnect = self._btn("btn.reconnect")
        self.btn_reconnect.clicked.connect(lambda _=False: self._reconnect())
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
        # the game patch is what lets the orbit turn the view at all, so it keeps a first-class
        # status row; the hand-operated buttons are advanced and stay folded away
        lay.addWidget(self._label("conn.patch"), 3, 0)
        lay.addWidget(self.lbl_patch, 3, 1, 1, 3)
        self._ln = self._label("conn.language")
        self.cmb_lang = QComboBox()
        for code, native in LANGUAGES.items():
            self.cmb_lang.addItem(native, code)
        self.cmb_lang.setCurrentIndex(max(0, self.cmb_lang.findData(current_language())))
        self.cmb_lang.currentIndexChanged.connect(self._on_language)
        lay.addWidget(self._ln, 4, 0)
        lay.addWidget(self.cmb_lang, 4, 1)
        self.chk_advanced = self._chk("btn.advanced")
        lay.addWidget(self.chk_advanced, 4, 3)
        self.btn_patch_load = self._btn("btn.patch_load", "tip.patch_load")
        self.btn_patch_remove = self._btn("btn.patch_remove", "tip.patch_remove")
        self.btn_patch_load.clicked.connect(lambda _=False: self._on_patch(True))
        self.btn_patch_remove.clicked.connect(lambda _=False: self._on_patch(False))
        lay.addWidget(self.btn_patch_load, 5, 1)
        lay.addWidget(self.btn_patch_remove, 5, 2)
        for w in (self.btn_patch_load, self.btn_patch_remove):
            w.setVisible(False)
        self.chk_advanced.toggled.connect(
            lambda on: [w.setVisible(on) for w in (self.btn_patch_load, self.btn_patch_remove)])
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
        self.chk_auto_center = self._chk("mode.autocenter", "tip.autocenter")
        self.chk_auto_center.setChecked(True)
        lay.addWidget(self.chk_auto_center)
        hint = QLabel(self._t("mode.hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        self._reg(hint, "text", "mode.hint")
        lay.addWidget(hint)
        lay.addStretch(1)
        return box

    def _build_controls(self) -> QGroupBox:
        box = self._group("group.controls")
        lay = QGridLayout(box)
        self.btn_enable = self._btn("btn.enable", "tip.enable")
        self.btn_restore = self._btn("btn.restore", "tip.restore")
        self.btn_center = self._btn("btn.center", "tip.center")
        self.btn_reset = self._btn("btn.reset", "tip.reset")
        self.btn_enable.setMinimumHeight(34)
        font = self.btn_enable.font()
        font.setBold(True)
        self.btn_enable.setFont(font)
        self.btn_save = self._btn("btn.save")
        self.btn_load = self._btn("btn.load")
        self.btn_enable.clicked.connect(lambda _=False: self._on_mode(MODE_ORBIT))
        self.btn_restore.clicked.connect(lambda _=False: self._restore())
        self.btn_center.clicked.connect(lambda _=False: self._center())
        self.btn_reset.clicked.connect(lambda _=False: self._reset_params())
        self.btn_save.clicked.connect(lambda _=False: self._save_preset())
        self.btn_load.clicked.connect(lambda _=False: self._load_preset())
        self.cmb_preset = QComboBox()
        self.cmb_preset.setMinimumWidth(120)
        self._tip(self.cmb_preset, "ctl.preset_tip")
        lay.addWidget(self.btn_enable, 0, 0, 1, 2)
        lay.addWidget(self.btn_restore, 1, 0, 1, 2)
        lay.addWidget(self.btn_center, 2, 0)
        lay.addWidget(self.btn_reset, 2, 1)
        preset = QHBoxLayout()
        preset.addWidget(self.cmb_preset, 1)
        preset.addWidget(self.btn_load)
        preset.addWidget(self.btn_save)
        lay.addLayout(preset, 3, 0, 1, 2)
        return box

    def _build_rotation(self) -> QGroupBox:
        box = self._group("group.rotation")
        form = QFormLayout(box)
        # The runtime wraps the yaw into -180..180, so the slider has the same range.
        self.sl_yaw = FloatSlider(-180, 180, 0, 1)
        self.sl_pitch = FloatSlider(-90, 90, 40.9, 1)      # range set per game in _apply_adapter_limits
        self.sl_speed = FloatSlider(10, 400, 150, 0, 5)
        self.sl_sens = FloatSlider(0.1, 4.0, 1.0, 2, 0.05)
        self.sl_dead = FloatSlider(0.0, 0.6, 0.12, 2, 0.01)
        self.sl_yaw.valueChanged.connect(lambda v: self._set(yaw_deg=v))
        self.sl_pitch.valueChanged.connect(lambda v: self._set(pitch_deg=self._pitch_from_display(v)))
        self.sl_speed.valueChanged.connect(lambda v: self._set(rotate_speed_deg=v))
        self.sl_sens.valueChanged.connect(lambda v: self._set(sensitivity=v))
        self.sl_dead.valueChanged.connect(lambda v: self._set(deadzone=v))
        self._row(form, "rot.yaw", self.sl_yaw)
        self._row(form, "rot.pitch", self.sl_pitch)
        self.lbl_pitch_hint = QLabel("")
        self.lbl_pitch_hint.setWordWrap(True)
        self.lbl_pitch_hint.setStyleSheet("color:#666;")
        form.addRow(self.lbl_pitch_hint)
        self._row(form, "rot.speed", self.sl_speed, "tip.speed")
        self._row(form, "rot.sens", self.sl_sens, "tip.sens")
        self._row(form, "rot.deadzone", self.sl_dead, "tip.deadzone")
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
        self._row(form, "rot.input", self.cmb_input, "tip.input")
        return box

    def _build_position(self) -> QGroupBox:
        box = self._group("group.position")
        lay = QVBoxLayout(box)
        form = QFormLayout()
        lay.addLayout(form)
        self.sl_dist = FloatSlider(1.0, 200.0, 28.7, 1, 0.5)
        self.sl_dist.valueChanged.connect(lambda v: self._set(distance=v))
        self._row(form, "pos.distance", self.sl_dist, "tip.distance")
        # how far the camera aims above/below the party anchor.  It decides whether the character
        # sits in the middle of the frame, so it is a first-class control, not an offset.
        self.sl_look = FloatSlider(-40.0, 40.0, -6.0, 2, 0.5)
        self.sl_look.valueChanged.connect(lambda v: self._set(look_height=v))
        self._row(form, "pos.look_height", self.sl_look, "tip.look_height")
        self.lbl_look_hint = QLabel("")
        self.lbl_look_hint.setWordWrap(True)
        self.lbl_look_hint.setStyleSheet("color:#666;")
        form.addRow(self.lbl_look_hint)

        # six world-space offsets: advanced, so folded away until asked for
        self.grp_offsets = self._group("group.offsets")
        self.grp_offsets.setCheckable(True)
        inner = QWidget()
        oform = QFormLayout(inner)
        oform.setContentsMargins(0, 0, 0, 0)
        box_lay = QVBoxLayout(self.grp_offsets)
        box_lay.addWidget(inner)
        self.off = []
        names = ["pos.cam_x", "pos.cam_y", "pos.cam_z", "pos.tgt_x", "pos.tgt_y", "pos.tgt_z"]
        for i, nm in enumerate(names):
            sl = FloatSlider(-80, 80, 0.0, 2, 0.25)
            if i < 3:
                sl.valueChanged.connect(lambda v, k=i: self._set_pos_offset(k, v))
            else:
                sl.valueChanged.connect(lambda v, k=i - 3: self._set_target_offset(k, v))
            sl.valueChanged.connect(lambda _v: self._update_offsets_title())
            self.off.append(sl)
            self._row(oform, nm, sl, "tip.cam_offset" if i < 3 else "tip.tgt_offset")
        self._offsets_inner = inner
        self.grp_offsets.setChecked(False)
        inner.setVisible(False)
        self.grp_offsets.toggled.connect(inner.setVisible)
        lay.addWidget(self.grp_offsets)
        lay.addStretch(1)               # the fold stays small when the neighbouring box is taller
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
        self.btn_fov_reset.clicked.connect(lambda _=False: self._reset_fov())
        self._row(form, "lens.fov", self.sl_fov, "tip.fov")
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
            self._reg(b, "text", "zoom.stage", n=n + 1)
            b.clicked.connect(lambda _c=False, n=n: self._on_zoom_stage(n))
            self.btn_zoom_stage.append(b)
            row.addWidget(b)
        form.addRow(self._label("zoom.stages"), row)
        self.chk_zoom_follow = self._chk("zoom.follow")
        self.chk_zoom_follow.setChecked(True)
        self.chk_zoom_follow.toggled.connect(self._on_zoom_follow)
        form.addRow(self.chk_zoom_follow)
        self.lbl_zoom_note = self._label("zoom.note")
        self.lbl_zoom_note.setWordWrap(True)
        self.lbl_zoom_note.setStyleSheet("color:#666;")
        form.addRow(self.lbl_zoom_note)
        return box

    def _build_debug(self) -> QGroupBox:
        box = self._group("group.debug")
        box.setCheckable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setContentsMargins(0, 0, 0, 0)
        self.lbl_cam = QLabel("-")
        self.lbl_aim = QLabel("-")
        self.lbl_player = QLabel("-")
        self.lbl_rate = QLabel("-")
        self.lbl_last = QLabel("-")
        for key, w in (("dbg.eye", self.lbl_cam), ("dbg.aim", self.lbl_aim),
                       ("dbg.player", self.lbl_player), ("dbg.rate", self.lbl_rate),
                       ("dbg.last", self.lbl_last)):
            self._row(form, key, w)
        lay = QVBoxLayout(box)
        lay.addWidget(inner)
        box.setChecked(False)
        inner.setVisible(False)
        box.toggled.connect(inner.setVisible)
        self.grp_debug = box
        return box

    # ---------------------------------------------------- enabling and game-specific limits
    def _set_usable(self, usable: bool) -> None:
        """Camera controls work only with a connected, supported game."""
        self._usable = usable
        for g in (self.grp_mode, self.grp_controls, self.grp_rotation, self.grp_position,
                  self.grp_lens, self.grp_zoom):
            g.setEnabled(usable)
        self.btn_patch_load.setEnabled(usable)
        self.btn_patch_remove.setEnabled(usable)
        if usable:
            self._apply_feature_gates()

    def _features(self) -> dict:
        return dict(getattr(self.adapter, "features", {}) or {})

    def _apply_feature_gates(self) -> None:
        """Disable the controls this game's adapter cannot use (and say why)."""
        f = self._features()
        free_ok = bool(f.get("free_camera", True))
        self.rb_free.setEnabled(free_ok)
        self.rb_free.setToolTip("" if free_ok else self._t("mode.free_unsupported"))
        for i, sl in enumerate(self.off):
            ok = bool(f.get("position_offsets", True)) if i < 3 else bool(f.get("target_offsets", True))
            sl.setEnabled(ok)
            sl.setToolTip("" if ok else self._t("tip.offsets_unsupported"))

    def _apply_adapter_limits(self, adapter, settings: CameraSettings) -> None:
        """Slider ranges and hints for this game (the adapter knows them; the GUI does not)."""
        lo, hi = getattr(adapter, "DISTANCE_RANGE", (1.0, 200.0))
        self.sl_dist.set_range(lo, hi)
        lo, hi = getattr(adapter, "LOOK_HEIGHT_RANGE", (-40.0, 40.0))
        self.sl_look.set_range(lo, hi)
        pitch_range = getattr(adapter, "PITCH_RANGE", None)
        if pitch_range is not None:
            # Adapter limits are authoritative, including over old settings/preset bounds.
            # Keep all persisted/runtime angles in the adapter's internal convention.
            lo, hi = pitch_range
            settings.pitch_min_deg, settings.pitch_max_deg = lo, hi
            settings.pitch_deg = max(lo, min(hi, settings.pitch_deg))
            self.app_settings.pitch_min_deg, self.app_settings.pitch_max_deg = lo, hi
            self.app_settings.pitch_deg = settings.pitch_deg
        else:
            lo, hi = min(settings.pitch_min_deg, -1.0), max(settings.pitch_max_deg, 1.0)
        sign = getattr(adapter, "PITCH_DISPLAY_SIGN", 1.0)
        self.sl_pitch.set_range(*sorted((lo * sign, hi * sign)))
        lo, hi = getattr(adapter, "OFFSET_RANGE", (-80.0, 80.0))
        for sl in self.off:
            sl.set_range(lo, hi)
        self._update_hints()
        self._apply_feature_gates()
        self._update_title()

    def _pitch_to_display(self, pitch: float) -> float:
        """Only the GUI changes convention; settings and presets retain internal pitch."""
        return pitch * getattr(self.adapter, "PITCH_DISPLAY_SIGN", 1.0)

    def _pitch_from_display(self, pitch: float) -> float:
        return pitch / getattr(self.adapter, "PITCH_DISPLAY_SIGN", 1.0)

    def _update_hints(self) -> None:
        ad = self.adapter
        look = getattr(ad, "LOOK_HEIGHT_POSITIVE_IS", None)
        pitch = getattr(ad, "PITCH_POSITIVE_IS", None)
        self.lbl_look_hint.setText(self._t("hint.look_up" if look == "up" else "hint.look_down") if look else "")
        self.lbl_pitch_hint.setText(self._t("hint.pitch_below" if pitch == "below" else "hint.pitch_above") if pitch else "")

    def _update_offsets_title(self) -> None:
        used = any(abs(sl.value()) > 1e-6 for sl in self.off)
        self.grp_offsets.setTitle(self._t("group.offsets_set" if used else "group.offsets"))

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
        self.app_settings.zoom_follow = self.chk_zoom_follow.isChecked()
        self.store.put(self.app_settings)

    # ------------------------------------------------------------ lifecycle
    def _reconnect(self, restore: bool = True) -> None:
        """(Re)connect and pick the adapter for the game that is running now.

        ``restore`` False is for a game that has changed: the old runtime is dropped without
        writing anything (see _teardown).
        """
        self._teardown(restore)
        self._conn_problem = None
        self._set_usable(False)
        try:
            backend = PineBackend()
            backend.connect()
            guard = GuardedBackend(backend)
            adapter_cls = ADAPTER_BY_GAME_ID.get(backend.game_id().strip().upper(), FFX2Adapter)
            adapter = adapter_cls(guard)
            info = adapter.identify()
        except Exception as exc:  # noqa: BLE001
            log.info("connect failed: %s", exc)
            self.lbl_pcsx2.setText(self._t("state.disconnected"))
            self.lbl_runtime.setText(self._t("state.stopped"))
            self._conn_problem = ("notice.no_game", "warn", {})
            self._update_title()
            return
        # arm the guard for exactly the game that was identified; an unsupported game stays read-only,
        # and is still watched so that starting a supported game later is noticed
        guard.bind(info.game_id, info.crc, writable=info.matched)
        self.backend = backend
        self.guard = guard
        self.adapter = adapter
        self._link_ok = True
        self.lbl_pcsx2.setText(self._t("state.connected"))
        self.lbl_game.setText(info.title or "-")
        self.lbl_serial.setText(f"{info.game_id} / {info.crc}")
        self.lbl_adapter.setText(adapter.name if info.matched else "-")
        self._update_title()
        if not info.matched:
            self._conn_problem = ("notice.unsupported", "error", {"gid": info.game_id, "crc": info.crc})
            return
        # settings are kept per game, so one game's values never reach another; a game seen for the
        # first time starts from the adapter's own stock framing
        gid = info.game_id.strip().upper()
        self.app_settings = self.store.get(gid)
        defaults = getattr(adapter, "default_settings", None)
        if callable(defaults) and gid not in self.store.data:
            for key, value in defaults().items():
                setattr(self.app_settings, key, value)
        # the mod never switches itself on: whatever mode was saved, the window starts in Original
        self.app_settings.mode = MODE_ORIGINAL
        settings = CameraSettings(**{k: v for k, v in self.app_settings.__dict__.items()
                                     if k in CameraSettings().__dict__})
        self._apply_adapter_limits(adapter, settings)
        self.runtime = CameraRuntime(adapter, settings)
        self.runtime.capture_original_fov()
        self._sync_widgets_from(settings)
        self._sync_mode_radios(MODE_ORIGINAL)
        self.chk_zoom_follow.blockSignals(True)
        self.chk_zoom_follow.setChecked(bool(getattr(self.app_settings, "zoom_follow", True)))
        self.chk_zoom_follow.blockSignals(False)
        self._zoom_last = None
        self.runtime.start()
        self._setup_input()
        self._refresh_presets()
        self._set_usable(True)
        self._status(self._t("status.connected"))

    def _sync_mode_radios(self, mode: str) -> None:
        """Select the radio that matches ``mode`` without firing _on_mode."""
        for rb, m in ((self.rb_original, MODE_ORIGINAL), (self.rb_orbit, MODE_ORBIT),
                      (self.rb_free, MODE_FREE)):
            blocked = rb.blockSignals(True)
            rb.setChecked(m == mode)
            rb.blockSignals(blocked)

    def _teardown(self, restore: bool = True) -> None:
        """Stop the runtime and close the link.

        ``restore`` hands the camera back to the game, which writes the game's addresses.  That is
        only done after the guard has confirmed the running game is still the one the runtime was
        made for (checked here too, because the poller may not have noticed a switch yet); otherwise
        the runtime is abandoned without a single write.  Fail closed: anything but a positive
        ``SAME`` (changed, unknown, unreachable, no guard, already revoked) means no restore.
        """
        guard, be = self.guard, self.backend
        restore = bool(restore and guard is not None and be is not None and be.available
                       and not guard.revoked and guard.verify() == SAME)
        if guard is not None and not restore:
            guard.revoke("teardown without restore")
        if self.pump:
            self.pump.stop()
            self.pump = None
        if self.runtime:
            if restore:
                # stop first: a tick still in flight could switch the orbit back on
                # after restore() has handed the projection to the area
                self.runtime.stop()
                self.runtime.restore()
            else:
                self.runtime.abandon()
            self.runtime = None
        if self.backend:
            self.backend.close()
            self.backend = None
        self.guard = None
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

    @safe_slot
    def _on_mode(self, mode: str) -> None:
        if self.runtime is None or self._updating:
            return
        self._updating = True
        try:
            self._sync_mode_radios(mode)
        finally:
            self._updating = False
        if mode == MODE_ORIGINAL:
            self.runtime.restore()
            return
        if mode == MODE_ORBIT:
            # "move onto the character first, then rotate": re-centre whenever the mod is
            # (re)enabled so a field whose own camera does not look at the party starts centred
            if self.runtime.stats.mode != MODE_ORBIT or self.chk_auto_center.isChecked():
                self.runtime.center_on_target()
                self._sync_widgets_from(self.runtime.snapshot())
        if mode == MODE_FREE and self.runtime.stats.applied_pose:
            eye, tgt = self.runtime.stats.applied_pose
            self.runtime.settings.free_eye = list(eye)
            self.runtime.settings.free_target = list(tgt)
        self.runtime.settings.mode = mode

    @safe_slot
    def _center(self) -> None:
        if self.runtime is None:
            return
        if self.runtime.center_on_target():
            self._sync_widgets_from(self.runtime.snapshot())
            self.runtime.settings.mode = MODE_ORBIT
            self._sync_mode_radios(MODE_ORBIT)
            self._status(self._t("status.centered"))
        else:
            self._flash(self._t("status.center_failed", err=self.runtime.stats.last_error), "warn")

    @safe_slot
    def _reset_params(self) -> None:
        if self.runtime is None:
            return
        self.runtime.sync_to_game()
        st = self.runtime.settings
        st.pos_offset = [0.0, 0.0, 0.0]
        st.target_offset = [0.0, 0.0, 0.0]
        self._sync_widgets_from(st)

    @safe_slot
    def _restore(self) -> None:
        if self.runtime is None:
            return
        self._on_mode(MODE_ORIGINAL)
        self._status(self._t("status.restored"))

    @safe_slot
    def _on_patch(self, load: bool) -> None:
        """Load or remove the game patch by hand.  The next camera mode change hands it back."""
        if self.runtime is None:
            self._status(self._t("status.patch_need_connection"))
            return
        self.runtime.set_patch_override(load)
        if not self.runtime.running:
            self.runtime.start()
        self._status(self._t("status.patch_loaded" if load else "status.patch_removed"))

    def _on_fov(self, value: float) -> None:
        if self.runtime is None or self._updating:
            return
        self.runtime.settings.fov_deg = value
        self.app_settings.fov_deg = value
        if self.chk_fov.isChecked():
            self.runtime.settings.use_fov = True
        self._persist_later()

    @safe_slot
    def _on_fov_enable(self, on: bool) -> None:
        if self.runtime is None or self._updating:
            return
        self.runtime.settings.use_fov = on
        if not on:
            self.runtime.adapter.restore_fov()

    @safe_slot
    def _reset_fov(self) -> None:
        if self.runtime is None:
            return
        self.runtime.adapter.restore_fov()
        self.runtime.settings.use_fov = False
        self._updating = True
        try:
            self.chk_fov.setChecked(False)
        finally:
            self._updating = False
        self.sl_fov.set_value(self.runtime.adapter.read_fov_deg())

    @safe_slot
    def _on_zoom_stage(self, stage: int) -> None:
        """Orbit mode: use the distance of that native stage and keep the game's stage in step."""
        ad = self.adapter
        if self.runtime is None or not hasattr(ad, "set_zoom_stage"):
            return
        dist = ad.set_zoom_stage(stage)
        if dist is not None and self.runtime.settings.mode != MODE_ORIGINAL:
            self._set(distance=dist)
            self.sl_dist.set_value(dist)

    def _on_zoom_follow(self, _on: bool) -> None:
        self._persist_later()

    def _refresh_native_zoom(self, data: dict) -> None:
        ad = self.adapter
        has = ad is not None and bool(getattr(ad, "features", {}).get("native_zoom"))
        if self.grp_zoom.isVisibleTo(self) != has:
            self.grp_zoom.setVisible(has)
        if not has or self.runtime is None:
            return
        stage, native = data.get("zoom_stage"), data.get("zoom_native")
        if stage is None:
            self._put(self.lbl_zoom_now, self._t("zoom.none"))
            return
        self._put(self.lbl_zoom_now, self._t("zoom.current", n=stage + 1, d=native or 0.0))
        orbit = self.runtime.settings.mode != MODE_ORIGINAL
        tip = self._t("tip.zoom_stage" if orbit else "tip.zoom_stage_off")
        for b in self.btn_zoom_stage:
            if b.isEnabled() != orbit:
                b.setEnabled(orbit)
            if b.toolTip() != tip:
                b.setToolTip(tip)
        # R1 / the game's zoom steps the orbit distance when "follow" is on
        if (orbit and self.chk_zoom_follow.isChecked() and self._zoom_last is not None
                and stage != self._zoom_last):
            dist = ad.stage_distance(stage)
            self._set(distance=dist)
            self.sl_dist.set_value(dist)
        self._zoom_last = stage

    # ----------------------------------------------------------------- presets
    @safe_slot
    def _save_preset(self) -> None:
        if self.runtime is None:
            return
        name, ok = _prompt(self, self._t("dlg.preset_title"), self._t("dlg.preset_label"), "orbit-default")
        if not ok or not name.strip():
            return
        name = name.strip()
        if self.presets.exists(name):
            answer = QMessageBox.question(self, self._t("dlg.overwrite_title"),
                                          self._t("dlg.overwrite_text", name=name))
            if answer != QMessageBox.Yes:
                return
        self._persist()
        path = self.presets.save(name, self.app_settings)
        self._refresh_presets()
        self._status(self._t("status.preset_saved", name=path.name))

    @safe_slot
    def _load_preset(self) -> None:
        """Apply a preset's values.  The camera mode is never changed by a preset."""
        if self.runtime is None:
            return
        name = self.cmb_preset.currentText()
        if not name:
            return
        st = self.presets.load(name, self.app_settings.game_id)
        if st is None:
            self._status(self._t("status.preset_missing", name=name))
            return
        keep = {"mode", "game_id", "version", "language", "input_source"}
        values = {k: v for k, v in st.__dict__.items() if k in CameraSettings().__dict__ and k not in keep}
        for k, v in values.items():
            setattr(self.runtime.settings, k, list(v) if isinstance(v, list) else v)
            if hasattr(self.app_settings, k):
                setattr(self.app_settings, k, list(v) if isinstance(v, list) else v)
        self._apply_adapter_limits(self.adapter, self.runtime.settings)
        self._sync_widgets_from(self.runtime.settings)
        self._persist_later()
        self._status(self._t("status.preset_loaded", name=name))

    def _refresh_presets(self) -> None:
        gid = self.app_settings.game_id
        self.cmb_preset.clear()
        self.cmb_preset.addItems(self.presets.list(gid))

    def _sync_widgets_from(self, st) -> None:
        self._updating = True
        try:
            self.sl_yaw.set_value(st.yaw_deg)
            self.sl_pitch.set_value(self._pitch_to_display(st.pitch_deg))
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
        finally:
            self._updating = False
        self._update_offsets_title()

    # ------------------------------------------------------------ notices
    def _flash(self, text: str, level: str = "info", seconds: float = 6.0) -> None:
        """A message for a few seconds in the notice bar and the status bar."""
        self._flash_msg = (text, level, time.monotonic() + seconds)
        self._status(text)

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)

    def _compute_notice(self, data: dict) -> tuple[str, str]:
        """The one message that matters now, in plain language: (text, level) or ('', '')."""
        if self._flash_msg and time.monotonic() < self._flash_msg[2]:
            return self._flash_msg[0], self._flash_msg[1]
        if self._conn_problem:
            key, level, args = self._conn_problem
            return self._t(key, **args), level
        if self.runtime is None:
            return self._t("notice.no_game"), "warn"
        if not data["link"]:
            return self._t("notice.lost"), "error"
        if data["patch"] == "unknown":
            return self._t("notice.patch_unknown"), "warn"
        err = self.runtime.stats.last_error
        if err and self.runtime.settings.mode != MODE_ORIGINAL:
            if err.startswith("scene guard"):
                return self._t("notice.not_field"), "info"
            return err, "warn"
        return "", ""

    # -------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        guard = self.guard
        if guard is not None and guard.revoked:
            self._on_game_changed()
            return
        data = self.poller.data
        if self.runtime is not None:
            self._show_link(data["link"])
        usable = self.runtime is not None and self._link_ok
        if usable != self._usable:
            self._set_usable(usable)
        text, level = self._compute_notice(data)
        if text:
            self._put(self.lbl_notice, text)
            self._style(self.lbl_notice, NOTICE_STYLE.get(level, NOTICE_STYLE["info"]))
            if not self.lbl_notice.isVisibleTo(self):
                self.lbl_notice.setVisible(True)
        elif self.lbl_notice.isVisibleTo(self):
            self.lbl_notice.setVisible(False)
        if self.runtime is None:
            self._put(self.lbl_runtime, self._t("state.stopped"))
            self._put(self.lbl_patch, "-")
            return
        st = self.runtime.stats
        mode = self.runtime.settings.mode
        self._put(self.lbl_runtime,
                  f"{self._t('state.running')} ({self._mode_name(mode)})"
                  if mode != MODE_ORIGINAL else self._t("state.stopped_original"))
        # PINE is read by the status poller thread; this timer only draws its last result, so a
        # closed or killed PCSX2 can never block the window.
        if data["link"] and data["fov"] is not None:
            key, style = PATCH_TEXT.get(data["patch"], ("patch.missing", "color:#a85b00;"))
            self._put(self.lbl_patch, self._t(key))
            self._style(self.lbl_patch, style)
            self._refresh_native_zoom(data)
            self._put(self.lbl_fov_now, self._t("lens.current", fov=data["fov"], scale=data["scale"]))
        else:
            self._put(self.lbl_patch, self._t("patch.missing"))
            self._style(self.lbl_patch, "color:#a85b00;")
            self._put(self.lbl_fov_now, self._t("lens.current_none"))
        if st.applied_pose:
            e, t = st.applied_pose
            self._put(self.lbl_cam, f"({e[0]:.2f}, {e[1]:.2f}, {e[2]:.2f})")
            self._put(self.lbl_aim, f"({t[0]:.2f}, {t[1]:.2f}, {t[2]:.2f})")
        if st.player:
            p = st.player
            self._put(self.lbl_player, f"({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})")
        self._put(self.lbl_rate, self._t("dbg.rate_value", n=st.writes_per_sec))
        self._put(self.lbl_last, time.strftime("%H:%M:%S") if st.total_writes else "-")
        # mirror runtime-driven values back into the widgets while the stick moves
        if mode != MODE_ORIGINAL and not self._updating:
            cur = self.runtime.settings
            self._updating = True
            try:
                if abs(self.sl_yaw.value() - cur.yaw_deg) > 0.05:
                    self.sl_yaw.set_value(cur.yaw_deg)
                pitch = self._pitch_to_display(cur.pitch_deg)
                if abs(self.sl_pitch.value() - pitch) > 0.05:
                    self.sl_pitch.set_value(pitch)
                if abs(self.sl_dist.value() - cur.distance) > 0.05:
                    self.sl_dist.set_value(cur.distance)
            finally:
                self._updating = False

    def _show_link(self, ok: bool) -> None:
        """Show when PCSX2 goes away or comes back.

        Whether it is still the same game is the guard's business: the poller verifies the serial and
        CRC on every poll, and writes stay refused until it has (PineBackend.epoch).
        """
        if ok == self._link_ok:
            return
        self._link_ok = ok
        if not ok:
            self.lbl_pcsx2.setText(self._t("state.disconnected"))
            self._status(self._t("status.pcsx2_lost"))
            return
        self.lbl_pcsx2.setText(self._t("state.connected"))
        self._status(self._t("status.pcsx2_back"))

    def _on_game_changed(self) -> None:
        """The running game is not the one the adapter was made for: drop it and choose again.

        Nothing is restored: the old game's addresses mean something else in the new game.
        """
        log.warning("game changed (%s); dropping the adapter without restoring",
                    self.guard.revoke_reason if self.guard else "?")
        if self.runtime is not None:
            self._persist()             # the old game's settings, before the window is re-armed
        self._reconnect(restore=False)
        self._status(self._t("status.game_changed"))

    # ------------------------------------------------------------ window state
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # the first focusable widget scrolls itself into view; always start at the top
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(0))

    def _restore_geometry(self) -> None:
        try:
            geo = QSettings("PS2UniversalCamera", "controller").value("geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            try:
                QSettings("PS2UniversalCamera", "controller").setValue("geometry", self.saveGeometry())
            except Exception:  # noqa: BLE001
                pass
            self.poller.stop()
            self._persist()
            self._teardown()
        finally:
            event.accept()


def _prompt(parent, title, label, default):
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getText(parent, title, label, QLineEdit.Normal, default)


def _setup_logging() -> None:
    """Errors go to a file next to the settings (a double-clicked launcher has no console to read)."""
    try:
        from logging.handlers import RotatingFileHandler
        home = _config_home()
        home.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(home / "gui.log", maxBytes=200_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("ps2cam").addHandler(handler)
        logging.getLogger("ps2cam").setLevel(logging.INFO)

        def hook(exc_type, exc, tb):
            log.error("uncaught exception", exc_info=(exc_type, exc, tb))
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = hook
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    # --screenshot PATH renders the window and exits; used to produce evidence images.
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
    _setup_logging()
    # PCSX2's PINE serves one client at a time: a second window would make both time out
    lock = None
    if not shot:
        lock = QLockFile(str(_config_home() / "gui.lock"))
        _config_home().mkdir(parents=True, exist_ok=True)
        if not lock.tryLock(200):
            QMessageBox.warning(None, tr("dlg.single_title"), tr("dlg.single_text"))
            return 3
    win = MainWindow()
    win.show()
    if shot:
        def _grab() -> None:
            try:
                win.grab().save(shot)
                print(f"PS2UniversalCamera: wrote {shot}")
            finally:
                app.quit()

        QTimer.singleShot(2500, _grab)
    code = app.exec()
    if lock is not None:
        lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
