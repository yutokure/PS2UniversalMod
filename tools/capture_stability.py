"""Capture-path stability check: is the window capture good enough for evidence?

Holds a fixed orbit override and measures frame-to-frame variance of the
PrintWindow capture.  Low variance means the path is usable for E2E verdicts.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, r"C:\PS2CameraLab\scripts")

import numpy as np  # noqa: E402

from adapters.ffx2.adapter import FFX2Adapter  # noqa: E402
from core.camera_runtime.engine import MODE_ORBIT, CameraRuntime, CameraSettings  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402
from sweep_camera import Window, diffscore  # noqa: E402


def main() -> None:
    backend = PineBackend()
    backend.connect()
    ad = FFX2Adapter(backend)
    ad.identify()
    st = CameraSettings()
    rt = CameraRuntime(ad, st)
    rt.start()
    rt.sync_to_game()
    st.mode = MODE_ORBIT
    time.sleep(0.8)
    w = Window()
    frames = []
    for i in range(1, 9):
        frames.append(w.grab())
        time.sleep(0.12)
    base = frames[0]
    scores = [diffscore(base, f) for f in frames[1:]]
    print("frame-to-frame (override static):")
    for i, s in enumerate(scores, 1):
        print(f"  +{i}: frac_gt16={s['frac_gt16']:.4f} mean={s['mean']:.2f}")
    print("max frac_gt16:", max(s["frac_gt16"] for s in scores))
    rt.restore()
    time.sleep(0.3)
    rt.stop()
    backend.close()


if __name__ == "__main__":
    main()
