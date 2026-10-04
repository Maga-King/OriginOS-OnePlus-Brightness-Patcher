"""BC05 lux + BC06 unified brightness, rebased by function symbols/structure."""
import json,struct
from native import ASSETS,signature,branch,object_code,patch_surfaceflinger
from research_native import Elf
from locator import locate,layouts,parameterize

def recipes():return json.loads((ASSETS/'extra_recipes.json').read_text(encoding='utf8'))

def undo_known(data,kind):
    for recipe in recipes()['undo']:
        edits=recipe['edits']
        if recipe['kind']==kind and edits and all(data[p:p+len(bytes.fromhex(after))]==bytes.fromhex(after) for p,before,after in edits):
            out=bytearray(data)
            for p,before,after in edits:out[p:p+len(bytes.fromhex(before))]=bytes.fromhex(before)
            return bytes(out),recipe['label']
    return data,None

def append_rx(data,asset,externals,fields=None):
    e=Elf(data);out=bytearray(data)
    idx,rx=next((i,s) for i,s in enumerate(e.elf.iter_segments()) if s['p_type']=='PT_LOAD' and s['p_flags']==5)
    if rx['p_filesz']!=rx['p_memsz']:raise ValueError('Executable segment has BSS')
    va=(rx['p_vaddr']+rx['p_filesz']+3)&~3
    payload,symbols=object_code(ASSETS/asset,va,externals)
    if fields:parameterize(payload,symbols,va,fields)
    offset=rx['p_offset']+va-rx['p_vaddr']
    end=offset+len(payload)
    next_offset=min(s['p_offset'] for s in e.elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_offset']>rx['p_offset'])
    if end>next_offset or any(out[offset:end]):raise ValueError('Executable padding unavailable')
    out[offset:end]=payload
    size=va+len(payload)-rx['p_vaddr']
    struct.pack_into('<QQ',out,e.elf['e_phoff']+idx*e.elf['e_phentsize']+32,size,size)
    return out,symbols

def surfaceflinger(data,panel,intents):
    clean,previous=undo_known(data,'surfaceflinger');e=Elf(clean)
    sites,rules=locate(e,'unified');fields,_=layouts(e)
    patched,report=patch_surfaceflinger(clean,panel,intents)
    bridge=next(a for n,(a,z) in e.symbols.items() if '24DisplayBrightnessManager25setDisplayBrightnessState' in n)
    out,symbols=append_rx(patched,'unified.o',{'op13_existing_output':bridge},
                          {'field_unified_max':fields['unified_max'],'field_unified_manager':fields['unified_manager']})
    site,cont=sites['site'],sites['continue']
    if cont-site!=56:raise ValueError('统一亮度私有调用块结构变化，需要扩展转换')
    code=struct.pack('<II',0xaa1303e0,0x2a1503e1)+branch(site+8,symbols['op13_unified_output'],True)+branch(site+12,cont)
    code+=bytes.fromhex('1f2003d5')*((cont-site-len(code))//4)
    out[e.offset(site,len(code)):e.offset(site,len(code))+len(code)]=code
    report['unified']={'function':rules['site']['name'],'site':site,'continue':cont,'helpers':symbols,'previous_hand_patch':previous}
    return bytes(out),report

def sensor_library(data):
    clean,previous=undo_known(data,'sensor');e=Elf(clean)
    sites,rules=locate(e,'sensor');site=sites.pop('site')
    out,symbols=append_rx(clean,'lux.o',sites)
    out[e.offset(site,4):e.offset(site,4)+4]=branch(site,symbols['mio_oplus_policy_lux'])
    return bytes(out),{'function':rules['site']['name'],'site':site,'helpers':symbols,'destinations':sites,'previous_hand_patch':previous,
                       'standard_handle':1001,'duplicate_private_alias':1701,'retains_vivo_filter_and_lifecycle':True,
                       'new_threads':0,'new_polling':False}
