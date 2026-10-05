"""Execute the Vivo SF private-transaction credential gate offline.

No transactions are sent to the phone. Tests only this actual gate, not the
entire Binder dispatcher or a proposed compatibility implementation.
"""
from pathlib import Path
import json
import struct
import sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'tools' / 'OplusOriginPatcher'))
from research_native import Elf
from native import DIS

elf = Elf((ROOT / 'origin_live_surfaceflinger').read_bytes())
index = json.loads((ROOT / 'official_branch_audit/originsf/index.json').read_text())
found = [f for f in index['functions'] if 'checkTransactCodeCredentialsEj' in f['symbol']]
assert len(found) == 1
info = found[0]
va, size = int(info['address'], 16), info['size']
calls = {int(c['site'], 16): c['symbol'] for c in info['calls']}
allowed_stubs = {'_ZN7android17LcmFeatureManager11getInstanceEv',
                 '_ZNK7android7RefBase9decStrongEPKv'}
assert set(calls.values()) == allowed_stubs
instructions = list(DIS.disasm(elf.read(va, size), va))
assert instructions[-1].mnemonic == 'ret'


def execute(code):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    high = max(int(s['p_vaddr']) + int(s['p_memsz']) for s in elf.elf.iter_segments()
               if s['p_type'] == 'PT_LOAD')
    u.mem_map(0, (high + 4095) & ~4095)
    for segment in elf.elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            u.mem_write(int(segment['p_vaddr']), segment.data())
    u.mem_map(0x2000000, 0x400000)
    u.reg_write(UC_ARM64_REG_SP, 0x23f0000)
    u.reg_write(UC_ARM64_REG_X30, 0x23ff000)
    u.reg_write(UC_ARM64_REG_X0, 0x2100000)
    u.reg_write(UC_ARM64_REG_W1, code)
    # A harmless RefBase-shaped dummy object for the two unrelated calls.
    u.mem_write(0x2100000, struct.pack('<Q', 0x2110000))
    u.mem_write(0x2110000 - 0x18, struct.pack('<Q', 0))

    def on_code(machine, address, count, userdata):
        if address not in calls:
            return
        if calls[address] == '_ZN7android17LcmFeatureManager11getInstanceEv':
            machine.mem_write(machine.reg_read(UC_ARM64_REG_X8), struct.pack('<Q', 0x2100000))
        machine.reg_write(UC_ARM64_REG_PC, address + 4)

    u.hook_add(UC_HOOK_CODE, on_code)
    u.emu_start(va, 0x23ff000, count=100)
    unsigned = u.reg_read(UC_ARM64_REG_W0)
    return unsigned if unsigned < 0x80000000 else unsigned - 0x100000000


cases = [(22002, -1, 'OPPO legacy screenshot RGB query'),
         (24002, -1, 'OPPO screenshot listener add/remove'),
         (1015, 0, 'existing Vivo special case'),
         (50000, 0, 'existing Vivo special case'),
         (130000, 0, 'existing Vivo special case')]
for base, length in [(110000, 150), (29999, 11), (120000, 201), (31000, 253)]:
    cases.extend((base + offset, 0, 'existing Vivo extension range')
                 for offset in (0, 1, length - 1))
observations = []
for code, expected, description in cases:
    actual = execute(code)
    assert actual == expected, (code, actual, expected)
    observations.append({'code': code, 'result': actual, 'description': description})
report = {'cases': len(observations), 'passed': True,
          'phone_transactions_sent': 0,
          'scope': 'actual private-transaction credential gate only, not full onTransact',
          'oppo_listener_and_query_allowed_by_gate': False,
          'results': observations}
(ROOT / 'official_branch_audit/vivo_sf_credential_report.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
print(f'PASS {len(observations)} offline cases; Vivo gate rejects OPPO 22002/24002.')
