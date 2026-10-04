from pathlib import Path
import io,lzma,struct,json
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

class Elf:
    def __init__(self,data):
        self.data=data;self.elf=ELFFile(io.BytesIO(data));self.symbols={}
        tables=[self.elf.get_section_by_name(n) for n in ('.dynsym','.symtab')]
        mini=self.elf.get_section_by_name('.gnu_debugdata')
        if mini:tables.append(ELFFile(io.BytesIO(lzma.decompress(mini.data()))).get_section_by_name('.symtab'))
        for table in tables:
            if table:
                for s in table.iter_symbols():
                    if s['st_info']['type']=='STT_FUNC' and s['st_size'] and s['st_shndx']!='SHN_UNDEF':
                        self.symbols[s.name]=(int(s['st_value']),int(s['st_size']))
    def offset(self,va,size=1):
        for s in self.elf.iter_segments():
            if s['p_type']=='PT_LOAD' and s['p_vaddr']<=va and va+size<=s['p_vaddr']+s['p_filesz']:
                return int(s['p_offset']+va-s['p_vaddr'])
        raise ValueError(hex(va))
    def read(self,va,size):
        pos=self.offset(va,size);return self.data[pos:pos+size]
    def containing(self,va):return sorted([(k,a,z) for k,(a,z) in self.symbols.items() if a<=va<a+z],key=lambda r:r[2])[0]

def normalized(data):
    out=[]
    for (w,) in struct.iter_unpack('<I',data):
        if w&0x7c000000==0x14000000:w&=0xfc000000
        elif w&0x7e000000==0x34000000 or w&0xff000010==0x54000000:w&=~0x00ffffe0
        elif w&0x7e000000==0x36000000:w&=~0x0007ffe0
        elif w&0x1f000000==0x10000000:w&=0x9f00001f
        out.append(w)
    return out

