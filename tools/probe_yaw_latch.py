"""Does the camera *latch* the yaw/pitch we write, or only sample it?

Hold the angle offset for a moment, stop writing, then keep observing.  If the
rotated view persists the game cached it and only needs an occasional trigger;
if it snaps back the game keeps re-deriving from its own state.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

from PIL import Image  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "yaw_latch"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    cur = b.read_floats(0x3403B0, 4)
    val = cur[:]
    val[0] = cur[0] + 0.6
    stop = threading.Event()

    def wr():
        while not stop.is_set():
            b.write_float_block(0x3403B0, val)

    th = threading.Thread(target=wr, daemon=True)
    th.start()
    rot_seen = 0
    t0 = time.time()
    while time.time() - t0 < 2.5:
        s = diffscore(base, w.grab())
        if s["frac_gt16"] > 0.15:
            rot_seen += 1
        time.sleep(0.2)
    stop.set()
    th.join(timeout=1)
    print(f"during hold: rotated samples {rot_seen}")
    time.sleep(0.3)
    after = []
    for i in range(8):
        s = diffscore(base, w.grab())
        after.append(round(s["frac_gt16"], 3))
        if i == 3:
            Image.fromarray(w.grab().astype("uint8")).save(OUT / "after_release.png")
        time.sleep(0.3)
    print("after release:", after)
    print("angle now", [round(v, 4) for v in b.read_floats(0x3403B0, 4)])
    # restore the original angle
    b.write_float_block(0x3403B0, cur)
    time.sleep(0.4)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
