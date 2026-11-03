"""Render-only override: preserve the native camera's current and goal values.

The displaced delay-slot load and following eye mirror store are reproduced.
The cave chooses alternative arguments only for the final world-matrix builders,
then rejoins the original shake call. Double-buffered host parameters are latched
once per guest frame; actor translation is added by the guest, not a host loop.
"""
from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    """Unknown hook, code cave or control block; never force an overwrite."""


def _r(rs, rt, rd, sa, fn):
    return (rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | fn


def _sq(rt, base, off):
    return 0x7C000000 | (base << 21) | (rt << 16) | (off & 65535)


def _lq(rt, base, off):
    return 0x78000000 | (base << 21) | (rt << 16) | (off & 65535)


def _load(e, reg, address):
    e(m.lui(reg, address >> 16)); e(m.ori(reg, reg, address))


def camera_words(dungeon=False):
    a = m.Assembler(); e = a.emit
    # Town delay loaded t0; dungeon load is immediately before its hook.
    # Preserve the displaced native eye mirror store in both cases.
    e(_sq(m.T0, m.V1, 0))
    e(m.addiu(m.SP, m.SP, -0x30))
    e(_sq(18, m.SP, 0)); e(_sq(19, m.SP, 0x10))
    _load(e, 18, mm.MOD_BLOCK)  # s2 survives native builder calls
    if dungeon:
        e(m.lwc1(0, m.S1, mm.CAM_FOV_RAD))
    e(m.swc1(0, 18, mm.MB_NATIVE_FOV))
    e(m.swc1(0, m.S1, mm.CAM_FOV_RAD))  # original displaced store / dungeon unchanged
    e(m.sw(m.S1, 18, mm.MB_CAMERA))
    e(m.lw(m.T0, 18, mm.MB_HEARTBEAT)); e(m.addiu(m.T0, m.T0, 1))
    e(m.sw(m.T0, 18, mm.MB_HEARTBEAT))
    e(m.sw(m.ZERO, 18, mm.MB_APPLIED))
    # Scene ownership is checked in the guest too: a host lease cannot make an
    # event/movie/other camera into the verified gameplay camera.
    _load(e, m.T0, mm.ROOT_PTR)
    e(m.lw(m.T1, m.T0, 0)); e(m.lw(m.T2, m.T0, 4))
    a.words.append(('bne', m.T2, m.S1, 'native')); e(m.NOP)
    e(m.addiu(m.T2, m.T1, mm.DUNGEON_CAMERA_OFFSET if dungeon else mm.CAMERA_OFFSET))
    a.words.append(('bne', m.T2, m.S1, 'native')); e(m.NOP)
    e(m.lw(m.T2, m.T1, 0)); _load(e, m.T3, mm.DUNGEON_ROOT_VTABLE if dungeon else mm.ROOT_VTABLE)
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    e(0x94000000 | (m.T1 << 21) | (m.T2 << 16) | 4)  # lhu root.state
    e(m.addiu(m.T3, m.ZERO, 3 if dungeon else 2))
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    e(m.lw(m.T2, m.S1, 0)); _load(e, m.T3, mm.DUNGEON_CAMERA_VTABLE if dungeon else mm.CAMERA_VTABLE)
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    e(m.lw(m.T2, m.S1, mm.CAM_MODE))
    e(m.addiu(m.T3, m.ZERO, 1 if dungeon else 0))
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    if dungeon:
        e(0x94000000 | (m.S1 << 21) | (m.T2 << 16) | 0x2DE)
        a.bnez(m.T2, 'native'); e(m.NOP)
    _load(e, m.T2, mm.GAME_STATE); e(m.lw(m.T2, m.T2, 0))
    e(m.addiu(m.T3, m.ZERO, 1 if dungeon else 2))
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    _load(e, m.T2, mm.GAME_FLAGS_WORD); e(m.lw(m.T2, m.T2, 0))
    e(_r(0, m.T2, m.T2, 16, 2)); e(m.andi(m.T2, m.T2, 0x4000))
    a.bnez(m.T2, 'native'); e(m.NOP)
    e(m.lw(m.T2, m.T1, mm.RENDERER_OFFSET+mm.RENDER_CAMERA))
    e(m.addiu(m.T3, m.S1, mm.CAM_VIEW))
    a.words.append(('bne', m.T2, m.T3, 'native')); e(m.NOP)
    _load(e, m.T2, mm.EVENT_ACTIVE); e(m.lw(m.T2, m.T2, 0))
    a.bnez(m.T2, 'native'); e(m.NOP)
    # Latch one immutable parameter bank. Host flips this word only after filling it.
    e(m.lw(m.T2, 18, mm.MB_SLOT)); e(m.andi(m.T2, m.T2, 1))
    e(_r(0, m.T2, m.T2, 6, 0)); e(m.addiu(19, 18, mm.SLOTS[0]))
    e(_r(19, m.T2, 19, 0, 0x21))
    e(m.lw(m.T3, 18, mm.MB_FLAGS)); e(m.sw(m.T3, m.SP, 0x20))
    e(m.andi(m.T2, m.T3, mm.FLAG_FOV)); a.beqz(m.T2, 'orbit'); e(m.NOP)
    e(m.lwc1(0, 19, mm.SLOT_FOV)); e(m.swc1(0, m.S1, mm.CAM_FOV_RAD))
    a.label('orbit')
    e(m.andi(m.T2, m.T3, mm.FLAG_ORBIT)); a.beqz(m.T2, 'native'); e(m.NOP)
    # bank anchor is a record INDEX, not an arbitrary pointer.
    e(m.lw(m.T2, 19, mm.SLOT_ANCHOR))
    e(0x2C000000 | (m.T2 << 21) | (m.T3 << 16) | mm.ENTITY_COUNT)
    a.beqz(m.T3, 'native'); e(m.NOP)
    e(_r(0, m.T2, m.T3, 9, 0)); e(_r(0, m.T2, m.T2, 6, 0))
    e(_r(m.T3, m.T2, m.T2, 0, 0x23))
    _load(e, m.T3, mm.ENTITY_TABLE); e(_r(m.T3, m.T2, m.T2, 0, 0x21))
    if dungeon:
        # Native dungeon actor owns this exact subentity; town ID1000 is absent.
        _load(e, m.T3, mm.DUNGEON_ACTOR_PTR); e(m.lw(m.T3, m.T3, 0))
        e(_r(0, m.T3, m.T4, 16, 2))
        e(0x2C000000 | (m.T4 << 21) | (m.T4 << 16) | 0x200)
        a.beqz(m.T4, 'native'); e(m.NOP)
        e(_r(0, m.T3, m.T4, 20, 2)); a.beqz(m.T4, 'native'); e(m.NOP)
        e(m.andi(m.T4, m.T3, 15)); a.bnez(m.T4, 'native'); e(m.NOP)
        e(m.lw(m.T3, m.T3, mm.ACTOR_ENTITY_PTR))
        e(m.addiu(m.T4, m.T2, mm.ENTITY_RENDERER))
        a.words.append(('bne', m.T3, m.T4, 'native')); e(m.NOP)
    else:
        e(0x94000000 | (m.T2 << 21) | (m.T3 << 16) | mm.ENTITY_ID)
        e(m.addiu(m.T4, m.ZERO, mm.PLAYER_ID))
        a.words.append(('bne', m.T3, m.T4, 'native')); e(m.NOP)
    e(m.lw(m.T3, m.T2, 0)); e(m.andi(m.T3, m.T3, 1))
    a.beqz(m.T3, 'native'); e(m.NOP)
    e(m.lw(m.T3, m.T2, mm.ENTITY_RENDERER))
    e(m.addiu(m.T4, m.T1, mm.RENDERER_OFFSET))
    a.words.append(('bne', m.T3, m.T4, 'native')); e(m.NOP)
    for delta, out in ((mm.SLOT_EYE, mm.MB_EYE), (mm.SLOT_TARGET, mm.MB_TARGET)):
        for i in range(3):
            e(m.lwc1(0, m.T2, mm.ENTITY_POS + i*4))
            e(m.lwc1(1, 19, delta + i*4)); e(m.add_s(0, 0, 1))
            e(m.swc1(0, 18, out + i*4))
        e(m.lui(m.T3, 0x3F80)); e(m.sw(m.T3, 18, out+12))
    e(m.addiu(m.T2, m.ZERO, 1)); e(m.sw(m.T2, 18, mm.MB_APPLIED))
    a.label('native')
    # Original final translation, with a different argument only when accepted.
    e(m.addiu(m.A0, m.S1, 0x10)); e(m.addiu(m.A1, m.S1, 0x250 if dungeon else 0x240))
    e(m.lw(m.T0, 18, mm.MB_APPLIED)); a.beqz(m.T0, 'eye'); e(m.NOP)
    e(m.addiu(m.A1, 18, mm.MB_EYE))
    a.label('eye'); e(m.jal(mm.FUN_TRANSLATE)); e(m.addiu(m.A2, m.ZERO, 0))
    # Keep native target mirror (the unmodified code did this before look-at).
    e(m.addiu(m.V0, m.S1, 0x280)); e(m.addiu(m.V1, m.S1, 0x290))
    e(_lq(m.T0, m.V0, 0)); e(_sq(m.T0, m.V1, 0))
    e(m.addiu(m.A0, m.S1, 0x10)); e(m.addiu(m.A1, m.S1, 0x290 if dungeon else 0x280))
    e(m.lw(m.T0, 18, mm.MB_APPLIED)); a.beqz(m.T0, 'target'); e(m.NOP)
    e(m.addiu(m.A1, 18, mm.MB_TARGET))
    a.label('target'); e(m.jal(mm.FUN_LOOK_AT)); e(m.NOP)
    e(_lq(18, m.SP, 0)); e(_lq(19, m.SP, 0x10))
    e(m.j(mm.DUNGEON_RETURN if dungeon else mm.CAM_RETURN)); e(m.addiu(m.SP, m.SP, 0x30))
    return a.assemble()


def pad_words():
    a=m.Assembler();e=a.emit
    e(mm.PAD_AXIS_STOCK[0])  # actual raw sample, unchanged for left axes
    e(0x2D070002)  # sltiu a3,t0,2: RX/RY iterations only
    a.beqz(m.A3,'left');e(m.NOP)
    e(m.addiu(m.A0,m.ZERO,127))
    a.label('left')
    e(mm.PAD_AXIS_STOCK[1])  # original signed/deadzone input
    e(m.j(mm.PAD_AXIS_RETURN));e(m.NOP)
    return a.assemble()


def movement_words(dungeon=False):
    """Local consumer override only; no pad, native goal, actor or camera writes.

    Keep full R5900 temporary registers and FPU bits, including on fallback.
    A global seqlock prevents a preempted reader using a bank reused by the host.
    """
    a = m.Assembler(); e = a.emit
    frame = 0xA0
    e(m.addiu(m.SP, m.SP, -frame))
    for i, reg in enumerate(range(m.T0, m.T7+1)):
        e(_sq(reg, m.SP, i*16))
    for i in range(6): e(m.swc1(i, m.SP, 0x80+i*4))
    _load(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T6, m.T0, mm.MB_MAGIC)); _load(e, m.T7, mm.MAGIC)
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    e(m.lw(m.T4, m.T0, mm.MB_MOVE_SEQ)); e(m.andi(m.T6, m.T4, 1))
    a.bnez(m.T6, 'native'); e(m.NOP)
    e(m.lw(m.T5, m.T0, mm.MB_FLAGS)); e(m.andi(m.T6, m.T5, mm.FLAG_ORBIT))
    a.beqz(m.T6, 'native'); e(m.NOP)
    _load(e, m.T6, mm.ROOT_PTR)
    e(m.lw(m.T1, m.T6, 0)); e(m.lw(m.T2, m.T6, 4))
    # Reject invalid allocations before dereferencing root/camera.
    e(_r(0, m.T1, m.T6, 20, 2)); a.beqz(m.T6, 'native'); e(m.NOP)
    _load(e, m.T7, 0x02000000-0x2400)
    e(_r(m.T1, m.T7, m.T6, 0, 0x2B)); a.beqz(m.T6, 'native'); e(m.NOP)
    e(m.andi(m.T6, m.T1, 15)); a.bnez(m.T6, 'native'); e(m.NOP)
    e(m.addiu(m.T6, m.T1, mm.DUNGEON_CAMERA_OFFSET if dungeon else mm.CAMERA_OFFSET))
    a.words.append(('bne', m.T2, m.T6, 'native')); e(m.NOP)
    if dungeon:
        _load(e, m.T6, mm.DUNGEON_MANAGER)
        a.words.append(('bne', m.A0, m.T6, 'native')); e(m.NOP)
        a.words.append(('bne', m.S2, m.T6, 'native')); e(m.NOP)
        # Decoder also serves target-selection UI; never rotate that caller.
        e(m.lw(m.T6, m.SP, frame+0x40))
        _load(e, m.T7, mm.DUNGEON_MOVE_CALLERS[0])
        a.words.append(('beq', m.T6, m.T7, 'caller_ok')); e(m.NOP)
        _load(e, m.T7, mm.DUNGEON_MOVE_CALLERS[1])
        a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
        a.label('caller_ok')
    else:
        e(m.addiu(m.T6, m.T1, mm.TOWN_CONTROLLER_OFFSET))
        a.words.append(('bne', m.S0, m.T6, 'native')); e(m.NOP)
    e(m.lw(m.T6, m.T1, 0)); _load(e, m.T7, mm.DUNGEON_ROOT_VTABLE if dungeon else mm.ROOT_VTABLE)
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    e(0x94000000 | (m.T1 << 21) | (m.T6 << 16) | 4)
    e(m.addiu(m.T7, m.ZERO, 3 if dungeon else 2))
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    e(m.lw(m.T6, m.T2, 0)); _load(e, m.T7, mm.DUNGEON_CAMERA_VTABLE if dungeon else mm.CAMERA_VTABLE)
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    e(m.lw(m.T6, m.T2, mm.CAM_MODE)); e(m.addiu(m.T7, m.ZERO, 1 if dungeon else 0))
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    if dungeon:
        e(0x94000000 | (m.T2 << 21) | (m.T6 << 16) | 0x2DE)
        a.bnez(m.T6, 'native'); e(m.NOP)
    _load(e, m.T6, mm.GAME_STATE); e(m.lw(m.T6, m.T6, 0))
    e(m.addiu(m.T7, m.ZERO, 1 if dungeon else 2))
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    _load(e, m.T6, mm.EVENT_ACTIVE); e(m.lw(m.T6, m.T6, 0))
    a.bnez(m.T6, 'native'); e(m.NOP)
    _load(e, m.T6, mm.GAME_FLAGS_WORD); e(m.lw(m.T6, m.T6, 0))
    e(_r(0, m.T6, m.T6, 16, 2)); e(m.andi(m.T6, m.T6, 0x4000))
    a.bnez(m.T6, 'native'); e(m.NOP)
    e(m.lw(m.T6, m.T1, mm.RENDERER_OFFSET+mm.RENDER_CAMERA))
    e(m.addiu(m.T7, m.T2, mm.CAM_VIEW))
    a.words.append(('bne', m.T6, m.T7, 'native')); e(m.NOP)
    e(m.lw(m.T3, m.T0, mm.MB_SLOT)); e(m.andi(m.T3, m.T3, 1))
    e(_r(0, m.T3, m.T3, 6, 0)); e(m.addiu(m.T3, m.T3, mm.SLOTS[0]))
    e(_r(m.T0, m.T3, m.T3, 0, 0x21))
    for off, reg in ((mm.SLOT_ROOT, m.T1), (mm.SLOT_CAMERA, m.T2)):
        e(m.lw(m.T6, m.T3, off)); a.words.append(('bne', m.T6, reg, 'native')); e(m.NOP)
    e(m.lw(m.T5, m.T3, mm.SLOT_MOVE)); e(m.andi(m.T6, m.T5, mm.MOVE_VALID))
    a.beqz(m.T6, 'native'); e(m.NOP)
    e(m.andi(m.T6, m.T5, mm.MOVE_VALID | 7))
    a.words.append(('bne', m.T6, m.T5, 'native')); e(m.NOP)
    e(m.lw(m.T6, m.T3, mm.SLOT_ANCHOR))
    e(0x2C000000 | (m.T6 << 21) | (m.T7 << 16) | mm.ENTITY_COUNT)
    a.beqz(m.T7, 'native'); e(m.NOP)
    e(_r(0, m.T6, m.T7, 9, 0)); e(_r(0, m.T6, m.T6, 6, 0))
    e(_r(m.T7, m.T6, m.T6, 0, 0x23))
    _load(e, m.T7, mm.ENTITY_TABLE); e(_r(m.T7, m.T6, m.T6, 0, 0x21))
    if dungeon:
        _load(e, m.T7, mm.DUNGEON_ACTOR_PTR); e(m.lw(m.T7, m.T7, 0))
        e(_r(0, m.T7, m.T2, 20, 2)); a.beqz(m.T2, 'native'); e(m.NOP)
        _load(e, m.T2, 0x02000000-mm.ACTOR_ENTITY_PTR-4)
        e(_r(m.T7, m.T2, m.T2, 0, 0x2B)); a.beqz(m.T2, 'native'); e(m.NOP)
        e(m.andi(m.T2, m.T7, 15)); a.bnez(m.T2, 'native'); e(m.NOP)
        e(m.lw(m.T7, m.T7, mm.ACTOR_ENTITY_PTR)); e(m.addiu(m.T2, m.T6, mm.ENTITY_RENDERER))
        a.words.append(('bne', m.T7, m.T2, 'native')); e(m.NOP)
    else:
        e(0x94000000 | (m.T6 << 21) | (m.T7 << 16) | mm.ENTITY_ID)
        e(m.addiu(m.T2, m.ZERO, mm.PLAYER_ID))
        a.words.append(('bne', m.T7, m.T2, 'native')); e(m.NOP)
    e(m.lw(m.T7, m.T6, 0)); e(m.andi(m.T7, m.T7, 1))
    a.beqz(m.T7, 'native'); e(m.NOP)
    e(m.lw(m.T7, m.T6, mm.ENTITY_RENDERER)); e(m.addiu(m.T2, m.T1, mm.RENDERER_OFFSET))
    a.words.append(('bne', m.T7, m.T2, 'native')); e(m.NOP)
    if not dungeon:
        # Town local +Z is Up; screen right=(Fz,-Fx), not its mirror.
        e(m.lwc1(0, m.SP, frame+0x70)); e(m.lwc1(1, m.SP, frame+0x78))
        e(m.lwc1(2, m.T3, mm.SLOT_FORWARD)); e(m.lwc1(3, m.T3, mm.SLOT_FORWARD+4))
        def fp(fn, fd, fs, ft): return 0x46000000 | (ft << 16) | (fs << 11) | (fd << 6) | fn
        e(fp(2, 4, 3, 0)); e(fp(2, 5, 2, 1)); e(m.add_s(4, 4, 5))
        e(fp(2, 5, 3, 1)); e(fp(2, 0, 2, 0)); e(fp(1, 5, 5, 0))
    # All bank reads precede the final sequence check; never publish mixed data.
    e(m.lw(m.T6, m.T0, mm.MB_MOVE_SEQ))
    a.words.append(('bne', m.T6, m.T4, 'native')); e(m.NOP)
    if dungeon:
        e(m.andi(m.V0, m.T5, 7))
    else:
        e(m.swc1(4, m.SP, frame+0x70)); e(m.swc1(5, m.SP, frame+0x78))
    a.beqz(m.ZERO, 'done'); e(m.NOP)
    a.label('native')
    # A separate epilogue keeps native fallback and successful return explicit.
    for i in range(6): e(m.lwc1(i, m.SP, 0x80+i*4))
    for i, reg in enumerate(range(m.T0, m.T7+1)): e(_lq(reg, m.SP, i*16))
    e(m.addiu(m.SP, m.SP, frame))
    if dungeon:
        e(m.j(mm.DUNGEON_SECTOR_FUN)); e(m.NOP)  # preserve caller ra
    else:
        e(mm.TOWN_MOVE_STOCK[0]); e(m.j(mm.TOWN_MOVE_NATIVE)); e(m.NOP)
    a.label('done')
    for i in range(6): e(m.lwc1(i, m.SP, 0x80+i*4))
    for i, reg in enumerate(range(m.T0, m.T7+1)): e(_lq(reg, m.SP, i*16))
    e(m.addiu(m.SP, m.SP, frame))
    e(_r(31, 0, 0, 0, 8) if dungeon else m.j(mm.TOWN_MOVE_RETURN)); e(m.NOP)
    return a.assemble()


TOWN_MOVE_WORDS = movement_words()
DUNGEON_MOVE_WORDS = movement_words(dungeon=True)
TOWN_MOVE_HOOK = (m.j(mm.TOWN_MOVE_CAVE), mm.TOWN_MOVE_STOCK[1])
DUNGEON_MOVE_HOOK = (m.jal(mm.DUNGEON_MOVE_CAVE), mm.DUNGEON_MOVE_STOCK[1])
MOVEMENT_RESOURCES = ((mm.TOWN_MOVE_HOOK, mm.TOWN_MOVE_STOCK, TOWN_MOVE_HOOK,
                       mm.TOWN_MOVE_CAVE, TOWN_MOVE_WORDS),) + tuple(
    (site, mm.DUNGEON_MOVE_STOCK, DUNGEON_MOVE_HOOK, mm.DUNGEON_MOVE_CAVE, DUNGEON_MOVE_WORDS)
    for site in mm.DUNGEON_MOVE_SITES)
assert mm.TOWN_MOVE_CAVE+len(TOWN_MOVE_WORDS)*4 <= mm.TOWN_MOVE_CAVE_END
assert mm.DUNGEON_MOVE_CAVE+len(DUNGEON_MOVE_WORDS)*4 <= mm.DUNGEON_MOVE_CAVE_END


PAD_WORDS=pad_words()
PAD_HOOK=(m.j(mm.PAD_CAVE),mm.PAD_AXIS_STOCK[1])
assert mm.PAD_CAVE+len(PAD_WORDS)*4<=mm.PAD_CAVE_END

WORDS = camera_words()
DUNGEON_WORDS = camera_words(dungeon=True)
HOOK = (m.j(mm.CAVE), mm.CAM_HOOK_WORDS[1])
DUNGEON_HOOK = (m.j(mm.DUNGEON_CAVE), mm.DUNGEON_HOOK_WORDS[1])
RESOURCES = ((mm.CAM_HOOK, mm.CAM_HOOK_WORDS, HOOK, mm.CAVE, WORDS),
             (mm.DUNGEON_HOOK, mm.DUNGEON_HOOK_WORDS, DUNGEON_HOOK, mm.DUNGEON_CAVE, DUNGEON_WORDS))
assert mm.CAVE + 4*len(WORDS) <= mm.CAVE_END
assert mm.DUNGEON_CAVE + 4*len(DUNGEON_WORDS) <= mm.DUNGEON_CAVE_END


def read_words(b, addr, n):
    return tuple(b.read_u32(addr+4*i) for i in range(n))


def movement_state(b):
    states = []
    for address, stock, hook, _, _ in MOVEMENT_RESOURCES:
        words = read_words(b, address, 2)
        states.append('stock' if words == stock else 'applied' if words == hook else 'unknown')
    return 'unknown' if 'unknown' in states else 'stock' if all(x == 'stock' for x in states) else 'applied'


def site_state(b):
    if movement_state(b) == 'unknown': return 'unknown'
    states = []
    for address,stock,hook,_,_ in RESOURCES:
        words = read_words(b,address,2)
        states.append('stock' if words == stock else 'applied' if words == hook else 'unknown')
    if 'unknown' in states: return 'unknown'
    return 'stock' if all(x == 'stock' for x in states) else 'applied'


def preflight(b):
    if site_state(b) == 'unknown':
        raise PatchConflict('unknown Druaga camera hook instructions')
    for _,_,_,address,expected in RESOURCES+MOVEMENT_RESOURCES:
        code = read_words(b,address,len(expected))
        if code != tuple(expected) and any(code):
            raise PatchConflict('Druaga code cave is occupied')
    magic = b.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC):
        raise PatchConflict('Druaga control block is occupied')
    if magic == 0 and any(read_words(b, mm.MOD_BLOCK, mm.BLOCK_SIZE//4)):
        raise PatchConflict('Druaga control block is not empty')


def prepare(b):
    """Validate ALL resources before the first write; leave the hook disconnected."""
    preflight(b)
    for _,_,_,address,words in RESOURCES+MOVEMENT_RESOURCES:
        if read_words(b,address,len(words)) != tuple(words):
            for i,w in enumerate(words): b.write_u32(address+4*i,w)
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC:
        b.write_u32(mm.MOD_BLOCK, mm.MAGIC)


def install(b):
    preflight(b)
    for address,stock,hook,_,_ in RESOURCES:
        if b.read_u32(address) == stock[0]:
            # Delay-slot words are identical to stock: one instruction per site.
            b.write_u32(address,hook[0])


def set_movement(b, on):
    """Connect only completed, preflighted code; FOV-only leaves all sites stock."""
    if movement_state(b) == 'unknown':
        raise PatchConflict('unknown Druaga movement hook instructions')
    if on and any(b.read_u32(address) != hook[0] for address, _, hook, _, _ in MOVEMENT_RESOURCES):
        preflight(b)
    for address, stock, hook, _, _ in MOVEMENT_RESOURCES:
        want = hook[0] if on else stock[0]
        if b.read_u32(address) != want: b.write_u32(address, want)


def uninstall(b):
    state = site_state(b)
    if state == 'unknown':
        raise PatchConflict('unknown Druaga hook during release')
    set_movement(b, False)
    if state == 'applied':
        for address,stock,hook,_,_ in RESOURCES:
            if b.read_u32(address) == hook[0]: b.write_u32(address,stock[0])
