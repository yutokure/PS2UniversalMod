"""Redirect only the main field camera's look-at argument, not the shared builder.

The jal at LOOKAT_CALL keeps its original delay slot (a2 = bank + 0x50).
The cave checks output, eye AND target pointers before adding 0x30 to a2.
All other camera contexts, including minimap/auxiliary callers, retain their
own target.  A tail jump to the original builder preserves the call's ra and
all arguments/FPU state except the deliberately redirected a2.  v0 is caller
saved and is overwritten by the builder before it is consumed.
"""
from __future__ import annotations

from core import mips_asm as m
from . import memory_map as mm


def cave_words() -> list[int]:
    a = m.Assembler()
    for reg, pointer in ((m.A0, mm.CAM_VIEW_MATRIX), (m.A1, mm.CAM_EYE), (m.A2, mm.CAM_AIM)):
        a.emit(m.lui(m.V0, pointer >> 16))
        a.emit(m.ori(m.V0, m.V0, pointer & 0xFFFF))
        a.words.append(("bne", reg, m.V0, "stock"))
        a.emit(m.NOP)
    a.emit(m.addiu(m.A2, m.A2, mm.CAM_AIM_SLOT - mm.CAM_AIM))
    a.label("stock")
    a.emit(m.j(mm.FN_LOOKAT_BUILD))
    a.emit(m.NOP)
    return a.assemble()
