"""SLPS-25401/EB925207 gameplay consumer caves (offline-derived, live unverified).

No host writes or camera dependency: the parent's guest lifecycle owns all sites.
Only renderer alpha input, monster detection transition, and ring draw input change.
Native mode, actor speed, sight-radius fields, and ring globals remain untouched.
"""
from __future__ import annotations

from core import mips_asm as m

MOD_BLOCK = 0x000FF000
MAGIC = 0x4D434131
MB_FLAGS = 4
FLAG_WIDE = 4
FLAG_NO_ENCOUNTERS = 8
ALL_FLAGS = 15
ROOT_POINTER = 0x005527BC
SIGHT_CAVE, ENCOUNTER_CAVE, RING_CAVE = 0xFA000, 0xFB000, 0xFC000
SIGHT_SITE, ENCOUNTER_SITE, RING_SITE = 0x3FA7A8, 0x3F6B04, 0x1D04DC
SIGHT_STOCK = (0xC4810378, 0x46016036)
ENCOUNTER_STOCK = (0x1040001F, 0x0220202D)
RING_STOCK = (0x8F858BF4, 0x18A00133)


def _r(rs, rt, rd, fn):
    return rs << 21 | rt << 16 | rd << 11 | fn


def _addr(a, reg, address):
    a.emit(m.lui(reg, address >> 16)); a.emit(m.ori(reg, reg, address))


def _branch(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label)); a.emit(m.NOP)


def _save(a):
    a.emit(m.addiu(m.SP, m.SP, -0x40))
    for i, r in enumerate((m.T0, m.T1, m.T2, m.T3)):
        a.emit(0x7C000000 | m.SP << 21 | r << 16 | i * 16)  # sq full128


def _restore(a):
    for i, r in enumerate((m.T0, m.T1, m.T2, m.T3)):
        a.emit(0x78000000 | m.SP << 21 | r << 16 | i * 16)  # lq full128
    a.emit(m.addiu(m.SP, m.SP, 0x40))


def _pointer(a, reg, reject):
    # Only aligned main-RAM objects, with room for every following field load.
    a.emit(m.andi(m.T3, reg, 3))
    _branch(a, 'bne', m.T3, m.ZERO, reject)
    _addr(a, m.T3, 0x100000)
    a.emit(_r(reg, m.T3, m.T3, 0x2B))  # sltu
    _branch(a, 'bne', m.T3, m.ZERO, reject)
    _addr(a, m.T3, 0x1FFF000)
    a.emit(_r(reg, m.T3, m.T3, 0x2B))
    _branch(a, 'beq', m.T3, m.ZERO, reject)


def _guard(a, mask, reject, context=None):
    _addr(a, m.T0, MOD_BLOCK)
    a.emit(m.lw(m.T1, m.T0, 0)); _addr(a, m.T2, MAGIC)
    _branch(a, 'bne', m.T1, m.T2, reject)
    a.emit(m.lw(m.T1, m.T0, MB_FLAGS))
    a.emit(m.andi(m.T1, m.T1, mask))
    _branch(a, 'beq', m.T1, m.ZERO, reject)
    _addr(a, m.T0, ROOT_POINTER); a.emit(m.lw(m.T0, m.T0, 0))
    _pointer(a, m.T0, reject)
    a.emit(m.lw(m.T1, m.T0, 0x330)); _pointer(a, m.T1, reject)
    a.emit(0x90000000 | m.T1 << 21 | m.T2 << 16 | 0x91)  # lbu
    a.emit(m.addiu(m.T2, m.T2, -1))
    a.emit(0x2C000000 | m.T2 << 21 | m.T2 << 16 | 2)  # sltiu(mode-1,2)
    _branch(a, 'beq', m.T2, m.ZERO, reject)
    if context is not None:
        reg, off = context
        # GameMagi a0 on alpha consumer; MonsterPlug s1->268 on encounter.
        a.emit(_r(reg, m.ZERO, m.T1, 0x2D))
        _pointer(a, m.T1, reject)
        if off:
            a.emit(m.lw(m.T1, m.T1, off)); _pointer(a, m.T1, reject)
        a.emit(m.lw(m.T2, m.T1, 0x220))
        _branch(a, 'bne', m.T2, m.T0, reject)


def sight_words():
    a = m.Assembler()
    # Original output f1 is the sole intended floating-point change.
    a.emit(SIGHT_STOCK[0]); _save(a)
    _guard(a, FLAG_WIDE, 'native', (m.A0, 0))
    a.emit(0x44000000 | m.T2 << 16 | 1 << 11)  # mfc1 t2,f1
    # IEEE bit ordering for nonnegative float32; no extra FP condition/FCSR use.
    # Preserve NaNs and +infinity, expand finite negatives and -infinity.
    _addr(a, m.T3, 0x7FFFFFFF)
    a.emit(_r(m.T2, m.T3, m.T1, 0x24))
    _addr(a, m.T3, 0x7F800000)
    a.emit(_r(m.T3, m.T1, m.T1, 0x2B))
    _branch(a, 'bne', m.T1, m.ZERO, 'native')  # NaN: retain native bits
    a.emit(_r(m.T2, m.ZERO, m.T1, 0x2A))  # slt signed (negative float bits)
    _branch(a, 'bne', m.T1, m.ZERO, 'expand')
    _addr(a, m.T3, 0x44700000)  # 960.0, walk sample radius
    a.emit(_r(m.T2, m.T3, m.T1, 0x2B))
    _branch(a, 'beq', m.T1, m.ZERO, 'native')
    a.label('expand'); _addr(a, m.T3, 0x44700000)
    a.emit(0x44800000 | m.T3 << 16 | 1 << 11)  # mtc1 t3,f1
    a.label('native'); _restore(a)
    a.emit(SIGHT_STOCK[1])  # native c.ole.s f12,f1, including its FCSR effects
    a.emit(m.j(SIGHT_SITE + 8)); a.emit(m.NOP)
    return a.assemble()


def encounter_words():
    a = m.Assembler(); _save(a)
    _guard(a, FLAG_NO_ENCOUNTERS, 'native', (m.S1, 0x268))
    # Skip only the native proximity -> monster-detect-state transition.
    _restore(a); a.emit(ENCOUNTER_STOCK[1])
    a.emit(m.j(0x3F6B84)); a.emit(m.NOP)
    a.label('native'); _restore(a)
    a.emit(ENCOUNTER_STOCK[1])  # original branch delay executes on both paths
    _branch(a, 'beq', m.V0, m.ZERO, 'exit')
    a.emit(m.j(ENCOUNTER_SITE + 8)); a.emit(m.NOP)
    a.label('exit'); a.emit(m.j(0x3F6B84)); a.emit(m.NOP)
    return a.assemble()


def ring_words():
    a = m.Assembler(); a.emit(RING_STOCK[0]); _save(a)
    _guard(a, FLAG_NO_ENCOUNTERS, 'native')
    # Local argument only. The registration global and Pawn DetectRange survive.
    a.emit(m.addiu(m.A1, m.ZERO, 0))
    a.label('native'); _restore(a)
    # Replay displaced blez a1,1D09B0 including unchanged s2=a0 delay slot.
    a.emit(_r(m.A0, m.ZERO, m.S2, 0x2D))
    a.emit(0x18000000 | m.A1 << 21 | 3)  # blez -> local exit j
    a.emit(m.NOP)
    a.emit(m.j(RING_SITE + 12)); a.emit(m.NOP)
    a.emit(m.j(0x1D09B0)); a.emit(m.NOP)
    return a.assemble()


def code_resources():
    return ((SIGHT_CAVE, sight_words()), (ENCOUNTER_CAVE, encounter_words()),
            (RING_CAVE, ring_words()))


def resources():
    return ((SIGHT_SITE, SIGHT_STOCK, (m.j(SIGHT_CAVE), m.NOP)),
            (ENCOUNTER_SITE, ENCOUNTER_STOCK, (m.j(ENCOUNTER_CAVE), m.NOP)),
            (RING_SITE, RING_STOCK, (m.j(RING_CAVE), m.NOP)))
