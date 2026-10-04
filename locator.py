"""Locate patch sites in target functions; recipes store patterns, not file offsets."""
import json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from capstone.arm64 import ARM64_OP_MEM,ARM64_OP_IMM,ARM64_OP_REG

DIS=Cs(CS_ARCH_ARM64,CS_MODE_ARM);DIS.detail=True
PATH=Path(__file__).resolve().parent/'assets/dynamic_sites.json'

def words(e,name):
    a,z=e.symbols[name]
    return a,list(struct.unpack('<'+'I'*(z//4),e.read(a,z)))

def resolve(e,rule):
    name=rule['name']
    if name not in e.symbols:raise ValueError('缺少原生符号 '+name)
    if rule.get('entry'):return e.symbols[name][0]
    a,raw=words(e,name);hits=set()
    for pattern in rule['patterns']:
        masks,values=pattern['masks'],pattern['words'];n=len(values)
        for index in range(len(raw)-n+1):
            if all(raw[index+j]&masks[j]==values[j] for j in range(n)):
                hits.add(a+(index+pattern['anchor'])*4)
    if len(hits)!=1:raise ValueError(f'原生指令定位不唯一：{name}，匹配 {len(hits)} 处')
    return hits.pop()

def locate(e,group):
    rules=json.loads(PATH.read_text(encoding='utf8'))[group]
    return {label:resolve(e,r) for label,r in rules.items()},rules

def layouts(e):
    values={};evidence={}
    for key,rule in json.loads(PATH.read_text(encoding='utf8'))['layout'].items():
        addr=resolve(e,rule);ins=next(DIS.disasm(e.read(addr,4),addr))
        operands=[o.mem.disp for o in ins.operands if o.type==ARM64_OP_MEM]
        if not operands:operands=[o.imm for o in ins.operands if o.type==ARM64_OP_IMM]
        if len(operands)!=1:raise ValueError('无法解析成员偏移 '+key)
        values[key]=operands[0]+rule.get('adjust',0)
        evidence[key]={'instruction':hex(addr),'assembly':ins.mnemonic+' '+ins.op_str,'value':values[key]}
    return values,evidence

def parameterize(code,symbols,base,assignments):
    for name,value in assignments.items():
        if name not in symbols:raise ValueError('Missing helper parameter '+name)
        pos=symbols[name]-base;op=struct.unpack_from('<I',code,pos)[0]
        if op&0x3b000000==0x39000000: # unsigned offset load/store
            shift=(op>>30)&3
            if op&(1<<26) and ((op>>22)&3)>1:shift=4
            if value%(1<<shift) or not 0<=value>>shift<4096:raise ValueError('成员偏移超出 LDR/STR 范围')
            op=(op&~0x003ffc00)|((value>>shift)<<10)
        elif op&0x7f000000==0x11000000: # ADD immediate
            if not 0<=value<4096:raise ValueError('成员偏移超出 ADD 范围')
            op=(op&~0x003ffc00)|(value<<10)
        else:raise ValueError('Unexpected helper field opcode '+name)
        struct.pack_into('<I',code,pos,op)
