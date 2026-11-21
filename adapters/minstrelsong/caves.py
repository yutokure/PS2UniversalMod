"""Field-only argument substitution; native rig and actor heading are untouched.

The field angle call computes native yaw first (for safe restoration) then the
render yaw. The stock compass disk/needle and walk consumers see that render yaw.
"""
import hashlib
import struct

from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    pass


def _addr(e, reg, address):
    e(m.lui(reg, address >> 16)); e(m.ori(reg, reg, address))


def _guard(a, reject):
    e = a.emit
    # Unsigned (mode - 1) < 2 admits only 1 and 2, including for high-bit inputs.
    # Keep the selector the same length as the previously shipped mode==2 guard.
    assert mm.FIELD_MODES == (1, 2)
    _addr(e, m.T2, mm.CAM_MODE); e(m.lw(m.T2, m.T2, 0))
    e(m.addiu(m.T2, m.T2, -1))
    e(0x2C000000 | (m.T2 << 21) | (m.T3 << 16) | 2)  # sltiu t3,t2,2
    a.beqz(m.T3, reject); e(m.NOP)
    for address, value in (*mm.EXACT_GUARDS, *((p, 0) for p in mm.ZERO_GUARDS)):
        _addr(e, m.T2, address); e(m.lw(m.T2, m.T2, 0))
        _addr(e, m.T3, value)
        a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)


def _bank(a, reject):
    """Copy a coherent host bank into guest-only snapshot, or fall back native."""
    e = a.emit
    _addr(e, m.T1, mm.MOD_BLOCK)
    e(m.lw(m.T2, m.T1, 0)); _addr(e, m.T3, mm.MAGIC)
    a.words.append(('bne', m.T2, m.T3, reject)); e(m.NOP)
    e(m.lw(m.T2, m.T1, mm.MB_FLAGS)); a.beqz(m.T2, reject); e(m.NOP)
    _guard(a, reject)
    e(m.lw(m.T2, m.T1, mm.MB_SLOT)); e(m.andi(m.T2, m.T2, 1))
    e((m.T2 << 16) | (m.T2 << 11) | (7 << 6))  # sll t2,t2,7
    e(m.addiu(m.T3, m.T1, mm.SLOTS[0]))
    e((m.T2 << 21) | (m.T3 << 16) | (m.T3 << 11) | 0x21)
    e(m.lw(m.T4, m.T3, mm.SLOT_SEQUENCE)); e(m.andi(m.T2, m.T4, 1))
    a.bnez(m.T2, reject); e(m.NOP)
    for off in range(0, mm.SLOT_SIZE, 4):
        e(m.lw(m.T2, m.T3, off)); e(m.sw(m.T2, m.T1, mm.MB_SNAPSHOT + off))
    e(m.lw(m.T2, m.T3, mm.SLOT_SEQUENCE))
    a.words.append(('bne', m.T2, m.T4, reject)); e(m.NOP)
    e(m.lw(m.T2, m.T1, mm.MB_SNAPSHOT + mm.SLOT_FLAGS))
    e(m.lw(m.T3, m.T1, mm.MB_FLAGS))
    e((m.T2 << 21) | (m.T3 << 16) | (m.T2 << 11) | 0x24)  # and


def camera_words():
    a = m.Assembler(); e = a.emit
    _addr(e, m.T1, mm.MOD_BLOCK)
    e(m.sw(m.ZERO, m.T1, mm.MB_APPLIED))
    _bank(a, 'native')
    e(m.andi(m.T2, m.T2, mm.FLAG_ORBIT)); a.beqz(m.T2, 'native'); e(m.NOP)
    _addr(e, m.T2, mm.PLAYER)
    for i in range(3):
        e(m.lwc1(0, m.T2, i*4))
        for src, dest in ((mm.SLOT_EYE, mm.MB_RENDER_EYE), (mm.SLOT_TARGET, mm.MB_RENDER_TARGET)):
            e(m.lwc1(1, m.T1, mm.MB_SNAPSHOT + src + i*4))
            e(m.add_s(1, 0, 1)); e(m.swc1(1, m.T1, dest + i*4))
    e(m.lui(m.T2, 0x3F80))
    e(m.sw(m.T2, m.T1, mm.MB_RENDER_EYE + 12)); e(m.sw(m.T2, m.T1, mm.MB_RENDER_TARGET + 12))
    e(m.addiu(m.T2, m.ZERO, mm.FLAG_ORBIT)); e(m.sw(m.T2, m.T1, mm.MB_APPLIED))
    e(m.lw(m.T2, m.T1, mm.MB_HEARTBEAT)); e(m.addiu(m.T2, m.T2, 1))
    e(m.sw(m.T2, m.T1, mm.MB_HEARTBEAT))
    e(m.addiu(m.A1, m.T1, mm.MB_RENDER_EYE)); e(m.addiu(m.A2, m.T1, mm.MB_RENDER_TARGET))
    a.label('native'); e(m.j(mm.FUN_LOOK_AT)); e(m.NOP)
    return a.assemble()


def angle_words():
    a = m.Assembler(); e = a.emit
    e(m.addiu(m.SP, m.SP, -0x20)); e(0xFFBF0010)  # sd ra
    e(m.sw(m.A0, m.SP, 0))
    e(m.jal(mm.FUN_ANGLES)); e(m.NOP)
    _addr(e, m.T1, mm.MOD_BLOCK)
    e(m.swc1(0, m.T1, mm.MB_NATIVE_DISTANCE))
    e(m.lw(m.A0, m.SP, 0)); e(m.lwc1(1, m.A0, 0x14))
    e(m.swc1(1, m.T1, mm.MB_NATIVE_YAW))
    e(m.addiu(m.T2, m.ZERO, 1)); e(m.sw(m.T2, m.T1, mm.MB_NATIVE_VALID))
    e(m.lw(m.T2, m.T1, mm.MB_APPLIED)); a.beqz(m.T2, 'done'); e(m.NOP)
    _guard(a, 'done')
    # Reuse exactly the eye/target accepted by this frame's camera call.
    for off in range(0, 16, 4):
        e(m.lw(m.T2, m.T1, mm.MB_RENDER_EYE + off)); e(m.sw(m.T2, m.A0, off))
    e(m.addiu(m.A1, m.T1, mm.MB_RENDER_TARGET))
    e(0xDFBF0010); e(m.addiu(m.SP, m.SP, 0x20))
    e(m.j(mm.FUN_ANGLES)); e(m.NOP)
    a.label('done'); e(0xDFBF0010); e(m.addiu(m.SP, m.SP, 0x20))
    e(0x03E00008); e(m.NOP)
    return a.assemble()


def fov_words():
    a = m.Assembler(); e = a.emit
    _addr(e, m.T1, mm.MOD_BLOCK)
    # Relinquish only our last exact projection. New native lens values win.
    e(m.lw(m.T2, m.T1, mm.MB_PROJ_OWNED)); a.beqz(m.T2, 'capture'); e(m.NOP)
    _addr(e, m.T3, mm.PROJECTION)
    for p, off in ((0, 0), (0x14, 4)):
        e(m.lw(m.T2, m.T3, p)); e(m.lw(m.T4, m.T1, mm.MB_LAST_PROJ + off))
        a.words.append(('bne', m.T2, m.T4, 'capture')); e(m.NOP)
    for p, off in ((0, 0), (0x14, 4)):
        e(m.lw(m.T2, m.T1, mm.MB_NATIVE_PROJ + off)); e(m.sw(m.T2, m.T3, p))
    a.label('capture'); e(m.sw(m.ZERO, m.T1, mm.MB_PROJ_OWNED))
    _addr(e, m.T3, mm.PROJECTION)
    for p, off in ((0, 0), (0x14, 4)):
        e(m.lw(m.T2, m.T3, p)); e(m.sw(m.T2, m.T1, mm.MB_NATIVE_PROJ + off))
    _bank(a, 'native')
    e(m.andi(m.T2, m.T2, mm.FLAG_FOV)); a.beqz(m.T2, 'native'); e(m.NOP)
    e(m.lw(m.T2, m.T1, mm.MB_SNAPSHOT + mm.SLOT_FOCAL))
    _addr(e, m.T3, mm.PROJECTION); e(m.sw(m.T2, m.T3, 0))
    e(m.sw(m.T2, m.T1, mm.MB_LAST_PROJ)); e(m.sw(m.T2, m.T1, mm.MB_RENDER_PROJ))
    e(m.lwc1(0, m.T1, mm.MB_SNAPSHOT + mm.SLOT_FOCAL))
    _addr(e, m.T2, 0x3F955555); e(0x44800000 | (m.T2 << 16) | (1 << 11))
    e(0x46000002 | (1 << 16))  # mul.s f0,f0,f1
    e(m.swc1(0, m.T3, 0x14)); e(m.swc1(0, m.T1, mm.MB_LAST_PROJ + 4))
    e(m.swc1(0, m.T1, mm.MB_RENDER_PROJ + 4))
    e(m.addiu(m.T2, m.ZERO, 1)); e(m.sw(m.T2, m.T1, mm.MB_PROJ_OWNED))
    a.label('native'); e(m.j(mm.FUN_SET_PROJECTION)); e(m.NOP)
    return a.assemble()


CAMERA_WORDS = camera_words(); ANGLE_WORDS = angle_words(); FOV_WORDS = fov_words()
RESOURCES = ((mm.CAMERA_HOOK, mm.CAMERA_STOCK, (m.jal(mm.CAMERA_CAVE), mm.CAMERA_STOCK[1]), mm.CAMERA_CAVE, CAMERA_WORDS),
             (mm.ANGLE_HOOK, mm.ANGLE_STOCK, (m.jal(mm.ANGLE_CAVE), mm.ANGLE_STOCK[1]), mm.ANGLE_CAVE, ANGLE_WORDS),
             (mm.FOV_HOOK, mm.FOV_STOCK, (m.jal(mm.FOV_CAVE), mm.FOV_STOCK[1]), mm.FOV_CAVE, FOV_WORDS))
assert mm.CAMERA_CAVE + len(CAMERA_WORDS)*4 <= mm.ANGLE_CAVE
assert mm.ANGLE_CAVE + len(ANGLE_WORDS)*4 <= mm.FOV_CAVE
assert mm.FOV_CAVE + len(FOV_WORDS)*4 <= mm.MOD_BLOCK


def read_words(b, address, count):
    return tuple(b.read_u32(address+i*4) for i in range(count))


def site_state(b):
    states = []
    for address, stock, hook, _, _ in RESOURCES:
        got = read_words(b, address, 2)
        states.append('stock' if got == stock else 'applied' if got == hook else 'unknown')
    if 'unknown' in states: return 'unknown'
    return 'stock' if all(s == 'stock' for s in states) else 'applied'


# SHA-256 of the three complete original MSG1 (mode-2-only) wrappers, little endian.
# An exact, *uninstalled* set is present in playable1 and other_area_1. The block
# layout and wrapper lengths did not change. Never rewrite legacy code under a live JAL.
_LEGACY_SHA256 = {
    mm.CAMERA_CAVE: 'c3be1854ea479dcef0b2ca33c3a4f572f605a264a2acd7bf0acd240b6349931b',
    mm.ANGLE_CAVE: 'ea89a807cde8e2dfc860d6ada0ef3c9bec42aaaf102e69ffe5620b74b70c72d2',
    mm.FOV_CAVE: '83188bc04b64d5b364aa8a4ecde4fc0f2ce95f2f3a4435dc60d68b7546472714',
}


def preflight(b):
    """Validate resources without writing. Return True only for an inert legacy set."""
    state = site_state(b)
    if state == 'unknown': raise PatchConflict('unknown Minstrel Song hook')
    legacy = 0
    for _, _, _, address, words in RESOURCES:
        got = read_words(b, address, len(words))
        if got == tuple(words) or not any(got): continue
        if hashlib.sha256(struct.pack(f'<{len(got)}I', *got)).hexdigest() != _LEGACY_SHA256[address]:
            raise PatchConflict('Minstrel Song code cave is occupied')
        legacy += 1
    magic = b.read_u32(mm.MOD_BLOCK)
    if magic not in (0, mm.MAGIC): raise PatchConflict('Minstrel Song control block is occupied')
    if not magic and any(read_words(b, mm.MOD_BLOCK, mm.BLOCK_SIZE//4)):
        raise PatchConflict('Minstrel Song control block is not empty')
    if legacy and (legacy != len(RESOURCES) or state != 'stock' or magic != mm.MAGIC
                   or any(b.read_u32(mm.MOD_BLOCK+off) for off in (mm.MB_FLAGS, mm.MB_APPLIED, mm.MB_PROJ_OWNED))):
        raise PatchConflict('active or incomplete legacy Minstrel Song patch; load an unpatched state')
    return bool(legacy)


def prepare(b):
    preflight(b)
    for _, _, _, address, words in RESOURCES:
        if read_words(b, address, len(words)) != tuple(words):
            for i, word in enumerate(words): b.write_u32(address+i*4, word)
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC: b.write_u32(mm.MOD_BLOCK, mm.MAGIC)


def install(b):
    if preflight(b): raise PatchConflict('legacy Minstrel Song code was not prepared')
    for address, stock, hook, _, _ in reversed(RESOURCES):
        if b.read_u32(address) == stock[0]: b.write_u32(address, hook[0])


def restore_projection(b):
    if b.read_u32(mm.MOD_BLOCK) != mm.MAGIC or not b.read_u32(mm.MOD_BLOCK+mm.MB_PROJ_OWNED): return
    current = (b.read_u32(mm.PROJECTION), b.read_u32(mm.PROJECTION_Y))
    last = read_words(b, mm.MOD_BLOCK+mm.MB_LAST_PROJ, 2)
    if current == last:
        native = read_words(b, mm.MOD_BLOCK+mm.MB_NATIVE_PROJ, 2)
        b.write_u32(mm.PROJECTION, native[0]); b.write_u32(mm.PROJECTION_Y, native[1])
    b.write_u32(mm.MOD_BLOCK+mm.MB_PROJ_OWNED, 0)


def uninstall(b):
    if preflight(b): return  # All hooks already stock; leave the released legacy state untouched.
    owned = b.read_u32(mm.MOD_BLOCK) == mm.MAGIC
    if owned: b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS, 0)
    for address, stock, hook, _, _ in RESOURCES:
        if b.read_u32(address) == hook[0]: b.write_u32(address, stock[0])
    if owned:
        restore_projection(b)
        if b.read_u32(mm.MOD_BLOCK+mm.MB_NATIVE_VALID):
            # Recompute from current native eye/target; never restore an old area pose.
            import math
            eye, target = b.read_floats(mm.CAM_EYE, 3), b.read_floats(mm.CAM_TARGET, 3)
            v = [x-y for x,y in zip(eye,target)]
            if all(math.isfinite(x) for x in v) and sum(x*x for x in v)>1e-8:
                yaw, distance = math.atan2(v[0], v[2]), math.sqrt(sum(x*x for x in v))
                b.write_float_block(mm.CAM_YAW, (yaw, distance, yaw, distance))
        b.write_u32(mm.MOD_BLOCK+mm.MB_APPLIED, 0)
