"""Code caves for Suikoden V: the camera override and the right-stick block.

Camera cave
-----------
``FUN_00243E10`` (the field camera update) stores the focus, the distance, the pitch and
the yaw into the camera globals and then sets the FOV.  The cave replaces that stretch
(``CAM_HOOK`` .. ``CAM_RETURN``) with the same stores, except that each value can come
from the mod block instead of the game's own goal value:

* flag ``FLAG_ANGLES``   pitch and yaw
* flag ``FLAG_DISTANCE`` distance
* flag ``FLAG_FOV``      field of view
* flag ``FLAG_OFFSET``   a world offset added to the focus

With every flag clear the cave stores exactly what the game stored.  The cave also writes
the camera control object pointer, a heartbeat counter and the game's own goal values
into the mod block, so the host can see them without an extra scan.

The hook is two words at ``CAM_HOOK``: ``j CAVE_CAMERA`` and a ``nop`` in its delay slot.
The cave then redoes the whole stretch, so the rest of the old code is never reached.
It uses only t1..t3 and f4..f8, which the function does not hold across the stretch.

Zoom cave
---------
``FUN_00244150`` reads the right stick (R1 is the button) to step the zoom.  The cave
runs first, and with ``FLAG_BLOCK_RSTICK`` set it writes 0 to the two right-stick bytes,
so the game sees a centred stick.  The left stick and every button, R1 included, are not
touched.  The hook is ``j CAVE_ZOOM`` at the entry; the entry's second word
(``sll v0,a2,2``) already runs in the delay slot, so the cave redoes only the first
(``addiu sp,sp,-0x70``) and returns to the third.

Both hooks are installed with compare-and-swap: a call site is changed only while it holds
the original or our own word, and an unknown word raises ``CavePatchError``.
"""
from __future__ import annotations

from core import mips_asm as m

from . import memory_map as mm


class CavePatchError(RuntimeError):
    """A hook site or the cave area holds something this module did not write."""


def _mb(off: int) -> int:
    return mm.MOD_BLOCK + off


def camera_cave_words() -> list[int]:
    a = m.Assembler()
    e = a.emit
    base = mm.MOD_BLOCK
    e(m.lui(m.T1, base >> 16))
    e(m.ori(m.T1, m.T1, base & 0xFFFF))
    e(m.lw(m.T2, m.T1, mm.MB_FLAGS))                 # t2 = flags
    e(m.lw(m.T3, m.T1, mm.MB_HEARTBEAT))
    e(m.addiu(m.T3, m.T3, 1))
    e(m.sw(m.T3, m.T1, mm.MB_HEARTBEAT))
    e(m.sw(m.S4, m.T1, mm.MB_CTL_PTR))               # s4 = the camera control object
    # the game's own goal values (s3 = object + 4)
    for src, dst in ((0x18, mm.MB_NATIVE_DISTANCE), (0x1C, mm.MB_NATIVE_PITCH),
                     (0x20, mm.MB_NATIVE_YAW), (0x24, mm.MB_NATIVE_FOV)):
        e(m.lwc1(4 if src == 0x18 else 5 if src == 0x1C else 6 if src == 0x20 else 7, m.S3, src))
        e(m.swc1(4 if src == 0x18 else 5 if src == 0x1C else 6 if src == 0x20 else 7, m.T1, dst))
    # focus = followed point + the game's offset, then the mod offset
    e(m.andi(m.T3, m.T2, mm.FLAG_OFFSET))
    e(m.add_s(2, 3, 2))                              # f2 = focus.x + offset.x   (original)
    e(m.swc1(2, m.T1, mm.MB_NATIVE_FOCUS))
    a.beqz(m.T3, "x")
    e(m.NOP)
    e(m.lwc1(8, m.T1, mm.MB_OFF_X))
    e(m.add_s(2, 2, 8))
    a.label("x")
    e(m.swc1(2, m.T0, -0x2424))                      # G_FOCUS.x
    e(m.lwc1(2, m.S3, 0x10))
    e(m.add_s(1, 2, 1))                              # f1 = focus.y + offset.y
    e(m.swc1(1, m.T1, mm.MB_NATIVE_FOCUS + 4))
    a.beqz(m.T3, "y")
    e(m.NOP)
    e(m.lwc1(8, m.T1, mm.MB_OFF_Y))
    e(m.add_s(1, 1, 8))
    a.label("y")
    e(m.swc1(1, m.A3, -0x2420))                      # G_FOCUS.y
    e(m.lwc1(1, m.S3, 0x14))
    e(m.add_s(0, 1, 0))                              # f0 = focus.z + offset.z
    e(m.swc1(0, m.T1, mm.MB_NATIVE_FOCUS + 8))
    a.beqz(m.T3, "z")
    e(m.NOP)
    e(m.lwc1(8, m.T1, mm.MB_OFF_Z))
    e(m.add_s(0, 0, 8))
    a.label("z")
    e(m.swc1(0, m.A2, -0x241C))                      # G_FOCUS.z
    # distance
    e(m.andi(m.T3, m.T2, mm.FLAG_DISTANCE))
    e(m.mov_s(0, 4))
    a.beqz(m.T3, "d")
    e(m.NOP)
    e(m.lwc1(0, m.T1, mm.MB_DISTANCE))
    a.label("d")
    e(m.swc1(0, m.A1, -0x2400))                      # G_DISTANCE
    # pitch and yaw
    e(m.andi(m.T3, m.T2, mm.FLAG_ANGLES))
    e(m.mov_s(0, 5))
    a.beqz(m.T3, "p")
    e(m.NOP)
    e(m.lwc1(0, m.T1, mm.MB_PITCH))
    a.label("p")
    e(m.swc1(0, m.A0, -0x240C))                      # G_PITCH
    e(m.mov_s(0, 6))
    a.beqz(m.T3, "w")
    e(m.NOP)
    e(m.lwc1(0, m.T1, mm.MB_YAW))
    a.label("w")
    e(m.swc1(0, m.V1, -0x2408))                      # G_YAW
    e(m.sw(m.ZERO, m.V0, -0x2404))                   # the game clears the word after it
    # field of view
    e(m.andi(m.T3, m.T2, mm.FLAG_FOV))
    e(m.mov_s(12, 7))
    a.beqz(m.T3, "f")
    e(m.NOP)
    e(m.lwc1(12, m.T1, mm.MB_FOV))
    a.label("f")
    e(m.jal(mm.FUN_FOV))
    e(m.NOP)
    e(m.lwc1(13, m.S3, 0x2C))                        # far
    e(m.jal(mm.FUN_NEARFAR))
    e(m.lwc1(12, m.S3, 0x28))                        # near (delay slot, as in the game)
    e(m.j(mm.CAM_RETURN))
    e(m.NOP)
    return a.assemble()


def zoom_cave_words() -> list[int]:
    a = m.Assembler()
    e = a.emit
    base = mm.MOD_BLOCK
    e(m.addiu(m.SP, m.SP, -0x70))                    # the entry's first instruction
    e(m.lui(m.T8, base >> 16))
    e(m.ori(m.T8, m.T8, base & 0xFFFF))
    e(m.lw(m.T9, m.T8, mm.MB_FLAGS))
    e(m.andi(m.T9, m.T9, mm.FLAG_BLOCK_RSTICK))
    a.beqz(m.T9, "out")
    e(m.lui(m.T9, 0x83))                             # delay slot, harmless when skipped
    e(m.sb(m.ZERO, m.T9, mm.PAD_RIGHT_X - 0x830000))
    e(m.sb(m.ZERO, m.T9, mm.PAD_RIGHT_Y - 0x830000))
    a.label("out")
    e(m.j(mm.ZOOM_RETURN))
    e(m.NOP)
    return a.assemble()


CAMERA_WORDS = camera_cave_words()
ZOOM_WORDS = zoom_cave_words()
CAMERA_HOOK = (m.j(mm.CAVE_CAMERA), m.NOP)
ZOOM_HOOK = (m.j(mm.CAVE_ZOOM), mm.ZOOM_HOOK_WORDS[1])

assert mm.CAVE_CAMERA + 4 * len(CAMERA_WORDS) <= mm.CAVE_ZOOM
assert mm.CAVE_ZOOM + 4 * len(ZOOM_WORDS) <= mm.CAVE_END


def _read(backend, addr: int, count: int) -> list[int]:
    return [backend.read_u32(addr + 4 * i) for i in range(count)]


def _site_state(backend, addr: int, original, hooked) -> str:
    have = tuple(_read(backend, addr, 2))
    if have == tuple(original):
        return "original"
    if have == tuple(hooked):
        return "patched"
    return "unknown"


def camera_site_state(backend) -> str:
    return _site_state(backend, mm.CAM_HOOK, mm.CAM_HOOK_WORDS, CAMERA_HOOK)


def zoom_site_state(backend) -> str:
    return _site_state(backend, mm.ZOOM_HOOK, mm.ZOOM_HOOK_WORDS, ZOOM_HOOK)


def _write_cave(backend, addr: int, words: list[int]) -> None:
    have = _read(backend, addr, len(words))
    if have == words:
        return
    if any(have):
        raise CavePatchError(f"cave area 0x{addr:08X} is not free")
    for i, w in enumerate(words):
        backend.write_u32(addr + 4 * i, w)


def _init_block(backend) -> None:
    if backend.read_u32(_mb(mm.MB_MAGIC)) != mm.MAGIC:
        for off in range(0, 0x80, 4):
            backend.write_u32(_mb(off), 0)
        backend.write_u32(_mb(mm.MB_MAGIC), mm.MAGIC)


def install_camera(backend) -> None:
    """Write the cave and the mod block, then point the camera site at it (idempotent)."""
    state = camera_site_state(backend)
    if state == "unknown":
        raise CavePatchError(f"camera site 0x{mm.CAM_HOOK:08X} holds an unexpected word")
    _write_cave(backend, mm.CAVE_CAMERA, CAMERA_WORDS)
    _init_block(backend)
    if state == "original":
        # the delay-slot word first, so the jump never meets the old second word
        backend.write_u32(mm.CAM_HOOK + 4, CAMERA_HOOK[1])
        backend.write_u32(mm.CAM_HOOK, CAMERA_HOOK[0])


def uninstall_camera(backend) -> None:
    """Give the game its own stretch back.  Does nothing when the site is not ours."""
    if camera_site_state(backend) == "patched":
        backend.write_u32(mm.CAM_HOOK, mm.CAM_HOOK_WORDS[0])
        backend.write_u32(mm.CAM_HOOK + 4, mm.CAM_HOOK_WORDS[1])


def install_zoom(backend) -> None:
    state = zoom_site_state(backend)
    if state == "unknown":
        raise CavePatchError(f"zoom site 0x{mm.ZOOM_HOOK:08X} holds an unexpected word")
    _write_cave(backend, mm.CAVE_ZOOM, ZOOM_WORDS)
    _init_block(backend)
    if state == "original":
        backend.write_u32(mm.ZOOM_HOOK, ZOOM_HOOK[0])


def uninstall_zoom(backend) -> None:
    if zoom_site_state(backend) == "patched":
        backend.write_u32(mm.ZOOM_HOOK, mm.ZOOM_HOOK_WORDS[0])


# --- mod block access ------------------------------------------------------------
def read_flags(backend) -> int:
    return backend.read_u32(_mb(mm.MB_FLAGS))


def write_flags(backend, flags: int) -> None:
    backend.write_u32(_mb(mm.MB_FLAGS), flags & 0xFFFFFFFF)


def block_valid(backend) -> bool:
    return backend.read_u32(_mb(mm.MB_MAGIC)) == mm.MAGIC
