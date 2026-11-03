"""Native-state-preserving Orbit camera for The Nightmare of Druaga (Japan)."""
from __future__ import annotations

import math
import threading
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm
from . import caves


def _hfov(rad, scale=1.0):
    return math.degrees(2*math.atan(math.tan(rad/2)/(mm.PROJECTION_X_FACTOR*scale)))


def _movement_basis(eye, target):
    """Actual offset-inclusive horizontal look vector, never the yaw setting.

    Exactly vertical/coincident geometry has no horizontal direction: fail closed.
    Dungeon reuses its native, non-sequential sector IDs and direction table.
    """
    delta = target-eye
    horizontal = math.hypot(delta.x, delta.z)
    if not math.isfinite(horizontal) or horizontal <= mm.MOVE_HORIZONTAL_EPS:
        return 0.0, 0.0, 0
    fx, fz = delta.x/horizontal, delta.z/horizontal
    back_angle = math.atan2(-fx, -fz)
    octant = math.floor((back_angle+math.pi/8)/(math.pi/4)) % 8
    sector = (1, 5, 2, 4, 0, 7, 3, 6)[octant]
    return fx, fz, mm.MOVE_VALID | sector


class DruagaAdapter:
    name = 'DRUAGA'
    display_name = 'The Nightmare of Druaga'
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = -1.0
    PITCH_POSITIVE_IS = 'above'
    LOOK_HEIGHT_POSITIVE_IS = 'up'
    PITCH_RANGE = (-89.5, 25.0)
    DISTANCE_RANGE = (2.0, 100.0)
    LOOK_HEIGHT_RANGE = (-15.0, 15.0)
    OFFSET_RANGE = (-30.0, 30.0)
    field_projection_centre = 0.0
    patch_recheck_s = 1.0

    def __init__(self, backend):
        self.backend = backend
        self.info = AdapterInfo()
        self.features = dict(orbit=True, free_camera=False, fov=True,
                             position_offsets=True, target_offsets=True, per_frame_write=False)
        self._lock = threading.RLock()
        self._orbit = False
        self._fov = None
        self._last_orbit = None
        self._last_fov_rad = None
        self._camera_owned = None
        self._prepared = False

    def identify(self):
        try:
            gid, crc, title = self.backend.game_id().strip(), self.backend.crc().strip(), self.backend.title().strip()
            matched = (gid.upper(), crc.upper()) == (mm.GAME_ID, mm.DISC_CRC)
            self.info = AdapterInfo(gid, crc, title, matched,
                                    '' if matched else f'expected {mm.GAME_ID}/{mm.DISC_CRC}')
        except Exception as exc:
            self.info = AdapterInfo(reason=f'PINE error: {exc}')
        return self.info

    @staticmethod
    def _ptr(p, length):
        return 0x100000 <= p <= 0x2000000-length and p & 15 == 0

    def _camera(self):
        b = self.backend
        root, cam = b.read_u32(mm.ROOT_PTR), b.read_u32(mm.CAMERA_PTR)
        if not self._ptr(root, mm.DUNGEON_CAMERA_OFFSET+0x300) or not self._ptr(cam,0x300):
            raise caves.PatchConflict('not the verified Druaga gameplay allocation')
        pair = (b.read_u32(root),b.read_u32(cam),cam-root)
        if pair not in ((mm.ROOT_VTABLE,mm.CAMERA_VTABLE,mm.CAMERA_OFFSET),
                        (mm.DUNGEON_ROOT_VTABLE,mm.DUNGEON_CAMERA_VTABLE,mm.DUNGEON_CAMERA_OFFSET)):
            raise caves.PatchConflict('unknown Druaga gameplay/camera class')
        return root, cam

    def _dungeon(self,root,cam):
        return cam-root == mm.DUNGEON_CAMERA_OFFSET

    def _actor(self, root):
        b = self.backend
        dungeon = b.read_u32(root) == mm.DUNGEON_ROOT_VTABLE
        if dungeon:
            actor = b.read_u32(mm.DUNGEON_ACTOR_PTR)
            if not self._ptr(actor,mm.ACTOR_ENTITY_PTR+4):
                raise caves.PatchConflict('invalid dungeon actor allocation')
            sub = b.read_u32(actor+mm.ACTOR_ENTITY_PTR)
            offset = sub-mm.ENTITY_TABLE-mm.ENTITY_RENDERER
            if offset < 0 or offset % mm.ENTITY_STRIDE or offset//mm.ENTITY_STRIDE >= mm.ENTITY_COUNT:
                raise caves.PatchConflict('dungeon actor does not own a valid entity')
            slots = (offset//mm.ENTITY_STRIDE,)
        else:
            slots = range(mm.ENTITY_COUNT)
        for i in slots:
            record = mm.ENTITY_TABLE+i*mm.ENTITY_STRIDE
            ids = b.read_u32(record+8)
            if not dungeon and ids >> 16 != mm.PLAYER_ID:
                continue
            if not b.read_u32(record) & 1 or b.read_u32(record+mm.ENTITY_RENDERER) != root+mm.RENDERER_OFFSET:
                continue
            values = b.read_floats(record+mm.ENTITY_POS, 4)
            if all(math.isfinite(x) and abs(x) < 1e5 for x in values) and abs(values[3]-1) < 1e-5:
                return i, Vec3(*values[:3])
        raise caves.PatchConflict('active verified player entity is absent')

    def _field(self):
        root, cam = self._camera()
        b = self.backend
        dungeon = self._dungeon(root,cam)
        if ((b.read_u32(root+4)&65535) != (3 if dungeon else 2)
                or b.read_u32(mm.GAME_STATE) != (1 if dungeon else 2)):
            raise caves.PatchConflict('Druaga gameplay process is inactive')
        if b.read_u32(mm.EVENT_ACTIVE) != 0 or b.read_u32(mm.GAME_FLAGS_WORD) & 0x40000000:
            raise caves.PatchConflict('Druaga event/loading/render suspension')
        if b.read_u32(cam+mm.CAM_MODE) != (1 if dungeon else 0):
            raise caves.PatchConflict('not the verified follow camera mode')
        if dungeon and (b.read_u32(cam+0x2DC)>>16):
            raise caves.PatchConflict('dungeon camera transition is active')
        if b.read_u32(root+mm.RENDERER_OFFSET+mm.RENDER_CAMERA) != cam+mm.CAM_VIEW:
            raise caves.PatchConflict('renderer is using a different camera')
        i, player = self._actor(root)
        return cam, i, player

    @property
    def CAM_EYE_ADDR(self):
        return self._camera()[1]+mm.CAM_WORLD+0x30

    @property
    def CAM_EYE_BASE_ADDR(self):
        return self._camera()[1]+mm.CAM_NATIVE_EYE

    @property
    def CAM_TARGET_ADDR(self):
        return self._camera()[1]+mm.CAM_NATIVE_TARGET

    def read_player(self):
        return self._actor(self._camera()[0])[1]

    def read_game_pose(self):
        cam = self._camera()[1]
        # Read the actual world matrix; native +240/+280 intentionally remain stock.
        matrix = self.backend.read_floats(cam+mm.CAM_WORLD, 16)
        eye = Vec3(*matrix[12:15])
        native_eye = Vec3(*self.backend.read_floats(cam+mm.CAM_NATIVE_EYE, 3))
        target = Vec3(*self.backend.read_floats(cam+mm.CAM_NATIVE_TARGET, 3))
        distance = (native_eye-target).length()
        if self.patch_active() and self.backend.read_u32(mm.MOD_BLOCK+mm.MB_APPLIED):
            target = Vec3(*self.backend.read_floats(mm.MOD_BLOCK+mm.MB_TARGET, 3))
            return CameraPose(eye, target)
        # Matrix Z points towards the scene in this engine (+Y up).
        return CameraPose(eye, eye+Vec3(*matrix[8:11]).scaled(distance))

    def read_fov_scale(self):
        cam = self._camera()[1]
        p = self.backend.read_floats(cam+mm.CAM_PROJECTION, 16)
        xscale = self.backend.read_floats(cam+mm.CAM_ASPECT_SCALE_X, 1)[0]
        return p[0]*mm.PROJECTION_X_FACTOR*xscale/p[11] if p[11] > 1e-9 else 0.0

    def read_fov_deg(self):
        scale = self.read_fov_scale()
        return math.degrees(2*math.atan(1/scale)) if math.isfinite(scale) and scale > 0 else 0.0

    def read_scene(self):
        try:
            cam, index, player = self._field()
            pose, fov = self.read_game_pose(), self.read_fov_deg()
            valid = all(math.isfinite(x) and abs(x) < 1e5 for x in (*pose.eye.as_tuple(), *pose.target.as_tuple()))
            valid = valid and .1 < pose.distance() < 500 and 1 < fov < 179
            return SceneState(player, pose, fov, pose.distance(), valid, '' if valid else 'invalid camera geometry')
        except caves.PatchConflict as exc:
            return SceneState(Vec3(0,0,0), CameraPose(Vec3(0,0,0), Vec3(0,0,1)), 0, 0, False, str(exc))

    def is_field_like(self, scene):
        return scene.valid

    def _valid_block(self):
        return self.backend.read_u32(mm.MOD_BLOCK) == mm.MAGIC

    def _publish(self):
        cam, index, player = self._field()
        b = self.backend
        # Hooks are checked every publish; full cave checks occur on activation,
        # reconciliation and the runtime's periodic set_patch(True), not per frame.
        if caves.site_state(b) == 'unknown':
            raise caves.PatchConflict('unknown Druaga camera/movement hook instructions')
        movement_reconnect = self._orbit and any(
            b.read_u32(address) == stock[0] for address, stock, _, _, _ in caves.MOVEMENT_RESOURCES)
        camera_reconnect = any(b.read_u32(address) == stock[0] for address, stock, _, _, _ in caves.RESOURCES)
        if not self._prepared or not self._valid_block() or camera_reconnect or movement_reconnect:
            caves.prepare(b)
            self._prepared = True
        if self._last_orbit is None:
            eye = Vec3(*b.read_floats(cam+mm.CAM_NATIVE_EYE,3))-player
            target = Vec3(*b.read_floats(cam+mm.CAM_NATIVE_TARGET,3))-player
        else:
            eye, target = self._last_orbit
        if self._fov is None:
            fov = math.radians(b.read_floats(cam+mm.CAM_NATIVE_FOV_DEG,1)[0])
        else:
            scale = b.read_floats(cam+mm.CAM_ASPECT_SCALE_X,1)[0]
            if not math.isfinite(scale) or not .25 < scale < 4:
                raise caves.PatchConflict('invalid Druaga projection scale')
            fov = 2*math.atan(mm.PROJECTION_X_FACTOR*scale*math.tan(math.radians(self._fov)/2))
        bank = (b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1
        addr = mm.MOD_BLOCK+mm.SLOTS[bank]
        fx, fz, movement = _movement_basis(eye, target)
        # Odd while writing, even only once slot AND flags refer to this payload.
        # On transport failure leave odd: the guest must fall back, not reuse it.
        seq = (b.read_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ)+1) | 1
        seq &= 0xFFFFFFFF
        b.write_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ, seq)
        b.write_float_block(addr+mm.SLOT_EYE, (*eye.as_tuple(),1.0))
        b.write_float_block(addr+mm.SLOT_TARGET, (*target.as_tuple(),1.0))
        b.write_float_block(addr+mm.SLOT_FOV,[fov])
        b.write_u32(addr+mm.SLOT_ANCHOR,index)
        b.write_float_block(addr+mm.SLOT_FORWARD, (fx, fz))
        b.write_u32(addr+mm.SLOT_ROOT, cam-(mm.DUNGEON_CAMERA_OFFSET if b.read_u32(cam)==mm.DUNGEON_CAMERA_VTABLE else mm.CAMERA_OFFSET))
        b.write_u32(addr+mm.SLOT_CAMERA, cam)
        b.write_u32(addr+mm.SLOT_MOVE, movement if self._orbit else 0)
        b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT,bank)  # publish complete bank atomically
        b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,(mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0))
        b.write_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ, (seq+1) & 0xFFFFFFFF)
        self._last_fov_rad = fov if self._fov is not None else None
        self._camera_owned = cam
        state = caves.site_state(b)
        if state == 'unknown':
            raise caves.PatchConflict('unknown Druaga camera hook instructions')
        if state == 'stock' or any(b.read_u32(addr) == stock[0] for addr,stock,_,_,_ in caves.RESOURCES):
            caves.install(b)
        caves.set_movement(b, self._orbit)

    def write_orbit_params(self, centre, yaw_deg, pitch_deg, distance, *, pos_offset=None, target_offset=None):
        if not all(math.isfinite(x) for x in (*centre.as_tuple(),yaw_deg,pitch_deg,distance)):
            raise ValueError('non-finite Druaga orbit parameter')
        self._field()
        # Explicit relative offsets avoid subtracting a later actor sample from centre.
        target = target_offset if target_offset is not None else centre-self.read_player()
        pos = pos_offset or Vec3(0,0,0)
        if not all(math.isfinite(x) for x in (*pos.as_tuple(),*target.as_tuple())):
            raise ValueError('non-finite Druaga camera offset')
        pose = orbit_pose(target, math.radians(yaw_deg), math.radians(max(self.PITCH_RANGE[0],min(self.PITCH_RANGE[1],pitch_deg))),
                          max(self.DISTANCE_RANGE[0],min(self.DISTANCE_RANGE[1],distance)))
        with self._lock:
            self._last_orbit = pose.eye+pos, pose.target
            self._orbit = True
            self._publish()

    def set_patch(self,on):
        with self._lock:
            if on:
                self._field()
                caves.preflight(self.backend)
                self._orbit = True
                self._publish()
                caves.install(self.backend)  # repair known mixed town/dungeon hook states
            else:
                self._orbit = False
                self._release()

    def _release(self):
        b = self.backend
        # Instruction ownership is verified before any release write.
        if caves.site_state(b) == 'unknown':
            raise caves.PatchConflict('unknown Druaga hook during release')
        if self._valid_block():
            flags = (mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0)
            seq = ((b.read_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ)+1) | 1) & 0xFFFFFFFF
            b.write_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ, seq)
            b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS, flags)
            b.write_u32(mm.MOD_BLOCK+mm.MB_MOVE_SEQ, (seq+1) & 0xFFFFFFFF)
        if not self._orbit:
            caves.set_movement(b, False)
        if self._orbit or self._fov is not None:
            # A menu/event may stop camera updates. Dropping one owner must not
            # fail and prevent runtime.restore() from dropping the other owner.
            # Flags already reflect the surviving owner; republish only in field.
            try:
                self._field()
            except caves.PatchConflict:
                return
            self._publish()
            return
        caves.uninstall(b)
        # The next unmodified update rebuilds the matrix and native FOV. Do not
        # restore saved coordinates into a new scene or freeze native smoothing.
        if self._last_fov_rad is not None and self._camera_owned is not None:
            try:
                cam = self._camera()[1]
                now = b.read_floats(cam+mm.CAM_FOV_RAD,1)[0]
                if cam == self._camera_owned and abs(now-self._last_fov_rad)<1e-6:
                    native = b.read_floats(cam+mm.CAM_NATIVE_FOV_DEG,1)[0]
                    b.write_float_block(cam+mm.CAM_FOV_RAD,[math.radians(native)])
            except caves.PatchConflict:
                pass
        self._last_fov_rad = None

    def patch_state(self):
        state = caves.site_state(self.backend)
        if state == 'applied' and self._valid_block():
            return 'applied' if self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT else 'stock'
        return state

    def patch_active(self):
        return self.patch_state() == 'applied'

    hook_active = patch_active

    def write_fov_deg(self,deg):
        if not math.isfinite(deg): raise ValueError('non-finite FOV')
        with self._lock:
            self._field()
            self._fov = max(20.0,min(110.0,deg))
            self._publish()

    def restore_fov(self):
        with self._lock:
            self._fov = None
            self._release()

    def capture_original_fov(self):
        cam = self._camera()[1]
        return _hfov(math.radians(self.backend.read_floats(cam+mm.CAM_NATIVE_FOV_DEG,1)[0]),
                     self.backend.read_floats(cam+mm.CAM_ASPECT_SCALE_X,1)[0])

    def fov_in_sync(self,deg):
        return self._valid_block() and caves.site_state(self.backend)=='applied' and abs(self.read_fov_deg()-deg)<.05

    def center_on_target(self,distance,look_height):
        scene = self.read_scene()
        if not scene.valid: raise caves.PatchConflict(scene.reason)
        y,p = scene.game_pose.yaw_pitch()
        target = scene.player+Vec3(0,look_height,0)
        self.write_orbit_params(target,math.degrees(y),math.degrees(p),distance,
                                target_offset=Vec3(0,look_height,0))
        return orbit_pose(target,y,p,distance)

    def read_aim(self): return self.read_game_pose().target
    def read_eye_base(self): return self.read_game_pose().eye
    def read_camera_forward(self):
        pose=self.read_game_pose(); delta=pose.target-pose.eye
        return delta.scaled(1/delta.length())
    def place_looking_at(self,target,distance): return target-self.read_camera_forward().scaled(distance)
    def write_pose(self,pose):
        y,p=pose.yaw_pitch(); self.write_orbit_params(pose.target,math.degrees(y),math.degrees(p),pose.distance())
    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE,look_height=0.0,pitch_deg=-40.925,
                    yaw_deg=165.631,fov_deg=_hfov(mm.STOCK_FOV_RAD))
    def default_look_height(self): return 0.0
    def heartbeat_addr(self): return mm.MOD_BLOCK+mm.MB_HEARTBEAT
    def heartbeat_word(self): return self.backend.read_u32(self.heartbeat_addr())
    def read_projection(self): return FOV_SCALE_REF,0.0
    def write_projection_centre(self,centre): pass
    def write_projection_scale(self,scale): pass
    def set_projection_source(self,redirected): pass
    def write_eye_offset(self,offset): pass
    def clear_eye_offset(self): pass
    def write_aim(self,target): pass
    def restore_aim(self): pass
    def write_walk_target(self,centre): pass
    def copy_stock_params(self): pass
    def set_stick_block(self,on):
        b=self.backend
        hook=caves.read_words(b,mm.PAD_AXIS_HOOK,2)
        have=[b.read_u32(addr) for addr,_ in mm.PAD_ACTION_LOADS]
        if hook not in (mm.PAD_AXIS_STOCK,caves.PAD_HOOK) or any(
                word not in (stock,neutral) for word,(_,stock),neutral in
                zip(have,mm.PAD_ACTION_LOADS,mm.PAD_NEUTRAL_WORDS)):
            raise caves.PatchConflict('unknown Druaga processed right-stick instruction')
        if on:
            code=caves.read_words(b,mm.PAD_CAVE,len(caves.PAD_WORDS))
            if code != tuple(caves.PAD_WORDS) and any(code):
                raise caves.PatchConflict('Druaga pad code cave is occupied')
            if code != tuple(caves.PAD_WORDS):
                for i,word in enumerate(caves.PAD_WORDS):b.write_u32(mm.PAD_CAVE+4*i,word)
            # Delay slot is unchanged and its a3 result is recomputed in the cave.
            # Connecting/disconnecting changes exactly one aligned instruction.
            if hook != caves.PAD_HOOK:b.write_u32(mm.PAD_AXIS_HOOK,caves.PAD_HOOK[0])
        elif hook == caves.PAD_HOOK:
            b.write_u32(mm.PAD_AXIS_HOOK,mm.PAD_AXIS_STOCK[0])
        for word,(addr,stock),neutral in zip(have,mm.PAD_ACTION_LOADS,mm.PAD_NEUTRAL_WORDS):
            want=neutral if on else stock
            if word != want:b.write_u32(addr,want)
