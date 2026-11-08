"""Field render-copy arguments and EE-thread lifecycle, bootstrapped through data.

The host never writes executable game instructions. Each lifecycle transaction
enters via the native renderer's virtual method pointer, restores that pointer,
then runs the original method. Unknown pairs/caves always fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
from core import mips_asm as m
from . import memory_map as mm, directions

class PatchConflict(RuntimeError):
    pass

def addr(e, reg, value):
    e(m.lui(reg, value >> 16)); e(m.ori(reg, reg, value))
def sq(reg, off): return 0x7C000000 | m.SP << 21 | reg << 16 | off
def lq(reg, off): return 0x78000000 | m.SP << 21 | reg << 16 | off
def br(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label)); a.emit(m.NOP)
def save(a, regs, off=0):
    for i, reg in enumerate(regs): a.emit(sq(reg, off+16*i))
def restore(a, regs, off=0):
    for i, reg in enumerate(regs): a.emit(lq(reg, off+16*i))
SCRATCH = (8, 9, 10, 11, 12)

def pointer(a, reg, reject, *, legacy=False):
    e=a.emit
    e(m.andi(11,reg,15)); br(a,'bne',11,0,reject)
    e(m.lui(11,0x10)); e(reg<<21 | 11<<16 | 11<<11 | 0x2B); br(a,'bne',11,0,reject)
    if legacy: e(m.lui(11,0x200))
    else: addr(e,11,0x1FFF000)  # room for every subsequent property load
    e(reg<<21 | 11<<16 | 11<<11 | 0x2B); br(a,'beq',11,0,reject)

def scene(a, reject, *, legacy=False):
    """t1=current pawn, t0=control. Scratch t2/t3/t4 only.

    legacy emits the exact released MCA1 body solely for safe state migration;
    it is never installed as the new renderer.
    """
    e=a.emit
    addr(e,9,mm.PLAYER_GLOBAL); e(m.lw(9,9,0)); pointer(a,9,reject,legacy=legacy)
    if legacy:
        addr(e,10,mm.FIELD_OWNER_GLOBAL); e(m.lw(10,10,0)); pointer(a,10,reject,legacy=legacy)
    else:
        e(m.lw(12,9,mm.PLAYER_MAGI)); pointer(a,12,reject)
        e(m.lw(10,12,mm.MAGI_OWNER)); pointer(a,10,reject,legacy=legacy)
        addr(e,11,mm.FIELD_OWNER_GLOBAL); e(m.lw(11,11,0)); br(a,'bne',11,10,reject)
        e(m.lw(11,10,mm.OWNER_MAGI)); br(a,'bne',11,12,reject)
    e(m.lw(10,10,mm.STATE_POINTER)); pointer(a,10,reject,legacy=legacy)
    e(0x90000000 | 10<<21 | 10<<16 | mm.STATE_MODE)
    e(m.addiu(11,0,1)); br(a,'beq',10,11,'scene_ok')
    e(m.addiu(11,0,2)); br(a,'bne',10,11,reject)
    a.label('scene_ok')
    if legacy:
        addr(e,10,0x56DB1C); e(m.lw(10,10,0)); pointer(a,10,reject,legacy=legacy)
    else:
        e(m.lw(10,9,mm.PLAYER_MAGI))  # already pointer/ownership checked above
    e(m.lw(10,10,0xC)); pointer(a,10,reject,legacy=legacy)
    e(m.lw(10,10,0x18)); pointer(a,10,reject,legacy=legacy)
    e(m.lw(10,10,0x20))
    e(m.addiu(11,0,mm.FIELD_SCRIPT_NAMES[0])); br(a,'beq',10,11,'script_ok')
    e(m.addiu(11,0,mm.FIELD_SCRIPT_NAMES[1])); br(a,'bne',10,11,reject)
    a.label('script_ok')

def render_words(*, legacy=False):
    a=m.Assembler(); e=a.emit; frame=0x100
    e(m.addiu(29,29,-frame)); save(a,SCRATCH); e(sq(31,0x50)); e(sq(7,0x60))
    for f,off in ((0,0x70),(1,0x74),(12,0x78)): e(m.swc1(f,29,off))
    addr(e,8,mm.MOD_BLOCK)
    e(m.lw(10,8,0)); addr(e,11,mm.MAGIC); br(a,'bne',10,11,'native')
    e(m.sw(0,8,mm.MB_ACCEPTED))  # Revoke stale movement ownership every render.
    e(m.lw(10,8,mm.MB_FLAGS)); e(m.andi(10,10,mm.FLAG_ORBIT)); br(a,'beq',10,0,'native')
    scene(a,'native',legacy=legacy)
    # This callsite's A2 is the ordinary player's view actor; never follow a
    # different script camera. Movement also checks its controller's pawn.
    br(a,'bne',9,6,'native')  # A2 is the current player view actor itself.
    for i in range(3):
        e(m.lw(10,7,4*i)); e(m.sw(10,8,mm.MB_NATIVE_EYE+4*i))
    e(m.lw(12,29,0))  # original T0 (rotation pointer), low word
    for i in range(3):
        e(m.lw(10,12,4*i)); e(m.sw(10,8,mm.MB_NATIVE_ROTATION+4*i))
    e(m.swc1(12,8,mm.MB_NATIVE_FOV))
    e(m.lw(10,8,mm.MB_SLOT)); e(m.andi(10,10,1)); e(10<<16 | 10<<11 | 7<<6)
    e(m.addiu(12,8,mm.SLOTS[0])); e(10<<21 | 12<<16 | 12<<11 | 0x21)
    e(m.lw(10,12,mm.SLOT_PLAYER)); br(a,'bne',9,10,'native')
    e(m.lw(11,12,mm.SLOT_SEQUENCE)); e(m.andi(10,11,1)); br(a,'bne',10,0,'native')
    for off in range(0,0x80,4): e(m.lw(10,12,off)); e(m.sw(10,8,mm.MB_SNAPSHOT+off))
    e(m.lw(10,12,0)); br(a,'bne',10,11,'native')
    for i in range(3):
        e(m.lwc1(0,9,mm.PLAYER_POSITION+4*i))
        for slot,out,stack in ((mm.SLOT_EYE,mm.MB_RENDER_EYE,0xA0),(mm.SLOT_TARGET,mm.MB_RENDER_TARGET,0xB0)):
            e(m.lwc1(1,8,mm.MB_SNAPSHOT+slot+4*i)); e(m.add_s(1,0,1))
            e(m.swc1(1,8,out+4*i)); e(m.swc1(1,29,stack+4*i))
    e(m.lw(10,8,mm.MB_SNAPSHOT+mm.SLOT_PITCH)); e(m.sw(10,29,0xC0))
    e(m.lw(10,8,mm.MB_SNAPSHOT+mm.SLOT_ROT_YAW)); e(m.sw(10,29,0xC4)); e(m.sw(0,29,0xC8))
    e(m.lw(10,8,mm.MB_SNAPSHOT+mm.SLOT_FLAGS)); e(m.andi(10,10,mm.FLAG_FOV))
    br(a,'beq',10,0,'lens_native'); e(m.lwc1(12,8,mm.MB_SNAPSHOT+mm.SLOT_FOV))
    a.label('lens_native'); e(m.swc1(12,8,mm.MB_RENDER_FOV))
    e(m.sw(9,8,mm.MB_ACCEPTED)); e(m.addiu(10,0,1)); e(m.sw(10,8,mm.MB_APPLIED))
    e(m.lw(10,8,mm.MB_HEARTBEAT)); e(m.addiu(10,10,1)); e(m.sw(10,8,mm.MB_HEARTBEAT))
    restore(a,SCRATCH); e(m.addiu(7,29,0xA0)); e(m.addiu(8,29,0xC0)); br(a,'beq',0,0,'call')
    a.label('native'); restore(a,SCRATCH); e(lq(7,0x60))
    a.label('call')
    # A0/A1/A2 untouched, native builder receives copied eye/rotator and FOV.
    e(m.lwc1(0,29,0x70)); e(m.lwc1(1,29,0x74)); e(m.jal(mm.RENDER_NATIVE)); e(m.NOP)
    e(lq(31,0x50)); e(lq(7,0x60)); e(m.lwc1(12,29,0x78))
    e(m.addiu(29,29,frame)); e(0x03E00008); e(m.NOP)
    return tuple(a.assemble())

RENDER_WORDS=render_words()
# Exact released body, not an allowlist based on magic/header alone.
LEGACY_RENDER_WORDS=render_words(legacy=True)

def _external():
    from . import gameplay
    return directions.resources()+gameplay.resources(), directions.code_resources()+gameplay.code_resources()

def resources():
    hooks,_=_external()
    return ((mm.RENDER_HOOK,mm.RENDER_STOCK,(m.jal(mm.RENDER_CAVE),mm.RENDER_STOCK[1])),)+hooks

def boot_words():
    a=m.Assembler(); e=a.emit
    e(m.addiu(29,29,-0x60)); save(a,SCRATCH); e(sq(31,0x50))
    addr(e,8,mm.MOD_BLOCK); e(m.lw(10,8,0)); addr(e,11,mm.MAGIC); br(a,'bne',10,11,'return_native')
    addr(e,9,mm.BOOT_SITE); e(m.lw(10,9,0)); addr(e,11,mm.BOOT_CAVE); br(a,'bne',10,11,'return_native')
    e(m.lw(10,8,mm.MB_COMMAND)); e(m.addiu(11,0,mm.CMD_SYNC)); br(a,'bne',10,11,'return_native')
    e(m.lw(12,8,mm.MB_FLAGS)); e(m.andi(10,12,0xFFF0)); br(a,'bne',10,0,'conflict')
    # Preflight every instruction pair before changing any pair.
    for i,(site,stock,pair) in enumerate(resources()):
        addr(e,9,site); e(m.lw(10,9,0)); addr(e,11,stock[0]); br(a,'beq',10,11,f'stock{i}')
        addr(e,11,pair[0]); br(a,'bne',10,11,'conflict')
        e(m.lw(10,9,4)); addr(e,11,pair[1]); br(a,'bne',10,11,'conflict'); br(a,'beq',0,0,f'ok{i}')
        a.label(f'stock{i}'); e(m.lw(10,9,4)); addr(e,11,stock[1]); br(a,'bne',10,11,'conflict'); a.label(f'ok{i}')
    br(a,'beq',12,0,'off')
    for site,stock,pair in resources():
        addr(e,9,site)
        for off,w in enumerate(pair): addr(e,10,w); e(m.sw(10,9,off*4))
    br(a,'beq',0,0,'ack')
    a.label('off')
    for site,stock,pair in reversed(resources()):
        addr(e,9,site)
        for off,w in enumerate(stock): addr(e,10,w); e(m.sw(10,9,off*4))
    e(m.sw(0,8,mm.MB_APPLIED)); e(m.sw(0,8,mm.MB_ACCEPTED))
    a.label('ack'); e(m.sw(12,8,mm.MB_ACK_FLAGS)); e(m.addiu(10,0,mm.CMD_ACK)); e(m.sw(10,8,mm.MB_COMMAND)); br(a,'beq',0,0,'return_native')
    a.label('conflict'); e(m.addiu(10,0,mm.CMD_CONFLICT)); e(m.sw(10,8,mm.MB_COMMAND))
    a.label('return_native'); addr(e,9,mm.BOOT_SITE); e(m.lw(10,9,0)); addr(e,11,mm.BOOT_CAVE)
    br(a,'bne',10,11,'tail'); addr(e,10,mm.BOOT_NATIVE); e(m.sw(10,9,0))
    a.label('tail'); restore(a,SCRATCH); e(lq(31,0x50)); e(m.addiu(29,29,0x60)); e(m.j(mm.BOOT_NATIVE)); e(m.NOP)
    return tuple(a.assemble())

def code_resources():
    _,code=_external()
    return ((mm.BOOT_CAVE,boot_words()),(mm.RENDER_CAVE,RENDER_WORDS))+code

def read_words(b,address,count): return tuple(b.read_u32(address+4*i) for i in range(count))
def site_state(b):
    states=['stock' if (actual:=read_words(b,s,2))==stock else 'applied' if actual==pair else 'unknown' for s,stock,pair in resources()]
    return 'unknown' if 'unknown' in states else 'stock' if set(states)=={'stock'} else 'applied'
@dataclass(frozen=True)
class Inspection:
    empty: tuple[int,...]
    init: bool
    state: str
    legacy: bool = False

def preflight(b):
    state=site_state(b)
    if state=='unknown': raise PatchConflict('unknown Magna Carta hook/delay instruction')
    boot=b.read_u32(mm.BOOT_SITE)
    if boot not in (mm.BOOT_NATIVE,mm.BOOT_CAVE): raise PatchConflict('unknown Magna Carta render virtual method')
    empty=[]; legacy=False
    for address,words in code_resources():
        actual=read_words(b,address,len(words))
        if actual!=tuple(words):
            if (address==mm.RENDER_CAVE
                    and actual==LEGACY_RENDER_WORDS+(0,)*(len(words)-len(LEGACY_RENDER_WORDS))):
                legacy=True
            else:
                if any(actual) or state!='stock' or boot!=mm.BOOT_NATIVE: raise PatchConflict('Magna Carta cave occupied, damaged or reachable')
                empty.append(address)
    magic=b.read_u32(mm.MOD_BLOCK)
    if magic not in (0,mm.MAGIC): raise PatchConflict('Magna Carta control block occupied')
    if (state!='stock' or boot!=mm.BOOT_NATIVE) and magic!=mm.MAGIC: raise PatchConflict('Magna Carta active hooks without ownership')
    if not magic and any(read_words(b,mm.MOD_BLOCK,mm.BLOCK_SIZE//4)): raise PatchConflict('Magna Carta control block not empty')
    if legacy and (empty or magic!=mm.MAGIC or boot!=mm.BOOT_NATIVE
                   or b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)!=mm.CMD_ACK
                   or b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)&~15
                   or b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)!=b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)):
        raise PatchConflict('Magna Carta legacy state is incomplete or busy; load clean stock state')
    return Inspection(tuple(empty),not magic,state,legacy)

def prepare(b,p):
    if p.legacy:
        # Drain the exact released renderer through its unchanged EE lifecycle.
        # Only after ACK + every hook stock + callback native is its body unreachable.
        sync(b,0,Inspection((),False,p.state))
        released=preflight(b)
        if (released.state!='stock' or not released.legacy
                or b.read_u32(mm.BOOT_SITE)!=mm.BOOT_NATIVE):
            raise PatchConflict('Magna Carta legacy release/readback mismatch')
        for i,w in enumerate(RENDER_WORDS): b.write_u32(mm.RENDER_CAVE+4*i,w)
    for address,words in code_resources():
        if address in p.empty:
            for i,w in enumerate(words): b.write_u32(address+4*i,w)
    if p.init: b.write_u32(mm.MOD_BLOCK,mm.MAGIC)

def matches(b,flags): return all(read_words(b,s,2)==(pair if flags else stock) for s,stock,pair in resources())
def ready(b):
    flags=b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)
    return (b.read_u32(mm.MOD_BLOCK)==mm.MAGIC and b.read_u32(mm.BOOT_SITE)==mm.BOOT_NATIVE
            and b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)==mm.CMD_ACK
            and b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)==flags and matches(b,flags))
def wait_ack(b,flags):
    deadline=time.monotonic()+1.0
    while True:
        cmd=b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
        if cmd==mm.CMD_CONFLICT: raise PatchConflict('Magna Carta guest found unknown hook instructions')
        if cmd==mm.CMD_ACK and b.read_u32(mm.BOOT_SITE)==mm.BOOT_NATIVE:
            if b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)!=flags or not matches(b,flags): raise PatchConflict('Magna Carta lifecycle ACK/readback mismatch')
            return
        if time.monotonic()>=deadline: raise PatchConflict('Magna Carta lifecycle paused/unavailable; resume game before retry')
        time.sleep(.001)
def sync(b,flags,p=None):
    if flags & ~15: raise ValueError('invalid Magna Carta flag mask')
    p=p or preflight(b)
    if not flags and p.init and p.state=='stock': return
    prepare(b,p)
    cmd=b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
    if cmd==mm.CMD_CONFLICT: raise PatchConflict('Magna Carta lifecycle conflict; load clean stock state')
    if cmd==mm.CMD_SYNC:
        # A previous paused enable must complete/cancel before new request.
        b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags); wait_ack(b,flags); return
    if ready(b) and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)==flags: return
    b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags)
    b.write_u32(mm.MOD_BLOCK+mm.MB_COMMAND,mm.CMD_SYNC)
    b.write_u32(mm.BOOT_SITE,mm.BOOT_CAVE)
    wait_ack(b,flags)
