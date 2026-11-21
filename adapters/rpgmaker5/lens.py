"""RPG Maker 5: SetCameraCondition's horizontal focal input for map editor and test play."""
from __future__ import annotations

import math
import struct

# LUI at,<high half of f32>; MTC1 at,f12; LUI at,0x4000 (kills previous at).
SITE = 0x11D6E0
STOCK = 0x3C014400                 # 512.0 in f12
SIGNATURE = (0x44816000, 0x3C014000, 0x44816800)
VIEW_SCREEN = 0x6BC4E0             # [0] = 2 * f12, with a 512-pixel-wide GS raster
NATIVE_DEG = math.degrees(2 * math.atan2(256, 1024))
FOV_RANGE = (20.0, 60.0)


class LensConflict(RuntimeError):
    """The site no longer matches stock or our own exact write on this connection."""


def _wanted_word(mode: str, deg: float | None) -> int:
    if mode not in ('editor', 'test'):
        raise ValueError(f'unsupported RPG Maker 5 lens scene: {mode!r}')
    if deg is None:
        return STOCK
    if not math.isfinite(deg) or not FOV_RANGE[0] <= deg <= FOV_RANGE[1]:
        raise ValueError(f'horizontal FOV must be within {FOV_RANGE} degrees')
    focal = 128.0 / math.tan(math.radians(deg) / 2.0)
    bits, = struct.unpack('<I', struct.pack('<f', focal))
    return 0x3C010000 | ((bits + 0x8000) >> 16)


class Lens:
    """Use under the adapter's lock and its scene/identity guard. Never adopt foreign code."""

    def __init__(self, backend):
        self.backend = backend
        self._epoch = getattr(backend, 'epoch', None)
        self._owned: int | None = None

    def read_deg(self) -> float:
        # Read actual render output, not a desired or cached UI setting.
        sx, = self.backend.read_floats(VIEW_SCREEN, 1)
        if not math.isfinite(sx) or sx <= 0:
            raise LensConflict('invalid RPG Maker 5 horizontal projection scale')
        return math.degrees(2 * math.atan2(256.0, sx))

    def _check_epoch(self):
        epoch = getattr(self.backend, 'epoch', None)
        if self._epoch != epoch:
            self._owned = None
            self._epoch = epoch
        return epoch

    def _inspect(self) -> int:
        epoch = self._check_epoch()
        live = self.backend.read_u32(SITE)
        tail = tuple(self.backend.read_u32(SITE + 4 * i) for i in range(1, len(SIGNATURE) + 1))
        if self._check_epoch() != epoch:
            raise LensConflict('connection changed while inspecting RPG Maker 5 projection')
        if live == STOCK:
            self._owned = None  # e.g. a stock savestate was loaded
        if tail != SIGNATURE or (live != STOCK and live != self._owned):
            self._owned = None
            raise LensConflict(f'unknown RPG Maker 5 projection instructions at {SITE:#x}')
        return live

    def in_sync(self, mode: str, deg: float | None) -> bool:
        wanted = _wanted_word(mode, deg)
        return self._inspect() == wanted

    def _set(self, word: int) -> None:
        if self._inspect() == word:
            return
        self.backend.write_u32(SITE, word)
        self._owned = None if word == STOCK else word
        if self._inspect() != word:
            raise LensConflict(f'RPG Maker 5 focal-length write did not persist at {SITE:#x}')

    def write(self, mode: str, deg: float | None) -> None:
        self._set(_wanted_word(mode, deg))

    def restore(self) -> None:
        self._check_epoch()
        if self._owned is not None:
            self._set(STOCK)
