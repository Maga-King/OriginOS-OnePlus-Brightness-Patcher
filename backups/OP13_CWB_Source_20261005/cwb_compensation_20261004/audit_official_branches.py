"""Offline inventory/CFG evidence for the exact extracted official libraries."""
from pathlib import Path
import argparse, hashlib, json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS

ROOT=Path(__file__).resolve().parent
SOURCES={
    'fusion':('coloros_live_ext.so',('OplusFusionLightNextGen','OplusFusionLightConfig','LuxMedianFiltering','ScreenShotResult')),
    'client':('coloros_live_client.so',('CwbClient',)),
    'vendor':('coloros_live_vendor_cwb.so',('Cwb','CWB','cwb','Rgb','rgb','ScreenShot')),
    'guihelper':('../analysis/originos_hdr_vendor_compare_20261003/coloros/files/system_ext/lib64/libguiextimpl.so',('OplusScreenShotHelper',)),
    'vivogui':('origin_live_libgui.so',('ScreenCaptureResults','ScreenCaptureListener','CaptureArgs','captureDisplayById')),
    'originsf':('origin_live_surfaceflinger',('SurfaceFlinger10onTransact','RegionSampling','ChinRegion','ScreenShot','Screenshot','ColorPicker','captureDisplay','SurfaceFlingerExtension28checkTransactCodeCredentials')),
    'officialsf':('../analysis/originos_hdr_vendor_compare_20261003/coloros/files/system/bin/surfaceflinger',('OplusScreenShot','OplusScreenRgb','OplusScreenshot','OplusRegionSampling','ScreenShotThread','screenShotWithTime','calcPixelsRGB','computeRect')),
}

def audit(kind):
    filename,keywords=SOURCES[kind]
    source=ROOT/filename; e=Elf(source.read_bytes())
    dyn=e.elf.get_section_by_name('.dynsym')
    if dyn:
        for s in dyn.iter_symbols():
            if s['st_shndx']!='SHN_UNDEF' and s['st_info']['type']=='STT_FUNC' and s['st_size']:
                e.symbols[s.name]=(int(s['st_value']),int(s['st_size']))
    reverse={va:name for name,(va,size) in e.symbols.items()}
    rela=e.elf.get_section_by_name('.rela.plt'); plt=e.elf.get_section_by_name('.plt')
    if rela and plt:
        symbols=e.elf.get_section(rela['sh_link'])
        got={int(r['r_offset']):symbols.get_symbol(r['r_info_sym']).name for r in rela.iter_relocations()}
        ins=list(DIS.disasm(plt.data(),int(plt['sh_addr'])))
        for a,b in zip(ins,ins[1:]):
            if a.mnemonic=='adrp' and b.mnemonic=='ldr':
                target=a.operands[1].imm+b.operands[1].mem.disp
                if target in got: reverse[a.address]=got[target]
    out=ROOT/'official_branch_audit'/kind; out.mkdir(parents=True,exist_ok=True)
    index=[]; addresses=set()
    for name,(va,size) in sorted(e.symbols.items(),key=lambda row:row[1][0]):
        if not any(k in name for k in keywords) or va in addresses: continue
        addresses.add(va)
        code=list(DIS.disasm(e.read(va,size),va))
        calls=[]; branches=[]; lines=[]; known={}
        for ins in code:
            suffix=''
            if ins.mnemonic in ('b','bl') and ins.operands and ins.operands[0].type==2:
                target=ins.operands[0].imm; label=reverse.get(target,'')
                suffix=label
                if ins.mnemonic=='bl' or target<va or target>=va+size:
                    calls.append({'site':hex(ins.address),'target':hex(target),'symbol':label})
            if ins.mnemonic.startswith('b.') or ins.mnemonic in ('cbz','cbnz','tbz','tbnz'):
                target=ins.operands[-1].imm
                branches.append({'site':hex(ins.address),'instruction':ins.mnemonic+' '+ins.op_str,'target':hex(target)})
            # Annotate only local adrp+add chains; reset on calls so stale
            # register values cannot invent strings across clobber boundaries.
            if ins.mnemonic=='adrp':
                known[ins.reg_name(ins.operands[0].reg)]=ins.operands[1].imm
            elif ins.mnemonic=='add' and len(ins.operands)==3 and ins.operands[2].type==2:
                dest=ins.reg_name(ins.operands[0].reg); src=ins.reg_name(ins.operands[1].reg)
                if src in known:
                    address=known[src]+ins.operands[2].imm; known[dest]=address
                    try:
                        text=e.read(address,200).split(b'\0',1)[0].decode('utf8')
                        if 4<=len(text)<=190 and all(ch.isprintable() for ch in text): suffix += ' STRING='+repr(text)
                    except (ValueError,UnicodeError): pass
            elif ins.mnemonic in ('bl','blr'): known.clear()
            lines.append(f'{ins.address:x}: {ins.mnemonic} {ins.op_str} ; {suffix}')
        namefile=f'{va:08x}_{name[:180]}.asm.txt'
        (out/namefile).write_text('FUNCTION '+name+f' VA={va:x} size={size}\n'+'\n'.join(lines)+'\n',encoding='utf8')
        index.append({'symbol':name,'address':hex(va),'size':size,'file':namefile,'calls':calls,'conditional_branches':branches})
    record={'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'coverage':'Function inventory and disassembly, NOT yet a verified semantic reconstruction',
            'functions':index}
    (out/'index.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'functions.tsv').write_text('\n'.join(f"{f['address']}\t{f['size']}\t{len(f['conditional_branches'])}\t{f['symbol']}" for f in index)+'\n',encoding='utf8')
    print(f'{kind}: {len(index)} functions, {sum(len(f["conditional_branches"]) for f in index)} conditional branches -> {out}')

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('kind',nargs='?',choices=[*SOURCES,'all'],default='all')
    args=p.parse_args()
    for kind in SOURCES if args.kind=='all' else [args.kind]: audit(kind)
