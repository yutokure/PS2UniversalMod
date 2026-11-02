"""Differential analysis of the four protected FFX-2 savestates.

Compares the *extracted* EE main memory (not the compressed .p2s containers),
filters the noise, and ranks float32 / float32-triple candidates by how well they
behave like a coordinate or a direction vector.

The savestates themselves are only ever read.  Extraction results are cached in
``C:\\PS2CameraLab\\work\\sstates_extracted\\<state>\\`` and reused.

    python analysis/savestate_diff/run.py                # full report
    python analysis/savestate_diff/run.py --top 20       # shorter console output
    python analysis/savestate_diff/run.py --only base_only_wait
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import zipfile
from pathlib import Path

LAB = Path(r"C:\PS2CameraLab")
STATES = LAB / "sstates"
EXTRACTED = LAB / "work" / "sstates_extracted"
OUT = LAB / "PS2UniversalMod" / "reports" / "savestate_diff.json"

STATES_ORDER = [
    "base",
    "base_only_wait",
    "base_left_moved",
    "base_chara_little_moved_and_cam_big_moved",
]

#: words that change on literally every frame and therefore carry no camera
#: information.  Anything inside these windows is dropped from the candidate list.
NOISE_WINDOWS = [
    (0x00000000, 0x00020000),   # kernel / exception vectors
    (0x00100000, 0x00180000),   # game code (self-modifying counters live here)
    (0x331200, 0x331400),       # auxiliary depth camera scratch (per frame)
    (0x340000, 0x340350),       # camera payload header / flags
    (0x340A00, 0x341000),       # per-frame inverse camera cache
    (0x480000, 0x490000),       # audio / timers
    (0x4FE000, 0x4FF000),       # render scratch
    (0x53A000, 0x53B000),       # render mirror written every frame
]


def extract(state: str) -> Path:
    """Return the cached ``eeMemory.bin`` for one savestate, extracting if needed."""
    dst = EXTRACTED / state
    ram = dst / "eeMemory.bin"
    if ram.exists() and ram.stat().st_size == 32 * 1024 * 1024:
        return ram
    src = STATES / f"{state}.p2s"
    if not src.exists():
        raise SystemExit(f"missing savestate: {src}")
    try:
        import zstandard
    except ImportError:
        raise SystemExit("zstandard is required to extract .p2s")
    dst.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if "eeMemory" not in info.filename:
                continue
            blob = zf.read(info)
            raw = blob
            if info.compress_type == 93:
                raw = zstandard.ZstdDecompressor().decompress(blob, max_output_size=32 << 20)
            ram.write_bytes(raw)
            return ram
    raise SystemExit(f"no eeMemory inside {src}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def was_noise(addr: int) -> bool:
    return any(lo <= addr < hi for lo, hi in NOISE_WINDOWS)


def load_float_triples(ram: bytes):
    """Yield (addr, (x, y, z)) for every plausible float triple in the image."""
    view = memoryview(ram)
    for addr in range(0x00100000, len(ram) - 16, 4):
        if was_noise(addr):
            continue
        vals = struct.unpack_from("<4f", view, addr)
        if not all(math.isfinite(v) and abs(v) < 1.0e5 for v in vals[:3]):
            continue
        # a coordinate is rarely exactly zero in all three components
        if abs(vals[0]) < 1e-6 and abs(vals[1]) < 1e-6 and abs(vals[2]) < 1e-6:
            continue
        yield addr, vals[:3]


def classify(values: list[tuple[float, float, float]]) -> dict:
    """Score how much a triple behaves like a point vs a direction."""
    lengths = [math.sqrt(sum(v * v for v in t)) for t in values]
    unit = all(abs(n - 1.0) < 0.02 for n in lengths)
    spread = max(lengths) - min(lengths)
    moving = sum(1 for a, b in zip(values, values[1:]) if a != b)
    return {"unit_length": unit, "length_spread": round(spread, 6), "changes": moving}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--only", default=None, help="restrict the comparison to one state")
    args = ap.parse_args()

    order = [args.only] if args.only else STATES_ORDER
    rams = {name: extract(name) for name in order}
    blobs = {name: path.read_bytes() for name, path in rams.items()}
    print("states:")
    for name in order:
        print(f"  {name:48s} {rams[name].stat().st_size:>10,} B  {sha256(rams[name])[:16]}…")

    base = order[0]
    base_blob = blobs[base]

    # --- candidate discovery ------------------------------------------------
    # A useful camera value must differ between at least two states and be a
    # well-formed float triple in *all* of them.
    candidates: dict[int, list[tuple[float, float, float]]] = {}
    for addr, vals in load_float_triples(base_blob):
        if addr + 4 > len(base_blob):
            continue
        row = [vals]
        ok = True
        for name in order[1:]:
            if addr + 12 > len(blobs[name]):
                ok = False
                break
            other = struct.unpack_from("<3f", blobs[name], addr)
            if not all(math.isfinite(v) and abs(v) < 1.0e5 for v in other):
                ok = False
                break
            row.append(tuple(other))
        if not ok:
            continue
        if any(r != row[0] for r in row[1:]):
            candidates[addr] = row

    print(f"\nchanged float triples: {len(candidates):,}")

    ranked = []
    for addr, row in candidates.items():
        info = classify(row)
        score = 0.0
        if info["unit_length"]:
            score += 3.0           # a direction vector keeps |v| == 1 in every state
        score += min(2.0, info["changes"] * 0.5)
        score += 1.0 if info["length_spread"] < 40 else 0.0
        ranked.append({"addr": f"0x{addr:08X}", "values": [list(map(round, r)) for r in row],
                       "score": round(score, 3), **info})
    ranked.sort(key=lambda r: (-r["score"], r["addr"]))

    known = {
        "0x00340360": "render eye",
        "0x00340370": "game eye (base for the additive offset)",
        "0x00340380": "player anchor / camera target",
        "0x0033FC10": "look-at point consumed by FUN_001b07a0",
        "0x003312D0": "auxiliary orbit camera centre",
    }
    for r in ranked:
        if r["addr"] in known:
            r["known"] = known[r["addr"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    #: verified camera words, reported separately because a pure "looks like a
    #: direction" ranking is dominated by ±1/0 basis vectors that happen to sit
    #: in the stack.  These were confirmed by live read/write watchpoints.
    verified = {}
    for addr_s, label in known.items():
        a = int(addr_s, 16)
        if a + 12 > min(len(v) for v in blobs.values()):
            continue
        verified[addr_s] = {
            "label": label,
            "values": {name: [round(v, 5) for v in struct.unpack_from("<3f", blobs[name], a)]
                       for name in order},
        }
    OUT.write_text(json.dumps({"states": order,
                               "sizes": {k: len(v) for k, v in blobs.items()},
                               "changed_triples": len(candidates),
                               "verified_camera_words": verified,
                               "top": ranked[:200]}, indent=1), encoding="utf-8")

    print(f"\n{'addr':>12}  {'score':>5}  unit  spread      values (first state)")
    for r in ranked[:args.top]:
        vals = ", ".join(f"{v:9.3f}" for v in r["values"][0])
        tag = f"  <- {r['known']}" if r.get("known") else ""
        print(f"{r['addr']:>12}  {r['score']:>5.2f}  {str(r['unit_length']):>5} "
              f"{r['length_spread']:>7.3f}  {vals}{tag}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
