"""Render-only copied camera, native movement yaw, and guest-thread lifecycle.

Only the main render jal is bootstrapped by the host. Every movement/clock
instruction update (and the final render detach) is executed at render tail on
the EE thread, avoiding PINE/recompiler races. Retained cave code is never wiped.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    """Unknown ownership, unsafe scene or unfinished guest lifecycle."""


def _addr(e, reg, value):
    e(m.lui(reg, value >> 16))
    e(m.ori(reg, reg, value))


def _r(rs, rt, rd, sa, fn):
    return rs << 21 | rt << 16 | rd << 11 | sa << 6 | fn


def _lq(rt, base, off):
    return 0x78000000 | base << 21 | rt << 16 | (off & 0xFFFF)


def _sq(rt, base, off):
    return 0x7C000000 | base << 21 | rt << 16 | (off & 0xFFFF)


def _branch(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label))
    a.emit(m.NOP)


def _guards(a, reject):
    """Integer-only checks shared by render and the mid-function movement cave."""
    e = a.emit
    for address, value in mm.EXACT_GUARDS:
        _addr(e, m.T2, address)
        e(m.lw(m.T2, m.T2, 0))
        _addr(e, m.T3, value)
        _branch(a, "bne", m.T2, m.T3, reject)
    _addr(e, m.T2, mm.FIELD_OWNER)
    e(m.lw(m.T2, m.T2, 0))
    _branch(a, "beq", m.T2, m.ZERO, reject)
    _addr(e, m.T2, mm.NATIVE_FLAGS)
    e(m.lw(m.T2, m.T2, 0))
    _addr(e, m.T3, mm.NATIVE_REJECT_MASK)
    e(_r(m.T2, m.T3, m.T2, 0, 0x24))
    _branch(a, "bne", m.T2, m.ZERO, reject)
    _addr(e, m.T2, mm.INPUT_GUARD_BYTE)
    e(0x90000000 | m.T2 << 21 | m.T2 << 16)  # lbu t2, 0(t2)
    e(m.andi(m.T2, m.T2, mm.INPUT_REJECT_MASK))
    _branch(a, "bne", m.T2, m.ZERO, reject)


def _enabled(a, reject):
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0))
    _addr(e, m.T3, mm.MAGIC)
    _branch(a, "bne", m.T2, m.T3, reject)
    e(m.lw(m.T2, m.T0, mm.MB_FLAGS))
    e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT))
    _branch(a, "beq", m.T2, m.ZERO, reject)
    _guards(a, reject)


def _bank(a, reject):
    """t3=bank, t4=even initial sequence. No FPU registers are touched."""
    e = a.emit
    e(m.lw(m.T2, m.T0, mm.MB_SLOT))
    e(m.andi(m.T2, m.T2, 1))
    e(_r(0, m.T2, m.T2, 7, 0))
    e(m.addiu(m.T3, m.T0, mm.SLOTS[0]))
    e(_r(m.T2, m.T3, m.T3, 0, 0x21))
    e(m.lw(m.T4, m.T3, mm.SLOT_SEQUENCE))
    e(m.andi(m.T2, m.T4, 1))
    _branch(a, "bne", m.T2, m.ZERO, reject)
    e(m.lw(m.T2, m.T3, mm.SLOT_FLAGS))
    e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT))
    _branch(a, "beq", m.T2, m.ZERO, reject)
    e(m.lw(m.T2, m.T3, mm.SLOT_PLAYER))
    _addr(e, m.T1, mm.PLAYER)
    _branch(a, "bne", m.T2, m.T1, reject)


def _owned_pair(a, address, stock, hook, index):
    """Accept two EXACT pairs, never a mixed hook/delay pair."""
    e = a.emit
    _addr(e, m.T1, address)
    e(m.lw(m.T2, m.T1, 0))
    _addr(e, m.T3, stock[0])
    _branch(a, "beq", m.T2, m.T3, f"stock_{index}")
    _addr(e, m.T3, hook[0])
    _branch(a, "bne", m.T2, m.T3, "conflict")
    e(m.lw(m.T2, m.T1, 4))
    _addr(e, m.T3, hook[1])
    _branch(a, "bne", m.T2, m.T3, "conflict")
    _branch(a, "beq", m.ZERO, m.ZERO, f"owned_{index}")
    a.label(f"stock_{index}")
    e(m.lw(m.T2, m.T1, 4))
    _addr(e, m.T3, stock[1])
    _branch(a, "bne", m.T2, m.T3, "conflict")
    a.label(f"owned_{index}")


def _lifecycle(a):
    """Validate ALL native instruction resources before ANY executable store."""
    e = a.emit
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0))
    _addr(e, m.T3, mm.MAGIC)
    _branch(a, "bne", m.T2, m.T3, "return")
    e(m.lw(m.T2, m.T0, mm.MB_PENDING))
    _branch(a, "bne", m.T2, m.ZERO, "return")
    e(m.lw(m.T2, m.T0, mm.MB_COMMAND))
    e(m.addiu(m.T3, m.ZERO, mm.CMD_SYNC))
    _branch(a, "bne", m.T2, m.T3, "return")
    e(m.lw(m.T4, m.T0, mm.MB_FLAGS))
    e(m.andi(m.T2, m.T4, 0xFFFF ^ mm.ALL_FLAGS))
    _branch(a, "bne", m.T2, m.ZERO, "conflict")
    # Upper bits are not legal either.
    e(_r(0, m.T4, m.T2, 16, 2))
    _branch(a, "bne", m.T2, m.ZERO, "conflict")
    _owned_pair(a, mm.RENDER_HOOK, mm.RENDER_STOCK, RENDER_PAIR, 0)
    _owned_pair(a, mm.MOVE_HOOK, mm.MOVE_STOCK, MOVE_PAIR, 1)
    _addr(e, m.T1, mm.MOVE_CONTINUE)
    e(m.lw(m.T2, m.T1, 0))
    _addr(e, m.T3, mm.MOVE_CONTINUE_STOCK)
    _branch(a, "bne", m.T2, m.T3, "conflict")
    _addr(e, m.T1, mm.CLOCK_HOOK)
    e(m.lw(m.T2, m.T1, 0))
    _addr(e, m.T3, mm.CLOCK_STOCK)
    _branch(a, "beq", m.T2, m.T3, "clock_owned")
    _addr(e, m.T3, mm.CLOCK_PAUSED)
    _branch(a, "bne", m.T2, m.T3, "conflict")
    a.label("clock_owned")
    e(m.andi(m.T2, m.T4, mm.FLAG_ORBIT))
    _branch(a, "beq", m.T2, m.ZERO, "move_off")
    _addr(e, m.T2, MOVE_PAIR[0])
    _addr(e, m.T3, MOVE_PAIR[1])
    _branch(a, "beq", m.ZERO, m.ZERO, "write_move")
    a.label("move_off")
    _addr(e, m.T2, mm.MOVE_STOCK[0])
    _addr(e, m.T3, mm.MOVE_STOCK[1])
    a.label("write_move")
    _addr(e, m.T1, mm.MOVE_HOOK)
    e(m.sw(m.T2, m.T1, 0))
    e(m.sw(m.T3, m.T1, 4))
    e(m.andi(m.T2, m.T4, mm.FLAG_TIME))
    _branch(a, "beq", m.T2, m.ZERO, "time_off")
    _addr(e, m.T2, mm.CLOCK_PAUSED)
    _branch(a, "beq", m.ZERO, m.ZERO, "write_clock")
    a.label("time_off")
    _addr(e, m.T2, mm.CLOCK_STOCK)
    a.label("write_clock")
    _addr(e, m.T1, mm.CLOCK_HOOK)
    e(m.sw(m.T2, m.T1, 0))
    _branch(a, "bne", m.T4, m.ZERO, "ack")
    _addr(e, m.T1, mm.RENDER_HOOK)
    _addr(e, m.T2, mm.RENDER_STOCK[0])
    e(m.sw(m.T2, m.T1, 0))
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    a.label("ack")
    e(m.sw(m.T4, m.T0, mm.MB_ACK_FLAGS))
    e(m.addiu(m.T2, m.ZERO, mm.CMD_ACK))
    e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    _branch(a, "beq", m.ZERO, m.ZERO, "return")
    a.label("conflict")
    e(m.addiu(m.T2, m.ZERO, mm.CMD_CONFLICT))
    e(m.sw(m.T2, m.T0, mm.MB_COMMAND))
    a.label("return")


RENDER_PAIR = (m.jal(mm.RENDER_CAVE), mm.RENDER_STOCK[1])
MOVE_PAIR = (m.j(mm.MOVE_CAVE), m.NOP)


def render_words():
    a = m.Assembler()
    e = a.emit
    e(m.addiu(m.SP, m.SP, -0x40))
    e(_sq(31, m.SP, 0x20))  # leave outgoing argument home area untouched
    e(m.sw(m.ZERO, m.SP, 0x30))  # this invocation owns the forward backup
    # Clear stale rendered output even when this frame fails a scene guard.
    # An outer transaction owns APPLIED while a nested invocation is in flight.
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T0, 0))
    _addr(e, m.T3, mm.MAGIC)
    _branch(a, "bne", m.T2, m.T3, "native")
    e(m.lw(m.T2, m.T0, mm.MB_PENDING))
    _branch(a, "bne", m.T2, m.ZERO, "native")
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    _enabled(a, "native")
    _addr(e, m.T2, mm.CAMERA)
    _branch(a, "bne", m.A0, m.T2, "native")
    e(m.lw(m.T2, m.T0, mm.MB_PENDING))
    _branch(a, "bne", m.T2, m.ZERO, "native")
    e(m.sw(m.ZERO, m.T0, mm.MB_APPLIED))
    _bank(a, "native")
    for off in range(0, mm.SLOT_SIZE, 16):
        e(_lq(m.T2, m.T3, off))
        e(_sq(m.T2, m.T0, mm.MB_SNAPSHOT + off))
    e(m.lw(m.T2, m.T3, mm.SLOT_SEQUENCE))
    _branch(a, "bne", m.T2, m.T4, "native")
    # The copied camera is private; native rig fields are never overwritten.
    _addr(e, m.T3, mm.CAMERA)
    for off in range(0, mm.CAMERA_SIZE, 16):
        e(_lq(m.T2, m.T3, off))
        e(_sq(m.T2, m.T0, mm.MB_CAMERA_SCRATCH + off))
    _addr(e, m.T1, mm.PLAYER)
    for i in range(3):
        e(m.lwc1(0, m.T1, i * 4))
        for source, output in ((mm.SLOT_EYE, mm.MB_RENDER_EYE),
                               (mm.SLOT_TARGET, mm.MB_RENDER_TARGET)):
            e(m.lwc1(1, m.T0, mm.MB_SNAPSHOT + source + i * 4))
            e(m.add_s(1, 0, 1))
            e(m.swc1(1, m.T0, output + i * 4))
            if source == mm.SLOT_EYE:
                e(m.swc1(1, m.T0, mm.MB_CAMERA_SCRATCH + i * 4))
    for source, dest in ((mm.SLOT_PITCH, 0x10), (mm.SLOT_YAW, 0x14)):
        e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + source))
        e(m.sw(m.T2, m.T0, mm.MB_CAMERA_SCRATCH + dest))
    e(m.sw(m.ZERO, m.T0, mm.MB_CAMERA_SCRATCH + 0x18))
    # Feed the original builder, not a late projection-output mirror. This also
    # rebuilds the game's focal-dependent clipping matrices from the same input.
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS))
    e(m.andi(m.T2, m.T2, mm.FLAG_FOV))
    _branch(a, "beq", m.T2, m.ZERO, "native_focal")
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FOCAL))
    e(m.sw(m.T2, m.T0, mm.MB_CAMERA_SCRATCH + 0x7C))
    a.label("native_focal")
    _addr(e, m.T3, mm.CAM_FORWARD)
    e(_lq(m.T2, m.T3, 0))
    e(_sq(m.T2, m.T0, mm.MB_SAVED_FORWARD))
    e(m.addiu(m.T2, m.ZERO, mm.FLAG_ORBIT))
    e(m.sw(m.T2, m.SP, 0x30))
    e(m.sw(m.T2, m.T0, mm.MB_PENDING))
    e(m.lw(m.T2, m.T0, mm.MB_SNAPSHOT + mm.SLOT_FLAGS))
    e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT | mm.FLAG_FOV))
    e(m.sw(m.T2, m.T0, mm.MB_APPLIED))
    e(m.lw(m.T2, m.T0, mm.MB_HEARTBEAT))
    e(m.addiu(m.T2, m.T2, 1))
    e(m.sw(m.T2, m.T0, mm.MB_HEARTBEAT))
    e(m.addiu(m.A0, m.T0, mm.MB_CAMERA_SCRATCH))
    a.label("native")
    e(m.jal(mm.FUN_BUILD_VIEW))
    e(m.NOP)
    _addr(e, m.T0, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.SP, 0x30))
    _branch(a, "beq", m.T2, m.ZERO, "tail")
    _addr(e, m.T3, mm.CAM_FORWARD)
    e(_lq(m.T2, m.T0, mm.MB_SAVED_FORWARD))
    e(_sq(m.T2, m.T3, 0))
    e(m.sw(m.ZERO, m.T0, mm.MB_PENDING))
    a.label("tail")
    # Lifecycle is integer-only and does not modify native return values or FPU.
    _lifecycle(a)
    e(_lq(31, m.SP, 0x20))
    e(m.addiu(m.SP, m.SP, 0x40))
    e(0x03E00008)
    e(m.NOP)
    return a.assemble()


def movement_words():
    a = m.Assembler()
    e = a.emit
    saved = (m.T0, m.T1, m.T2, m.T3, m.T4, m.T5)
    frame = len(saved) * 16
    e(m.addiu(m.SP, m.SP, -frame))
    for i, reg in enumerate(saved):
        e(_sq(reg, m.SP, i * 16))
    # Reproduce the displaced native load unconditionally, including on success.
    e(m.lw(m.V0, 28, mm.CAMERA_GP_OFFSET))
    _enabled(a, "fallback")
    _addr(e, m.T2, mm.PLAYER)
    _branch(a, "bne", m.S2, m.T2, "fallback")
    _bank(a, "fallback")
    # Keep the candidate in a saved integer register until the sequence is stable;
    # f0 is the caller's input angle, and f12 is our only intentional FPU output.
    e(m.lw(m.T5, m.T3, mm.SLOT_YAW))
    e(m.lw(m.T2, m.T3, mm.SLOT_SEQUENCE))
    _branch(a, "bne", m.T2, m.T4, "fallback")
    e(0x44800000 | m.T5 << 16 | 12 << 11)  # mtc1 t5, f12
    _branch(a, "beq", m.ZERO, m.ZERO, "finish")
    a.label("fallback")
    e(m.lwc1(12, m.V0, 0x14))
    a.label("finish")
    for i, reg in enumerate(saved):
        e(_lq(reg, m.SP, i * 16))
    e(m.addiu(m.SP, m.SP, frame))
    e(m.j(mm.MOVE_CONTINUE))
    e(m.NOP)
    return a.assemble()


RENDER_WORDS = render_words()
MOVE_WORDS = movement_words()
RESOURCES = ((mm.RENDER_HOOK, mm.RENDER_STOCK, RENDER_PAIR, mm.RENDER_CAVE, RENDER_WORDS),
             (mm.MOVE_HOOK, mm.MOVE_STOCK, MOVE_PAIR, mm.MOVE_CAVE, MOVE_WORDS))
assert mm.RENDER_CAVE + len(RENDER_WORDS) * 4 <= mm.MOVE_CAVE
assert mm.MOVE_CAVE + len(MOVE_WORDS) * 4 <= mm.MOD_BLOCK
assert mm.MOD_BLOCK + mm.BLOCK_SIZE <= mm.RESERVED_END


def read_words(backend, address, count):
    return tuple(backend.read_u32(address + i * 4) for i in range(count))


def site_state(backend):
    states = []
    for address, stock, hook, _, _ in RESOURCES:
        pair = read_words(backend, address, 2)
        states.append("stock" if pair == stock else "applied" if pair == hook else "unknown")
    clock = backend.read_u32(mm.CLOCK_HOOK)
    states.append("stock" if clock == mm.CLOCK_STOCK else
                  "applied" if clock == mm.CLOCK_PAUSED else "unknown")
    if "unknown" in states:
        return "unknown"
    return "stock" if all(state == "stock" for state in states) else "applied"


@dataclass(frozen=True)
class _Inspection:
    """One locked transaction's inspection, never cached across adapter calls."""
    site_state: str
    needs_magic: bool
    empty_caves: tuple[int, ...]


def preflight(backend):
    """Read all resources once before any write and return an immutable plan.

    The adapter may pass this result only to private checked helpers during the
    SAME RLock transaction. Public preparation/lifecycle APIs always inspect for
    themselves; no host-side safety lease or cross-publication cache is created.
    """
    state = site_state(backend)
    if state == "unknown" or backend.read_u32(mm.MOVE_CONTINUE) != mm.MOVE_CONTINUE_STOCK:
        raise PatchConflict("unknown Innocent Life hook, delay or movement continuation")
    empty = []
    for _, _, _, address, words in RESOURCES:
        actual = read_words(backend, address, len(words))
        if actual != tuple(words):
            if any(actual) or state != "stock":
                raise PatchConflict("Innocent Life code cave is occupied, damaged or still reachable")
            empty.append(address)
    magic = backend.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC):
        raise PatchConflict("Innocent Life control block is occupied")
    if state != "stock" and magic != mm.MAGIC:
        raise PatchConflict("Innocent Life active code has no owned control block")
    if not magic and any(read_words(backend, mm.MOD_BLOCK, mm.BLOCK_SIZE // 4)):
        raise PatchConflict("Innocent Life control block is not empty")
    return _Inspection(state, magic == 0, tuple(empty))


def _prepare_checked(backend, inspection):
    """Consume this transaction's read-only plan without rereading code blobs."""
    for _, _, _, address, words in RESOURCES:
        if address in inspection.empty_caves:
            for i, word in enumerate(words):
                backend.write_u32(address + i * 4, word)
    if inspection.needs_magic:
        backend.write_u32(mm.MOD_BLOCK, mm.MAGIC)
    return _Inspection(inspection.site_state, False, ())


def prepare(backend):
    return _prepare_checked(backend, preflight(backend))


def matches(backend, flags):
    return (read_words(backend, mm.RENDER_HOOK, 2) == (RENDER_PAIR if flags else mm.RENDER_STOCK)
            and read_words(backend, mm.MOVE_HOOK, 2) ==
            (MOVE_PAIR if flags & mm.FLAG_ORBIT else mm.MOVE_STOCK)
            and backend.read_u32(mm.MOVE_CONTINUE) == mm.MOVE_CONTINUE_STOCK
            and backend.read_u32(mm.CLOCK_HOOK) ==
            (mm.CLOCK_PAUSED if flags & mm.FLAG_TIME else mm.CLOCK_STOCK))


def _wait_ack(backend, flags, deadline):
    while True:
        result = backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)
        if result == mm.CMD_ACK:
            if (backend.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) != flags
                    or not matches(backend, flags)):
                raise PatchConflict("Innocent Life guest acknowledgement has inconsistent instruction readback")
            return
        if result == mm.CMD_CONFLICT:
            raise PatchConflict("Innocent Life instructions changed during guest lifecycle; no forced restore")
        if time.monotonic() >= deadline:
            raise PatchConflict("Innocent Life guest lifecycle is paused or unavailable; resume before enabling/restoring")
        time.sleep(0.001)


def sync(backend, flags):
    """Synchronize an independently owned Orbit/clock mask, bounded to 0.5 s.

    Unknown code is never force-restored. A paused emulator keeps the command
    pending and the intact bootstrap attached; resume then retry the same action.
    """
    if flags & ~mm.ALL_FLAGS:
        raise ValueError("unsupported Innocent Life lifecycle flag")
    _sync_checked(backend, flags, preflight(backend))


def _sync_checked(backend, flags, inspection):
    """Private continuation of the SAME fully inspected adapter transaction."""
    magic = not inspection.needs_magic
    if not flags and inspection.site_state == "stock":
        if magic:
            backend.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, 0)
            backend.write_u32(mm.MOD_BLOCK + mm.MB_APPLIED, 0)
            backend.write_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS, 0)
            backend.write_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_ACK)
        return
    if not magic:
        raise PatchConflict("Innocent Life lifecycle requires prepared caves and banks")
    command = backend.read_u32(mm.MOD_BLOCK + mm.MB_COMMAND)
    if command == mm.CMD_CONFLICT:
        raise PatchConflict("Innocent Life guest lifecycle conflict; load a stock state before retrying")
    deadline = time.monotonic() + 0.5
    if command == mm.CMD_SYNC:
        # Never overwrite a pending request: its guest may already have sampled
        # the old mask. Drain that transaction first, sharing the same deadline.
        pending = backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS)
        _wait_ack(backend, pending, deadline)
        command = mm.CMD_ACK
    if (matches(backend, flags) and command == mm.CMD_ACK
            and backend.read_u32(mm.MOD_BLOCK + mm.MB_ACK_FLAGS) == flags
            and backend.read_u32(mm.MOD_BLOCK + mm.MB_FLAGS) == flags):
        return
    # Decide bootstrap BEFORE publishing SYNC: an already attached guest may
    # acknowledge mask=0 and detach immediately after that command write. Reading
    # the site afterwards would race the detach and incorrectly reattach it.
    bootstrap = backend.read_u32(mm.RENDER_HOOK) == mm.RENDER_STOCK[0]
    backend.write_u32(mm.MOD_BLOCK + mm.MB_FLAGS, flags)
    backend.write_u32(mm.MOD_BLOCK + mm.MB_COMMAND, mm.CMD_SYNC)
    if bootstrap:
        backend.write_u32(mm.RENDER_HOOK, RENDER_PAIR[0])
    _wait_ack(backend, flags, deadline)


def uninstall(backend):
    sync(backend, 0)
