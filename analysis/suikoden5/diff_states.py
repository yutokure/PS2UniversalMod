r"""Suikoden V savestate differencing (offline, uses extracted eeMemory.bin).

Usage: python diff_states.py A B [--top N]
States are looked up under <dump dir>/su5_extracted (see core/config/paths.py).
"""
from __future__ import annotations
import argparse, os, struct, sys
import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from core.config import paths  # noqa: E402

ROOT = os.environ.get("PS2_SU5_EXTRACTED") or str(paths.dump_dir() / "su5_extracted")
NAMES = {
    "S0": "base", "S1": "base_only_wait", "S2": "base_no_move_and_cam_zoom_only",
    "S3": "chara_and_cam_moved_from_base",
    "S4": "chara_little_moved_and_cam_bigger_moved_from_base",
}

def load(tag: str) -> np.ndarray:
    n = NAMES.get(tag, tag)
    return np.fromfile(os.path.join(ROOT, n, "eeMemory.bin"), dtype=np.uint8)

def f32(a: np.ndarray) -> np.ndarray:
    return a.view("<f4")

def plausible(x: np.ndarray) -> np.ndarray:
    ax = np.abs(x)
    return np.isfinite(x) & (ax < 1e6) & ((ax > 1e-4) | (x == 0))

def changed_words(a, b):
    wa, wb = a.view("<u4"), b.view("<u4")
    return np.nonzero(wa != wb)[0]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    args = ap.parse_args()
    a, b = load(args.a), load(args.b)
    idx = changed_words(a, b)
    print(args.a, args.b, "changed words:", len(idx))
