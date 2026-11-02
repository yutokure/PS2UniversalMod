"""Code cave that scales the field camera's view-projection for the field of view.

The game builds the 4x4 view-projection at ``CAM_VP`` every frame and loads it into the
VU with ``jal FUN_001AA080`` at ``VP_LOAD_CALL``.  The same call also loads the
view-projection of the map and the other overlays, from other structs.  The cave sits on
that call.  Only when the flag is set and the matrix being loaded is the field camera's
(``a0 == CAM_VP``) does it multiply columns 0 and 1 by the block's ratio.  Columns 0 and
1 carry the x and y projection scales, so the ratio is exactly the field-of-view change,
and the scaling is about the clip origin, so the screen centre stays fixed.  Everything
else (the map, the overlays) keeps its own matrix and its size.

Installed with compare-and-swap:
  VP_LOAD_CALL   jal 0x001AA080 (0x0C06A820)  ->  j FOV_CAVE
  FOV_CAVE       if flag and a0 == CAM_VP: scale; jal 0x001AA080; nop; j VP_LOAD_RETURN; nop
The delay slot of the original call (a store) is untouched, so it still runs before the
cave.  ``uninstall_call_site`` puts the original call back and leaves the cave words in
place (they do nothing without the call site).
"""
from __future__ import annotations

from . import memory_map as mm


class CavePatchError(RuntimeError):
    """The call site or the cave area holds something this module did not write."""


def _j(target: int) -> int:
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def _jal(target: int) -> int:
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def _lui_t0_block() -> list[int]:
    base = mm.FOV_BLOCK
    return [
        0x3C080000 | (base >> 16),                    # lui  t0,hi(FOV_BLOCK)
        0x35080000 | (base & 0xFFFF),                 # ori  t0,t0,lo(FOV_BLOCK)
    ]


def cave_words() -> list[int]:
    """The cave as 32-bit instructions, starting at ``FOV_CAVE``."""
    scale = [0xC5080000]                                   # lwc1 f8,0x00(t0)   ratio
    for off in mm.VP_COLUMN_OFFSETS:
        scale += [
            0xC4840000 | off,                              # lwc1 f4,off(a0)
            0x46082102,                                    # mul.s f4,f4,f8
            0xE4840000 | off,                              # swc1 f4,off(a0)
        ]
    jal_index = 9 + len(scale)                             # nine head words come first
    words = _lui_t0_block()
    words += [
        0x8D090000 | (mm.FOV_BLOCK_FLAG - mm.FOV_BLOCK),   # lw   t1,flag(t0)
        0x11200000 | (jal_index - 4),                      # beq  t1,zero,-> jal
        0x00000000,                                        # nop
        0x3C0A0000 | (mm.CAM_VP >> 16),                    # lui  t2,hi(CAM_VP)
        0x354A0000 | (mm.CAM_VP & 0xFFFF),                 # ori  t2,t2,lo(CAM_VP)
        0x148A0000 | (jal_index - 8),                      # bne  a0,t2,-> jal  (not the camera)
        0x00000000,                                        # nop
    ]
    words += scale
    words += [
        _jal(mm.VP_LOAD_TARGET),                           # jal  FUN_001AA080 (the original call)
        0x00000000,                                        # nop
        _j(mm.VP_LOAD_RETURN),                             # j    0x001A9A30
        0x00000000,                                        # nop
    ]
    return words


def _read_words(backend, addr: int, count: int) -> list[int]:
    return [backend.read_u32(addr + 4 * i) for i in range(count)]


def call_site_state(backend) -> str:
    """'original', 'patched' or 'unknown' for the jal at VP_LOAD_CALL."""
    word = backend.read_u32(mm.VP_LOAD_CALL)
    if word == mm.VP_LOAD_WORD:
        return "original"
    if word == _j(mm.FOV_CAVE):
        return "patched"
    return "unknown"


def install(backend) -> None:
    """Write the cave (if absent) and point the call site at it.  Idempotent."""
    words = cave_words()
    have = _read_words(backend, mm.FOV_CAVE, len(words))
    if have != words:
        if any(have):
            raise CavePatchError(f"cave area 0x{mm.FOV_CAVE:08X} is not free")
        for i, w in enumerate(words):
            backend.write_u32(mm.FOV_CAVE + 4 * i, w)
    state = call_site_state(backend)
    if state == "patched":
        return
    if state != "original":
        raise CavePatchError(f"call site 0x{mm.VP_LOAD_CALL:08X} holds an unexpected word")
    backend.write_u32(mm.VP_LOAD_CALL, _j(mm.FOV_CAVE))


def uninstall_call_site(backend) -> None:
    """Put the original call back.  Does nothing when the call site is not ours."""
    if call_site_state(backend) == "patched":
        backend.write_u32(mm.VP_LOAD_CALL, mm.VP_LOAD_WORD)


def set_ratio(backend, ratio: float, on: bool) -> None:
    """Set the scale factor and the flag: the flag is cleared while the ratio is written."""
    backend.write_u32(mm.FOV_BLOCK_FLAG, 0)
    backend.write_float_block(mm.FOV_BLOCK_RATIO, [ratio])
    backend.write_u32(mm.FOV_BLOCK_FLAG, 1 if on else 0)


def read_ratio(backend) -> tuple[bool, float]:
    """(flag, ratio) as the cave will read them."""
    flag = backend.read_u32(mm.FOV_BLOCK_FLAG) != 0
    ratio = backend.read_floats(mm.FOV_BLOCK_RATIO, 1)[0]
    return flag, ratio
