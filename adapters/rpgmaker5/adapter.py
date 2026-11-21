"""Control the map task's own orbit; never write the tile, actor, pad or rendered eye."""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading

from core.camera_math.orbit import CameraPose, FOV_SCALE_REF, Vec3, orbit_pose
from .lens import FOV_RANGE, NATIVE_DEG, VIEW_SCREEN, Lens

GAME_ID, CRC = 'SLPS-20143', 'BB78C51D'
TASK_ROOT, DRAW_ROOT = 0x70C3E0, 0x70C190  # active task registry slots 77 and 3
MAP_TASK, RIG = 0x11458C0, 0x1145900
VIEW_EYE = 0x6BC3E0
# Only accept the allocation and task family verified in the seven supplied states.
OWNER = {TASK_ROOT: MAP_TASK, TASK_ROOT + 4: MAP_TASK, MAP_TASK: RIG, MAP_TASK + 8: MAP_TASK,
         MAP_TASK + 0x2C: 0x169C48, MAP_TASK + 0x30: 0x1697C8,
         MAP_TASK + 0x34: 0x169B20, RIG + 4: 0x16A770}
PARAMS = (RIG + 8, RIG + 0x20, RIG + 0x14)  # yaw, pitch, distance (all s32)


class RigConflict(RuntimeError):
    pass


def signed(word):
    return word - (1 << 32) if word & 0x80000000 else word


@dataclass
class Info:
    game_id: str = ''
    crc: str = ''
    title: str = ''
    matched: bool = False
    reason: str = ''


@dataclass
class Scene:
    player: Vec3
    game_pose: CameraPose
    fov_deg: float
    max_dist_game: float
    valid: bool
    reason: str = ''


@dataclass
class Lease:
    owner: tuple
    original: tuple
    expected: tuple


class RPGMaker5Adapter:
    name = 'RPGMAKER5'
    display_name = 'RPGツクール5'
    display_name_key = 'game.rpgmaker5'
    DISTANCE_RANGE = (200.0, 1600.0)
    PITCH_RANGE = (20.0, 75.0)
    FOV_RANGE = FOV_RANGE
    uses_offset_injection = False
    patch_recheck_s = 0.25
    field_projection_centre = 0.0
    features = dict(orbit=True, fov=True, fov_requires_orbit=True, free_camera=False, position_offsets=False,
                    target_offsets=False, look_height=False, per_frame_write=False)

    def __init__(self, backend):
        self.backend = backend
        self.info = Info()
        self._lens = Lens(backend)
        self._lock = threading.RLock()  # GUI restore/centre and worker share ownership
        self._lease: Lease | None = None
        self._conflict = False

    def identify(self):
        gid, crc = self.backend.game_id().strip().upper(), self.backend.crc().strip().upper()
        ok = (gid, crc) == (GAME_ID, CRC)
        self.info = Info(gid, crc, self.backend.title(), ok, '' if ok else f'expected {GAME_ID}/{CRC}')
        return self.info

    def _owner(self):
        read = self.backend.read_u32
        if not self.info.matched or any(read(addr) != value for addr, value in OWNER.items()):
            raise RigConflict('not the verified RPG Maker 5 map task')
        child = read(DRAW_ROOT)
        if (not 0x100000 <= child < 0x2000000 - 0x40 or child & 0xF or read(DRAW_ROOT + 4) != child
                or read(child + 4) != MAP_TASK or read(child + 8) != child or read(child + 0x2C) != 0x11D950
                or read(MAP_TASK + 0x3C) & 0xffff != 77):
            raise RigConflict('map draw task is no longer scheduled')
        mode = {0: 'editor', 3: 'test'}.get(read(RIG + 0x68))
        if not mode or read(RIG + 0x10) or read(RIG + 0x18) or read(RIG + 0x28):
            raise RigConflict('unsupported map mode or native camera transition')
        return getattr(self.backend, 'epoch', None), mode, child

    def _params(self):
        return tuple(self.backend.read_u32(a) for a in PARAMS)

    def _anchor(self, mode):
        # P_editscroll_main samples fractional scroll during a tile step, then
        # switches to the committed tile. The display routine negates world Z.
        b = self.backend
        if b.read_u32(RIG + 0x738):
            x, y, h = b.read_floats(RIG + 0x810, 3)
            x, y = int(x), int(y)
        else:
            x, y = (16 * signed(b.read_u32(RIG + off)) + 8 for off in (0x60, 0x64))
            h = signed(b.read_u32(RIG))
        return Vec3(x, -h if mode == 'test' else 0, y)  # canonical = (world X, Z, Y)

    def read_player(self):
        return self._anchor(self._owner()[1])

    def read_game_pose(self):
        target = self.read_player()
        x, y, z = self.backend.read_floats(VIEW_EYE, 3)
        return CameraPose(Vec3(x, z, y), target)

    def read_scene(self):
        try:
            pose = self.read_game_pose()
            valid = all(math.isfinite(v) and abs(v) < 1e6 for v in (*pose.eye.as_tuple(), *pose.target.as_tuple()))
            radius = pose.distance()
            return Scene(pose.target, pose, self.read_fov_deg(), radius, valid and 100 < radius < 2500)
        except RigConflict as exc:
            zero = Vec3(0, 0, 0)
            return Scene(zero, CameraPose(zero, zero), 0, 0, False, str(exc))

    def is_field_like(self, scene):
        return scene.valid

    def center_on_target(self, distance, look_height):
        # The target already belongs to the game. Seed from its *parameters* to
        # avoid rounding the rendered axis (the guest's yaw uses pi = 3.14).
        target = self.read_player()
        yaw, pitch, radius = self._params()
        return orbit_pose(target, -signed(yaw) * math.tau / 65536,
                          math.pi / 2 - pitch * math.pi / 65536, radius)

    def _lose(self):
        self._lease = None
        self._conflict = True
        self._lens.restore()  # fixed code, not heap data; exact word + epoch only
        raise RigConflict('map camera ownership changed; select Original before enabling Orbit again')

    def _check(self):
        lease = self._lease
        if lease is None:
            raise RigConflict('Orbit is not armed')
        try:
            owner = self._owner()
        except RigConflict:
            self._lose()
        if lease.owner != owner or self._params() != lease.expected:
            self._lose()
        return lease

    def _publish(self, wanted):
        for i, (addr, word) in enumerate(zip(PARAMS, wanted)):
            lease = self._check()
            if word != lease.expected[i]:
                self.backend.write_u32(addr, word)
                lease.expected = lease.expected[:i] + (word,) + lease.expected[i + 1:]
        self._check()

    def set_patch(self, on):
        with self._lock:
            if on:
                if self._conflict:
                    raise RigConflict('map camera changed; return to Original first')
                if self._lease is None:
                    owner, params = self._owner(), self._params()
                    y, p, r = params
                    if not (-32768 <= signed(y) <= 32768 and 0 < p < 32768 and 100 < r < 2500):
                        raise RigConflict('unexpected native camera parameters')
                    self._lease = Lease(owner, params, params)
                self._check()
            else:
                try:
                    if self._lease:
                        self._publish(self._lease.original)
                finally:
                    self._lease = None
                    self._conflict = False
                    self._lens.restore()

    def patch_state(self):
        with self._lock:
            if self._conflict:
                return 'unknown'
            return 'applied' if self._lease else 'stock'

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance):
        # Keep the game's native scrolling (including sub-tile movement), not a
        # target cached by the host. Match native signed wrap (-32768, 32768].
        if not all(math.isfinite(v) for v in (yaw_deg, pitch_deg, distance)):
            raise ValueError('non-finite orbit')
        yaw = round(-yaw_deg * 65536 / 360) % 65536
        yaw = yaw - 65536 if yaw > 32768 else yaw
        lo, hi = self.PITCH_RANGE
        pitch = round((90 - min(hi, max(lo, pitch_deg))) * 65536 / 180)
        lo, hi = self.DISTANCE_RANGE
        with self._lock:
            self._publish((yaw & 0xffffffff, pitch, round(min(hi, max(lo, distance)))))

    def read_fov_scale(self):
        return self.backend.read_floats(VIEW_SCREEN, 1)[0]

    def read_fov_deg(self):
        return self._lens.read_deg()

    def capture_original_fov(self):
        return NATIVE_DEG  # fixed immediate, not an already overridden matrix

    def fov_in_sync(self, deg):
        with self._lock:
            return self._lens.in_sync(self._check().owner[1], deg)

    def write_fov_deg(self, deg):
        with self._lock:
            self._lens.write(self._check().owner[1], deg)

    def restore_fov(self):
        with self._lock:
            self._lens.restore()

    def default_settings(self):
        return dict(distance=1000.0, pitch_deg=45.0, look_height=0.0, fov_deg=NATIVE_DEG)

    # No offset slot, projection-centre override or stock look-at hook to mirror.
    def read_projection(self):
        return FOV_SCALE_REF, self.field_projection_centre

    def write_projection_centre(self, _value):
        pass

    def copy_stock_params(self):
        pass
