"""Scan the 16 KiB EE scratchpad for the live camera direction and eye.

Everything in EE main RAM that looks like the view basis turned out to be an
output copy; the scratchpad is the only fast RAM the EE writes every frame and
the renderer reads directly.  If the direction lives there it can be written
deterministically.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

SCRATCH = 0x70000000
SIZE = 0x4000


def main() -> None:
    b = PineBackend()
    b.connect()
    fwd = b.read_floats(0x53ADA0, 3)
    eye = b.read_floats(0x340360, 3)
    n = math.sqrt(sum(v * v for v in fwd))
    fwd = [v / n for v in fwd]
    print("fwd", [round(v, 4) for v in fwd], "eye", [round(v, 3) for v in eye])
    words = []
    for off in range(0, SIZE, 4):
        words.append(b.read_f32(SCRATCH + off))
    hits_f, hits_e = [], []
    for i in range(len(words) - 4):
        if all(abs(words[i + k] - fwd[k]) <= 2e-3 for k in range(3)):
            hits_f.append(i * 4)
        if all(abs(words[i + k] - eye[k]) <= 5e-3 for k in range(3)):
            hits_e.append(i * 4)
    print("forward hits:", [hex(h) for h in hits_f])
    print("eye hits    :", [hex(h) for h in hits_e])
    for h in hits_f[:5]:
        ctx = [round(words[h // 4 + k], 4) for k in range(0, 16) if h // 4 + k < len(words)]
        print(f"  ctx @{h:#06x}: {ctx}")
    b.close()


if __name__ == "__main__":
    main()
