"""Scoped render/RX transactions and native player movement yaw consumers.

WORLD/lens are restored before returning from renderer update. Movement keeps
native speed/collision/facing calculations and changes only their yaw inputs;
no permanent native camera yaw, packet or actor-heading stores are patched.
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


def _enabled(a, reject, flag, clear_latch=False):
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)
    if clear_latch: e(m.sw(m.ZERO, m.T0, mm.MB_MOVE_SP))
    e(m.lw(m.T2, m.T0, mm.MB_FLAGS)); e(m.andi(m.T2, m.T2, flag))
    a.beqz(m.T2, reject); e(m.NOP)
    _guards(a, reject)


def _lifecycle(a):
    """Install/detach on EE, apart from the sole PINE render-hook bootstrap.

    Lifecycle is independent of scene/Orbit guards, but requires exact ownership
    of every hook+delay before the first store. Nested renders cannot detach an
    outer transaction. The currently executing cave page is left untouched.
    """
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    a.words.append(('bne', m.T2, m.T3, 'return')); e(m.NOP)
    e(m.lw(m.T4, m.T0, mm.MB_COMMAND)); e(m.addiu(m.T3, m.ZERO, mm.CMD_UNINSTALL))
    a.words.append(('beq', m.T4, m.T3, 'lifecycle')); e(m.NOP)
    e(m.addiu(m.T3, m.ZERO, mm.CMD_INSTALL))
    a.words.append(('bne', m.T4, m.T3, 'return')); e(m.NOP)
    a.label('lifecycle')
    e(m.lw(m.T2, m.T0, mm.MB_PENDING)); a.bnez(m.T2, 'return'); e(m.NOP)
    sites = ((mm.RENDER_HOOK, mm.RENDER_STOCK, m.jal(mm.RENDER_CAVE)),
             (mm.PAD_HOOK, mm.PAD_STOCK, m.jal(mm.PAD_CAVE)),
             (mm.MOVE_HOOK, mm.MOVE_STOCK, m.j(mm.MOVE_CAVE)),
             (mm.FACING_HOOK, mm.FACING_STOCK, m.j(mm.FACING_CAVE)))
    for i, (address, stock, hook) in enumerate(sites):
        _addr(e, m.T1, address); e(m.lw(m.T2, m.T1, 0)); _addr(e, m.T3, stock[0])
        a.words.append(('beq', m.T2, m.T3, f'owned_{i}')); e(m.NOP)
        _addr(e, m.T3, hook)
        a.words.append(('bne', m.T2, m.T3, 'cleanup_conflict')); e(m.NOP)
        a.label(f'owned_{i}'); e(m.lw(m.T2, m.T1, 4)); _addr(e, m.T3, stock[1])
        a.words.append(('bne', m.T2, m.T3, 'cleanup_conflict')); e(m.NOP)
    e(m.addiu(m.T3, m.ZERO, mm.CMD_INSTALL))
    a.words.append(('beq', m.T4, m.T3, 'guest_install')); e(m.NOP)
    for address, stock, _ in reversed(sites):
        _addr(e, m.T1, address); _addr(e, m.T2, stock[0]); e(m.sw(m.T2, m.T1, 0))
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED)); e(m.sw(m.ZERO, m.T0, mm.MB_MOVE_SP))
    e(m.addiu(m.T2, m.ZERO, mm.CMD_DONE)); e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    a.beqz(m.ZERO, 'return'); e(m.NOP)
    a.label('guest_install')
    for i, (address, _, hook) in enumerate(sites[1:]):
        _addr(e, m.T1, address); e(m.lw(m.T2, m.T1, 0)); _addr(e, m.T3, hook)
        a.words.append(('beq', m.T2, m.T3, f'installed_{i}')); e(m.NOP)
        e(m.sw(m.T3, m.T1, 0)); a.label(f'installed_{i}')
    e(m.addiu(m.T2, m.ZERO, mm.CMD_INSTALLED)); e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    a.beqz(m.ZERO, 'return'); e(m.NOP)
    a.label('cleanup_conflict'); e(m.addiu(m.T2, m.ZERO, mm.CMD_CONFLICT))
    e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    a.label('return')


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
    a.label('done'); _lifecycle(a)
    e(0xDFBF0010); e(m.addiu(m.SP, m.SP, 0x20)); e(0x03E00008); e(m.NOP)
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


def _player_input(a, reject, clear_latch=False):
    """Integer-only validation at the two mid-function movement boundaries."""
    e = a.emit
    _enabled(a, reject, mm.FLAG_ORBIT, clear_latch=clear_latch)
    _addr(e, m.T2, mm.PLAYER_MANAGER)
    a.words.append(('bne', m.S3, m.T2, reject)); e(m.NOP)
    _addr(e, m.T1, mm.PLAYER_PTR); e(m.lw(m.T1, m.T1, 0))
    e(m.andi(m.T2, m.T1, 15)); a.bnez(m.T2, reject); e(m.NOP)
    e(_r(0, m.T1, m.T2, 20, 2)); a.beqz(m.T2, reject); e(m.NOP)
    e(0x2C000020 | m.T2 << 21 | m.T2 << 16); a.beqz(m.T2, reject); e(m.NOP)
    _addr(e, m.T3, 0x01FFFE00)
    e(_r(m.T1, m.T3, m.T2, 0, 0x2B)); a.beqz(m.T2, reject); e(m.NOP)
    e(m.lw(m.T2, m.S3, mm.MANAGER_ACTOR))
    a.words.append(('bne', m.T1, m.T2, reject)); e(m.NOP)
    e(0x90000000 | m.T1 << 21 | m.T2 << 16 | mm.ACTOR_SCRIPTED)
    a.bnez(m.T2, reject); e(m.NOP)
    e(m.lw(m.T2, m.T1, mm.ACTOR_INPUT_FLAGS)); _addr(e, m.T3, mm.NORMAL_INPUT_FLAGS)
    a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)
    e(m.lw(m.T1, m.T1, mm.PLAYER_NODE))


def movement_words(facing=False):
    """Select native-yaw inputs, not a second implementation of game movement.

    j hooks keep RA and the original delay stores intact. Vector takes one
    seqlocked yaw and latches it for facing; a host publish between the two
    consumers cannot split their directions. No pad/global camera yaw writes.
    """
    a = m.Assembler(); e = a.emit
    saved = (m.T0, m.T1, m.T2, m.T3, m.T4)
    frame = 16 * len(saved)
    e(m.addiu(m.SP, m.SP, -frame))
    for i, reg in enumerate(saved): e(_sq(reg, m.SP, 16*i))
    _addr(e, m.T0, mm.MOD_BLOCK)
    _player_input(a, 'fallback', clear_latch=not facing)
    if facing:
        e(m.lw(m.T2, m.T0, mm.MB_MOVE_SP)); e(m.addiu(m.T3, m.SP, frame))
        a.words.append(('bne', m.T2, m.T3, 'fallback')); e(m.NOP)
        e(m.lw(m.T2, m.T0, mm.MB_MOVE_NODE))
        a.words.append(('bne', m.T1, m.T2, 'fallback')); e(m.NOP)
        e(m.lwc1(0, m.T0, mm.MB_MOVE_YAW))
        e(m.sw(m.ZERO, m.T0, mm.MB_MOVE_SP))
    else:
        e(m.lw(m.T2, m.T0, mm.MB_SLOT)); e(m.andi(m.T2, m.T2, 1))
        e(_r(0, m.T2, m.T2, 7, 0)); e(m.addiu(m.T3, m.T0, mm.SLOTS[0]))
        e(_r(m.T2, m.T3, m.T3, 0, 0x21))
        e(m.lw(m.T4, m.T3, mm.SLOT_SEQUENCE)); e(m.andi(m.T2, m.T4, 1))
        a.bnez(m.T2, 'fallback'); e(m.NOP)
        e(m.lw(m.T2, m.T3, mm.SLOT_FLAGS)); e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT))
        a.beqz(m.T2, 'fallback'); e(m.NOP)
        e(m.lw(m.T2, m.T3, mm.SLOT_NODE))
        a.words.append(('bne', m.T1, m.T2, 'fallback')); e(m.NOP)
        e(m.lw(m.T2, m.T3, mm.SLOT_YAW)); e(m.sw(m.T2, m.T0, mm.MB_MOVE_YAW))
        e(m.lw(m.T2, m.T3, mm.SLOT_SEQUENCE))
        a.words.append(('bne', m.T2, m.T4, 'fallback')); e(m.NOP)
        e(m.sw(m.T1, m.T0, mm.MB_MOVE_NODE)); e(m.addiu(m.T2, m.SP, frame))
        e(m.sw(m.T2, m.T0, mm.MB_MOVE_SP)); e(m.lwc1(12, m.T0, mm.MB_MOVE_YAW))
    for i, reg in enumerate(saved): e(_lq(reg, m.SP, 16*i))
    e(m.addiu(m.SP, m.SP, frame))
    if facing: e(m.lwc1(1, m.SP, 0x114))
    e(m.j(0x5470CC if facing else 0x546CF0)); e(m.NOP)
    a.label('fallback')
    for i, reg in enumerate(saved): e(_lq(reg, m.SP, 16*i))
    e(m.addiu(m.SP, m.SP, frame))
    a.beqz(m.V0, 'world_relative'); e(m.NOP)
    e(m.j(0x5470C0 if facing else 0x546CE8)); e(m.NOP)
    a.label('world_relative'); e(m.j(0x5470B0 if facing else 0x546CD4)); e(m.NOP)
    return a.assemble()


RENDER_WORDS = render_words(); PAD_WORDS = pad_words()
MOVE_WORDS = movement_words(); FACING_WORDS = movement_words(True)
RESOURCES = ((mm.RENDER_HOOK, mm.RENDER_STOCK, (m.jal(mm.RENDER_CAVE), mm.RENDER_STOCK[1]), mm.RENDER_CAVE, RENDER_WORDS),
             (mm.PAD_HOOK, mm.PAD_STOCK, (m.jal(mm.PAD_CAVE), mm.PAD_STOCK[1]), mm.PAD_CAVE, PAD_WORDS),
             (mm.MOVE_HOOK, mm.MOVE_STOCK, (m.j(mm.MOVE_CAVE), mm.MOVE_STOCK[1]), mm.MOVE_CAVE, MOVE_WORDS),
             (mm.FACING_HOOK, mm.FACING_STOCK, (m.j(mm.FACING_CAVE), mm.FACING_STOCK[1]), mm.FACING_CAVE, FACING_WORDS))
assert mm.RENDER_CAVE + len(RENDER_WORDS)*4 <= mm.PAD_CAVE
assert mm.PAD_CAVE + len(PAD_WORDS)*4 <= mm.MOVE_CAVE
assert mm.MOVE_CAVE + len(MOVE_WORDS)*4 <= mm.FACING_CAVE
assert mm.FACING_CAVE + len(FACING_WORDS)*4 <= mm.MOD_BLOCK


def read_words(b, address, count): return tuple(b.read_u32(address + i*4) for i in range(count))


def site_state(b):
    states = []
    for address, stock, hook, _, _ in RESOURCES:
        got = read_words(b, address, 2)
        states.append('stock' if got == stock else 'applied' if got == hook else 'unknown')
    return 'unknown' if 'unknown' in states else 'stock' if all(s == 'stock' for s in states) else 'applied'


def preflight(b):
    state = site_state(b)
    if state == 'unknown': raise PatchConflict('unknown DQ5 hook instruction')
    for _, _, _, address, words in RESOURCES:
        got = read_words(b, address, len(words))
        if got != tuple(words) and (any(got) or state != 'stock'):
            raise PatchConflict('DQ5 code cave is occupied, damaged or still reachable')
    magic = b.read_u32(mm.MOD_BLOCK)
    if state != 'stock' and magic != mm.MAGIC:
        raise PatchConflict('DQ5 active hook has no owned control block')
    if magic not in (0, mm.MAGIC): raise PatchConflict('DQ5 control block is occupied')
    if not magic and any(read_words(b, mm.MOD_BLOCK, mm.BLOCK_SIZE//4)):
        raise PatchConflict('DQ5 control block is not empty')


def prepare(b):
    preflight(b)
    if (b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
            and b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND) == mm.CMD_UNINSTALL):
        raise PatchConflict('DQ5 guest cleanup is pending; resume before enabling')
    for _, _, _, address, words in RESOURCES:
        if read_words(b, address, len(words)) != tuple(words):
            for i, word in enumerate(words): b.write_u32(address + i*4, word)
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC: b.write_u32(mm.MOD_BLOCK, mm.MAGIC)


def all_applied(b):
    return all(read_words(b, address, 2) == hook for address, _, hook, _, _ in RESOURCES)


def install(b):
    preflight(b)
    command = b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)
    if command in (mm.CMD_UNINSTALL, mm.CMD_CONFLICT):
        raise PatchConflict('DQ5 guest lifecycle is pending or conflicted; restore before enabling')
    if all_applied(b) and command != mm.CMD_INSTALL: return
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC:
        raise PatchConflict('DQ5 install requires a prepared control block')
    b.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    b.write_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_INSTALL)
    # Only the bootstrap hook is written by PINE. The other native code pages
    # are installed by the EE-thread callback; activate flags only after ACK.
    if b.read_u32(mm.RENDER_HOOK) == mm.RENDER_STOCK[0]:
        b.write_u32(mm.RENDER_HOOK, m.jal(mm.RENDER_CAVE))
    deadline = time.monotonic() + .5
    while True:
        result = b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)
        if result == mm.CMD_INSTALLED:
            if not all_applied(b): raise PatchConflict('DQ5 guest install acknowledgement is inconsistent')
            return
        if result == mm.CMD_CONFLICT: raise PatchConflict('DQ5 hook changed during guest install')
        if time.monotonic() >= deadline:
            raise PatchConflict('DQ5 guest install is paused or unavailable; resume before enabling')
        time.sleep(.001)


def uninstall(b):
    preflight(b)
    magic = b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
    if magic: b.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
    if site_state(b) == 'stock':
        if magic:
            b.write_u32(mm.MOD_BLOCK + mm.MB_APPLIED, 0)
            b.write_u32(mm.MOD_BLOCK + mm.MB_MOVE_SP, 0)
            b.write_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_DONE)
        return
    if not magic or b.read_u32(mm.RENDER_HOOK) != m.jal(mm.RENDER_CAVE):
        raise PatchConflict('DQ5 guest cleanup hook unavailable; load a stock state')
    # Code-page stores from the PINE thread can race PCSX2's EE recompiler.
    # Publish DATA only; the render-tail callback restores code on the EE thread.
    b.write_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_UNINSTALL)
    deadline = time.monotonic() + .5
    while True:
        result = b.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)
        if result == mm.CMD_DONE:
            if site_state(b) != 'stock': raise PatchConflict('DQ5 guest cleanup acknowledgement is inconsistent')
            return
        if result == mm.CMD_CONFLICT: raise PatchConflict('DQ5 hook changed during guest cleanup')
        if time.monotonic() >= deadline:
            raise PatchConflict('DQ5 guest cleanup is paused or unavailable; resume before restoring')
        time.sleep(.001)
