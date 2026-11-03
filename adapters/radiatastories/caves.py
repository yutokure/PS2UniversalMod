"""Render transaction plus the field player's camera-relative movement getter.

Native camera state keeps updating. Only the movement consumer sees the Orbit
forward outside rendering. All hooks keep their delays and attach with one word.
"""
from core import mips_asm as m
from . import memory_map as mm


class PatchConflict(RuntimeError):
    pass


def _r(rs, rt, rd, sa, fn):
    return (rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | fn


def _addr(e, reg, address):
    e(m.lui(reg, address >> 16)); e(m.ori(reg, reg, address))


def _ptr(a, reg, reject='native'):
    """Aligned physical allocations with 64 KiB of upper-address headroom."""
    e=a.emit
    e(_r(0,reg,m.T7,20,2)); a.beqz(m.T7,reject); e(m.NOP)
    e(_r(0,reg,m.T7,16,2))
    e(0x2C0001FF | (m.T7<<21) | (m.T7<<16))
    a.beqz(m.T7,reject); e(m.NOP)
    e(m.andi(m.T7,reg,15)); a.bnez(m.T7,reject); e(m.NOP)


def _lq(rt, base, off): return 0x78000000|(base<<21)|(rt<<16)|(off&65535)
def _sq(rt, base, off): return 0x7C000000|(base<<21)|(rt<<16)|(off&65535)


def view_words():
    a=m.Assembler(); e=a.emit
    _addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T1,m.T0,0));_addr(e,m.T2,mm.MAGIC)
    a.words.append(('bne',m.T1,m.T2,'native'));e(m.NOP)
    # Do not overwrite another outstanding transaction's backup.
    e(m.lw(m.T1,m.T0,mm.MB_PENDING)); a.bnez(m.T1,'native'); e(m.NOP)
    e(m.lw(m.T1,m.T0,mm.MB_FLAGS)); a.beqz(m.T1,'native'); e(m.NOP)
    _addr(e,m.T1,mm.FIELD_MANAGER_PTR); e(m.lw(m.T1,m.T1,0)); _ptr(a,m.T1)
    e(m.lw(m.T1,m.T1,mm.FIELD_OWNER)); _ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,mm.OWNER_CAMERA))
    a.words.append(('bne',m.T2,m.S0,'native')); e(m.NOP)
    _ptr(a,m.S0)
    e(m.lw(m.T2,m.S0,0)); _addr(e,m.T3,mm.CAMERA_VTABLE)
    a.words.append(('bne',m.T2,m.T3,'native'));e(m.NOP)
    _addr(e,m.T2,mm.RENDERER_PTR);e(m.lw(m.T2,m.T2,0));_ptr(a,m.T2)
    e(m.lw(m.T2,m.T2,mm.RENDERER_CAMERA))
    a.words.append(('bne',m.T2,m.S0,'native'));e(m.NOP)
    _addr(e,m.T1,mm.SCENE_PTR);e(m.lw(m.T1,m.T1,0));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,0x10));e(m.andi(m.T2,m.T2,1));a.bnez(m.T2,'native');e(m.NOP)
    e(m.lw(m.T2,m.T1,0x1C));e(m.andi(m.T2,m.T2,8));a.bnez(m.T2,'native');e(m.NOP)
    e(0x94000000|(m.T1<<21)|(m.T4<<16)|mm.PLAYER_ID)
    a.beqz(m.T4,'native');e(m.NOP)
    e(m.lw(m.T5,m.T0,mm.MB_SLOT));e(m.andi(m.T5,m.T5,1))
    e(_r(0,m.T5,m.T5,7,0));e(m.addiu(m.T6,m.T0,mm.SLOTS[0]))
    e(_r(m.T6,m.T5,m.T6,0,0x21))
    # Host may publish more than twice per guest frame. Copy the whole bank
    # under a sequence lock, rather than retaining a reusable host-bank pointer.
    e(m.lw(m.T5,m.T6,mm.SLOT_SEQUENCE));e(m.andi(m.T7,m.T5,1))
    a.bnez(m.T7,'native');e(m.NOP)
    for off in range(0,0x70,16):
        e(_lq(m.T2,m.T6,off));e(_sq(m.T2,m.T0,mm.MB_SNAPSHOT+off))
    e(m.lw(m.T2,m.T6,mm.SLOT_SEQUENCE))
    a.words.append(('bne',m.T2,m.T5,'native'));e(m.NOP)
    e(m.addiu(m.T6,m.T0,mm.MB_SNAPSHOT))
    e(m.lw(m.T2,m.T6,mm.SLOT_ACTOR_ID))
    a.words.append(('bne',m.T2,m.T4,'native'));e(m.NOP)
    _addr(e,m.T1,mm.ACTOR_MANAGER_PTR);e(m.lw(m.T1,m.T1,0));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,mm.ACTOR_COUNT));e(m.addiu(m.T3,m.T2,-1))
    e(0x2C000000|(m.T3<<21)|(m.T3<<16)|mm.ACTOR_LIMIT)
    a.beqz(m.T3,'native');e(m.NOP)
    e(m.lw(m.T3,m.T6,mm.SLOT_ACTOR_INDEX))
    e(_r(m.T3,m.T2,m.T7,0,0x2B));a.beqz(m.T7,'native');e(m.NOP)
    e(m.lw(m.T1,m.T1,mm.ACTOR_RECORDS));_ptr(a,m.T1)
    e(_r(0,m.T3,m.T3,7,0));e(_r(m.T1,m.T3,m.T1,0,0x21))
    e(m.lw(m.T2,m.T1,mm.ACTOR_ID))
    a.words.append(('bne',m.T2,m.T4,'native'));e(m.NOP)
    e(m.lw(m.T2,m.T1,mm.ACTOR_OBJECT));_ptr(a,m.T2)
    e(m.lw(m.T1,m.T1,mm.ACTOR_NODE));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,0));_addr(e,m.T3,mm.NODE_VTABLE)
    a.words.append(('bne',m.T2,m.T3,'native'));e(m.NOP)
    # Cache one accepted bank for both the view and tangent hooks.
    e(m.sw(m.T6,m.T0,mm.MB_LATCH));e(m.sw(m.S0,m.T0,mm.MB_PENDING))
    e(m.sw(m.S0,m.T0,mm.MB_CAMERA))
    e(m.lw(m.T2,m.T6,mm.SLOT_FLAGS));e(m.lw(m.T3,m.T0,mm.MB_FLAGS))
    e(_r(m.T2,m.T3,m.T2,0,0x24));e(m.sw(m.T2,m.T0,mm.MB_APPLIED))
    e(m.lw(m.T3,m.T0,mm.MB_HEARTBEAT));e(m.addiu(m.T3,m.T3,1));e(m.sw(m.T3,m.T0,mm.MB_HEARTBEAT))
    e(m.andi(m.T2,m.T2,mm.FLAG_ORBIT));a.beqz(m.T2,'native');e(m.NOP)
    for off in range(0,64,16):
        e(_lq(m.T2,m.S0,mm.CAM_NATIVE_WORLD+off));e(_sq(m.T2,m.T0,mm.MB_SAVED_WORLD+off))
        e(_lq(m.T2,m.T6,mm.SLOT_WORLD+off));e(_sq(m.T2,m.T0,mm.MB_RENDER_WORLD+off))
    for i in range(3):
        out=mm.MB_RENDER_WORLD+12+16*i
        e(m.lwc1(0,m.T1,mm.NODE_POS+4*i));e(m.lwc1(1,m.T0,out))
        e(m.add_s(0,0,1));e(m.swc1(0,m.T0,out))
    for i in range(3):
        e(m.lwc1(0,m.T1,mm.NODE_POS+4*i));e(m.lwc1(1,m.T6,mm.SLOT_TARGET+4*i))
        e(m.add_s(0,0,1));e(m.swc1(0,m.T0,mm.MB_RENDER_TARGET+4*i))
    for off in range(0,64,16):
        e(_lq(m.T2,m.T0,mm.MB_RENDER_WORLD+off));e(_sq(m.T2,m.S0,mm.CAM_NATIVE_WORLD+off))
    a.label('native')
    # a0/a1 were never modified. Source now holds a coherent matrix only during
    # this render update; native position/quaternion are never changed.
    e(m.j(mm.FUN_INVERSE));e(m.NOP)
    return a.assemble()


def fov_words():
    a=m.Assembler();e=a.emit
    _addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T1,m.T0,mm.MB_PENDING))
    a.words.append(('bne',m.T1,m.S0,'native'));e(m.NOP)
    e(m.lw(m.T1,m.T0,mm.MB_APPLIED));e(m.andi(m.T1,m.T1,mm.FLAG_FOV))
    a.beqz(m.T1,'native');e(m.NOP)
    e(m.lw(m.T1,m.T0,mm.MB_LATCH));e(m.lwc1(12,m.T1,mm.SLOT_HALF_FOV))
    a.label('native');e(m.j(mm.FUN_TAN));e(m.NOP)
    return a.assemble()


def finish_words():
    a=m.Assembler();e=a.emit
    # Keep the original call ABI and preserve full-width saved registers.
    e(m.addiu(m.SP,m.SP,-0x20));e(0xFFBF0010);e(m.sw(m.A0,m.SP,0))
    e(m.jal(mm.FUN_FRUSTUM));e(m.NOP)
    _addr(e,m.T0,mm.MOD_BLOCK);e(m.lw(m.T1,m.T0,mm.MB_PENDING));e(m.lw(m.T2,m.SP,0))
    a.words.append(('bne',m.T1,m.T2,'done'));e(m.NOP)
    e(m.lw(m.T1,m.T0,mm.MB_APPLIED));e(m.andi(m.T1,m.T1,mm.FLAG_ORBIT))
    a.beqz(m.T1,'clear');e(m.NOP)
    for off in range(0,64,16):
        e(_lq(m.T1,m.T0,mm.MB_SAVED_WORLD+off));e(_sq(m.T1,m.T2,mm.CAM_NATIVE_WORLD+off))
    a.label('clear');e(m.sw(m.ZERO,m.T0,mm.MB_PENDING))
    a.label('done');e(0xDFBF0010);e(m.addiu(m.SP,m.SP,0x20))
    e(0x03E00008);e(m.NOP)
    return a.assemble()


def move_words():
    """Replace only FUN_00387C10's forward getter, keeping its yaw conversion.

    a0=output float4, a1=camera, s0=current actor record. The original caller
    handles both analog and D-pad, magnitude, deadzone and movement gating.
    Never write native camera/pad state or depend on a previous render latch.
    """
    a=m.Assembler();e=a.emit
    _addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T1,m.T0,0));_addr(e,m.T2,mm.MAGIC)
    a.words.append(('bne',m.T1,m.T2,'native'));e(m.NOP)
    e(m.lw(m.T1,m.T0,mm.MB_FLAGS));e(m.andi(m.T1,m.T1,mm.FLAG_ORBIT))
    a.beqz(m.T1,'native');e(m.NOP)
    _addr(e,m.T1,mm.FIELD_MANAGER_PTR);e(m.lw(m.T1,m.T1,0));_ptr(a,m.T1)
    e(m.lw(m.T1,m.T1,mm.FIELD_OWNER));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,mm.OWNER_CAMERA))
    a.words.append(('bne',m.T2,m.A1,'native'));e(m.NOP)
    _ptr(a,m.A1)
    e(m.lw(m.T2,m.A1,0));_addr(e,m.T3,mm.CAMERA_VTABLE)
    a.words.append(('bne',m.T2,m.T3,'native'));e(m.NOP)
    _addr(e,m.T2,mm.RENDERER_PTR);e(m.lw(m.T2,m.T2,0));_ptr(a,m.T2)
    e(m.lw(m.T2,m.T2,mm.RENDERER_CAMERA))
    a.words.append(('bne',m.T2,m.A1,'native'));e(m.NOP)
    _addr(e,m.T1,mm.SCENE_PTR);e(m.lw(m.T1,m.T1,0));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,0x10));e(m.andi(m.T2,m.T2,1));a.bnez(m.T2,'native');e(m.NOP)
    e(m.lw(m.T2,m.T1,0x1C));e(m.andi(m.T2,m.T2,8));a.bnez(m.T2,'native');e(m.NOP)
    e(0x94000000|(m.T1<<21)|(m.T4<<16)|mm.PLAYER_ID)
    a.beqz(m.T4,'native');e(m.NOP)
    e(m.lw(m.T5,m.T0,mm.MB_SLOT));e(m.andi(m.T5,m.T5,1))
    e(_r(0,m.T5,m.T5,7,0));e(m.addiu(m.T6,m.T0,mm.SLOTS[0]))
    e(_r(m.T6,m.T5,m.T6,0,0x21))
    e(m.lw(m.T5,m.T6,mm.SLOT_SEQUENCE));e(m.andi(m.T7,m.T5,1))
    a.bnez(m.T7,'native');e(m.NOP)
    e(m.lw(m.T2,m.T6,mm.SLOT_FLAGS));e(m.andi(m.T2,m.T2,mm.FLAG_ORBIT))
    a.beqz(m.T2,'native');e(m.NOP)
    e(m.lw(m.T2,m.T6,mm.SLOT_ACTOR_ID))
    a.words.append(('bne',m.T2,m.T4,'native'));e(m.NOP)
    _addr(e,m.T1,mm.ACTOR_MANAGER_PTR);e(m.lw(m.T1,m.T1,0));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,mm.ACTOR_COUNT));e(m.addiu(m.T3,m.T2,-1))
    e(0x2C000000|(m.T3<<21)|(m.T3<<16)|mm.ACTOR_LIMIT)
    a.beqz(m.T3,'native');e(m.NOP)
    e(m.lw(m.T3,m.T6,mm.SLOT_ACTOR_INDEX))
    e(_r(m.T3,m.T2,m.T7,0,0x2B));a.beqz(m.T7,'native');e(m.NOP)
    e(m.lw(m.T1,m.T1,mm.ACTOR_RECORDS));_ptr(a,m.T1)
    e(_r(0,m.T3,m.T3,7,0));e(_r(m.T1,m.T3,m.T1,0,0x21))
    a.words.append(('bne',m.T1,m.S0,'native'));e(m.NOP)
    e(m.lw(m.T2,m.T1,mm.ACTOR_ID))
    a.words.append(('bne',m.T2,m.T4,'native'));e(m.NOP)
    e(m.lw(m.T2,m.T1,mm.ACTOR_OBJECT));_ptr(a,m.T2)
    e(m.lw(m.T1,m.T1,mm.ACTOR_NODE));_ptr(a,m.T1)
    e(m.lw(m.T2,m.T1,0));_addr(e,m.T3,mm.NODE_VTABLE)
    a.words.append(('bne',m.T2,m.T3,'native'));e(m.NOP)
    # Forward is the actual eye->target basis after independent eye offsets,
    # not the nominal Orbit yaw. Copy all components under the same sequence.
    for reg,off in ((m.T1,8),(m.T2,24),(m.T3,40)):
        e(m.lw(reg,m.T6,mm.SLOT_WORLD+off))
    e(m.lw(m.T4,m.T6,mm.SLOT_SEQUENCE))
    a.words.append(('bne',m.T4,m.T5,'native'));e(m.NOP)
    e(m.lw(m.T4,m.T0,mm.MB_FLAGS));e(m.andi(m.T4,m.T4,mm.FLAG_ORBIT))
    a.beqz(m.T4,'native');e(m.NOP)
    for reg,off in ((m.T1,0),(m.T2,4),(m.T3,8)):
        e(m.sw(reg,m.A0,off))
    e(m.lui(m.T4,0x3F80));e(m.sw(m.T4,m.A0,12))
    e(0x03E00008);e(m.NOP)
    a.label('native');e(m.j(mm.FUN_FORWARD));e(m.NOP)
    return a.assemble()


VIEW_WORDS=view_words();FOV_WORDS=fov_words();FINISH_WORDS=finish_words();MOVE_WORDS=move_words()
RESOURCES=((mm.VIEW_HOOK,mm.VIEW_STOCK,(m.jal(mm.VIEW_CAVE),mm.VIEW_STOCK[1]),mm.VIEW_CAVE,VIEW_WORDS),
           (mm.FOV_HOOK,mm.FOV_STOCK,(m.jal(mm.FOV_CAVE),mm.FOV_STOCK[1]),mm.FOV_CAVE,FOV_WORDS),
           (mm.FINISH_HOOK,mm.FINISH_STOCK,(m.jal(mm.FINISH_CAVE),mm.FINISH_STOCK[1]),mm.FINISH_CAVE,FINISH_WORDS),
           (mm.MOVE_HOOK,mm.MOVE_STOCK,(m.jal(mm.MOVE_CAVE),mm.MOVE_STOCK[1]),mm.MOVE_CAVE,MOVE_WORDS))
assert mm.VIEW_CAVE+len(VIEW_WORDS)*4<=mm.FOV_CAVE
assert mm.FOV_CAVE+len(FOV_WORDS)*4<=mm.FINISH_CAVE
assert mm.FINISH_CAVE+len(FINISH_WORDS)*4<=mm.MOD_BLOCK
assert mm.MOD_BLOCK+mm.BLOCK_SIZE<=mm.MOVE_CAVE
assert mm.MOVE_CAVE+len(MOVE_WORDS)*4<=0x000F2000


def read_words(b,addr,n):return tuple(b.read_u32(addr+i*4) for i in range(n))

def site_state(b):
    states=[]
    for addr,stock,hook,_,_ in RESOURCES:
        got=read_words(b,addr,2)
        states.append('stock' if got==stock else 'applied' if got==hook else 'unknown')
    if 'unknown' in states:return 'unknown'
    return 'stock' if all(s=='stock' for s in states) else 'applied'


def preflight(b):
    if site_state(b)=='unknown':raise PatchConflict('unknown Radiata camera hook')
    for _,_,_,addr,words in RESOURCES:
        got=read_words(b,addr,len(words))
        if got!=tuple(words) and any(got):raise PatchConflict('Radiata code cave is occupied')
    magic=b.read_u32(mm.MOD_BLOCK)
    if magic not in (0,mm.MAGIC):raise PatchConflict('Radiata control block is occupied')
    if magic==0 and any(read_words(b,mm.MOD_BLOCK,mm.BLOCK_SIZE//4)):
        raise PatchConflict('Radiata control block is not empty')


def prepare(b):
    preflight(b)
    for _,_,_,addr,words in RESOURCES:
        if read_words(b,addr,len(words))!=tuple(words):
            for i,w in enumerate(words):b.write_u32(addr+i*4,w)
    if b.read_u32(mm.MOD_BLOCK)!=mm.MAGIC:b.write_u32(mm.MOD_BLOCK,mm.MAGIC)


def install(b):
    preflight(b)
    # Cleanup must exist before any transaction can begin.
    for addr,stock,hook,_,_ in reversed(RESOURCES):
        if b.read_u32(addr)==stock[0]:b.write_u32(addr,hook[0])


def uninstall(b):
    import time
    preflight(b)
    if b.read_u32(mm.MOD_BLOCK)==mm.MAGIC:b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,0)
    # Disconnect entry/tangent/movement first. A render transaction already
    # in flight may finish through its still-attached cleanup call. Movement
    # writes no persistent state and needs no pending-transaction cleanup.
    for addr,stock,hook,_,_ in (*RESOURCES[:2],RESOURCES[3]):
        if b.read_u32(addr)==hook[0]:b.write_u32(addr,stock[0])
    deadline=time.monotonic()+.25
    while b.read_u32(mm.MOD_BLOCK+mm.MB_PENDING):
        if time.monotonic()>deadline:
            raise PatchConflict('Radiata render transaction is paused; resume before release')
        time.sleep(.001)
    addr,stock,hook,_,_=RESOURCES[2]
    if b.read_u32(addr)==hook[0]:b.write_u32(addr,stock[0])
