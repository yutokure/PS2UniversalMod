"""Live check of the game-identity guard: PCSX2 comes back running a different game.

    python tools/game_switch_check.py

Starts PCSX2 with Suikoden V, opens the real (offscreen) GUI window, switches the orbit on, then ends
PCSX2 abruptly and starts it again with Shining Force Neo.  The window must

* never write to a Suikoden V address after PCSX2 was ended (no restore into the new game),
* pick the Shining Force Neo adapter by itself,
* stay responsive (longest GUI stall below 0.5 s).

PCSX2 is started from the lab folders configured in ``core.config.paths``; disc images and
savestates are only read, never modified.  Needs the lab setup (PCSX2 with PINE enabled, both discs).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.shiningforceneo import memory_map as sf_mm  # noqa: E402
from adapters.suikoden5 import memory_map as su_mm  # noqa: E402
from core.config import paths  # noqa: E402
from core.memory_backend import pine_backend  # noqa: E402
from gui.camera_controller.app import MODE_ORBIT, MainWindow  # noqa: E402

FIRST_ISO, SECOND_ISO = "suikoden5.iso", "シャイニングフォースネオ.ISO"
SU_ADDRS = {su_mm.CAM_HOOK, su_mm.CAM_HOOK + 4, su_mm.ZOOM_HOOK, su_mm.ZOOM_HOOK + 4}


def su_address(a: int) -> bool:
    return a in SU_ADDRS or su_mm.MOD_BLOCK <= a < su_mm.CAVE_END


def kill_pcsx2() -> None:
    for p in psutil.process_iter(["name"]):
        if "pcsx2" in (p.info.get("name") or "").lower():
            p.kill()


def launch(iso: str, state: Path | None = None) -> None:
    """Start PCSX2 with a disc (and optionally a savestate, which is only read)."""
    exe = paths.pcsx2_dir() / "pcsx2-qt.exe"
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    args = [str(exe)] + (["-statefile", str(state)] if state else []) + ["--", str(paths.game_dir() / iso)]
    subprocess.Popen(args, cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def main() -> int:
    log: list[tuple[float, int]] = []
    orig = pine_backend.PineBackend.write_u32

    def logged(self, addr, value):
        log.append((time.monotonic(), addr & 0xFFFFFFFF))
        return orig(self, addr, value)
    pine_backend.PineBackend.write_u32 = logged

    kill_pcsx2()
    time.sleep(1.0)                      # before the window exists
    launch(FIRST_ISO, paths.savestate_dir() / "suikoden5" / "base.p2s")
    app = QApplication(sys.argv[:1])
    last, worst = [time.monotonic()], [0.0]

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

    # wait for PCSX2 + PINE, then connect
    deadline = time.monotonic() + 120
    win = MainWindow()
    win.show()
    while time.monotonic() < deadline and win.runtime is None:
        spin(2.0)
        win._reconnect()
    print("first game:", win.lbl_serial.text(), "|", type(win.adapter).__name__)
    if win.runtime is None:
        print("RESULT FAIL (never connected)")
        return 1
    win._on_mode(MODE_ORBIT)
    wait = time.monotonic() + 90
    while time.monotonic() < wait and not any(su_address(a) for _, a in log):
        spin(0.5)
    spin(2.0)
    wrote = sum(1 for _, a in log if su_address(a))
    print(f"Suikoden V addresses written while it ran: {wrote}")

    # --- PCSX2 ends, comes back with another game --------------------------------------------------
    worst[0] = 0.0
    t_kill = time.monotonic()
    kill_pcsx2()
    launch(SECOND_ISO)
    deadline = time.monotonic() + 150
    switched = False
    while time.monotonic() < deadline:
        spin(0.5)
        if type(win.adapter).__name__ == "SFNeoAdapter" and win.runtime is not None:
            switched = True
            break
    stall = worst[0]
    late = [a for t, a in log if t > t_kill and su_address(a)]
    print(f"new adapter chosen: {switched} ({type(win.adapter).__name__}) after {time.monotonic() - t_kill:.1f} s;"
          f" serial {win.lbl_serial.text()}")
    print(f"Suikoden V addresses written after PCSX2 ended: {len(late)}  (must be 0)")
    print(f"longest GUI stall: {stall:.3f} s")
    t0 = time.monotonic()
    win.close()
    spin(0.2)
    close_s = time.monotonic() - t0
    print(f"close took {close_s:.2f} s")
    kill_pcsx2()
    time.sleep(0.5)
    ok = switched and not late and stall < 0.5 and close_s < 3.0 and wrote > 0
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
