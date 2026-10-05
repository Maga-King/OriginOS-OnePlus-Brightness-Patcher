"""Inventory the actual Vivo capture ABI; no code or ELF patching."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

output = ROOT / 'sf_abi_audit'
output.mkdir(exist_ok=True)
keywords = ('ScreenshotClient', 'ScreenCaptureListener', 'ScreenCaptureResults',
            'DisplayCaptureArgs', 'CaptureArgs', 'onCompositionComplete', 'calcPixelsRGB',
            'captureSample', 'screenShotWithTime', 'computeRect', 'getPhysicalDisplayIds')
paths = {'vivo_gui': ROOT / 'origin_live_libgui.so',
         'vivo_sf': ROOT / 'origin_live_surfaceflinger',
         'oppo_sf': ROOT.parent / 'analysis/originos_hdr_vendor_compare_20261003/coloros/files/system/bin/surfaceflinger'}
report = {}
for label, source in paths.items():
    elf = Elf(source.read_bytes())
    rows = []
    for name, (va, size) in elf.symbols.items():
        if not any(k in name for k in keywords):
            continue
        rows.append({'symbol': name, 'address': hex(va), 'size': size})
        if size > 32768:
            continue
        lines = [f'{i.address:x}: {i.mnemonic} {i.op_str}' for i in DIS.disasm(elf.read(va, size), va)]
        filename = f'{label}_{va:08x}_{name[:145]}.asm.txt'
        (output / filename).write_text(name + '\n' + '\n'.join(lines), encoding='utf8')
    report[label] = rows
    selected = [r for r in rows if label == 'vivo_gui' or any(k in r['symbol'] for k in ('captureSample', 'calcPixelsRGB', 'computeRect'))]
    print(label, json.dumps(selected, ensure_ascii=False))
(output / 'index.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
for label, name in [('libui', 'origin_live_libui.so'), ('binder_ndk', 'origin_live_libbinder_ndk.so')]:
    elf = Elf((ROOT / name).read_bytes())
    exports = [s.name for s in elf.elf.get_section_by_name('.dynsym').iter_symbols()
               if s['st_shndx'] != 'SHN_UNDEF' and any(k in s.name for k in
                  ('HardwareBuffer', 'GraphicBuffer', 'AParcel_view', 'Fence4wait', 'ABinderProcess_'))]
    print(label, json.dumps(exports))
