"""Dump the FFX-2 field-camera structures decoded from FUN_001a91a0.

Layout recovered from the decompilation:
    entity slot table  : 0x33F730 + slot*0x1C0
    entity camera base : 0x33FBC0 + entity*0x1050
    camera payload     : base + view*0x750 + 0x40     (view 1 -> 0x340350)
      +0x00 flags        +0x10 eye   +0x20 game eye  +0x30 target
      +0x40 matrix?      +0x50 pos   +0x60 yaw/pitch/dist/dolly
      +0x70 pos target   +0x8C roll  +0x90 eye offset
    camera params      : payload + mode*0x130 + 0xC0
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_backend.pine_backend import PineBackend  # noqa: E402

CAM = 0x340350


def f32(b: PineBackend, a: int) -> float:
    return b.read_f32(a)


def vec(b: PineBackend, a: int, n: int = 4):
    return [round(f32(b, a + 4 * i), 4) for i in range(n)]


def u8(b: PineBackend, a: int) -> int:
    return b.read_u32(a) & 0xFF


def main() -> int:
    b = PineBackend()
    b.connect()
    print("version", b.version(), "| game", b.game_id(), "| status", hex(b.status()))

    print("\n== entity slot table 0x33F730 (3 slots, stride 0x1C0) ==")
    for slot in range(3):
        base = 0x33F730 + slot * 0x1C0
        raw = b.read_u32(base)
        print(f"  slot{slot} 0x{base:08X} active={raw & 0xFF} entity={u8(b, base + 1)}"
              f" raw=0x{raw:08X}")

    print("\n== entity camera bases (entity 0..3) ==")
    for ent in range(4):
        base = 0x33FBC0 + ent * 0x1050
        print(f"  ent{ent} 0x{base:08X} e0={u8(b, base)} e1={u8(b, base + 1)} e2={u8(b, base + 2)}")

    print(f"\n== camera payload 0x{CAM:08X} ==")
    print("  flags  [%02X %02X %02X %02X %02X %02X %02X %02X]" % tuple(u8(b, CAM + i) for i in range(8)))
    print("  +0x08  ", vec(b, CAM + 0x08))
    print("  +0x10 eye       ", vec(b, CAM + 0x10))
    print("  +0x20 game eye  ", vec(b, CAM + 0x20))
    print("  +0x30 target    ", vec(b, CAM + 0x30))
    print("  +0x40 m0        ", vec(b, CAM + 0x40))
    print("  +0x50 pos       ", vec(b, CAM + 0x50))
    print("  +0x60 yaw/pit/d ", vec(b, CAM + 0x60))
    print("  +0x70 posTarget ", vec(b, CAM + 0x70))
    print("  +0x80 misc      ", vec(b, CAM + 0x80))
    print("  +0x8c roll/off  ", vec(b, CAM + 0x8C, 3))
    print("  +0x90 eyeOffset ", vec(b, CAM + 0x90))
    print("  +0xA0           ", vec(b, CAM + 0xA0))

    print("\n== camera params: payload + mode*0x130 + 0xC0 ==")
    for mode in range(8):
        p = CAM + mode * 0x130 + 0xC0
        print(f"  mode{mode} 0x{p:08X} [%02X %02X %02X %02X]" % tuple(u8(b, p + i) for i in range(4)))

    print("\n== 0x33F620 view struct ==")
    print("  +0x00", vec(b, 0x33F620, 8))
    print("  +0x20", vec(b, 0x33F620 + 0x20, 8))
    print("  +0x40", vec(b, 0x33F620 + 0x40, 8))

    print("\n== render mirror 0x53AD80 ==")
    print("  right ", vec(b, 0x53AD80))
    print("  up    ", vec(b, 0x53AD90))
    print("  fwd   ", vec(b, 0x53ADA0))
    print("  eye   ", vec(b, 0x53ADB0))
    print("  look  ", vec(b, 0x53ADD0))

    print("\n== projection 0x340B00 ==")
    print("  ", vec(b, 0x340B00, 4))
    b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
