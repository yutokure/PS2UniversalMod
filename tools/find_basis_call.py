"""Locate the call sites of FUN_001b0388 (camera basis from yaw/pitch/distance).

The decompiled camera update computes
    FUN_001b0388(yaw, pitch, roll, basis_out, ...)
where the angles live at +0x60/+0x64/+0x68 of the camera object.  Patching the
load offsets at the call site is a one-immediate change that makes the game
compute the basis from *our* angles.

This scans the ELF for `jal 0x001B0388` and decodes the preceding instructions.
"""
from __future__ import annotations

import struct
from pathlib import Path

ELF = Path(r"C:\PS2CameraLab\work\elf\SLPS_252.50")
TARGET = 0x001B0388


def decode(word: int, addr: int) -> str:
    op = word >> 26
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    imm = word & 0xFFFF
    simm = imm - 0x10000 if imm & 0x8000 else imm
    names = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
             "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
             "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
             "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra"]
    if op == 0x31:
        return f"lwc1 $f{rt}, {simm}({names[rs]})"
    if op == 0x39:
        return f"swc1 $f{rt}, {simm}({names[rs]})"
    if op == 0x23:
        return f"lw {names[rt]}, {simm}({names[rs]})"
    if op == 0x2B:
        return f"sw {names[rt]}, {simm}({names[rs]})"
    if op == 0x0F:
        return f"lui {names[rt]}, 0x{imm:04x}"
    if op == 0x0D:
        return f"ori {names[rt]}, {names[rs]}, 0x{imm:04x}"
    if op == 0x09:
        return f"addiu {names[rt]}, {names[rs]}, {simm}"
    if op == 0x03:
        return f"jal 0x{(addr & 0xF0000000) | ((word & 0x3FFFFFF) << 2):08x}"
    if word == 0:
        return "nop"
    return f".word 0x{word:08x}"


def main() -> None:
    data = ELF.read_bytes()
    words = struct.unpack(f"<{len(data) // 4}I", data[: len(data) // 4 * 4])
    jal = 0x0C000000 | ((TARGET >> 2) & 0x3FFFFFF)
    print(f"looking for jal 0x{TARGET:08x} (0x{jal:08x})")
    for i, w in enumerate(words):
        if w == jal:
            addr = i * 4
            print(f"\n=== call site at 0x{addr:08x} ===")
            for j in range(i - 8, i + 4):
                if 0 <= j < len(words):
                    print(f"  0x{j*4:08x}: 0x{words[j]:08x}  {decode(words[j], j*4)}")


if __name__ == "__main__":
    main()
