"""Locate the official SF lookup table from its code references, not a saved VA."""
from pathlib import Path
import json
import math
import struct
from sf_rgb_oracle import OfficialSF, ROOT
from native import DIS

def generate():
    oracle = OfficialSF()
    instructions = list(DIS.disasm(oracle.elf.read(oracle.address, oracle.function['size']), oracle.address))
    candidates = set()
    for first, second in zip(instructions, instructions[1:]):
        if first.mnemonic != 'adrp' or second.mnemonic != 'add':
            continue
        register, page = first.op_str.split(', ')
        operands = second.op_str.split(', ')
        if operands[:2] != [register, register] or not operands[-1].startswith('#'):
            continue
        address = int(page.lstrip('#'), 0) + int(operands[-1].lstrip('#'), 0)
        try:
            table = struct.unpack('<256f', oracle.elf.read(address, 1024))
        except (ValueError, struct.error):
            continue
        if table[0] == 0 and table[-1] == 255 and all(math.isfinite(v) for v in table) and all(a <= b for a, b in zip(table, table[1:])):
            candidates.add(address)
    if len(candidates) != 1:
        raise ValueError(f'Expected one code-referenced SF gamma table, got {candidates}')
    address = candidates.pop()
    values = struct.unpack('<256f', oracle.elf.read(address, 1024))
    literals = [v.hex() + 'f' for v in values]
    rows = [','.join(literals[i:i+8]) for i in range(0, 256, 8)]
    (ROOT / 'sf_rgb_lut.h').write_text('#pragma once\n// Generated from the official ELF, dynamically located by code references.\nstatic constexpr float sf_rgb_lut[256]={\n' + ',\n'.join(rows) + '\n};\n', encoding='utf8')
    report = {'source': str(oracle.elf.path) if hasattr(oracle.elf, 'path') else str(__import__('sf_rgb_oracle').SOURCE),
              'function': oracle.function['symbol'], 'table_address': hex(address),
              'entries': 256, 'purpose': 'SF RGB reconstruction, not ordinary hardware CWB weights'}
    (ROOT / 'official_branch_audit/sf_lut_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    generate()
