"""Find the writers of vendor CWB timestamps and inspect client static defaults."""
import sys, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

root=Path(__file__).parent
for filename in ('coloros_live_client.so','coloros_live_vendor_cwb.so'):
    e=Elf((root/filename).read_bytes())
    print('\nLIBRARY', filename)
    if 'client' in filename:
        pointer=struct.unpack('<Q',e.read(0xb5b8,8))[0]
        print('Feature GOT initial pointer',hex(pointer))
        if pointer:
            print('Feature initial value',struct.unpack('<I',e.read(pointer,4))[0])
    else:
        for name,(address,size) in e.symbols.items():
            ins=list(DIS.disasm(e.read(address,size),address))
            sites=[i for i,op in enumerate(ins) if op.mnemonic.startswith(('str','stp')) and
                   any(x in op.op_str for x in ('#0x378]','#0x2f4]','#0x2f8]','#0x2fc]','#0x308]'))]
            if sites:
                print('WRITER',name,hex(address))
                for site in sites:
                    for op in ins[max(0,site-6):site+4]:
                        print(f'{op.address:x}: {op.mnemonic} {op.op_str}')
