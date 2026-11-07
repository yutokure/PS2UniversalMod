"""Field render transaction and movement-only camera copy for Grandia II.

The host bootstraps ONE jal word. The EE thread owns all other instruction
changes and final detach. Native rig/angles stay untouched; rendering consumes
an NJ camera copy. Queued projection cache entries are never rolled back.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    pass


def _addr(e, reg, value):
    e(m.lui(reg, value >> 16)); e(m.ori(reg, reg, value))


def _r(rs, rt, rd, sa, fn):
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn


def _branch(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label)); a.emit(m.NOP)


def _copy(e, src, dst, length):
    # Deliberately word copies: native camera structures need only 4-byte alignment.
    _addr(e, m.T2, src); _addr(e, m.T3, dst)
    for off in range(0, length, 4):
        e(m.lw(m.T4, m.T2, off)); e(m.sw(m.T4, m.T3, off))


def _guards(a, reject):
    e = a.emit
    for address, value in mm.EXACT_GUARDS:
        _addr(e, m.T2, address); e(m.lw(m.T2, m.T2, 0))
        _addr(e, m.T3, value)
        _branch(a, 'bne', m.T2, m.T3, reject)
    # Both ordinary outside (8) AND fixed inside (0) are accepted.
    _addr(e, m.T2, mm.CAMERA); e(m.lw(m.T2, m.T2, 0))
    e(m.andi(m.T2, m.T2, 0xFFF7))
    _branch(a, 'bne', m.T2, m.ZERO, reject)


def _bank(a, reject):
    """t0=block, t1=bank; coherent snapshot and owned actor/node required."""
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    _branch(a, 'bne', m.T2, m.T3, reject)
    e(m.lw(m.T2, m.T0, mm.MB_FLAGS)); e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT))
    _branch(a, 'beq', m.T2, m.ZERO, reject)
    _guards(a, reject)
    e(m.lw(m.T2, m.T0, mm.MB_SLOT)); e(m.andi(m.T2, m.T2, 1))
    e(_r(0, m.T2, m.T2, 7, 0))
    e(m.addiu(m.T1, m.T0, mm.SLOTS[0])); e(_r(m.T2, m.T1, m.T1, 0, 0x21))
    e(m.lw(m.T5, m.T1, mm.SLOT_SEQUENCE)); e(m.andi(m.T2, m.T5, 1))
    _branch(a, 'bne', m.T2, m.ZERO, reject)
    for off in range(0, mm.SLOT_SIZE, 4):
        e(m.lw(m.T2, m.T1, off)); e(m.sw(m.T2, m.T0, mm.MB_SNAPSHOT + off))
    e(m.lw(m.T2, m.T1, mm.SLOT_SEQUENCE))
    _branch(a, 'bne', m.T2, m.T5, reject)
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS))
    e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT)); _branch(a, 'beq', m.T2, m.ZERO, reject)
    _addr(e, m.T2, mm.PLAYER_PTR); e(m.lw(m.T2, m.T2, 0))
    e(m.lw(m.T3, m.T0, mm.MB_SNAPSHOT + mm.SLOT_PLAYER))
    _branch(a, 'bne', m.T2, m.T3, reject)
    # The bank is validated before publication; exact live owner matches first.
    e(m.lw(m.T2, m.T2, mm.ACTOR_NODE))
    e(m.lw(m.T3, m.T0, mm.MB_SNAPSHOT + mm.SLOT_NODE))
    _branch(a, 'bne', m.T2, m.T3, reject)


RENDER_PAIR = (m.jal(mm.RENDER_CAVE), mm.RENDER_STOCK[1])
TAIL_PAIR = (m.j(mm.TAIL_CAVE), mm.TAIL_STOCK[1])
MOVE_PAIR = (m.jal(mm.MOVE_CAVE), mm.MOVE_STOCK[1])
SITES = ((mm.RENDER_HOOK, mm.RENDER_STOCK, RENDER_PAIR),
         (mm.TAIL_HOOK, mm.TAIL_STOCK, TAIL_PAIR),
         (mm.MOVE_HOOK, mm.MOVE_STOCK, MOVE_PAIR))


def _lifecycle(a, prefix):
    """Validate ALL instruction pairs, then atomically change one-word sites."""
    e = a.emit
    done, conflict = prefix + 'done', prefix + 'conflict'
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    _branch(a, 'bne', m.T2, m.T3, done)
    e(m.lw(m.T2, m.T0, mm.MB_PENDING)); _branch(a, 'bne', m.T2, m.ZERO, done)
    e(m.lw(m.T2, m.T0, mm.MB_COMMAND)); e(m.addiu(m.T3, m.ZERO, mm.CMD_SYNC))
    _branch(a, 'bne', m.T2, m.T3, done)
    e(m.lw(m.T6, m.T0, mm.MB_FLAGS)); e(m.andi(m.T2, m.T6, 1))
    _branch(a, 'bne', m.T2, m.T6, conflict)
    for index, (address, stock, hook) in enumerate(SITES):
        _addr(e, m.T1, address)
        e(m.lw(m.T2, m.T1, 4)); _addr(e, m.T3, stock[1])
        _branch(a, 'bne', m.T2, m.T3, conflict)
        e(m.lw(m.T2, m.T1, 0)); _addr(e, m.T3, stock[0])
        _branch(a, 'beq', m.T2, m.T3, prefix + f'owned{index}')
        _addr(e, m.T3, hook[0]); _branch(a, 'bne', m.T2, m.T3, conflict)
        a.label(prefix + f'owned{index}')
    _branch(a, 'beq', m.T6, m.ZERO, prefix + 'off')
    for address, stock, hook in SITES:
        _addr(e, m.T1, address); _addr(e, m.T2, hook[0]); e(m.sw(m.T2, m.T1, 0))
    _branch(a, 'beq', m.ZERO, m.ZERO, prefix + 'ack')
    a.label(prefix + 'off')
    for address, stock, hook in SITES:
        _addr(e, m.T1, address); _addr(e, m.T2, stock[0]); e(m.sw(m.T2, m.T1, 0))
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    a.label(prefix + 'ack')
    e(m.sw(m.T6, m.T0, mm.MB_ACK)); e(m.addiu(m.T2, m.ZERO, mm.CMD_ACK))
    e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    _branch(a, 'beq', m.ZERO, m.ZERO, done)
    a.label(conflict); e(m.addiu(m.T2, m.ZERO, mm.CMD_CONFLICT))
    e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    a.label(done)


def render_words():
    a = m.Assembler(); e = a.emit
    e(m.addiu(m.SP, m.SP, -0x20)); e(0xFFBF0010)  # sd ra,16(sp)
    # Native camera is evaluated ONCE. Never freeze its smoothing or L1/R1 state.
    e(m.jal(mm.FUN_NATIVE_CAMERA)); e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, mm.MB_PENDING)); _branch(a, 'bne', m.T2, m.ZERO, 'return')
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    # Apply/detach requests even when scene guards prevent Orbit rendering.
    _lifecycle(a, 'render_life_')
    _bank(a, 'return')
    # Save numeric engine outputs, NOT queued projection records/count.
    _copy(e, mm.NJ_STATE, mm.MOD_BLOCK + mm.MB_NATIVE_NJ, mm.NJ_STATE_SIZE)
    # Field VIEW/WORLD still describe the previous frame here. Capture the
    # freshly built native view, and derive its inverse before the Orbit build.
    _copy(e, mm.NJ_VIEW, mm.MOD_BLOCK + mm.MB_NATIVE_WORLD, 0x40)
    _copy(e, mm.NJ_VIEW, mm.MOD_BLOCK + mm.MB_NATIVE_WORLD + 0x40, 0x40)
    _addr(e, m.A0, mm.MOD_BLOCK + mm.MB_NATIVE_WORLD + 0x40)
    e(m.jal(mm.FUN_INVERT)); e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    for address, offset in ((mm.FIELD_FOCAL, mm.MB_NATIVE_FOCAL),
                            (mm.NJ_FLAGS, mm.MB_NATIVE_FLAGS),
                            (mm.PROJECTION_RECORD_PTR, mm.MB_NATIVE_PROJECTION_PTR)):
        _addr(e, m.T2, address); e(m.lw(m.T2, m.T2, 0)); e(m.sw(m.T2, m.T0, offset))
    _addr(e, m.T2, mm.NJ_STACK_PTR); e(m.lw(m.T2, m.T2, 0)); e(m.sw(m.T2, m.T0, mm.MB_STACK_PTR))
    for off in range(0, 64, 4):
        e(m.lw(m.T3, m.T2, off)); e(m.sw(m.T3, m.T0, mm.MB_NATIVE_STACK + off))
    _copy(e, mm.NJ_CAMERA, mm.MOD_BLOCK + mm.MB_NJ_SCRATCH, mm.NJ_CAMERA_SIZE)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_NODE))
    for i in range(3):
        e(m.lwc1(0, m.T2, mm.NODE_POSITION + i*4))
        for src, dest in ((mm.SLOT_EYE, mm.MB_RENDER_EYE), (mm.SLOT_TARGET, mm.MB_RENDER_TARGET)):
            e(m.lwc1(1, m.T0, mm.MB_SNAPSHOT + src + i*4)); e(m.add_s(1, 0, 1))
            e(m.swc1(1, m.T0, dest + i*4))
        e(m.lw(m.T3, m.T0, mm.MB_RENDER_EYE + i*4))
        e(m.sw(m.T3, m.T0, mm.MB_NJ_SCRATCH + i*4))
        e(m.lw(m.T3, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FORWARD + i*4))
        e(m.sw(m.T3, m.T0, mm.MB_NJ_SCRATCH + 0x0C + i*4))
    e(m.sw(m.ZERO, m.T0, mm.MB_NJ_SCRATCH + 0x18))  # no native camera roll
    e(m.addiu(m.T2, m.ZERO, 1)); e(m.sw(m.T2, m.T0, mm.MB_PENDING))
    e(m.addiu(m.A0, m.T0, mm.MB_NJ_SCRATCH)); e(m.jal(mm.FUN_NJ_CAMERA)); e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lwc1(12, m.T0, mm.MB_NATIVE_FOCAL))
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS)); e(m.andi(m.T2, m.T2, mm.FLAG_FOV))
    _branch(a, 'beq', m.T2, m.ZERO, 'focal')
    e(m.lwc1(12, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FOCAL))
    a.label('focal')
    e(m.swc1(12, m.T0, mm.MB_RENDER_FOCAL))
    _addr(e, m.T2, mm.FIELD_FOCAL); e(m.swc1(12, m.T2, 0))
    e(m.jal(mm.FUN_SET_FOCAL)); e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS)); e(m.sw(m.T2, m.T0, mm.MB_APPLIED))
    e(m.lw(m.T2, m.T0, mm.MB_HEARTBEAT)); e(m.addiu(m.T2, m.T2, 1)); e(m.sw(m.T2, m.T0, mm.MB_HEARTBEAT))
    a.label('return')
    e(0xDFBF0010); e(0x03E00008); e(m.addiu(m.SP, m.SP, 0x20))
    return a.assemble()


def tail_words():
    a = m.Assembler(); e = a.emit
    # Original tail site's delay slot has ALREADY restored the caller's sp.
    e(m.addiu(m.SP, m.SP, -0x20)); e(0xFFBF0010)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0)); _addr(e, m.T3, mm.MAGIC)
    _branch(a, 'bne', m.T2, m.T3, 'native')
    e(m.lw(m.T2, m.T0, mm.MB_PENDING)); _branch(a, 'beq', m.T2, m.ZERO, 'lifecycle')
    # Restore the matrix stack before restoring its saved pointer words.
    e(m.lw(m.T2, m.T0, mm.MB_STACK_PTR))
    for off in range(0, 64, 4):
        e(m.lw(m.T3, m.T0, mm.MB_NATIVE_STACK + off)); e(m.sw(m.T3, m.T2, off))
    _copy(e, mm.MOD_BLOCK + mm.MB_NATIVE_NJ, mm.NJ_STATE, mm.NJ_STATE_SIZE)
    _copy(e, mm.MOD_BLOCK + mm.MB_NATIVE_WORLD, mm.VIEW, 0x80)
    _addr(e, m.T0, mm.MOD_BLOCK)
    for address, offset in ((mm.FIELD_FOCAL, mm.MB_NATIVE_FOCAL),
                            (mm.NJ_FLAGS, mm.MB_NATIVE_FLAGS),
                            (mm.PROJECTION_RECORD_PTR, mm.MB_NATIVE_PROJECTION_PTR)):
        e(m.lw(m.T2, m.T0, offset)); _addr(e, m.T3, address); e(m.sw(m.T2, m.T3, 0))
    # Next culling consumer must rebuild from restored numeric camera state.
    _addr(e, m.T2, 0x233C1C); e(m.sw(m.ZERO, m.T2, 0))
    e(m.sw(m.ZERO, m.T0, mm.MB_PENDING))
    a.label('lifecycle'); _lifecycle(a, 'tail_life_')
    a.label('native'); e(0xDFBF0010); e(m.addiu(m.SP, m.SP, 0x20))
    e(m.j(mm.FUN_NATIVE_TAIL)); e(m.NOP)
    return a.assemble()


def move_words():
    a = m.Assembler(); e = a.emit
    # Preserve untouched pad argument. Only the camera argument changes.
    e(m.addiu(m.SP, m.SP, -0x20)); e(m.sw(m.A0, m.SP, 0x10)); e(m.sw(m.A1, m.SP, 0x14))
    _bank(a, 'native')
    _copy(e, mm.CAMERA, mm.MOD_BLOCK + mm.MB_MOVE_CAMERA, mm.CAMERA_SIZE)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_YAW))
    e(m.sw(m.T2, m.T0, mm.MB_MOVE_CAMERA + 0x58))
    e(m.addiu(m.A1, m.T0, mm.MB_MOVE_CAMERA)); _branch(a, 'beq', m.ZERO, m.ZERO, 'call')
    a.label('native'); e(m.lw(m.A1, m.SP, 0x14))
    a.label('call'); e(m.lw(m.A0, m.SP, 0x10)); e(m.addiu(m.SP, m.SP, 0x20))
    e(m.j(mm.FUN_MOVE)); e(m.NOP)
    return a.assemble()


RENDER_WORDS, TAIL_WORDS, MOVE_WORDS = render_words(), tail_words(), move_words()
RESOURCES = ((mm.RENDER_CAVE, RENDER_WORDS), (mm.TAIL_CAVE, TAIL_WORDS), (mm.MOVE_CAVE, MOVE_WORDS))
assert mm.RENDER_CAVE + len(RENDER_WORDS)*4 <= 0xBA000
assert mm.TAIL_CAVE + len(TAIL_WORDS)*4 <= mm.MOVE_CAVE
assert mm.MOVE_CAVE + len(MOVE_WORDS)*4 <= 0xF6000


def read_words(b, address, count):
    return tuple(b.read_u32(address+i*4) for i in range(count))


def _site_states(b):
    return tuple('stock' if got == stock else 'applied' if got == hook else 'unknown'
                 for address, stock, hook in SITES
                 for got in (read_words(b, address, 2),))


def site_state(b):
    states = _site_states(b)
    if 'unknown' in states: return 'unknown'
    return 'stock' if all(s == 'stock' for s in states) else 'applied'


def ready(b):
    """Lightweight live check, not proof that cave bodies still match.

    Only an adapter already prepared for this exact backend/epoch may use this
    to authorize a hot bank publication. New objects and periodic checks perform
    a full preflight; unknown site/control ownership always rejects immediately.
    """
    states = _site_states(b)
    if 'unknown' in states: raise PatchConflict('unknown Grandia II hook instruction')
    magic = b.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC): raise PatchConflict('Grandia II control block occupied')
    return (magic == mm.MAGIC and all(s == 'applied' for s in states)
            and b.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == mm.FLAG_ORBIT
            and b.read_u32(mm.MOD_BLOCK + mm.MB_ACK) == mm.FLAG_ORBIT)


@dataclass(frozen=True)
class _Inspection:
    backend: object
    states: tuple
    empty_resources: tuple
    needs_magic: bool


def preflight(b):
    """Inspect every owned resource before installation, release or full audit."""
    states = _site_states(b)
    if 'unknown' in states: raise PatchConflict('unknown Grandia II hook instruction')
    empty = []
    for address, words in RESOURCES:
        got = read_words(b, address, len(words))
        if got != tuple(words):
            if any(got): raise PatchConflict('Grandia II code cave occupied')
            empty.append((address, words))
    magic = b.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC): raise PatchConflict('Grandia II control block occupied')
    if not magic and any(read_words(b, mm.MOD_BLOCK, mm.BLOCK_SIZE//4)):
        raise PatchConflict('Grandia II control block not empty')
    return _Inspection(b, states, tuple(empty), not magic)


def _prepare_checked(b, inspection):
    # Reuse ONLY a local result within the same adapter-locked transaction.
    if inspection.backend is not b: raise ValueError('Grandia II inspection backend mismatch')
    for address, words in inspection.empty_resources:
        for i, word in enumerate(words): b.write_u32(address+i*4, word)
    if inspection.needs_magic: b.write_u32(mm.MOD_BLOCK, mm.MAGIC)


def prepare(b):
    inspection = preflight(b)
    _prepare_checked(b, inspection)


def synchronize(b, flags):
    """Synchronize the adapter's prepared transaction, or fully audit removal.

    ORBIT callers must have prepared/audited this backend before publishing the
    bank; an already-acknowledged install uses only the lightweight live check.
    This is not a stand-alone full ownership audit for arbitrary fresh callers.
    Adapter periodic checks detect cave-body-only changes at their next audit
    (normally about one second plus runtime/transport scheduling latency).
    """
    if flags not in (0, mm.FLAG_ORBIT): raise ValueError('invalid Grandia II lifecycle mask')
    # Steady Orbit has no lifecycle change. The caller's initial/periodic audit
    # owns cave-body validation; still reject unknown live site pairs here.
    if flags and ready(b): return
    inspection = preflight(b)
    if not flags and all(s == 'stock' for s in inspection.states): return
    _prepare_checked(b, inspection)
    expected = 'applied' if flags else 'stock'
    b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS, flags)
    b.write_u32(mm.MOD_BLOCK+mm.MB_COMMAND, mm.CMD_SYNC)
    if flags and inspection.states[0] == 'stock':
        b.write_u32(mm.RENDER_HOOK, RENDER_PAIR[0])
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        command = b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
        if command == mm.CMD_CONFLICT: raise PatchConflict('Grandia II guest hook ownership conflict')
        if command == mm.CMD_ACK and b.read_u32(mm.MOD_BLOCK+mm.MB_ACK) == flags:
            states = _site_states(b)
            if all(s == expected for s in states): return
            if 'unknown' in states: raise PatchConflict('unknown Grandia II hook instruction')
        time.sleep(0.005)
    raise PatchConflict('Grandia II hook transaction pending; resume the VM/ordinary field and retry')
