"""Extract only the audited pure ARM64 timing function for an isolated test."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

root=Path(__file__).parent
e=Elf((root/'coloros_live_ext.so').read_bytes())
address,size=e.symbols['_ZN7android16ScreenShotResult10matchRatioEliiiii']
code=e.read(address,size)
instructions=list(DIS.disasm(code,address))
if size!=224 or instructions[0].mnemonic!='bti':
    raise ValueError('Unknown timing oracle ABI')
for ins in instructions:
    if ins.mnemonic in ('bl','blr','adr','adrp','br'):
        raise ValueError('Oracle is not an isolated pure function')
    if ins.mnemonic in ('b','b.lo','b.hs','b.lt','b.le','b.ge','b.gt'):
        if not address<=ins.operands[0].imm<address+size:
            raise ValueError('Oracle branch exits its copied code')
(root/'timing_oracle.h').write_text('#pragma once\nstatic const unsigned char timing_oracle_code[]={'+','.join(str(x) for x in code)+'};\n',encoding='utf-8')
print('Isolated official timing oracle:',hex(address),size,'bytes')
