"""Re-test the render look-at control, carefully.

We verified that the rendered forward equals normalize(look - eye) where
look = 0x53ADD0 and eye = 0x340360.  That means rotating `look` around the eye
must rotate the view.  An earlier attempt reported "holds but no effect"; this
run re-checks with the VM state verified, a longer hold, and a large angle so
there is no chance of misreading a small delta.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths  # noqa: F401,E402  (repo + lab scripts on sys.path)

from PIL import Image  # noqa: E402

from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402

OUT = ROOT / "reports" / "look_retest"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    b = PineBackend()
    b.connect()
    print("vm status", b.status(), "(0=running)")
    w = Window()
    eye = b.read_floats(0x340360, 3)
    look = b.read_floats(0x53ADD0, 3)
    fwd = b.read_floats(0x53ADA0, 3)
    d = [look[i] - eye[i] for i in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    print("eye ", [round(v, 3) for v in eye])
    print("look", [round(v, 3) for v in look])
    print("dir ", [round(v / n, 4) for v in d], " fwd", [round(v, 4) for v in fwd])
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")

    for deg in (25.0, 60.0):
        th = math.radians(deg)
        # rotate the look-at around the eye about the world +Y axis
        ca, sa = math.cos(th), math.sin(th)
        nd = [d[0] * ca - d[2] * sa, d[1], d[0] * sa + d[2] * ca]
        new_look = [eye[i] + nd[i] for i in range(3)]
        stop = threading.Event()

        def wr(new_look=new_look, stop=stop):
            while not stop.is_set():
                b.write_float_block(0x53ADD0, new_look)

        t = threading.Thread(target=wr, daemon=True)
        t.start()
        time.sleep(1.5)
        held = b.read_floats(0x53ADD0, 3)
        fwd_now = b.read_floats(0x53ADA0, 3)
        shot = w.grab()
        score = diffscore(base, shot)
        stop.set()
        t.join(timeout=1)
        time.sleep(0.4)
        b.write_float_block(0x53ADD0, look)
        Image.fromarray(shot.astype("uint8")).save(OUT / f"yaw{int(deg)}.png")
        print(f"yaw {deg}: held={[round(v,2) for v in held]} "
              f"fwd={[round(v,3) for v in fwd_now]} frac={score['frac_gt16']:.3f}")
        time.sleep(0.4)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
