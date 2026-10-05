"""Small focused ELF audit; inspect symbols rather than trusting shifted offsets."""
import sys
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

e=Elf(Path(sys.argv[1]).read_bytes())
# patchelf can move the outer ELF's symbols without rewriting .gnu_debugdata.
# Prefer current dynsym addresses over historical mini-debug copies.
dyn=e.elf.get_section_by_name('.dynsym')
if dyn:
    for sym in dyn.iter_symbols():
        if sym['st_shndx']!='SHN_UNDEF' and sym['st_size']:
            e.symbols[sym.name]=(int(sym['st_value']),int(sym['st_size']))
reverse={a:n for n,(a,s) in e.symbols.items()}
rela=e.elf.get_section_by_name('.rela.plt'); plt=e.elf.get_section_by_name('.plt')
if rela and plt:
    syms=e.elf.get_section(rela['sh_link'])
    got={int(r['r_offset']):syms.get_symbol(r['r_info_sym']).name for r in rela.iter_relocations()}
    ins=list(DIS.disasm(plt.data(),int(plt['sh_addr'])))
    for a,b in zip(ins,ins[1:]):
        if a.mnemonic=='adrp' and b.mnemonic=='ldr':
            target=a.operands[1].imm+b.operands[1].mem.disp
            if target in got:reverse[a.address]=got[target]
for n,(a,s) in e.symbols.items():
    if s and any(q in n for q in sys.argv[2:]):
        print(f'FUNCTION {n} {a:x} {s}')
        for i in DIS.disasm(e.read(a,s),a):
            extra=reverse.get(i.operands[0].imm,'') if i.mnemonic in ('bl','b') else ''
            print(f'{i.address:x}: {i.mnemonic} {i.op_str} ; {extra}')
