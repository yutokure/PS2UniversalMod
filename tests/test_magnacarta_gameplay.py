"""Small instruction interpreter: branch delay slots, full128 GPRs and FP flags.

These tests prove cave control flow/state preservation, not game-visible effects.
Run standalone from the repo with PYTHONPATH=repo and gameplay.py alongside.
"""
import importlib.util
from pathlib import Path
import struct
import unittest

try:
    from adapters.magnacarta import gameplay as g
except ImportError:
    spec = importlib.util.spec_from_file_location('gameplay', Path(__file__).with_name('gameplay.py'))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)

MASK64 = (1 << 64) - 1
MASK128 = (1 << 128) - 1

def sx(n, bits):
    n &= (1 << bits) - 1
    return n - (1 << bits) if n >> (bits - 1) else n

def fb(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]

class EE:
    def __init__(self, flags=0, mode=1):
        self.r = [((0x12340000+i)<<96) | ((0x56780000+i)<<64) | (0x11110000+i) for i in range(32)]
        self.r[0] = 0; self.r[29] = 0x1F00000; self.r[28] = 0x542C70
        self.f = [fb(100+i) for i in range(32)]; self.fcsr = 0x01000000
        self.mem = {}; self.pc = 0; self.steps = 0
        self.owner = 0xE30210; self.state = 0xE3CCF0; self.magi = 0x12031B0; self.monster = 0x14934C0
        self.put(g.MOD_BLOCK, g.MAGIC); self.put(g.MOD_BLOCK+4, flags)
        self.put(g.ROOT_POINTER, self.owner); self.put(self.owner+0x330, self.state)
        self.mem[self.state+0x91] = mode
        self.put(self.magi+0x220, self.owner); self.put(self.monster+0x268, self.magi)
        self.r[4] = self.magi; self.r[17] = self.monster
        self.put(self.magi+0x378, fb(240)); self.put(0x53B864, 5)
    def put(self, a, v, n=4):
        for i in range(n): self.mem[a+i] = (v>>(8*i)) & 255
    def get(self, a, n=4):
        return sum(self.mem.get(a+i, 0)<<(8*i) for i in range(n))
    def setr(self, r, v):
        if r: self.r[r] = (self.r[r] & (MASK128 ^ MASK64)) | (v & MASK64)
    def ins(self, w):
        op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;rd=(w>>11)&31;imm=sx(w,16)
        a=(self.r[rs]+imm)&MASK64
        if w==0: return None
        if op==2: return (self.pc & 0xF0000000)|((w&0x3FFFFFF)<<2)
        if op in (4,5):
            eq=(self.r[rs]&MASK64)==(self.r[rt]&MASK64)
            return self.pc+4+imm*4 if (eq if op==4 else not eq) else self.pc+8
        if op==6: return self.pc+4+imm*4 if sx(self.r[rs],64)<=0 else self.pc+8
        if op==9: self.setr(rt,sx(a,32))
        elif op==15: self.setr(rt,sx((w&65535)<<16,32))
        elif op==13: self.setr(rt,self.r[rs]|(w&65535))
        elif op==12: self.setr(rt,self.r[rs]&(w&65535))
        elif op==11: self.setr(rt,int((self.r[rs]&MASK64)<(imm&MASK64)))
        elif op==35: self.setr(rt,sx(self.get(a),32))
        elif op==36: self.setr(rt,self.get(a,1))
        elif op==49: self.f[rt]=self.get(a)
        elif op==31: self.put(a,self.r[rt],16)
        elif op==30:
            if rt:self.r[rt]=self.get(a,16)
        elif op==0:
            fn=w&63
            if fn==0x24:self.setr(rd,self.r[rs]&self.r[rt])
            elif fn==0x2D:self.setr(rd,self.r[rs]+self.r[rt])
            elif fn==0x2A:self.setr(rd,int(sx(self.r[rs],64)<sx(self.r[rt],64)))
            elif fn==0x2B:self.setr(rd,int((self.r[rs]&MASK64)<(self.r[rt]&MASK64)))
            else:raise AssertionError(hex(w))
        elif op==17:
            if rs==0:self.setr(rt,sx(self.f[rd],32))
            elif rs==4:self.f[rd]=self.r[rt]&0xFFFFFFFF
            elif w==g.SIGHT_STOCK[1]:
                x,y=[struct.unpack('<f',struct.pack('<I',self.f[i]))[0] for i in (12,1)]
                self.fcsr=(self.fcsr&~(1<<23))|((1<<23) if x<=y else 0)
            else:raise AssertionError(hex(w))
        else:raise AssertionError(hex(w))
        return None
    def run(self, base, words):
        code={base+i*4:w for i,w in enumerate(words)}; self.pc=base
        while self.pc in code:
            self.steps+=1
            assert self.steps<1000
            target=self.ins(code[self.pc])
            if target is not None:
                self.pc+=4
                assert self.pc in code
                assert self.ins(code[self.pc]) is None
                self.pc=target
            else:self.pc+=4
        return self.pc

class GameplayCavesTest(unittest.TestCase):
    def test_resource_sizes_and_exact_pairs(self):
        self.assertEqual([a for a,_ in g.code_resources()], [0xFA000,0xFB000,0xFC000])
        for addr,words in g.code_resources():
            self.assertLessEqual(len(words)*4,0x1000)
            self.assertTrue(all(isinstance(w,int) and 0<=w<2**32 for w in words))
        for (site,stock,pair),(addr,_) in zip(g.resources(),g.code_resources()):
            self.assertEqual(pair,(g.m.j(addr),0))
        self.assertEqual(g.SIGHT_STOCK,(0xC4810378,0x46016036))
        self.assertEqual(g.ENCOUNTER_STOCK,(0x1040001F,0x0220202D))
        self.assertEqual(g.RING_STOCK,(0x8F858BF4,0x18A00133))
    def check_scratch(self,e,before,outputs):
        for r in range(32):
            if r not in outputs:self.assertEqual(e.r[r],before[r],f'reg {r}')
    def test_sight_max_and_preservation(self):
        for native in (240.,960.,1200.,0.,-1.,float('inf')):
            for flags in (0,1,2,4,8,12):
                e=EE(flags);e.put(e.magi+0x378,fb(native));before=e.r.copy();mem=e.mem.copy();fs=e.f.copy()
                self.assertEqual(e.run(g.SIGHT_CAVE,g.sight_words()),g.SIGHT_SITE+8)
                self.assertEqual(e.f[1],fb(max(native,960.) if flags&4 else native))
                self.assertEqual([v for i,v in enumerate(e.f) if i!=1],[v for i,v in enumerate(fs) if i!=1])
                self.check_scratch(e,before,set())
                for a,v in mem.items():self.assertEqual(e.mem[a],v)
    def test_sight_nan_unchanged(self):
        for bits in (0x7FC01234,0xFFC01234):
            e=EE(4);e.put(e.magi+0x378,bits);e.run(g.SIGHT_CAVE,g.sight_words());self.assertEqual(e.f[1],bits)
    def test_encounter_branch_both_paths(self):
        for flags in (0,4,8,12):
            for v0 in (0,1,0x123456):
                e=EE(flags);e.r[2]=v0;before=e.r.copy();f=e.f.copy();fc=e.fcsr
                expected=0x3F6B84 if flags&8 or not v0 else g.ENCOUNTER_SITE+8
                self.assertEqual(e.run(g.ENCOUNTER_CAVE,g.encounter_words()),expected)
                self.assertEqual(e.r[4]&MASK64,before[17]&MASK64)
                self.check_scratch(e,before,{4});self.assertEqual(e.f,f);self.assertEqual(e.fcsr,fc)
    def test_ring_hides_only_no_encounters_and_preserves_globals(self):
        for flags in (0,1,2,4,8):
            for radius in (-1,0,5,20):
                e=EE(flags);e.put(0x53B864,radius&0xFFFFFFFF);before=e.r.copy();fc=e.fcsr
                self.assertEqual(e.run(g.RING_CAVE,g.ring_words()),0x1D09B0 if flags&8 or radius<=0 else g.RING_SITE+12)
                self.check_scratch(e,before,{5,18});self.assertEqual(e.r[18]&MASK64,before[4]&MASK64)
                self.assertEqual(e.get(0x53B864),radius&0xFFFFFFFF);self.assertEqual(e.fcsr,fc)
    def test_reject_bad_magic_mode_root_and_context(self):
        for kind in ('magic','mode','root_low','root_unaligned','state_high','owner'):
            for lane,addr,words in [('sight',g.SIGHT_CAVE,g.sight_words()),('enc',g.ENCOUNTER_CAVE,g.encounter_words()),('ring',g.RING_CAVE,g.ring_words())]:
                if kind=='owner' and lane=='ring':continue
                e=EE(12);e.r[2]=1
                if kind=='magic':e.put(g.MOD_BLOCK,0)
                if kind=='mode':e.mem[e.state+0x91]=3
                if kind=='root_low':e.put(g.ROOT_POINTER,0x200)
                if kind=='root_unaligned':e.put(g.ROOT_POINTER,e.owner+1)
                if kind=='state_high':e.put(e.owner+0x330,0x2000000)
                if kind=='owner':e.put(e.magi+0x220,e.owner+4)
                e.run(addr,words)
                if lane=='sight':self.assertEqual(e.f[1],fb(240))
                elif lane=='enc':self.assertEqual(e.pc,g.ENCOUNTER_SITE+8)
                else:self.assertEqual(e.pc,g.RING_SITE+12)

if __name__=='__main__':unittest.main()
