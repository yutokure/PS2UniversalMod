"""Does the GUI freeze when PCSX2 is killed?  (offscreen GUI, needs PCSX2 with a supported game)

    python tools/gui_freeze_check.py [--kill]

Starts the real MainWindow, runs a 20 ms heartbeat on the GUI thread, then (with ``--kill``) ends
the PCSX2 process abruptly and watches for 6 s.  The longest gap between two heartbeats is the
longest time the window was unresponsive.  Then the window is closed and the close time measured.
Passing means: no stall above 0.5 s, the window reports the lost link, and closing takes under 3 s.

With ``--relaunch`` (after ``--kill``) PCSX2 is started again with the same disc and the window
must notice that it is back and read the game again without being restarted.

Without ``--kill`` the same measurement runs against the live emulator (baseline).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import subprocess  # noqa: E402

import psutil  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.camera_controller.app import MODE_ORBIT, MainWindow  # noqa: E402

MAX_STALL_S = 0.5
MAX_CLOSE_S = 3.0


def kill_pcsx2() -> int:
    n = 0
    for p in psutil.process_iter(["name"]):
        if "pcsx2" in (p.info.get("name") or "").lower():
            p.kill()
            n += 1
    return n


def main() -> int:
    kill = "--kill" in sys.argv
    app = QApplication(sys.argv[:1])
    win = MainWindow()
    win.show()
    last = [time.monotonic()]
    worst = [0.0]

    def beat() -> None:
        now = time.monotonic()
        worst[0] = max(worst[0], now - last[0])
        last[0] = now

    hb = QTimer()
    hb.timeout.connect(beat)
    hb.start(20)

    def spin(secs: float) -> None:
        end = time.monotonic() + secs
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)

    spin(1.5)
    connected = win.runtime is not None
    print("connected:", connected, "|", win.lbl_serial.text())
    if connected:
        win._on_mode(MODE_ORBIT)
    spin(1.0)
    worst[0] = 0.0
    if kill:
        print("killed PCSX2 processes:", kill_pcsx2())
    spin(6.0)
    stall = worst[0]
    lost_shown = getattr(win, "_link_ok", None) is False or "PCSX2" in (win.statusBar().currentMessage() or "") or not kill
    print(f"longest GUI stall: {stall:.3f} s")
    print("link flagged lost:", getattr(win, "_link_ok", None) is False)
    lost_flagged = getattr(win, "_link_ok", None) is False
    relaunch_ok = True
    if kill and "--relaunch" in sys.argv:
        from core.config import paths
        exe = paths.pcsx2_dir() / "pcsx2-qt.exe"
        iso = paths.game_dir() / "suikoden5.iso"
        env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}   # not the offscreen test platform
        subprocess.Popen([str(exe), str(iso)], cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        t1 = time.monotonic()
        worst[0] = 0.0
        relaunch_ok = False
        while time.monotonic() - t1 < 120.0:
            spin(0.5)
            d = win.poller.data
            if getattr(win, "_link_ok", None) and d["link"] and "SLPM-66286" in win.lbl_serial.text():
                relaunch_ok = True
                break
        print(f"window noticed the new PCSX2: {relaunch_ok} after {time.monotonic() - t1:.1f} s; "
              f"longest stall meanwhile {worst[0]:.3f} s; status: {win.lbl_pcsx2.text()}")
        stall = max(stall, worst[0])
    t0 = time.monotonic()
    win.close()
    spin(0.2)
    close_s = time.monotonic() - t0
    print(f"close took {close_s:.2f} s")
    ok = relaunch_ok and connected and stall < MAX_STALL_S and close_s < MAX_CLOSE_S and (lost_flagged or not kill)
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
