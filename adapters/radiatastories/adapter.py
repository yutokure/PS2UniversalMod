"""Player-relative render Orbit for Radiata Stories, SLPM-65800/AC73005E."""
from __future__ import annotations

import math
import threading
from adapters.ffx2.adapter import AdapterInfo, SceneState
from core.camera_math.orbit import CameraPose, Vec3, orbit_pose, FOV_SCALE_REF
from . import memory_map as mm
from . import caves


class RadiataStoriesAdapter:
    name = 'RADIATA'
    display_name = 'Radiata Stories'
    display_name_key = 'game.radiata'
    uses_offset_injection = False
    accepts_orbit_offsets = True
    PITCH_DISPLAY_SIGN = PITCH_INPUT_SIGN = 1.0
    PITCH_POSITIVE_IS = 'above'
    LOOK_HEIGHT_POSITIVE_IS = 'down'
    PITCH_RANGE = (-25.0, 89.5)
    DISTANCE_RANGE = (150.0, 6000.0)
    LOOK_HEIGHT_RANGE = (-500.0, 500.0)
    OFFSET_RANGE = (-1500.0, 1500.0)
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
    def _ptr(p, size):
        return 0x100000 <= p <= 0x2000000-size and not p & 15

    def _pointer(self, p, size, label):
        if not self._ptr(p,size): raise caves.PatchConflict(f'invalid Radiata {label}')
        return p

    def _camera(self):
        b=self.backend
        manager=self._pointer(b.read_u32(mm.FIELD_MANAGER_PTR),mm.FIELD_OWNER+4,'field manager')
        owner=self._pointer(b.read_u32(manager+mm.FIELD_OWNER),0x18,'camera owner')
        cam=self._pointer(b.read_u32(owner+mm.OWNER_CAMERA),0xB00,'camera')
        if b.read_u32(cam)!=mm.CAMERA_VTABLE: raise caves.PatchConflict('unknown Radiata camera class')
        target=self._pointer(b.read_u32(owner+mm.OWNER_TARGET),0xD0,'camera target')
        if b.read_u32(target)!=mm.NODE_VTABLE:raise caves.PatchConflict('unknown Radiata target class')
        renderer=self._pointer(b.read_u32(mm.RENDERER_PTR),mm.RENDERER_CAMERA+4,'renderer')
        if b.read_u32(renderer+mm.RENDERER_CAMERA)!=cam:
            raise caves.PatchConflict('renderer is using a different Radiata camera')
        return cam,target

    def _scene_flags(self):
        b=self.backend
        scene=self._pointer(b.read_u32(mm.SCENE_PTR),mm.PLAYER_ID+2,'scene')
        if b.read_u32(scene+0x10)&1 or b.read_u32(scene+0x1C)&8:
            raise caves.PatchConflict('Radiata player processing is suspended')
        return scene

    def _actor(self, scene):
        b=self.backend
        player_id=b.read_u32(scene+mm.PLAYER_ID)&65535
        if not player_id:raise caves.PatchConflict('Radiata player alias is absent')
        manager=self._pointer(b.read_u32(mm.ACTOR_MANAGER_PTR),0x20,'actor manager')
        count=b.read_u32(manager+mm.ACTOR_COUNT)
        if not 1<=count<=mm.ACTOR_LIMIT:raise caves.PatchConflict('invalid Radiata actor count')
        records=self._pointer(b.read_u32(manager+mm.ACTOR_RECORDS),count*mm.ACTOR_STRIDE,'actor records')
        found=[]
        for i in range(count):
            record=records+i*mm.ACTOR_STRIDE
            if b.read_u32(record+mm.ACTOR_ID)==player_id: found.append((i,record))
        if len(found)!=1:raise caves.PatchConflict('Radiata player record is absent or ambiguous')
        index,record=found[0]
        self._pointer(b.read_u32(record+mm.ACTOR_OBJECT),4,'player object')
        node=self._pointer(b.read_u32(record+mm.ACTOR_NODE),0xD0,'player node')
        if b.read_u32(node)!=mm.NODE_VTABLE:raise caves.PatchConflict('unknown Radiata player node class')
        pos=b.read_floats(node+mm.NODE_POS,4)
        if not all(math.isfinite(v) and abs(v)<1e6 for v in pos) or abs(pos[3]-1)>1e-5:
            raise caves.PatchConflict('invalid Radiata player coordinates')
        return index,player_id,node,Vec3(*pos[:3])

    def _field(self):
        cam,target=self._camera()
        scene=self._scene_flags()
        return cam,target,self._actor(scene)

    @property
    def CAM_EYE_ADDR(self):return self._camera()[0]+mm.NODE_POS
    @property
    def CAM_TARGET_ADDR(self):return self._camera()[1]+mm.NODE_POS
    @property
    def CAM_EYE_BASE_ADDR(self):return self.CAM_EYE_ADDR

    def read_player(self):return self._actor(self._scene_flags())[3]

    def _native_pose(self,cam,target):
        b=self.backend
        address=cam+mm.CAM_NATIVE_WORLD
        if (b.read_u32(mm.MOD_BLOCK)==mm.MAGIC
                and b.read_u32(mm.MOD_BLOCK+mm.MB_PENDING)==cam
                and b.read_u32(mm.MOD_BLOCK+mm.MB_APPLIED)&mm.FLAG_ORBIT):
            address=mm.MOD_BLOCK+mm.MB_SAVED_WORLD
        matrix=b.read_floats(address,16)
        eye=Vec3(matrix[3],matrix[7],matrix[11])
        aim=Vec3(*self.backend.read_floats(target+mm.NODE_POS,3))
        distance=(aim-eye).length()
        # The separate native target is a camera rig node, not the player anchor.
        forward=Vec3(matrix[2],matrix[6],matrix[10])
        return CameraPose(eye,eye+forward.scaled(distance))

    def read_game_pose(self):
        cam,target=self._camera()
        b=self.backend
        if (b.read_u32(mm.MOD_BLOCK)==mm.MAGIC
                and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT
                and b.read_u32(mm.MOD_BLOCK+mm.MB_APPLIED)&mm.FLAG_ORBIT
                and b.read_u32(mm.MOD_BLOCK+mm.MB_CAMERA)==cam):
            matrix=b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_WORLD,16)
            eye=Vec3(matrix[3],matrix[7],matrix[11])
            return CameraPose(eye,Vec3(*b.read_floats(mm.MOD_BLOCK+mm.MB_RENDER_TARGET,3)))
        return self._native_pose(cam,target)

    def _lens(self,cam):
        b=self.backend
        left=b.read_floats(cam+mm.CAM_VIEWPORT_MIN_X,1)[0]
        right=b.read_floats(cam+mm.CAM_VIEWPORT_MAX_X,1)[0]
        sx=b.read_floats(cam+mm.CAM_FOV_SCALE_X,1)[0]
        sy=b.read_floats(cam+mm.CAM_FOV_SCALE_Y,1)[0]
        if not all(math.isfinite(v) for v in (left,right,sx,sy)) or not 16<right-left<8192 or not .05<sx*sy<20:
            raise caves.PatchConflict('invalid Radiata projection inputs')
        return (right-left)/2,sx*sy

    def read_fov_scale(self):
        cam=self._camera()[0]
        half,_=self._lens(cam)
        focal=self.backend.read_floats(cam+mm.CAM_FOCAL,1)[0]
        return focal/half

    def read_fov_deg(self):
        scale=self.read_fov_scale()
        return math.degrees(2*math.atan(1/scale)) if math.isfinite(scale) and scale>0 else 0.0

    def read_scene(self):
        try:
            cam,target,actor=self._field()
            pose,fov=self.read_game_pose(),self.read_fov_deg()
            valid=all(math.isfinite(v) and abs(v)<1e6 for v in (*pose.eye.as_tuple(),*pose.target.as_tuple()))
            valid=valid and 1<pose.distance()<50000 and 1<fov<179
            return SceneState(actor[3],pose,fov,pose.distance(),valid,'' if valid else 'invalid camera geometry')
        except caves.PatchConflict as exc:
            return SceneState(Vec3(0,0,0),CameraPose(Vec3(0,0,0),Vec3(0,0,1)),0,0,False,str(exc))

    def is_field_like(self,scene):return scene.valid

    @staticmethod
    def _matrix(pose):
        forward=pose.target-pose.eye
        length=forward.length()
        if length<1e-6:raise ValueError('degenerate Radiata camera')
        f=forward.scaled(1/length)
        h=math.hypot(f.x,f.z)
        if h<1e-6:raise ValueError('vertical Radiata camera basis')
        r=Vec3(f.z/h,0,-f.x/h)
        u=Vec3(f.y*r.z,f.z*r.x-f.x*r.z,-f.y*r.x)
        return (r.x,u.x,f.x,pose.eye.x,r.y,u.y,f.y,pose.eye.y,
                r.z,u.z,f.z,pose.eye.z,0,0,0,1)

    def _publish(self):
        cam,target,(index,player_id,node,player)=self._field()
        b=self.backend
        _,scale=self._lens(cam)
        state = caves.site_state(b)
        if state == 'unknown':raise caves.PatchConflict('unknown Radiata camera hook')
        if not self._prepared or b.read_u32(mm.MOD_BLOCK)!=mm.MAGIC or state=='stock':
            caves.prepare(b)
            self._prepared = True
        if self._last_orbit is None:
            pose=self._native_pose(cam,target)
            relative=CameraPose(pose.eye-player,pose.target-player)
        else:relative=self._last_orbit
        half_fov=math.atan(scale*math.tan(math.radians(self._fov)/2)) if self._fov is not None else 0.0
        slot=(b.read_u32(mm.MOD_BLOCK+mm.MB_SLOT)&1)^1
        addr=mm.MOD_BLOCK+mm.SLOTS[slot]
        sequence=(b.read_u32(addr+mm.SLOT_SEQUENCE)+2)&0xFFFFFFFE
        b.write_u32(addr+mm.SLOT_SEQUENCE,sequence|1)
        b.write_float_block(addr+mm.SLOT_WORLD,self._matrix(relative))
        b.write_float_block(addr+mm.SLOT_TARGET,(*relative.target.as_tuple(),1))
        b.write_float_block(addr+mm.SLOT_HALF_FOV,[half_fov])
        b.write_u32(addr+mm.SLOT_ACTOR_INDEX,index)
        b.write_u32(addr+mm.SLOT_ACTOR_ID,player_id)
        flags=(mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0)
        b.write_u32(addr+mm.SLOT_FLAGS,flags)
        b.write_u32(addr+mm.SLOT_SEQUENCE,sequence)
        b.write_u32(mm.MOD_BLOCK+mm.MB_SLOT,slot)
        b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags)
        if any(b.read_u32(addr)==stock[0] for addr,stock,_,_,_ in caves.RESOURCES):
            caves.install(b)

    def write_orbit_params(self,centre,yaw_deg,pitch_deg,distance,*,pos_offset=None,target_offset=None):
        pos=pos_offset or Vec3(0,0,0)
        target=target_offset if target_offset is not None else centre-self.read_player()
        if not all(math.isfinite(v) for v in (*centre.as_tuple(),*pos.as_tuple(),*target.as_tuple(),yaw_deg,pitch_deg,distance)):
            raise ValueError('non-finite Radiata orbit parameter')
        pitch_deg=max(self.PITCH_RANGE[0],min(self.PITCH_RANGE[1],pitch_deg))
        distance=max(self.DISTANCE_RANGE[0],min(self.DISTANCE_RANGE[1],distance))
        pose=orbit_pose(target,math.radians(yaw_deg),math.radians(pitch_deg),distance)
        with self._lock:
            self._last_orbit=CameraPose(pose.eye+pos,pose.target)
            self._orbit=True
            self._publish()

    def set_patch(self,on):
        with self._lock:
            self._orbit=bool(on)
            if on:
                caves.preflight(self.backend)  # periodic runtime hook recheck
                self._publish()
            else:self._release()

    def _release(self):
        b=self.backend
        caves.preflight(b)
        if b.read_u32(mm.MOD_BLOCK)==mm.MAGIC:
            b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,(mm.FLAG_ORBIT if self._orbit else 0)|(mm.FLAG_FOV if self._fov is not None else 0))
        if self._orbit or self._fov is not None:
            try:self._field()
            except caves.PatchConflict:return
            self._publish()
        else:caves.uninstall(b)

    def patch_state(self):
        state=caves.site_state(self.backend)
        if state=='applied' and self.backend.read_u32(mm.MOD_BLOCK)==mm.MAGIC:
            return 'applied' if self.backend.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&mm.FLAG_ORBIT else 'stock'
        return state
    def patch_active(self):return self.patch_state()=='applied'
    hook_active=patch_active

    def capture_original_fov(self):
        cam=self._camera()[0]
        _,scale=self._lens(cam)
        rad=self.backend.read_floats(cam+mm.CAM_FOV,1)[0]
        return math.degrees(2*math.atan(math.tan(rad/2)/scale))

    def write_fov_deg(self,deg):
        if not math.isfinite(deg):raise ValueError('non-finite Radiata FOV')
        with self._lock:
            self._fov=max(20.0,min(110.0,deg));self._publish()

    def restore_fov(self):
        with self._lock:
            self._fov=None;self._release()

    def fov_in_sync(self,deg):
        return self._fov is not None and abs(self._fov-deg)<.01 and caves.site_state(self.backend)=='applied' and abs(self.read_fov_deg()-deg)<.1

    def center_on_target(self,distance,look_height):
        cam,target,_=self._field();pose=self._native_pose(cam,target);y,p=pose.yaw_pitch()
        aim=self.read_player()+Vec3(0,look_height,0)
        self.write_orbit_params(aim,math.degrees(y),math.degrees(p),distance,target_offset=Vec3(0,look_height,0))
        return orbit_pose(aim,y,p,distance)

    def read_aim(self):return self.read_game_pose().target
    def read_eye_base(self):return self.read_game_pose().eye
    def read_camera_forward(self):
        p=self.read_game_pose();d=p.target-p.eye;return d.scaled(1/d.length())
    def place_looking_at(self,target,distance):return target-self.read_camera_forward().scaled(distance)
    def write_pose(self,pose):
        y,p=pose.yaw_pitch();self.write_orbit_params(pose.target,math.degrees(y),math.degrees(p),pose.distance())
    def default_settings(self):
        return dict(distance=mm.STOCK_DISTANCE,look_height=-90.0,pitch_deg=20.0,yaw_deg=180.0,fov_deg=mm.STOCK_FOV_DEG)
    def default_look_height(self):return -90.0
    def heartbeat_addr(self):return mm.MOD_BLOCK+mm.MB_HEARTBEAT
    def heartbeat_word(self):return self.backend.read_u32(self.heartbeat_addr())
    def read_projection(self):return FOV_SCALE_REF,0.0
    def write_projection_centre(self,centre):pass
    def write_projection_scale(self,scale):pass
    def set_projection_source(self,redirected):pass
    def write_eye_offset(self,offset):pass
    def clear_eye_offset(self):pass
    def write_aim(self,target):pass
    def restore_aim(self):pass
    def write_walk_target(self,centre):pass
    def copy_stock_params(self):pass
    def set_stick_block(self,on):pass  # No native right-stick action to suppress.
