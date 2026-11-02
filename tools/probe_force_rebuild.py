"""Force a camera rebuild and see whether the angle we wrote gets applied.

Hypothesis: the view direction is only recomputed when the game's camera
controller considers the camera "dirty".  The eye offset at 0x3403E0 is applied
by the game every frame, so wiggling it by a sub-pixel amount should force a
full camera pass -- and that pass may pick up the yaw/pitch we wrote.
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

OUT = ROOT / "reports" / "force_rebuild"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    cur_ang = b.read_floats(0x3403B0, 4)
    yaw_val = cur_ang[:]
    yaw_val[0] = cur_ang[0] + 0.6
    print("base ang", [round(v, 4) for v in cur_ang])
    stop = threading.Event()
    state = {"n": 0}

    def wr():
        i = 0
        while not stop.is_set():
            b.write_float_block(0x3403B0, yaw_val)
            # wiggle the additive eye offset to force the game's camera pass
            j = 0.02 if (i % 2 == 0) else -0.02
            b.write_float_block(0x3403E0, [j, 0.0, 0.0])
            i += 1
            state["n"] = i

    th = threading.Thread(target=wr, daemon=True)
    th.start()
    scores = []
    try:
        time.sleep(0.8)
        for k in range(8):
            shot = w.grab()
            s = diffscore(base, shot)
            scores.append(round(s["frac_gt16"], 3))
            Image.fromarray(shot.astype("uint8")).save(OUT / f"f{k}.png")
            print(f"  frame {k}: frac={s['frac_gt16']:.3f} ang={round(b.read_floats(0x3403B0,1)[0],4)}")
            time.sleep(0.3)
    finally:
        stop.set()
        th.join(timeout=2)
        time.sleep(0.3)
        b.write_float_block(0x3403E0, [0.0, 0.0, 0.0])
        b.write_float_block(0x3403B0, cur_ang)
        b.close()
    rot = sum(1 for s in scores if s > 0.15)
    print(f"iters={state['n']} rotated={rot}/{len(scores)}")
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
