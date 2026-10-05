"""Execute extracted official ARM64 selectors offline, without Android services.

The region-channel test intercepts only calls (mutex and activation), keeping
the original conditional branches intact. This verifies channel selection, not
SF transport, compensation formula, lifecycle, or end-to-end equivalence.
"""
from pathlib import Path
import itertools, json, struct, sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

elf=Elf((ROOT/'coloros_live_ext.so').read_bytes())
index=json.loads((ROOT/'official_branch_audit/fusion/index.json').read_text(encoding='utf8'))
functions=index['functions']
def find(fragment):
    hits=[f for f in functions if fragment in f['symbol']]
    if len(hits)!=1: raise ValueError((fragment,len(hits)))
    f=hits[0]; return int(f['address'],16), f['size'], f

def machine():
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(0,0x100000)
    for p in elf.elf.iter_segments():
        if p['p_type']=='PT_LOAD': u.mem_write(int(p['p_vaddr']),p.data())
    u.mem_map(0x200000,0x200000)
    u.reg_write(UC_ARM64_REG_SP,0x3f0000)
    u.reg_write(UC_ARM64_REG_X30,0x3ff000)
    return u

def selector(fragment,data,expected):
    va,size,_=find(fragment)
    u=machine(); u.mem_write(0x220000+24,struct.pack('<16f',*data))
    u.reg_write(UC_ARM64_REG_X0,0x200000)
    if fragment.endswith('Ei'):
        u.reg_write(UC_ARM64_REG_W1,int(data[15]))
    else:
        u.reg_write(UC_ARM64_REG_X1,0x220000)
    u.emu_start(va,0x3ff000,count=100)
    actual=u.reg_read(UC_ARM64_REG_W0)
    assert actual==expected,(fragment,data,actual,expected)

checks=0
for flag in range(16):
    data=[0.0]*16; data[2]=flag
    selector('11checkDCMode',data,(flag>>1)&1)
    selector('14isPWMTurboMode',data,flag&1)
    checks+=2
for bits in range(16):
    for seq in [0,1,65534,65535]:
        data=[0.0]*16; data[15]=(bits<<16)|seq
        for name,bit in [('24isFactoryModeSensorEvent',18),('26isForceReportedSensorEvent',17),('22isTheLatestSensorEvent',16)]:
            # Names are discovered from symbols rather than fixed addresses.
            hits=[f for f in functions if name[2:] in f['symbol']]
            if len(hits)!=1: raise ValueError(name)
            selector(hits[0]['symbol'],data,(int(data[15])>>bit)&1)
            checks+=1
        hits=[f for f in functions if 'isPendingSensorEventEi' in f['symbol']]
        if len(hits)!=1: raise ValueError('pending selector')
        selector(hits[0]['symbol'],data,int(int(data[15])<65536)); checks+=1
        hits=[f for f in functions if 'getSensorEventIndexE' in f['symbol']]
        if len(hits)!=1: raise ValueError('sequence selector')
        selector(hits[0]['symbol'],data,seq); checks+=1

va,size,info=find('28handleEventForRegionSampling')
ins=list(DIS.disasm(elf.read(va,size),va))
# Locate the actual channel-selection basic block in this binary.
anchors=[i for i in range(1,len(ins)-1) if ins[i].mnemonic=='ldrb' and
         ins[i].op_str=='w9, [x8, #0x44]' and ins[i+1].mnemonic=='tst' and ins[i+1].op_str=='w9, w26']
if len(anchors)!=1: raise ValueError('ambiguous region selector')
first=anchors[0]-1
assert ins[first].mnemonic=='ldur' and ins[first].op_str=='x8, [x29, #-0x48]'
calls={int(c['site'],16):c['symbol'] for c in info['calls']}
activation_sites=[int(c['site'],16) for c in info['calls'] if
    int(c['site'],16)>ins[first].address and ('activateSFScreenshotMonitorLocked' in c['symbol'] or 'activateCWBScreenshotMonitorLocked' in c['symbol'])][:2]
assert len(activation_sites)==2
end_candidates=[a.address for a in ins if a.address>max(activation_sites) and
                a.mnemonic=='bl' and 'mutex6unlockEv' in calls.get(a.address,'')]
assert end_candidates
stop=min(end_candidates)+4
observations=[]
for cwb,available,dc,force_sf,factory,hall in itertools.product([0,1],repeat=6):
    u=machine()
    u.reg_write(UC_ARM64_REG_X19,0x200000)
    u.reg_write(UC_ARM64_REG_X29,0x3e0000)
    u.mem_write(0x3e0000-0x48,struct.pack('<Q',0x210000))
    u.mem_write(0x210000+0x44,bytes([cwb]))
    u.mem_write(0x210000+0xb9,bytes([force_sf]))
    for reg,value in [(UC_ARM64_REG_W21,hall),(UC_ARM64_REG_W22,dc),
                      (UC_ARM64_REG_W24,factory<<18),(UC_ARM64_REG_W26,available)]:
        u.reg_write(reg,value)
    seen=[]
    def hook(uc,address,length,unused):
        name=calls.get(address)
        if name is None: return
        if 'activate' in name:
            seen.append(('SF' if 'activateSF' in name else 'CWB',
                         uc.reg_read(UC_ARM64_REG_W1),uc.reg_read(UC_ARM64_REG_W3),uc.reg_read(UC_ARM64_REG_W4)))
        elif 'mutex6unlockEv' not in name:
            raise ValueError('unexpected external call '+name)
        uc.reg_write(UC_ARM64_REG_W0,0)
        uc.reg_write(UC_ARM64_REG_PC,address+4)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(ins[first].address,stop,count=100)
    expected='CWB' if cwb and available and not(dc and force_sf) else 'SF'
    assert seen==[(expected,hall,factory,1)],(cwb,available,dc,force_sf,factory,hall,seen)
    observations.append(dict(cwb=cwb,available=available,dc=dc,force_sf=force_sf,factory=factory,hall=hall,channel=expected))
    checks+=1

report={'source':index['source'],'source_sha256':index['sha256'],'checks_passed':checks,
        'coverage':['DC/PWM flag extraction','factory/forced-report/latest flags','pending: packed<65536','16-bit sequence extraction',
                    'region CWB/SF selection: all 64 Boolean combinations'],
        'not_covered':['SF Binder transport','filtering/compensation','mode-transition state cleanup',
                       'frame geometry','hardware callbacks','power behaviour'],
        'selector_window':[hex(ins[first].address),hex(stop)],'channel_cases':observations}
(ROOT/'official_branch_audit/mode_oracle_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(f'PASS {checks} official ARM64 branch/selector cases (limited coverage; see mode_oracle_report.json)')
