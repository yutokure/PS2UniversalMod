"""Bounded native VIF packet streaming (SLPM-65081/B6AB7BC2 only).

Reserve BEFORE opening a DIRECT/UNPACK payload, never inside one. A closed
stream can be submitted without resetting VIF/VU/GS state or changing sort order.
The original two 2-MiB DMA banks and fatal bounds checks remain unchanged.
"""
from core import mips_asm as m
from . import memory_map as mm

BASE = 0xBC100
LIMIT = 0xBD800
CONTROL = BASE
DIRECT = BASE + 0x80
UNPACK = BASE + 0x100
RESERVE = BASE + 0x180
BANK_BASE = 0x428380
BANK_SIZE = 0x200000
BANK_INDEX = 0x428300
PUT = 0x8283A8
VU_INDEX = 0x828398
# Valid VIF payload maxima, plus alignment, closing tag and control overhead.
DIRECT_RESERVE = 0x100100  # 65535 QW + overhead, not a scene-derived guess
UNPACK_RESERVE = 0x1100  # up to 256 QW + overhead
CONTROL_RESERVE = 0x100
MB_FLUSHES = 0x54
MB_HIGH_WATER = 0x58
MB_STREAM_BUSY = 0x5C


def _addr(e, reg, value):
    e(m.lui(reg, value >> 16)); e(m.ori(reg, reg, value))


def _r(rs, rt, rd, sa, fn):
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn


def _branch(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label)); a.emit(m.NOP)


# Entry hooks retain the independent native second instruction as delay slot.
SPECS = ((0x260A60, (0x3C040083, 0x3C031300), CONTROL, CONTROL_RESERVE),
         (0x260B38, (0x3C100083, 0xFFBF0010), DIRECT, DIRECT_RESERVE),
         (0x260BF8, (0x3C050083, 0x3C060083), UNPACK, UNPACK_RESERVE))
SITES = tuple((address, stock, (m.j(cave), stock[1]))
              for address, stock, cave, _size in SPECS)

# The hook may replace a leaf: protect full-width R5900 registers, not merely
# the C ABI's lower-64-bit callee-saved subset. Never touch kernel k0/k1.
REGS = (*range(1, 26), 28, 30, 31)
FRAME = 0x300
GPR_OFFSET = 0x40  # Keep the native callee's outgoing argument home area free.
FPU_OFFSET = GPR_OFFSET + len(REGS) * 16
SPECIAL_OFFSET = FPU_OFFSET + 32 * 4


def entry_words(cave, native, first, reserve):
    a = m.Assembler(); e = a.emit
    # The common path is a bounded integer check, not 32 FPU saves per strip.
    # Only a real flush (or DIRECT CNT split) needs the fully transparent call.
    e(m.addiu(m.SP, m.SP, -FRAME))
    hot = (m.T0, m.T1, m.T2, m.T3, m.T4, m.T5)
    for reg in hot:
        e(0x7C000000 | m.SP << 21 | reg << 16 | (GPR_OFFSET + REGS.index(reg) * 16))
    if reserve != DIRECT_RESERVE:
        _addr(e, m.T0, mm.MOD_BLOCK)
        e(m.lw(m.T1, m.T0, 0)); _addr(e, m.T2, mm.MAGIC)
        _branch(a, 'bne', m.T1, m.T2, 'hot_return')
        e(m.lw(m.T1, m.T0, MB_STREAM_BUSY))
        _branch(a, 'bne', m.T1, m.ZERO, 'hot_return')
        _addr(e, m.T1, BANK_INDEX); e(m.lw(m.T1, m.T1, 0))
        e(0x2D2A0002)
        _branch(a, 'beq', m.T2, m.ZERO, 'hot_return')
        e(_r(0, m.T1, m.T1, 21, 0))
        _addr(e, m.T2, BANK_BASE); e(_r(m.T1, m.T2, m.T1, 0, 0x21))
        _addr(e, m.T2, PUT); e(m.lw(m.T2, m.T2, 0))
        e(_r(m.T2, m.T1, m.T3, 0, 0x23))
        e(m.lw(m.T4, m.T0, MB_HIGH_WATER)); e(_r(m.T4, m.T3, m.T5, 0, 0x2B))
        _branch(a, 'beq', m.T5, m.ZERO, 'water_done')
        e(m.sw(m.T3, m.T0, MB_HIGH_WATER))
        a.label('water_done')
        _addr(e, m.T4, BANK_SIZE - reserve)
        e(_r(m.T4, m.T3, m.T5, 0, 0x2B))
        _branch(a, 'beq', m.T5, m.ZERO, 'hot_return')
    for i, reg in enumerate(REGS):
        if reg not in hot:
            e(0x7C000000 | m.SP << 21 | reg << 16 | (GPR_OFFSET + i * 16))
    _addr(e, m.A0, reserve)
    e(m.jal(RESERVE)); e(m.NOP)
    for i, reg in enumerate(REGS):
        if reg not in hot:
            e(0x78000000 | m.SP << 21 | reg << 16 | (GPR_OFFSET + i * 16))
    a.label('hot_return')
    for reg in hot:
        e(0x78000000 | m.SP << 21 | reg << 16 | (GPR_OFFSET + REGS.index(reg) * 16))
    e(m.addiu(m.SP, m.SP, FRAME))
    e(first)
    e(m.j(native + 8)); e(m.NOP)
    return a.assemble()


def reserve_words():
    a = m.Assembler(); e = a.emit
    # ra belongs to the small entry wrapper; original ra lives in its frame.
    e(0xFFBF0000 | (FRAME - 8))
    e(m.sw(m.A0, m.SP, FRAME - 24))
    for f in range(32):
        e(m.swc1(f, m.SP, FPU_OFFSET + f * 4))
    # Preserve HI/LO, secondary pipeline HI1/LO1, SA and FCSR.
    for i, word in enumerate((0x00004010, 0x00004012, 0x70004010,
                              0x70004012, 0x00004028, 0x4448F800)):
        e(word); e(0xFC000000 | m.SP << 21 | m.T0 << 16 | (SPECIAL_OFFSET + i * 8))
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T1, m.T0, 0)); _addr(e, m.T2, mm.MAGIC)
    _branch(a, 'bne', m.T1, m.T2, 'return')
    e(m.lw(m.T1, m.T0, MB_STREAM_BUSY))
    _branch(a, 'bne', m.T1, m.ZERO, 'return')
    _addr(e, m.T1, BANK_INDEX); e(m.lw(m.T1, m.T1, 0))
    e(0x2D2A0002)  # sltiu t2,t1,2
    _branch(a, 'beq', m.T2, m.ZERO, 'return')
    e(_r(0, m.T1, m.T1, 21, 0))
    _addr(e, m.T2, BANK_BASE); e(_r(m.T1, m.T2, m.T1, 0, 0x21))
    _addr(e, m.T2, PUT); e(m.lw(m.T2, m.T2, 0))
    e(_r(m.T2, m.T1, m.T3, 0, 0x23))  # subu used,put,base
    e(m.lw(m.T4, m.T0, MB_HIGH_WATER)); e(_r(m.T4, m.T3, m.T5, 0, 0x2B))
    _branch(a, 'beq', m.T5, m.ZERO, 'water_done')
    e(m.sw(m.T3, m.T0, MB_HIGH_WATER))
    a.label('water_done')
    _addr(e, m.T4, BANK_SIZE)
    e(_r(m.T3, m.A0, m.T5, 0, 0x21))
    e(_r(m.T4, m.T5, m.T5, 0, 0x2B))
    _branch(a, 'beq', m.T5, m.ZERO, 'space_ready')
    # Closed payload boundary. No queue/cache reset, no geometry is discarded.
    e(m.addiu(m.T1, m.ZERO, 1)); e(m.sw(m.T1, m.T0, MB_STREAM_BUSY))
    _addr(e, m.T1, VU_INDEX); e(m.lw(m.T1, m.T1, 0)); e(m.sw(m.T1, m.SP, FRAME - 16))
    # Use the native flush sequence directly: its convenience entry gates on
    # UNPACK work count and incorrectly ignores DIRECT-only packet occupancy.
    for target in (0x2610D8, 0x261268):
        e(m.jal(target)); e(m.NOP)
    e(m.jal(0x2A5820)); e(m.addiu(m.A0, m.ZERO, 0))  # FlushCache(0)
    for target in (0x261358, 0x260F50, 0x261098):
        e(m.jal(target)); e(m.NOP)
    e(m.lw(m.T1, m.SP, FRAME - 16)); _addr(e, m.T2, VU_INDEX); e(m.sw(m.T1, m.T2, 0))
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T1, m.T0, MB_FLUSHES)); e(m.addiu(m.T1, m.T1, 1)); e(m.sw(m.T1, m.T0, MB_FLUSHES))
    e(m.sw(m.ZERO, m.T0, MB_STREAM_BUSY))
    a.label('space_ready')
    # DIRECT does not run the UNPACK closer's native CNT-size splitter. Start
    # its own CNT so accumulated meshes plus a large font/overlay DIRECT cannot
    # overflow the DMA tag's separate 16-bit QWC. Supported field sources are
    # bounded by an 80000-byte source scratch arena (fonts are also bounded); arbitrary
    # malformed >64K-QW DIRECTs are not made valid by bank reservation.
    e(m.lw(m.T1, m.SP, FRAME - 24)); _addr(e, m.T0, DIRECT_RESERVE)
    _branch(a, 'bne', m.T1, m.T0, 'return')
    e(m.jal(0x260D90)); e(m.NOP)
    a.label('return')
    for i, word in enumerate((0x01000011, 0x01000013, 0x71000011,
                              0x71000013, 0x01000029, 0x44C8F800)):
        e(0xDC000000 | m.SP << 21 | m.T0 << 16 | (SPECIAL_OFFSET + i * 8)); e(word)
    for f in range(32):
        e(m.lwc1(f, m.SP, FPU_OFFSET + f * 4))
    e(0xDFBF0000 | (FRAME - 8)); e(0x03E00008); e(m.NOP)
    return a.assemble()


# All entry wrappers share one full register-save body (the wrappers themselves
# only contain a tiny jump shim; generated together below).
def words():
    # Larger wrappers need separate space; place them after the shared body.
    shared = reserve_words()
    result = [m.NOP] * ((RESERVE - BASE) // 4) + shared
    for native, stock, cave, reserve in SPECS:
        # Each stable entry jumps to its out-of-line full-save wrapper.
        # Full-save wrapper is emitted out of line, leaving stable small entries.
        wrapper = BASE + len(result) * 4
        generated = entry_words(wrapper, native, stock[0], reserve)
        result.extend(generated)
        i = (cave - BASE) // 4
        result[i:i+2] = [m.j(wrapper), m.NOP]
    assert BASE + len(result) * 4 <= LIMIT
    return result


WORDS = words()
