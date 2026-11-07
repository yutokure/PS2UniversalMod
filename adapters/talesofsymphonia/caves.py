"""Copied look-at/projection arguments and scoped movement/HUD consumers.

A temporary native DATA callback enters lifecycle on the EE thread; the host
never writes executable game code. The projection-call wrapper acknowledges later
changes. No native camera rig, input buffer or actor heading is stored. Code
resources remain after detach, and active damaged caves fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
from core import mips_asm as m
from . import memory_map as mm

class PatchConflict(RuntimeError): pass

def addr(e, reg, value):
    e(m.lui(reg, value >> 16)); e(m.ori(reg, reg, value))
def r(rs, rt, rd, sa, fn): return rs<<21 | rt<<16 | rd<<11 | sa<<6 | fn
def lq(rt, base, off): return 0x78000000 | base<<21 | rt<<16 | (off&65535)
def sq(rt, base, off): return 0x7C000000 | base<<21 | rt<<16 | (off&65535)
def br(a, kind, rs, rt, label):
    a.words.append((kind, rs, rt, label)); a.emit(m.NOP)
def lb(rt, base, off): return 0x90000000 | base<<21 | rt<<16 | (off&65535)
def save(a, regs, off=0):
    for i,reg in enumerate(regs): a.emit(sq(reg,m.SP,off+16*i))
def restore(a, regs, off=0):
    for i,reg in enumerate(regs): a.emit(lq(reg,m.SP,off+16*i))
SCRATCH=(m.T0,m.T1,m.T2,m.T3,m.T4)

def scene(a, reject, mode=None):
    """t1=current native player address; t2=mode. Only ordinary walking."""
    e=a.emit
    addr(e,m.T2,mm.SUBMODE); e(m.lw(m.T2,m.T2,0)); br(a,'bne',m.T2,0,reject)
    addr(e,m.T2,mm.MODE); e(m.lw(m.T2,m.T2,0))
    if mode is not None:
        e(m.addiu(m.T3,0,mode)); br(a,'bne',m.T2,m.T3,reject)
    e(m.addiu(m.T3,0,mm.WORLD_MODE)); br(a,'beq',m.T2,m.T3,'world_scene')
    e(m.addiu(m.T3,0,mm.TOWN_MODE)); br(a,'bne',m.T2,m.T3,reject)
    for address in (mm.TOWN_SCRIPT_CAMERA, mm.TOWN_ALT_CAMERA):
        addr(e,m.T3,address); e(lb(m.T3,m.T3,0)); br(a,'bne',m.T3,0,reject)
    addr(e,m.T1,mm.TOWN_ACTOR); e(m.lw(m.T3,m.T1,0)); addr(e,m.T4,0x13BA20)
    br(a,'bne',m.T3,m.T4,reject)
    e(m.addiu(m.T1,m.T1,4)); br(a,'beq',0,0,'scene_ok')
    a.label('world_scene')
    addr(e,m.T1,mm.WORLD_ROOT); e(m.lw(m.T1,m.T1,0))
    # Validate before dereferencing: aligned, physical EE RAM, enough owner bytes.
    e(m.andi(m.T3,m.T1,15)); br(a,'bne',m.T3,0,reject)
    addr(e,m.T3,0x100000); e(r(m.T1,m.T3,m.T3,0,0x2B)); br(a,'bne',m.T3,0,reject)
    addr(e,m.T3,0x1600000); e(r(m.T1,m.T3,m.T3,0,0x2B)); br(a,'beq',m.T3,0,reject)
    e(m.lw(m.T3,m.T1,0)); e(m.addiu(m.T4,0,1)); br(a,'bne',m.T3,m.T4,reject)
    addr(e,m.T3,mm.WORLD_FLAGS); e(r(m.T1,m.T3,m.T3,0,0x21)); e(m.lw(m.T3,m.T3,0))
    e(m.andi(m.T3,m.T3,mm.WORLD_REJECT_MASK)); br(a,'bne',m.T3,0,reject)
    for off in mm.WORLD_BUSY_BYTES:
        addr(e,m.T3,off); e(r(m.T1,m.T3,m.T3,0,0x21)); e(lb(m.T3,m.T3,0)); br(a,'bne',m.T3,0,reject)
    e(m.addiu(m.T1,m.T1,4)); a.label('scene_ok')

def enabled(a,reject,mode=None):
    e=a.emit; addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T2,m.T0,0)); addr(e,m.T3,mm.MAGIC); br(a,'bne',m.T2,m.T3,reject)
    e(m.lw(m.T2,m.T0,mm.MB_FLAGS)); e(m.andi(m.T2,m.T2,mm.FLAG_ORBIT)); br(a,'beq',m.T2,0,reject)
    scene(a,reject,mode)

def bank(a,reject):
    """t3=published bank, t4=initial even sequence. t1=player, t2=mode."""
    e=a.emit
    e(m.lw(m.T3,m.T0,mm.MB_SLOT)); e(m.andi(m.T3,m.T3,1)); e(r(0,m.T3,m.T3,7,0))
    e(m.addiu(m.T4,m.T0,mm.SLOTS[0])); e(r(m.T3,m.T4,m.T3,0,0x21))
    e(m.lw(m.T4,m.T3,mm.SLOT_MODE)); br(a,'bne',m.T2,m.T4,reject)
    e(m.lw(m.T4,m.T3,mm.SLOT_PLAYER)); br(a,'bne',m.T1,m.T4,reject)
    e(m.lw(m.T4,m.T3,mm.SLOT_SEQUENCE)); e(m.andi(m.T2,m.T4,1)); br(a,'bne',m.T2,0,reject)

def accepted(a,reject,mode=None):
    enabled(a,reject,mode); e=a.emit
    e(m.lw(m.T3,m.T0,mm.MB_ACCEPTED)); br(a,'bne',m.T2,m.T3,reject)
    e(m.lw(m.T3,m.T0,mm.MB_SNAPSHOT+mm.SLOT_PLAYER)); br(a,'bne',m.T1,m.T3,reject)

def callers(a, register, mapping, reject):
    e=a.emit
    for mode,ras in mapping.items():
        e(m.addiu(m.T3,0,mode)); br(a,'bne',m.T2,m.T3,f'caller_next_{mode}')
        for value in ras:
            addr(e,m.T3,value); br(a,'beq',register,m.T3,'caller_ok')
        br(a,'beq',0,0,reject); a.label(f'caller_next_{mode}')
    br(a,'beq',0,0,reject); a.label('caller_ok')

def look_words():
    a=m.Assembler(); e=a.emit; frame=0xE0
    e(m.addiu(m.SP,m.SP,-frame)); e(0xFFBF0090); save(a,SCRATCH)
    save(a,(m.A0,m.A1,m.A2,m.A3),0x50)
    e(m.swc1(0,m.SP,0x98)); e(m.swc1(1,m.SP,0x9C))
    enabled(a,'native')
    e(m.lw(m.T4,m.SP,frame)); callers(a,m.T4,mm.LOOK_CALLERS,'native')
    # Native inputs are recorded, not modified. Accepted data only after seqlock.
    for source,dest in ((m.A1,mm.MB_NATIVE_EYE),(m.A2,mm.MB_NATIVE_TARGET)):
        for off in (0,4,8): e(m.lw(m.T2,source,off)); e(m.sw(m.T2,m.T0,dest+off))
    # callers() clobbers t2; scene mode is read again for bank ownership.
    addr(e,m.T2,mm.MODE); e(m.lw(m.T2,m.T2,0)); bank(a,'native')
    for off in range(0,mm.SLOT_SIZE,16): e(lq(m.T2,m.T3,off)); e(sq(m.T2,m.T0,mm.MB_SNAPSHOT+off))
    e(m.lw(m.T2,m.T3,0)); br(a,'bne',m.T2,m.T4,'native')
    for i in range(3):
        e(m.lwc1(0,m.T1,i*4))
        for slot,out,stack in ((mm.SLOT_EYE,mm.MB_RENDER_EYE,0xA0),(mm.SLOT_TARGET,mm.MB_RENDER_TARGET,0xB0)):
            e(m.lwc1(1,m.T0,mm.MB_SNAPSHOT+slot+i*4)); e(m.add_s(1,0,1))
            e(m.swc1(1,m.T0,out+i*4)); e(m.swc1(1,m.SP,stack+i*4))
    addr(e,m.T2,mm.MODE); e(m.lw(m.T2,m.T2,0)); e(m.sw(m.T2,m.T0,mm.MB_ACCEPTED))
    e(m.lw(m.T2,m.T0,mm.MB_APPLIED)); e(m.ori(m.T2,m.T2,mm.FLAG_ORBIT)); e(m.sw(m.T2,m.T0,mm.MB_APPLIED))
    e(m.lw(m.T2,m.T0,mm.MB_HEARTBEAT)); e(m.addiu(m.T2,m.T2,1)); e(m.sw(m.T2,m.T0,mm.MB_HEARTBEAT))
    restore(a,(m.A0,m.A1,m.A2,m.A3),0x50)
    e(m.addiu(m.A1,m.SP,0xA0)); e(m.addiu(m.A2,m.SP,0xB0))
    br(a,'beq',0,0,'call')
    a.label('native'); restore(a,(m.A0,m.A1,m.A2,m.A3),0x50)
    a.label('call'); restore(a,SCRATCH); e(m.lwc1(0,m.SP,0x98)); e(m.lwc1(1,m.SP,0x9C))
    e(m.jal(mm.LOOK_NATIVE)); e(m.NOP)
    e(0xDFBF0090); e(m.addiu(m.SP,m.SP,frame)); e(0x03E00008); e(m.NOP)
    return a.assemble()

def lens_words():
    a=m.Assembler(); e=a.emit; frame=0xD0
    e(m.addiu(m.SP,m.SP,-frame)); e(0xFFBF0080); save(a,SCRATCH)
    save(a,(m.A0,),0x50); e(m.swc1(0,m.SP,0x60)); e(m.swc1(1,m.SP,0x64)); e(m.swc1(2,m.SP,0x68))
    enabled(a,'native')
    e(m.lw(m.T4,m.SP,frame+0x20)); callers(a,m.T4,mm.LENS_CALLERS,'native')
    e(m.lw(m.T2,m.A0,0)); e(m.sw(m.T2,m.T0,mm.MB_NATIVE_LENS))
    e(m.lw(m.T2,m.A0,20)); e(m.sw(m.T2,m.T0,mm.MB_NATIVE_LENS+4))
    e(m.lw(m.T2,m.A0,0)); e(m.sw(m.T2,m.T0,mm.MB_RENDER_LENS))
    e(m.lw(m.T2,m.A0,20)); e(m.sw(m.T2,m.T0,mm.MB_RENDER_LENS+4))
    addr(e,m.T2,mm.MODE); e(m.lw(m.T2,m.T2,0)); bank(a,'native')
    e(m.lw(m.T2,m.T3,mm.SLOT_FLAGS)); e(m.andi(m.T2,m.T2,mm.FLAG_FOV)); br(a,'beq',m.T2,0,'native')
    e(m.lwc1(0,m.T3,mm.SLOT_SX)); e(m.lw(m.T2,m.T3,0)); br(a,'bne',m.T2,m.T4,'native')
    for off in range(0,64,16): e(lq(m.T2,m.A0,off)); e(sq(m.T2,m.SP,0x90+off))
    # Preserve native sy/sx, near/far and all other projection coefficients.
    e(m.lwc1(1,m.A0,20)); e(m.lwc1(2,m.A0,0)); e(0x46020843)  # div.s f1,f1,f2
    e(0x46000842)  # mul.s f1,f1,f0
    e(m.swc1(0,m.SP,0x90)); e(m.swc1(1,m.SP,0xA4))
    e(m.swc1(0,m.T0,mm.MB_RENDER_LENS)); e(m.swc1(1,m.T0,mm.MB_RENDER_LENS+4))
    e(m.lw(m.T2,m.T0,mm.MB_APPLIED)); e(m.ori(m.T2,m.T2,mm.FLAG_FOV)); e(m.sw(m.T2,m.T0,mm.MB_APPLIED))
    e(m.addiu(m.A0,m.SP,0x90)); br(a,'beq',0,0,'call')
    a.label('native'); restore(a,(m.A0,),0x50)
    a.label('call'); restore(a,SCRATCH)
    for f,off in ((0,0x60),(1,0x64),(2,0x68)): e(m.lwc1(f,m.SP,off))
    e(m.jal(mm.LENS_NATIVE)); e(m.NOP)
    # Post-native lifecycle preserves every register it uses, including V0/V1.
    save(a,SCRATCH); e(m.jal(mm.LIFECYCLE_CAVE)); e(m.NOP)
    restore(a,SCRATCH); e(0xDFBF0080); e(m.addiu(m.SP,m.SP,frame)); e(0x03E00008); e(m.NOP)
    return a.assemble()

def consumer_words(kind,native=None,continuation=None,stock=None,mode=None):
    a=m.Assembler(); e=a.emit
    # No extra native calls: tail-jump after restoring full-width scratch GPRs.
    e(m.addiu(m.SP,m.SP,-0x50)); save(a,SCRATCH)
    if kind in ('move','stream'):
        e(stock[0])
    accepted(a,'fallback',mode)
    if kind=='town':
        e(m.lwc1(12,m.T0,mm.MB_SNAPSHOT+mm.SLOT_FORWARD)); e(m.lwc1(13,m.T0,mm.MB_SNAPSHOT+mm.SLOT_FORWARD+4))
    elif kind in ('compass','map'):
        e(m.lwc1(12,m.T0,mm.MB_SNAPSHOT+mm.SLOT_YAW))
    elif kind in ('move','stream'):
        e(m.lwc1(2 if kind=='move' else 4,m.T0,mm.MB_SNAPSHOT+mm.SLOT_YAW))
    elif kind=='rx':
        restore(a,SCRATCH); e(m.addiu(m.SP,m.SP,0x50)); e(m.addiu(m.V0,0,0)); e(0x03E00008); e(m.NOP)
    a.label('fallback'); restore(a,SCRATCH); e(m.addiu(m.SP,m.SP,0x50))
    if kind in ('move','stream'):
        e(m.j(continuation)); e(stock[1])
    else:
        e(m.j(native)); e(m.NOP)
    return a.assemble()

# Lifecycle uses resources declared below, resolved only when lens_words runs.
def lifecycle(a):
    e=a.emit; addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T2,m.T0,0)); addr(e,m.T3,mm.MAGIC); br(a,'bne',m.T2,m.T3,'life_return')
    e(m.lw(m.T2,m.T0,mm.MB_COMMAND)); e(m.addiu(m.T3,0,mm.CMD_SYNC)); br(a,'bne',m.T2,m.T3,'life_return')
    e(m.lw(m.T4,m.T0,mm.MB_FLAGS)); e(m.andi(m.T2,m.T4,~3&65535)); br(a,'bne',m.T2,0,'life_conflict')
    e(r(0,m.T4,m.T2,16,2)); br(a,'bne',m.T2,0,'life_conflict')
    for i,(site,stock,pair,_,_) in enumerate(RESOURCES):
        addr(e,m.T1,site); e(m.lw(m.T2,m.T1,0)); addr(e,m.T3,stock[0]); br(a,'beq',m.T2,m.T3,f'life_stock{i}')
        addr(e,m.T3,pair[0]); br(a,'bne',m.T2,m.T3,'life_conflict')
        e(m.lw(m.T2,m.T1,4)); addr(e,m.T3,pair[1]); br(a,'bne',m.T2,m.T3,'life_conflict'); br(a,'beq',0,0,f'life_owned{i}')
        a.label(f'life_stock{i}'); e(m.lw(m.T2,m.T1,4)); addr(e,m.T3,stock[1]); br(a,'bne',m.T2,m.T3,'life_conflict')
        a.label(f'life_owned{i}')
    br(a,'beq',m.T4,0,'life_off')
    for site,stock,pair,_,_ in RESOURCES:
        addr(e,m.T1,site); addr(e,m.T2,pair[0]); addr(e,m.T3,pair[1]); e(m.sw(m.T2,m.T1,0)); e(m.sw(m.T3,m.T1,4))
    br(a,'beq',0,0,'life_ack')
    a.label('life_off')
    for site,stock,_,_,_ in reversed(RESOURCES):
        addr(e,m.T1,site); addr(e,m.T2,stock[0]); addr(e,m.T3,stock[1]); e(m.sw(m.T2,m.T1,0)); e(m.sw(m.T3,m.T1,4))
    e(m.sw(0,m.T0,mm.MB_APPLIED)); e(m.sw(0,m.T0,mm.MB_ACCEPTED))
    a.label('life_ack'); e(m.sw(m.T4,m.T0,mm.MB_ACK_FLAGS)); e(m.addiu(m.T2,0,mm.CMD_ACK)); e(m.sw(m.T2,m.T0,mm.MB_COMMAND)); br(a,'beq',0,0,'life_return')
    a.label('life_conflict'); e(m.addiu(m.T2,0,mm.CMD_CONFLICT)); e(m.sw(m.T2,m.T0,mm.MB_COMMAND))
    a.label('life_return')

def lifecycle_words():
    a=m.Assembler(); lifecycle(a)
    a.emit(0x03E00008); a.emit(m.NOP)
    return a.assemble()

def bootstrap_words():
    a=m.Assembler(); e=a.emit
    # Uses no floating point, VU, HI/LO/SA, or unsaved GPR. Native callback is
    # tail-called with its original arguments and full 128-bit caller registers.
    e(m.addiu(m.SP,m.SP,-0x80)); save(a,SCRATCH); e(sq(31,m.SP,0x50))
    addr(e,m.T0,mm.MOD_BLOCK)
    e(m.lw(m.T2,m.T0,0)); addr(e,m.T3,mm.MAGIC); br(a,'bne',m.T2,m.T3,'boot_return')
    e(m.lw(m.T1,m.T0,mm.MB_BOOT_SITE))
    addr(e,m.T3,mm.BOOT_TOWN_SITE); br(a,'beq',m.T1,m.T3,'boot_town')
    addr(e,m.T3,mm.BOOT_WORLD_SITE); br(a,'bne',m.T1,m.T3,'boot_return')
    # Post-world callback has a single exact caller.
    e(m.lw(m.T2,m.SP,0x50)); addr(e,m.T3,0x27FD64); br(a,'bne',m.T2,m.T3,'boot_return')
    e(m.lw(m.T2,m.T0,mm.MB_BOOT_ORIGINAL)); br(a,'beq',m.T2,0,'boot_owned')
    addr(e,m.T3,0x14DC20); br(a,'bne',m.T2,m.T3,'boot_return'); br(a,'beq',0,0,'boot_owned')
    a.label('boot_town')
    e(m.lw(m.T2,m.T0,mm.MB_BOOT_ORIGINAL)); addr(e,m.T3,0x13BA20); br(a,'bne',m.T2,m.T3,'boot_return')
    a.label('boot_owned')
    e(m.lw(m.T2,m.T1,0)); addr(e,m.T3,mm.BOOTSTRAP_CAVE); br(a,'bne',m.T2,m.T3,'boot_return')
    e(m.jal(mm.LIFECYCLE_CAVE)); e(m.NOP)
    addr(e,m.T0,mm.MOD_BLOCK); e(m.lw(m.T1,m.T0,mm.MB_BOOT_SITE))
    e(m.lw(m.T2,m.T1,0)); addr(e,m.T3,mm.BOOTSTRAP_CAVE); br(a,'bne',m.T2,m.T3,'boot_return')
    e(m.lw(m.T2,m.T0,mm.MB_BOOT_ORIGINAL)); e(m.sw(m.T2,m.T1,0))
    br(a,'beq',m.T2,0,'boot_return')
    # Retain target in stack until scratch restored, then use RA as tail-jump
    # temporary? No: JR must preserve caller RA, so branch on original values.
    addr(e,m.T3,0x13BA20); br(a,'beq',m.T2,m.T3,'boot_tail_town')
    restore(a,SCRATCH); e(lq(31,m.SP,0x50)); e(m.addiu(m.SP,m.SP,0x80)); e(m.j(0x14DC20)); e(m.NOP)
    a.label('boot_tail_town'); restore(a,SCRATCH); e(lq(31,m.SP,0x50)); e(m.addiu(m.SP,m.SP,0x80)); e(m.j(0x13BA20)); e(m.NOP)
    a.label('boot_return'); restore(a,SCRATCH); e(lq(31,m.SP,0x50)); e(m.addiu(m.SP,m.SP,0x80)); e(0x03E00008); e(m.NOP)
    return a.assemble()

LOOK_WORDS=look_words()
RESOURCES=[(mm.LOOK_HOOK,mm.LOOK_STOCK,(m.jal(mm.LOOK_CAVE),mm.LOOK_STOCK[1]),mm.LOOK_CAVE,LOOK_WORDS),
           (mm.LENS_HOOK,mm.LENS_STOCK,(m.jal(mm.LENS_CAVE),mm.LENS_STOCK[1]),mm.LENS_CAVE,[])]
for index,site in enumerate(mm.TOWN_MOVE_HOOKS):
    cave=mm.CONSUMER_BASE+index*0x400
    RESOURCES.append((site,mm.TOWN_MOVE_STOCK,(m.jal(cave),mm.TOWN_MOVE_STOCK[1]),cave,consumer_words('town',native=mm.TOWN_MOVE_NATIVE,mode=mm.TOWN_MODE)))
for index,(site,stock,native,kind) in enumerate(((mm.COMPASS_HOOK,mm.COMPASS_STOCK,mm.COMPASS_NATIVE,'compass'),*( (s,st,n,'map') for s,st,n in zip(mm.MAP_HOOKS,mm.MAP_STOCK,mm.MAP_NATIVE)))):
    cave=mm.CONSUMER_BASE+0x800+index*0x400
    RESOURCES.append((site,stock,(m.jal(cave),stock[1]),cave,consumer_words(kind,native=native,mode=mm.WORLD_MODE)))
# Last map wrapper occupies FE000; the rest use the next slots of that page.
for index,(site,stock,kind) in enumerate(((mm.WORLD_MOVE_HOOK,mm.WORLD_MOVE_STOCK,'move'),*((s,st,'stream') for s,st in zip(mm.STREAM_HOOKS,mm.STREAM_STOCK)))):
    cave=mm.EXTRA_BASE+0x400+index*0x300
    RESOURCES.append((site,stock,(m.j(cave),m.NOP),cave,consumer_words(kind,continuation=site+8,stock=stock,mode=mm.WORLD_MODE)))
RX_CAVE=mm.EXTRA_BASE+0xD00
RESOURCES.append((mm.RX_HOOK,mm.RX_STOCK,(m.jal(RX_CAVE),mm.RX_STOCK[1]),RX_CAVE,consumer_words('rx',native=mm.RX_NATIVE,mode=mm.WORLD_MODE)))
LENS_WORDS=lens_words()
RESOURCES[1]=(*RESOURCES[1][:4],LENS_WORDS)
RESOURCES=tuple(RESOURCES)
LIFECYCLE_WORDS=lifecycle_words()
BOOTSTRAP_WORDS=bootstrap_words()
CODE_RESOURCES=tuple((address,words) for _,_,_,address,words in RESOURCES)+((mm.LIFECYCLE_CAVE,LIFECYCLE_WORDS),(mm.BOOTSTRAP_CAVE,BOOTSTRAP_WORDS))

@dataclass(frozen=True)
class Inspection:
    state: str
    empty: tuple[int,...]
    init: bool

def read_words(b,address,count): return tuple(b.read_u32(address+4*i) for i in range(count))
def site_state(b):
    states=[('stock' if (p:=read_words(b,s,2))==stock else 'applied' if p==pair else 'unknown') for s,stock,pair,_,_ in RESOURCES]
    return 'unknown' if 'unknown' in states else 'stock' if set(states)=={'stock'} else 'applied'
def ready(b):
    """Hot ownership check; body-only damage is detected by the next full audit."""
    if not matches(b,1): return False
    if b.read_u32(mm.MOD_BLOCK)!=mm.MAGIC: return False
    flags=b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)
    return flags in (1,3) and b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)==mm.CMD_ACK and b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)==flags

def preflight(b):
    state=site_state(b)
    if state=='unknown': raise PatchConflict('unknown Symphonia instruction or delay; refusing writes')
    empty=[]
    for address,words in CODE_RESOURCES:
        actual=read_words(b,address,len(words))
        if actual!=tuple(words):
            if any(actual) or state!='stock': raise PatchConflict('Symphonia cave occupied, damaged or still reachable')
            empty.append(address)
    magic=b.read_u32(mm.MOD_BLOCK)
    if magic not in (0,mm.MAGIC): raise PatchConflict('Symphonia control block occupied')
    if state!='stock' and magic!=mm.MAGIC: raise PatchConflict('Symphonia active code without control ownership')
    for site in (mm.BOOT_TOWN_SITE,mm.BOOT_WORLD_SITE):
        if b.read_u32(site)==mm.BOOTSTRAP_CAVE and (magic!=mm.MAGIC or empty):
            raise PatchConflict('Symphonia active data callback has no intact owned resources')
    if not magic and any(read_words(b,mm.MOD_BLOCK,mm.BLOCK_SIZE//4)): raise PatchConflict('Symphonia control block is not empty')
    return Inspection(state,tuple(empty),not magic)
def prepare(b,inspection):
    for address,words in CODE_RESOURCES:
        if address in inspection.empty:
            for i,w in enumerate(words): b.write_u32(address+4*i,w)
    if inspection.init: b.write_u32(mm.MOD_BLOCK,mm.MAGIC)
    return Inspection(inspection.state,(),False)
def matches(b,flags): return all(read_words(b,s,2)==(pair if flags else stock) for s,stock,pair,_,_ in RESOURCES)
def wait_ack(b,flags,deadline):
    while True:
        command=b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
        if command==mm.CMD_ACK:
            if b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)!=flags or not matches(b,flags): raise PatchConflict('Symphonia guest ACK/readback mismatch')
            site=b.read_u32(mm.MOD_BLOCK+mm.MB_BOOT_SITE)
            if site in (mm.BOOT_TOWN_SITE,mm.BOOT_WORLD_SITE) and b.read_u32(site)==mm.BOOTSTRAP_CAVE:
                if time.monotonic()>=deadline: raise PatchConflict('Symphonia data callback has not returned')
                time.sleep(.001); continue
            return
        if command==mm.CMD_CONFLICT: raise PatchConflict('Symphonia guest found unknown instructions; load stock state')
        if time.monotonic()>=deadline: raise PatchConflict('Symphonia lifecycle paused/unavailable; resume before enable/restore')
        time.sleep(.001)
def sync(b,flags,inspection=None):
    if flags not in (0,1,3): raise ValueError('invalid Symphonia lifecycle mask')
    p=inspection or preflight(b)
    if not flags and p.state=='stock':
        if not p.init:
            pending=any(b.read_u32(site)==mm.BOOTSTRAP_CAVE for site in (mm.BOOT_TOWN_SITE,mm.BOOT_WORLD_SITE))
            if pending:
                site=b.read_u32(mm.MOD_BLOCK+mm.MB_BOOT_SITE)
                if site not in (mm.BOOT_TOWN_SITE,mm.BOOT_WORLD_SITE) or b.read_u32(site)!=mm.BOOTSTRAP_CAVE:
                    raise PatchConflict('unknown Symphonia pending data callback owner')
                # Cancel a paused/timed-out enable before it can install hooks.
                # Completion still requires the EE to return its DATA callback.
                command=b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
                if command==mm.CMD_SYNC:
                    # Do not re-arm CMD_SYNC: the EE can consume this request
                    # immediately after FLAGS0 and return the last callback.
                    b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,0)
                    wait_ack(b,0,time.monotonic()+.75)
                elif command==mm.CMD_ACK:
                    # The earlier enable may already be completing. Drain that
                    # ACK/callback before starting a fresh, fully audited detach.
                    wait_ack(b,b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS),time.monotonic()+.75)
                    return sync(b,0)
                else:
                    raise PatchConflict('unknown Symphonia pending lifecycle request')
            else:
                b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,0); b.write_u32(mm.MOD_BLOCK+mm.MB_ACCEPTED,0); b.write_u32(mm.MOD_BLOCK+mm.MB_APPLIED,0)
        return
    if p.init or p.empty: raise PatchConflict('Symphonia caves must be prepared before attaching')
    deadline=time.monotonic()+.75
    cmd=b.read_u32(mm.MOD_BLOCK+mm.MB_COMMAND)
    if cmd==mm.CMD_CONFLICT: raise PatchConflict('Symphonia lifecycle conflict; load stock state')
    if cmd==mm.CMD_SYNC: wait_ack(b,b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS),deadline)
    if matches(b,flags) and b.read_u32(mm.MOD_BLOCK+mm.MB_FLAGS)==flags and b.read_u32(mm.MOD_BLOCK+mm.MB_ACK_FLAGS)==flags: return
    bootstrap=b.read_u32(mm.LENS_HOOK)==mm.LENS_STOCK[0]
    boot=None
    if bootstrap:
        mode=b.read_u32(mm.MODE)
        if mode==mm.TOWN_MODE:
            site=mm.BOOT_TOWN_SITE; allowed=(0x13BA20,)
        elif mode==mm.WORLD_MODE:
            site=mm.BOOT_WORLD_SITE; allowed=(0,0x14DC20)
        else: raise PatchConflict('Symphonia bootstrap needs an ordinary town/world frame')
        original=b.read_u32(site)
        if original==mm.BOOTSTRAP_CAVE:
            if b.read_u32(mm.MOD_BLOCK+mm.MB_BOOT_SITE)!=site: raise PatchConflict('unknown Symphonia bootstrap data owner')
        elif original in allowed: boot=(site,original)
        else: raise PatchConflict('native Symphonia frame callback is not available')
    b.write_u32(mm.MOD_BLOCK+mm.MB_FLAGS,flags)
    if boot:
        b.write_u32(mm.MOD_BLOCK+mm.MB_BOOT_SITE,boot[0]); b.write_u32(mm.MOD_BLOCK+mm.MB_BOOT_ORIGINAL,boot[1])
    b.write_u32(mm.MOD_BLOCK+mm.MB_COMMAND,mm.CMD_SYNC)
    if boot: b.write_u32(boot[0],mm.BOOTSTRAP_CAVE)
    wait_ack(b,flags,deadline)
