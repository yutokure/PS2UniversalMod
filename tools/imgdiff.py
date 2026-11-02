"""Compare PNG screenshots: mean abs difference and the fraction of pixels that moved."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("PIL missing")
    raise SystemExit(2)


def load(p: str):
    return Image.open(p).convert("RGB")


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: imgdiff.py A.png B.png [...]")
        return 2
    base = load(sys.argv[1])
    for other in sys.argv[2:]:
        im = load(other)
        if im.size != base.size:
            print(f"{other}: size {im.size} != {base.size}")
            continue
        w, h = base.size
        a, b = base.load(), im.load()
        total = 0
        moved = 0
        big = 0
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                pa, pb = a[x, y], b[x, y]
                d = (abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])) / 3.0
                total += d
                if d > 8:
                    moved += 1
                if d > 40:
                    big += 1
        n = (w // 2 + w % 2) * (h // 2 + h % 2)
        print(f"{Path(other).name}: mean={total / n:7.3f}  frac>8={moved / n:6.3f}  frac>40={big / n:6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
