"""Run the extracted official SF RGB function offline; never touches the phone.

The ROM's pixel loop, matrix branches, LUT and purity tests run as ARM64.
Only Android logging and libm pow are external stubs. This is an oracle for
math reconstruction, NOT proof of transport, power or end-to-end equivalence.
"""
from pathlib import Path
import json
import math
import struct
import sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'tools/OplusOriginPatcher'))
from research_native import Elf

SOURCE = ROOT.parent / 'analysis/originos_hdr_vendor_compare_20261003/coloros/files/system/bin/surfaceflinger'
IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]


class OfficialSF:
    def __init__(self):
        self.elf = Elf(SOURCE.read_bytes())
        index = json.loads((ROOT / 'official_branch_audit/officialsf/index.json').read_text(encoding='utf8'))
        hits = [f for f in index['functions'] if '19OplusSurfaceFlinger13calcPixelsRGB' in f['symbol']]
        if len(hits) != 1:
            raise ValueError('Official function must be uniquely located')
        self.function = hits[0]
        self.address = int(self.function['address'], 16)
        calls = self.function['calls']
        self.log_targets = {int(c['target'], 16) for c in calls if c['symbol'] == '__android_log_print'}
        self.pow_targets = {int(c['target'], 16) for c in calls if c['symbol'] == 'pow'}
        self.template = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.template.mem_map(0, 0x1800000)
        for segment in self.elf.elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                self.template.mem_write(int(segment['p_vaddr']), segment.data())
        self.template.mem_map(0x4000000, 0x400000)
        self.template.hook_add(UC_HOOK_CODE, self.external)

    def external(self, u, address, size, unused):
        if address in self.log_targets:
            u.reg_write(UC_ARM64_REG_W0, 0)
            u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))
        elif address in self.pow_targets:
            a = struct.unpack('<d', struct.pack('<Q', u.reg_read(UC_ARM64_REG_D0)))[0]
            b = struct.unpack('<d', struct.pack('<Q', u.reg_read(UC_ARM64_REG_D1)))[0]
            result = math.pow(a, b)
            u.reg_write(UC_ARM64_REG_D0, struct.unpack('<Q', struct.pack('<d', result))[0])
            u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))

    def calculate(self, pixels, width, height, matrix=None, color_correction=False,
                  display_gains=(1., 1., 1.), thresholds=(2, 216, 32, 38), debug=False):
        if len(pixels) != width * height or width <= 0 or height <= 0:
            raise ValueError('Invalid bounded test image')
        u = self.template
        obj, thread, mat, rect, buf, out = [0x4010000 + i * 0x10000 for i in range(6)]
        # Reset every invocation's actual object and output; avoid cross-case state.
        u.mem_write(obj, bytes(0x400))
        u.mem_write(thread, bytes(0x300))
        u.mem_write(obj + 0x2b0, struct.pack('<Q', thread))
        u.mem_write(thread + 0x90, bytes([int(debug), int(color_correction)]))
        u.mem_write(thread + 0x94, struct.pack('<3f', *display_gains))
        u.mem_write(thread + 0x160, struct.pack('<4i', *thresholds))
        u.mem_write(mat, struct.pack('<16f', *(matrix or IDENTITY)))
        u.mem_write(rect, struct.pack('<4i', 0, 0, width, height))
        packed = [r | (g << 8) | (b << 16) | (a << 24) for r, g, b, a in pixels]
        u.mem_write(buf, struct.pack('<' + 'I' * len(packed), *packed))
        u.mem_write(out, bytes(16))
        for register, value in [(UC_ARM64_REG_X0, obj), (UC_ARM64_REG_X1, buf),
                                (UC_ARM64_REG_X2, mat), (UC_ARM64_REG_W3, width),
                                (UC_ARM64_REG_X4, rect), (UC_ARM64_REG_X5, out),
                                (UC_ARM64_REG_SP, 0x43f0000), (UC_ARM64_REG_X30, 0x43ff000)]:
            u.reg_write(register, value)
        u.emu_start(self.address, 0x43ff000, count=500000)
        if u.reg_read(UC_ARM64_REG_PC) != 0x43ff000:
            raise RuntimeError('Official oracle instruction budget exceeded')
        return list(struct.unpack('<4i', u.mem_read(out, 16))), list(struct.unpack('<16f', u.mem_read(mat, 64)))


if __name__ == '__main__':
    oracle = OfficialSF()
    rows = []
    for name, rgba in [('red', (255, 0, 0, 255)), ('green', (0, 255, 0, 255)),
                       ('blue', (0, 0, 255, 255)), ('black', (0, 0, 0, 255)),
                       ('white', (255, 255, 255, 255)), ('gray', (128, 128, 128, 255))]:
        rgb, matrix = oracle.calculate([rgba] * (38 * 42), 38, 42)
        rows.append({'case': name, 'rgba': rgba, 'official_rgb_and_purity': rgb})
    report = {'source': str(SOURCE), 'function': oracle.function['symbol'],
              'address': hex(oracle.address), 'scope': 'Offline mathematical oracle, not live SF backend',
              'cases': rows}
    (ROOT / 'official_branch_audit/sf_rgb_oracle_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
