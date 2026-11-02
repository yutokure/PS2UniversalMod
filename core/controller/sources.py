"""Input abstraction for the right-stick camera.

Three concrete sources are provided because the right-stick path differs
between automated tests and real play:

* ``XInputSource``   - the physical pad, read directly through XInput.  This is
  the real gameplay path: PCSX2 does not need to cooperate at all.
* ``KeyboardSource`` - arrow / IJKL keys, for users without a pad.
* ``ScriptedSource`` - programmatic values used by the automated end-to-end
  tests (and by the MCP-driven input bridge, which cannot be seen by XInput).

All expose ``poll() -> (x, y)`` in the range [-1, 1] plus a ``name``.
"""
from __future__ import annotations

import ctypes
import math
import threading
import time
from ctypes import wintypes


class InputSource:
    name = "none"

    def poll(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def close(self) -> None:
        pass


class NullSource(InputSource):
    name = "none"


class ScriptedSource(InputSource):
    """Values set from code; used by tests and by the MCP input bridge."""

    name = "scripted"

    def __init__(self) -> None:
        self._v = (0.0, 0.0)
        self._lock = threading.Lock()

    def set(self, x: float, y: float) -> None:
        with self._lock:
            self._v = (x, y)

    def poll(self) -> tuple[float, float]:
        with self._lock:
            return self._v


class _XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", _XINPUT_GAMEPAD)]


class XInputSource(InputSource):
    """Right stick of the first connected XInput pad.

    XInput has four player slots and a pad is not always in slot 0: a pad that
    was connected after another one, or one behind a virtual bus, can sit in
    slot 1.  Reading only slot 0 made the stick silently dead, so the slot is
    found at run time.  Pass ``index`` to pin a slot instead.
    """

    name = "xinput"
    SLOTS = 4

    def __init__(self, index: int | None = None) -> None:
        self.index = index
        #: slot that answered the last poll, None while no pad is connected
        self.active_slot: int | None = None
        self._dll = None
        self.dll_name = ""
        for dll in ("XInput1_4.dll", "XInput1_3.dll", "XInput9_1_0.dll"):
            try:
                self._dll = ctypes.WinDLL(dll)
                self.dll_name = dll
                break
            except OSError:
                continue
        if self._dll is not None:
            self._dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(_XINPUT_STATE)]
            self._dll.XInputGetState.restype = wintypes.DWORD

    @property
    def available(self) -> bool:
        return self._dll is not None

    def _slots(self) -> tuple[int, ...]:
        if self.index is not None:
            return (self.index,)
        if self.active_slot is None:
            return tuple(range(self.SLOTS))
        # try the last working slot first, then the rest in order
        others = tuple(i for i in range(self.SLOTS) if i != self.active_slot)
        return (self.active_slot,) + others

    def _read_slot(self, slot: int):
        """Return the gamepad struct for ``slot`` or None when it is not connected."""
        st = _XINPUT_STATE()
        if self._dll.XInputGetState(slot, ctypes.byref(st)) != 0:
            return None
        return st.Gamepad

    def connected(self) -> bool:
        if self._dll is None:
            return False
        return any(self._read_slot(slot) is not None for slot in self._slots())

    def poll(self) -> tuple[float, float]:
        if self._dll is None:
            self.active_slot = None
            return (0.0, 0.0)
        for slot in self._slots():
            g = self._read_slot(slot)
            if g is None:
                continue
            self.active_slot = slot
            x = g.sThumbRX / 32767.0
            y = g.sThumbRY / 32767.0
            return (max(-1.0, x), max(-1.0, y))
        self.active_slot = None
        return (0.0, 0.0)


def _foreground_process_name() -> str:
    """Lower-case exe name of the window that has the keyboard focus ('' when unknown)."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
    return ""


def keyboard_focus_ok(name: str, own_exe: str | None = None) -> bool:
    """True when the key presses are meant for the game or for this program.

    Arrow keys are global state: without this check the camera would turn whenever an arrow key is
    pressed in *any* window (a text editor, a browser).  The game window (PCSX2) and the controller
    itself count; an unknown foreground window counts as "not for us".
    """
    if not name:
        return False
    own = (own_exe or "").lower()
    return name.startswith("pcsx2") or name in ("python.exe", "pythonw.exe") or (own != "" and name == own)


class KeyboardSource(InputSource):
    """Right-stick emulation from the keyboard (arrows by default).

    The keys are read only while PCSX2 or this program is the foreground window
    (``foreground_only=True``); pass False to read them regardless (tests, headless use).
    """

    name = "keyboard"

    VK = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}

    def __init__(self, foreground_only: bool = True) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.foreground_only = foreground_only
        self._focus_checked = 0.0
        self._focus_ok = True

    def _focused(self) -> bool:
        if not self.foreground_only:
            return True
        now = time.monotonic()
        if now - self._focus_checked >= 0.1:            # the pump polls at 120 Hz; look at 10 Hz
            self._focus_checked = now
            self._focus_ok = keyboard_focus_ok(_foreground_process_name())
        return self._focus_ok

    def poll(self) -> tuple[float, float]:
        if not self._focused():
            return (0.0, 0.0)

        def down(vk: int) -> bool:
            return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)

        x = float(down(self.VK["right"])) - float(down(self.VK["left"]))
        y = float(down(self.VK["up"])) - float(down(self.VK["down"]))
        return (x, y)


class CompositeSource(InputSource):
    """First source that reports a non-zero deflection wins."""

    def __init__(self, sources) -> None:
        self.sources = list(sources)
        self.name = "+".join(s.name for s in self.sources)

    def poll(self) -> tuple[float, float]:
        for s in self.sources:
            x, y = s.poll()
            if abs(x) > 1e-3 or abs(y) > 1e-3:
                return (x, y)
        return (0.0, 0.0)

    def close(self) -> None:
        for s in self.sources:
            s.close()


class InputPump:
    """Polls the active source at a fixed rate and feeds the runtime."""

    def __init__(self, runtime, source: InputSource, hz: float = 120.0) -> None:
        self.runtime = runtime
        self.source = source
        self.hz = hz
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.last = (0.0, 0.0)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        period = 1.0 / self.hz
        while not self._stop.is_set():
            try:
                x, y = self.source.poll()
            except Exception:  # noqa: BLE001
                x, y = 0.0, 0.0
            self.last = (x, y)
            self.runtime.set_stick(x, y)
            time.sleep(period)


def deadzone_apply(x: float, y: float, dz: float) -> tuple[float, float]:
    mag = math.hypot(x, y)
    if mag <= dz or mag == 0.0:
        return (0.0, 0.0)
    scale = (mag - dz) / (1.0 - dz)
    return (x / mag * scale, y / mag * scale)
