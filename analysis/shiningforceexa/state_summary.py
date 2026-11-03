"""Read-only validation of Exa's known camera layout in extracted EE RAM.

Usage: python analysis/shiningforceexa/state_summary.py <base-dir> <wait-dir> ...
Each directory contains eeMemory.bin. Extraction is the lab's existing
scripts/ps2lab/sstate_zip.py; never store RAM, screenshots or ELF in Git.
Prints numeric summaries and hashes only; does not infer that zero RAM is free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.shiningforceexa import memory_map as mm


def summarize(path: Path) -> dict:
    ram = path.read_bytes()
    if len(ram) != 0x2000000:
        raise ValueError('expected a 32 MiB eeMemory.bin')
    u32 = lambda a: struct.unpack_from('<I', ram, a)[0]
    floats = lambda a, n: struct.unpack_from(f'<{n}f', ram, a)
    eye, focus = floats(mm.CAM_EYE, 3), floats(mm.CAM_FOCUS, 3)
    d = [a - b for a, b in zip(eye, focus)]
    vp = floats(mm.CAM_VP, 16)
    sx = math.sqrt(sum(vp[i] ** 2 for i in (0, 4, 8)))
    actor = u32(mm.PARTY_ACTOR_PTR)
    actor_ok = 0x100000 <= actor < 0x2000000 - mm.PARTY_POS_OFFSET - 12 and not actor & 15
    return dict(state=path.parent.name, sha256=hashlib.sha256(ram).hexdigest(),
                active_camera=hex(u32(mm.CAM_ACTIVE_PTR)), actor=hex(actor),
                anchor=floats(actor + mm.PARTY_POS_OFFSET, 3) if actor_ok else None,
                eye=eye, focus=focus, distance=math.sqrt(sum(x*x for x in d)),
                yaw=math.degrees(math.atan2(d[0], d[2])),
                pitch=math.degrees(math.atan2(-d[1], math.hypot(d[0], d[2]))),
                field_distance=floats(mm.CAM_DISTANCE, 1)[0], height=floats(mm.CAM_HEIGHT, 1)[0],
                yaw_pitch=struct.unpack_from('<hh', ram, mm.CAM_YAW),
                vertical_fov_units=struct.unpack_from('<H', ram, mm.CAM_FOV)[0],
                sx=sx, horizontal_fov=math.degrees(2*math.atan(1/sx)) if sx > 0 else None,
                mode=u32(mm.CAM_MODE), focus_mode=u32(mm.CAM_FOCUS_MODE),
                smoothing_gate=ram[mm.SMOOTH_GATE],
                pad_stock_words=[hex(u32(a)) for a in (mm.PAD_RX_LOAD, mm.PAD_RY_LOAD)],
                raw_right=[list(ram[a:a+2]) for a in mm.PAD_RX_SOURCES])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('states', nargs='+', type=Path)
    args = ap.parse_args()
    for d in args.states:
        print(json.dumps(summarize(d / 'eeMemory.bin'), ensure_ascii=False))


if __name__ == '__main__':
    main()
