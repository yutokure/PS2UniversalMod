"""Tiny MIPS (R5900) instruction encoders used to build code caves.

Only the handful of instructions the adapters need.  Every encoder returns the 32-bit
instruction word; tests check them against known game words.
"""
from __future__ import annotations

ZERO = 0
V0, V1 = 2, 3
A0, A1, A2, A3 = 4, 5, 6, 7
T0, T1, T2, T3, T4, T5, T6, T7 = 8, 9, 10, 11, 12, 13, 14, 15
S0, S1, S2, S3, S4 = 16, 17, 18, 19, 20
T8, T9 = 24, 25
SP = 29

NOP = 0x00000000


def _s16(v: int) -> int:
    return v & 0xFFFF


def j(target: int) -> int:
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def jal(target: int) -> int:
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def lui(rt: int, imm: int) -> int:
    return 0x3C000000 | (rt << 16) | (imm & 0xFFFF)


def ori(rt: int, rs: int, imm: int) -> int:
    return 0x34000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def andi(rt: int, rs: int, imm: int) -> int:
    return 0x30000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def addiu(rt: int, rs: int, imm: int) -> int:
    return 0x24000000 | (rs << 21) | (rt << 16) | _s16(imm)


def lw(rt: int, base: int, off: int) -> int:
    return 0x8C000000 | (base << 21) | (rt << 16) | _s16(off)


def sw(rt: int, base: int, off: int) -> int:
    return 0xAC000000 | (base << 21) | (rt << 16) | _s16(off)


def sb(rt: int, base: int, off: int) -> int:
    return 0xA0000000 | (base << 21) | (rt << 16) | _s16(off)


def lwc1(ft: int, base: int, off: int) -> int:
    return 0xC4000000 | (base << 21) | (ft << 16) | _s16(off)


def swc1(ft: int, base: int, off: int) -> int:
    return 0xE4000000 | (base << 21) | (ft << 16) | _s16(off)


def beq(rs: int, rt: int, off_words: int) -> int:
    return 0x10000000 | (rs << 21) | (rt << 16) | _s16(off_words)


def bne(rs: int, rt: int, off_words: int) -> int:
    return 0x14000000 | (rs << 21) | (rt << 16) | _s16(off_words)


def add_s(fd: int, fs: int, ft: int) -> int:
    return 0x46000000 | (ft << 16) | (fs << 11) | (fd << 6)


def mov_s(fd: int, fs: int) -> int:
    return 0x46000006 | (fs << 11) | (fd << 6)


class Assembler:
    """Collects words and resolves forward/backward branches by label."""

    def __init__(self) -> None:
        self.words: list = []
        self.labels: dict[str, int] = {}

    def emit(self, word: int) -> int:
        self.words.append(word)
        return len(self.words) - 1

    def label(self, name: str) -> None:
        self.labels[name] = len(self.words)

    def beqz(self, rs: int, label: str) -> None:
        self.words.append(("beq", rs, ZERO, label))

    def bnez(self, rs: int, label: str) -> None:
        self.words.append(("bne", rs, ZERO, label))

    def assemble(self) -> list[int]:
        out: list[int] = []
        for i, w in enumerate(self.words):
            if isinstance(w, tuple):
                kind, rs, rt, name = w
                off = self.labels[name] - (i + 1)
                out.append((beq if kind == "beq" else bne)(rs, rt, off))
            else:
                out.append(w)
        return out
