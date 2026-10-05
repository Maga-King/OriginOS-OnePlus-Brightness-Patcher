"""Keep OP13 CWB allocation in the calibrated native tap-point coordinate space.

Only prepareCwbBuffer's PRIMARY dimension load changes. No table relocation,
new dependency, output algorithm, Binder ABI or secondary-panel change.
"""
from pathlib import Path
import io, json, struct, sys
from elftools.elf.elffile import ELFFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

NAME = '_ZN4aidl6vendor5oplus8hardware3cwb14implementation10CwbService16prepareCwbBufferEv'

def patch(source: bytes, width: int, height: int):
    if (width, height) != (1440, 3168):
        raise ValueError('This runtime fix is audited for OP13 native 1440x3168 only')
    e = Elf(source)
    elf = ELFFile(io.BytesIO(source))
    address, size = e.symbols[NAME]
    instructions = list(DIS.disasm(e.read(address, size), address))
    matches = [i for i, ins in enumerate(instructions[:-1])
               if ins.mnemonic == 'ldur' and ins.op_str == 'd0, [x8, #4]'
               and instructions[i+1].mnemonic == 'str'
               and instructions[i+1].op_str == 'q0, [sp]']
    if len(matches) != 1:
        raise ValueError('PRIMARY allocation load is not uniquely identified')
    site = instructions[matches[0]].address
    segments = list(elf.iter_segments())
    candidates = [(i, p) for i, p in enumerate(segments)
                  if p['p_type'] == 'PT_LOAD' and p['p_flags'] == 4
                  and p['p_filesz'] == p['p_memsz']]
    if len(candidates) != 1:
        raise ValueError('Expected one purely read-only file-backed LOAD')
    index, segment = candidates[0]
    literal_offset = int(segment['p_offset'] + segment['p_filesz'])
    literal_address = int(segment['p_vaddr'] + segment['p_filesz'])
    if literal_address % 8 or literal_offset % 8:
        raise ValueError('Literal gap is not 8-byte aligned')
    if any(source[literal_offset:literal_offset+8]) or len(source[literal_offset:literal_offset+8]) != 8:
        raise ValueError('No zero gap available after existing read-only data')
    for section in elf.iter_sections():
        if section['sh_type'] != 'SHT_NOBITS' and section['sh_size']:
            low, high = int(section['sh_offset']), int(section['sh_offset']+section['sh_size'])
            if low < literal_offset+8 and literal_offset < high:
                raise ValueError('Literal would overlap an existing section')
    for other in segments:
        if other['p_type'] == 'PT_LOAD' and other is not segment:
            low, high = int(other['p_vaddr']), int(other['p_vaddr']+other['p_memsz'])
            if low < literal_address+8 and literal_address < high:
                raise ValueError('Literal would overlap another LOAD')
    delta = literal_address - site
    if delta % 4 or not -(1 << 20) <= delta < (1 << 20):
        raise ValueError('Literal is outside AArch64 LDR literal reach')
    # LDR D0, signed imm19*4. Integer Width/Height retain their original bit layout.
    replacement = struct.pack('<I', 0x5c000000 | (((delta//4) & 0x7ffff) << 5))
    text = elf.get_section_by_name('.text')
    site_offset = int(text['sh_offset']) + site - int(text['sh_addr'])
    patched = bytearray(source)
    patched[site_offset:site_offset+4] = replacement
    struct.pack_into('<II', patched, literal_offset, width, height)
    ph = int(elf['e_phoff']) + index*int(elf['e_phentsize'])
    struct.pack_into('<Q', patched, ph+32, int(segment['p_filesz'])+8)
    struct.pack_into('<Q', patched, ph+40, int(segment['p_memsz'])+8)
    allowed = set(range(site_offset,site_offset+4)) | set(range(literal_offset,literal_offset+8)) | set(range(ph+32,ph+48))
    changed = {i for i, (a,b) in enumerate(zip(source,patched)) if a != b}
    if len(source) != len(patched) or not changed <= allowed:
        raise ValueError('Unexpected edit outside dimension load / literal / LOAD size')
    check = ELFFile(io.BytesIO(patched))
    for name in ('.dynsym','.dynstr','.dynamic','.plt','.got','.got.plt','.rela.dyn','.relr.dyn','.gnu_debugdata'):
        if elf.get_section_by_name(name).data() != check.get_section_by_name(name).data():
            raise ValueError(f'Unexpected metadata edit: {name}')
    decoded = list(DIS.disasm(replacement, site))
    if len(decoded) != 1 or decoded[0].mnemonic != 'ldr' or decoded[0].operands[1].imm != literal_address:
        raise ValueError('Incorrect LDR literal encoding')
    return bytes(patched), {'function': NAME, 'site':hex(site), 'literal':hex(literal_address),
        'native_allocation':[width,height], 'text_bytes_replaced':4, 'read_only_load_extended_bytes':8,
        'secondary_allocation_unchanged':True, 'metadata_not_relocated':True,
        'file_size_unchanged':True, 'changed_byte_count':len(changed)}

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    out, report = patch((root/'origin_live_vendor_cwb.so').read_bytes(), 1440, 3168)
    (root/'patched_vendor_cwb_v5.so').write_bytes(out)
    (root/'deploy').mkdir(exist_ok=True)
    (root/'deploy'/'cwb_buffer_patch_v5.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))
