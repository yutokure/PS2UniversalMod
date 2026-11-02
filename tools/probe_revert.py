"""Does the game rewrite the camera words we own?

Writes a distinctive pose once, then stops writing for a moment and reads the
words back.  A value that snaps back to the stock one is being rewritten by the
game every frame, which is what turns our per-frame writes into visible
flicker (the renderer occasionally samples the game's value instead of ours).
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

WORDS = {
    "eye  0x340360": 0x340360,
    "game 0x340370": 0x340370,
    "pos  0x3403A0": 0x3403A0,
    "aim  0x33FC10": 0x33FC10,
    "player0x340380": 0x340380,
    "fov  0x340B00": 0x340B00,
}


def main() -> int:
    b = PineBackend()
    b.connect()

    def vec(a, n=3):
        return [b.read_f32(a + 4 * i) for i in range(n)]

    def snap():
        return {k: [round(v, 4) for v in vec(a)] for k, a in WORDS.items()}

    before = snap()
    print("baseline:")
    for k, v in before.items():
        print(f"  {k} {v}")

    # distinctive probe value, far from anything the game would produce
    probe = [1234.0, -567.0, 890.0]
    for a in (0x340360, 0x33FC10):
        b.write_float_block(a, probe)
    print(f"\nwrote probe {probe} to eye and aim; sampling without further writes")

    for gap in (0.05, 0.12, 0.25, 0.5, 1.0):
        time.sleep(gap)
        e = [round(v, 2) for v in vec(0x340360)]
        a = [round(v, 2) for v in vec(0x33FC10)]
        print(f"  +{gap * 1000:4.0f}ms  eye={e}  aim={a}")

    # restore
    for k in ("eye  0x340360",):
        pass
    b.write_float_block(0x340360, before["eye  0x340360"])
    b.write_float_block(0x33FC10, before["aim  0x33FC10"])
    print("restored to baseline")
    after = snap()
    print("final:")
    for k, v in after.items():
        print(f"  {k} {v}")
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
