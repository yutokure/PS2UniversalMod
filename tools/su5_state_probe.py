"""Print the camera values of the Suikoden V state that is loaded now (read-only).

    python tools/su5_state_probe.py

Used to confirm that each of the five savestates loads in PCSX2 and shows the values the offline
analysis (reports/SUIKODEN5_STATE_DIFF.md) predicts: distance, pitch, yaw, FOV and the zoom stage
of the camera control object seen in the base state.  Nothing is written.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.suikoden5 import memory_map as mm  # noqa: E402
from core.memory_backend.pine_backend import PineBackend  # noqa: E402

CAM_CTL_BASE_STATE = 0x0129D7D8       # heap address of the control object in the five savestates


def main() -> int:
    b = PineBackend()
    b.connect()
    print(f"{b.game_id().strip()} / {b.crc().strip()}")
    g = {
        "distance": b.read_floats(mm.G_DISTANCE, 1)[0], "pitch": b.read_floats(mm.G_PITCH, 1)[0],
        "yaw": b.read_floats(mm.G_YAW, 1)[0], "fov": b.read_floats(mm.G_FOV, 1)[0],
        "focus": [round(v, 1) for v in b.read_floats(mm.G_FOCUS, 3)],
        "eye": [round(v, 1) for v in b.read_floats(mm.G_EYE, 3)],
        "zoom_stage": b.read_u32(CAM_CTL_BASE_STATE + mm.CTL_ZOOM_STAGE) & 0xFFFF,
    }
    for k, v in g.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
