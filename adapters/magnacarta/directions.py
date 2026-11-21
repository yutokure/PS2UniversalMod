"""Scoped camera-yaw consumer for Magna Carta's native analog movement.

ProcessAnalog (0x445C30) caches a native camera rotator while a stick direction
is held. Intercepting its axes-builder call covers both fresh and cached paths:
only the function's local rotator yaw changes. Native input scaling, speed,
heading slew, pawn rotation and collision remain the game's responsibility.
The minimap already draws the pawn's real heading; it must not be changed just
because the camera turns. Lifecycle installation is owned by the parent caves.
"""
from __future__ import annotations

from core import mips_asm as m

CAVE = 0x000F8000
HOOK = 0x00446314
NATIVE_AXES = 0x00192080
# Confirmed in offline ELF/RAM: jal 192080; addiu a2,sp,0xC8.
STOCK_PAIR = (0x0C064820, 0x27A600C8)
PATCHED_PAIR = (m.jal(CAVE), STOCK_PAIR[1])
SCRATCH = (m.T0, m.T1, m.T2, m.T3)
FRAME = 16 * len(SCRATCH)


def _map():
    # Delay import so this isolated emitter is importable while the shared map
    # and parent adapter are being assembled. No fallback address contract.
    from . import memory_map
    return memory_map


def _addr(e, reg, value):
    e(m.lui(reg, value >> 16))
    e(m.ori(reg, reg, value))


def _sq(reg, offset):
    return 0x7C000000 | m.SP << 21 | reg << 16 | offset


def _lq(reg, offset):
    return 0x78000000 | m.SP << 21 | reg << 16 | offset


def _branch(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label))
    a.emit(m.NOP)


def movement_words(*, released=False) -> tuple[int, ...]:
    mm = _map()
    a = m.Assembler()
    e = a.emit
    e(m.addiu(m.SP, m.SP, -FRAME))
    for i, reg in enumerate(SCRATCH):
        e(_sq(reg, i * 16))
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T1, m.T0, 0))
    _addr(e, m.T2, mm.MAGIC)
    _branch(a, 'bne', m.T1, m.T2, 'native')
    e(m.lw(m.T1, m.T0, mm.MB_FLAGS))
    e(m.andi(m.T1, m.T1, mm.FLAG_ORBIT))
    _branch(a, 'beq', m.T1, m.ZERO, 'native')
    if released:  # only to recognize both earlier MCA1 state formats
        _addr(e, m.T1, mm.PLAYER_GLOBAL)
        e(m.lw(m.T1, m.T1, 0))
        _branch(a, 'beq', m.T1, m.ZERO, 'native')
        e(m.andi(m.T2, m.T1, 15))
        _branch(a, 'bne', m.T2, m.ZERO, 'native')
    else:
        from .caves import pointer
        pointer(a, m.S1, 'native')
        e(m.lw(m.T1, m.S1, mm.PC_PAWN))
        pointer(a, m.T1, 'native')
    e(m.lw(m.T2, m.T0, mm.MB_ACCEPTED))
    _branch(a, 'bne', m.T1, m.T2, 'native')
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_PLAYER))
    _branch(a, 'bne', m.T1, m.T2, 'native')
    # ProcessAnalog's S1 is the native player controller (not a fixed heap
    # address). Never redirect another controller's movement using our snapshot.
    if released:
        e(m.lw(m.T2, m.S1, 0x1EC))
        _branch(a, 'bne', m.T1, m.T2, 'native')
    else:
        e(m.lw(m.T2, m.T1, mm.PLAYER_CONTROLLER))
        _branch(a, 'bne', m.S1, m.T2, 'native')
    e(m.lw(m.T3, m.T0, mm.MB_SNAPSHOT + mm.SLOT_YAW))
    e(m.sw(m.T3, m.A2, 4))
    a.label('native')
    for i, reg in enumerate(SCRATCH):
        e(_lq(reg, i * 16))
    e(m.addiu(m.SP, m.SP, FRAME))
    # Tail jump: original hook's JAL already established RA=HOOK+8 and its
    # delay slot established A2 in the caller's frame. Do not alter RA, arguments,
    # FPU/VU/HI/LO/SA or any scratch upper 96 bits before the original builder.
    e(m.j(NATIVE_AXES))
    e(m.NOP)
    return tuple(a.assemble())


def code_resources() -> tuple[tuple[int, tuple[int, ...]], ...]:
    return ((CAVE, movement_words()),)


def resources() -> tuple[tuple[int, tuple[int, int], tuple[int, int]], ...]:
    return ((HOOK, STOCK_PAIR, PATCHED_PAIR),)
