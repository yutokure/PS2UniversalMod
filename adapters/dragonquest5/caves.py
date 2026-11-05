"""Scoped render transaction and scoped native camera RX suppression.

WORLD/lens are restored before returning from renderer update. Native rig,
input packet, actor heading and other camera users are not rewritten.
"""
import time
from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    pass


def _addr(e, reg, value):
    e(m.lui(reg, value >> 16)); e(m.ori(reg, reg, value))


def _r(rs, rt, rd, sa, fn):
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn


def _lq(rt, base, off): return 0x78000000 | base << 21 | rt << 16 | off

def _sq(rt, base, off): return 0x7C000000 | base << 21 | rt << 16 | off


def _guards(a, reject):
    e = a.emit
    for address, word in mm.EXACT_GUARDS:
        _addr(e, m.T2, address); e(m.lw(m.T2, m.T2, 0)); _addr(e, m.T3, word)
        a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)
    for address in mm.ZERO_HALF_GUARDS:
        _addr(e, m.T2, address); e(0x94000000 | m.T2 << 21 | m.T2 << 16)
        a.bnez(m.T2, reject); e(m.NOP)


def _enabled(a, reject, flag):
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)
    e(m.lw(m.T2, m.T0, mm.MB_FLAGS)); e(m.andi(m.T2, m.T2, flag))
    a.beqz(m.T2, reject); e(m.NOP)
    _guards(a, reject)


def render_words():
    a = m.Assembler(); e = a.emit
    e(m.addiu(m.SP, m.SP, -0x20)); e(0xFFBF0010); e(m.sw(m.A0, m.SP, 0)); e(m.sw(m.ZERO, m.SP, 4))
    _enabled(a, 'native', mm.FLAG_ORBIT | mm.FLAG_FOV)
    _addr(e, m.T2, mm.RENDERER)
    a.words.append(('bne', m.A0, m.T2, 'native')); e(m.NOP)
    e(m.lw(m.T2, m.T0, mm.MB_PENDING)); a.bnez(m.T2, 'native'); e(m.NOP)
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    e(m.lw(m.T2, m.T0, mm.MB_SLOT)); e(m.andi(m.T2, m.T2, 1))
    e(_r(0, m.T2, m.T2, 7, 0)); e(m.addiu(m.T3, m.T0, mm.SLOTS[0]))
    e(_r(m.T2, m.T3, m.T3, 0, 0x21))
    e(m.lw(m.T4, m.T3, mm.SLOT_SEQUENCE)); e(m.andi(m.T2, m.T4, 1))
    a.bnez(m.T2, 'native'); e(m.NOP)
    for off in range(0, mm.SLOT_SIZE, 16):
        e(_lq(m.T2, m.T3, off)); e(_sq(m.T2, m.T0, mm.MB_SNAPSHOT + off))
    e(m.lw(m.T2, m.T3, mm.SLOT_SEQUENCE))
    a.words.append(('bne', m.T2, m.T4, 'native')); e(m.NOP)
    # Owner from current game allocation must still match the host bank.
    _addr(e, m.T1, mm.PLAYER_PTR); e(m.lw(m.T1, m.T1, 0))
    e(m.andi(m.T2, m.T1, 15)); a.bnez(m.T2, 'native'); e(m.NOP)
    e(_r(0, m.T1, m.T2, 20, 2)); a.beqz(m.T2, 'native'); e(m.NOP)
    e(0x2C000020 | m.T2 << 21 | m.T2 << 16); a.beqz(m.T2, 'native'); e(m.NOP)
    e(m.lw(m.T1, m.T1, mm.PLAYER_NODE)); e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_NODE))
    a.words.append(('bne', m.T1, m.T2, 'native')); e(m.NOP)
    e(m.lw(m.T4, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS))
    e(m.lw(m.T2, m.T0, mm.MB_FLAGS)); e(_r(m.T4, m.T2, m.T4, 0, 0x24))
    a.beqz(m.T4, 'native'); e(m.NOP)
    e(m.sw(m.T4, m.T0, mm.MB_APPLIED)); e(m.sw(m.T4, m.T0, mm.MB_PENDING)); e(m.sw(m.T4, m.SP, 4))
    e(m.lw(m.T2, m.T0, mm.MB_HEARTBEAT)); e(m.addiu(m.T2, m.T2, 1)); e(m.sw(m.T2, m.T0, mm.MB_HEARTBEAT))
    _addr(e, m.T3, mm.WORLD)
    e(m.andi(m.T2, m.T4, mm.FLAG_ORBIT)); a.beqz(m.T2, 'lens'); e(m.NOP)
    for off in range(0, 64, 16):
        e(_lq(m.T2, m.T3, off)); e(_sq(m.T2, m.T0, mm.MB_SAVED_WORLD + off))
        e(_lq(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_WORLD + off))
        e(_sq(m.T2, m.T0, mm.MB_RENDER_WORLD + off))
    for i in range(3):
        e(m.lwc1(0, m.T1, mm.NODE_POSITION + i*4))
        for src, dest in ((mm.MB_RENDER_WORLD + 0x30, mm.MB_RENDER_EYE),
                          (mm.MB_SNAPSHOT + mm.SLOT_TARGET, mm.MB_RENDER_TARGET)):
            e(m.lwc1(1, m.T0, src + i*4)); e(m.add_s(1, 0, 1))
            e(m.swc1(1, m.T0, dest + i*4))
            if dest == mm.MB_RENDER_EYE: e(m.swc1(1, m.T0, src + i*4))
    for off in range(0, 64, 16):
        e(_lq(m.T2, m.T0, mm.MB_RENDER_WORLD + off)); e(_sq(m.T2, m.T3, off))
    a.label('lens'); e(m.andi(m.T2, m.T4, mm.FLAG_FOV)); a.beqz(m.T2, 'native'); e(m.NOP)
    _addr(e, m.T3, mm.CAM_FOV); e(m.lw(m.T2, m.T3, 0)); e(m.sw(m.T2, m.T0, mm.MB_NATIVE_FOV))
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FOV)); e(m.sw(m.T2, m.T3, 0))
    a.label('native'); e(m.jal(mm.FUN_RENDER)); e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T4, m.SP, 4)); a.beqz(m.T4, 'done'); e(m.NOP)
    e(m.andi(m.T2, m.T4, mm.FLAG_ORBIT)); a.beqz(m.T2, 'restore_lens'); e(m.NOP)
    _addr(e, m.T3, mm.WORLD)
    for off in range(0, 64, 16):
        e(_lq(m.T2, m.T0, mm.MB_SAVED_WORLD + off)); e(_sq(m.T2, m.T3, off))
    a.label('restore_lens'); e(m.andi(m.T2, m.T4, mm.FLAG_FOV)); a.beqz(m.T2, 'clear'); e(m.NOP)
    _addr(e, m.T3, mm.CAM_FOV); e(m.lw(m.T2, m.T3, 0)); e(m.lw(m.T1, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FOV))
    a.words.append(('bne', m.T2, m.T1, 'clear')); e(m.NOP)
    e(m.lw(m.T2, m.T0, mm.MB_NATIVE_FOV)); e(m.sw(m.T2, m.T3, 0))
    a.label('clear'); e(m.sw(m.ZERO, m.T0, mm.MB_PENDING))
    a.label('done'); e(0xDFBF0010); e(m.addiu(m.SP, m.SP, 0x20)); e(0x03E00008); e(m.NOP)
    return a.assemble()


def pad_words():
    a = m.Assembler(); e = a.emit
    e(m.addiu(m.SP, m.SP, -0x30)); e(0xFFBF0020); e(m.sw(m.A0, m.SP, 0)); e(m.sw(m.ZERO, m.SP, 4))
    _enabled(a, 'native', mm.FLAG_ORBIT)
    _addr(e, m.T2, mm.CAM_EYE)
    a.words.append(('bne', m.A0, m.T2, 'native')); e(m.NOP)
    # gp-0x6788 owns processed pad; RX+0x190 is signed and centered at zero.
    e(m.lw(m.T1, 28, -0x6788)); a.beqz(m.T1, 'native'); e(m.NOP)
    e(m.lw(m.T2, m.T1, 0x190)); e(m.sw(m.T2, m.SP, 8)); e(m.sw(m.T1, m.SP, 4))
    e(m.sw(m.ZERO, m.T1, 0x190))
    a.label('native'); e(m.jal(mm.FUN_PAD_CAMERA)); e(m.NOP)
    e(m.lw(m.T1, m.SP, 4)); a.beqz(m.T1, 'done'); e(m.NOP)
    e(m.lw(m.T2, m.SP, 8)); e(m.sw(m.T2, m.T1, 0x190))
    a.label('done'); e(0xDFBF0020); e(m.addiu(m.SP, m.SP, 0x30)); e(0x03E00008); e(m.NOP)
    return a.assemble()


RENDER_WORDS = render_words(); PAD_WORDS = pad_words()
RESOURCES = ((mm.RENDER_HOOK, mm.RENDER_STOCK, (m.jal(mm.RENDER_CAVE), mm.RENDER_STOCK[1]), mm.RENDER_CAVE, RENDER_WORDS),
             (mm.PAD_HOOK, mm.PAD_STOCK, (m.jal(mm.PAD_CAVE), mm.PAD_STOCK[1]), mm.PAD_CAVE, PAD_WORDS))
assert mm.RENDER_CAVE + len(RENDER_WORDS)*4 <= mm.PAD_CAVE
assert mm.PAD_CAVE + len(PAD_WORDS)*4 <= mm.MOD_BLOCK


def read_words(b, address, count): return tuple(b.read_u32(address + i*4) for i in range(count))


def site_state(b):
    states = []
    for address, stock, hook, _, _ in RESOURCES:
        got = read_words(b, address, 2)
        states.append('stock' if got == stock else 'applied' if got == hook else 'unknown')
    return 'unknown' if 'unknown' in states else 'stock' if all(s == 'stock' for s in states) else 'applied'


def preflight(b):
    if site_state(b) == 'unknown': raise PatchConflict('unknown DQ5 hook instruction')
    for _, _, _, address, words in RESOURCES:
        got = read_words(b, address, len(words))
        if got != tuple(words) and any(got): raise PatchConflict('DQ5 code cave is occupied or damaged')
    magic = b.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC): raise PatchConflict('DQ5 control block is occupied')
    if not magic and any(read_words(b, mm.MOD_BLOCK, mm.BLOCK_SIZE//4)):
        raise PatchConflict('DQ5 control block is not empty')


def prepare(b):
    preflight(b)
    for _, _, _, address, words in RESOURCES:
        if read_words(b, address, len(words)) != tuple(words):
            for i, word in enumerate(words): b.write_u32(address + i*4, word)
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC: b.write_u32(mm.MOD_BLOCK, mm.MAGIC)


def install(b):
    preflight(b)
    for address, stock, hook, _, _ in RESOURCES:
        if b.read_u32(address) == stock[0]: b.write_u32(address, hook[0])


def uninstall(b):
    preflight(b)
    if b.read_u32(mm.MOD_BLOCK) == mm.MAGIC:
        b.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
        deadline = time.monotonic() + .25
        while b.read_u32(mm.MOD_BLOCK + mm.MB_PENDING):
            if time.monotonic() >= deadline:
                raise PatchConflict('DQ5 render transaction is paused; resume before restoring')
            time.sleep(.001)
    for address, stock, hook, _, _ in reversed(RESOURCES):
        if b.read_u32(address) == hook[0]: b.write_u32(address, stock[0])
    if b.read_u32(mm.MOD_BLOCK) == mm.MAGIC: b.write_u32(mm.MOD_BLOCK + mm.MB_APPLIED, 0)
