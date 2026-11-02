"""Capture the visual effect of the strong hits found by scan_rotation_offset."""
from __future__ import annotations

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

OUT = ROOT / "reports" / "hits"
OUT.mkdir(parents=True, exist_ok=True)
HITS = [0x340418, 0x3403DC, 0x340450]


def main() -> None:
    b = PineBackend()
    b.connect()
    w = Window()
    base = w.grab()
    Image.fromarray(base.astype("uint8")).save(OUT / "base.png")
    for addr in HITS:
        for delta in (0.05, 0.35):
            cur = b.read_f32(addr)
            val = cur + delta
            stop = threading.Event()

            def wr(addr=addr, val=val, stop=stop):
                while not stop.is_set():
                    b.write_float_block(addr, [val])

            th = threading.Thread(target=wr, daemon=True)
            th.start()
            time.sleep(0.8)
            held = b.read_f32(addr)
            shot = w.grab()
            score = diffscore(base, shot)
            stop.set()
            th.join(timeout=1)
            time.sleep(0.3)
            b.write_float_block(addr, [cur])
            name = f"{addr:08x}_d{delta}.png"
            Image.fromarray(shot.astype("uint8")).save(OUT / name)
            print(f"{addr:#08x} d={delta}: held={held:+.4f} frac={score['frac_gt16']:.3f} -> {name}")
            time.sleep(0.3)
    b.close()
    print("shots ->", OUT)


if __name__ == "__main__":
    main()
