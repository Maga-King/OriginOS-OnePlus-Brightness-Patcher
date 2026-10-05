"""Symbol-based native recipes, finite event-driven helpers, no runtime process."""
import bisect, io, json, lzma, struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
from research_native import Elf

ASSETS=Path(__file__).resolve().parent/'assets'
DIS=Cs(CS_ARCH_ARM64,CS_MODE_ARM);DIS.detail=True

def signature(e,addr,size):
    """Keep register/object offsets, normalize relocations only, preserve local CFG."""
    output=[];pages=set()
    for i in DIS.disasm(e.read(addr,size),addr):
        w=int.from_bytes(i.bytes,'little');mask=0xffffffff
        if i.mnemonic in ('adr','adrp'):mask=0x9f00001f
        elif w&0x7c000000==0x14000000:
            dest=i.operands[0].imm
            if not addr<=dest<addr+size:mask=0xfc000000
        elif i.mnemonic=='add' and len(i.operands)==3 and i.operands[1].type==ARM64_OP_REG and i.operands[1].reg in pages and i.operands[2].type==ARM64_OP_IMM:
            mask=~0x003ffc00&0xffffffff
        elif any(o.type==ARM64_OP_MEM and o.mem.base in pages for o in i.operands):
            # Unsigned-offset LDR with an ADRP base references .rodata/.got, not an object.
            if w&0x3b000000==0x39000000:mask=~0x003ffc00&0xffffffff
        output.append(w&mask)
        _,writes=i.regs_access();pages.difference_update(writes)
        if i.mnemonic=='adrp':pages.add(i.operands[0].reg)
    if len(output)*4!=size:raise ValueError('Native function contains undecoded instructions')
    return output

def branch(src,dst,link=False):
    d=dst-src
    if d%4 or not -(1<<27)<=d<(1<<27):raise ValueError('AArch64 branch out of range')
    return struct.pack('<I',(0x94000000 if link else 0x14000000)|((d>>2)&0x3ffffff))

def object_code(path,base,externals):
    e=ELFFile(io.BytesIO(Path(path).read_bytes()));sec=e.get_section_by_name('.text');data=bytearray(sec.data())
    syms=e.get_section_by_name('.symtab');textidx=next(i for i,s in enumerate(e.iter_sections()) if s.name=='.text')
    symbols={s.name:base+s['st_value'] for s in syms.iter_symbols() if s['st_shndx']==textidx}
    for relsec in e.iter_sections():
        if relsec['sh_type']!='SHT_RELA' or relsec['sh_info']!=textidx:continue
        for rel in relsec.iter_relocations():
            sym=syms.get_symbol(rel['r_info_sym']);name=sym.name
            dest=(symbols[name] if name in symbols else externals[name])+rel['r_addend'];offset=rel['r_offset'];pc=base+offset
            w=struct.unpack_from('<I',data,offset)[0];kind=rel['r_info_type']
            if kind in (282,283):data[offset:offset+4]=branch(pc,dest,kind==283);continue
            if kind==280:
                distance=dest-pc
                if distance%4 or not -(1<<20)<=distance<(1<<20):raise ValueError('Conditional branch out of range')
                struct.pack_into('<I',data,offset,(w&~0x00ffffe0)|(((distance>>2)&0x7ffff)<<5))
                continue
            if kind==275:
                d=(dest>>12)-(pc>>12)
                if not -(1<<20)<=d<(1<<20):raise ValueError('ADRP out of range')
                w=(w&0x9f00001f)|((d&3)<<29)|(((d>>2)&0x7ffff)<<5)
            elif kind==277:w=(w&~0x003ffc00)|((dest&4095)<<10)
            else:raise ValueError('Unsupported helper relocation '+str(kind))
            struct.pack_into('<I',data,offset,w)
    return data,symbols

def inverse_table(panel):
    physical=[int(r[1]) for r in panel.rows[:panel.logical_max+1]]
    inverse=[bisect.bisect_right(physical,d)-1 for d in range(panel.maximum+1)]
    packed=bytearray()
    for start in range(0,panel.maximum+1,16):
        vals=[inverse[min(i,panel.maximum)] for i in range(start,start+16)]
        deltas=[b-a for a,b in zip(vals,vals[1:])]
        if any(not 0<=d<=15 for d in deltas):raise ValueError('该屏幕 Apollo 逆表步长超过压缩格式，需扩展 native helper。')
        packed+=struct.pack('<HQ',vals[0],sum(d<<(4*i) for i,d in enumerate(deltas)))
    return bytes(packed),inverse,physical

def audit_apollo(data):
    """Confirm the HAL transport assumed by the inverse helper, from this target library."""
    e=Elf(data)
    name='_ZN7android13ApolloService20SetDisplayBrightnessEf'
    if name not in e.symbols:raise ValueError('目标显示库没有已研究的 ApolloService 输出入口')
    a,z=e.symbols[name];ins=list(DIS.disasm(e.read(a,z),a))
    seq=[(i.mnemonic,i.op_str) for i in ins]
    expected=[('fsub','s2, s2, s1'),('fmul','s0, s2, s0'),('fadd','s0, s1, s0'),('fcvtzs','w1, s0')]
    if not any(seq[i:i+4]==expected for i in range(len(seq)-3)):
        raise ValueError('目标 Apollo 浮点到逻辑亮度公式不同，不能使用已有逆向输出')
    # Determine the minimum member from the actual s1 load used by the formula.
    end=next(j for j in range(len(seq)-3) if seq[j:j+4]==expected)
    loads=[]
    for i in ins[:end]:
        if i.mnemonic=='ldr' and i.operands[0].type==ARM64_OP_REG and i.reg_name(i.operands[0].reg)=='s1' and i.operands[1].type==ARM64_OP_MEM:
            loads.append(i.operands[1].mem.disp)
        elif i.mnemonic=='ldp' and i.operands[2].type==ARM64_OP_MEM:
            for slot in (0,1):
                if i.reg_name(i.operands[slot].reg)=='s1':loads.append(i.operands[2].mem.disp+4*slot)
    if not loads:raise ValueError('Apollo minimum member could not be located')
    minimum_offset=loads[-1]
    ctors=[(a,z) for n,(a,z) in e.symbols.items() if 'ApolloServiceC1' in n]
    for a,z in ctors:
        constants={}
        for i in DIS.disasm(e.read(a,z),a):
            if i.mnemonic=='str' and i.operands[1].type==ARM64_OP_MEM:
                mem=i.operands[1].mem
                if i.reg_name(mem.base)=='x19' and mem.disp==minimum_offset and constants.get(i.operands[0].reg)==0x3f800000:
                    return {'minimum':1,'minimum_member':minimum_offset,'initializer':hex(i.address),
                            'formula':'truncate(min + (logical_max-min)*fraction)','source':'target libsdmcore.so decoded loads and stores'}
            _,writes=i.regs_access()
            for register in writes:constants.pop(register,None)
            if i.mnemonic=='mov' and len(i.operands)==2 and i.operands[1].type==ARM64_OP_IMM:
                constants[i.operands[0].reg]=i.operands[1].imm
    raise ValueError('无法从该库确认 Apollo 最小逻辑值为 1；需扩展转换，而非套一加 13 常量')

def patch_surfaceflinger(data,panel,intents):
    from locator import locate,layouts,parameterize
    e=Elf(data)
    if e.elf['e_machine']!='EM_AARCH64':raise ValueError('仅支持 AArch64 SurfaceFlinger')
    sites,rules=locate(e,'sf');fields,field_evidence=layouts(e)
    selected={'label':'target_ELF_instruction_locator','sites':rules}
    # STL node traversal has a real ABI; verify the target's implementations.
    recipes=json.loads((ASSETS/'recipes.json').read_text('utf8'))
    for key in ('insert','find'):
        name=rules[key]['name']
        if not any(name in r['functions'] and signature(e,*e.symbols[name])==r['functions'][name]['signature'] for r in recipes):
            raise ValueError('目标 libc++ 哈希节点实现有变化，需要扩展 '+key+' 的原生适配')
    patched=bytearray(data);changes=[]
    def replace(va,new,reason):
        offset=e.offset(va,len(new));patched[offset:offset+len(new)]=new;changes.append({'vaddr':hex(va),'bytes':len(new),'purpose':reason})
    loads=[(i,s) for i,s in enumerate(e.elf.iter_segments()) if s['p_type']=='PT_LOAD']
    ri,ro=next((i,s) for i,s in loads if s['p_flags']==4);xi,rx=next((i,s) for i,s in loads if s['p_flags']==5)
    if ro['p_memsz']!=ro['p_filesz'] or rx['p_memsz']!=rx['p_filesz']:raise ValueError('无法使用已有段间隙')
    table_va=(ro['p_vaddr']+ro['p_filesz']+3)&~3;code_va=(rx['p_vaddr']+rx['p_filesz']+3)&~3
    table,inverse,physical=inverse_table(panel)
    helper,symbols=object_code(ASSETS/'domain.o',code_va,{'op13_inverse_table':table_va,'op13_persist_brightness':sites['persist']})
    parameterize(helper,symbols,code_va,{'field_'+key:fields[key] for key in
                 ('sdr_enable','sdr_hbm','hbm_normal','sdr_output','dbm_device','device_brightness','device_dirty')}
                 | {'field_sdr_original':fields['sdr_output']})
    # Parameterize audited MOV instructions, not global byte replacement.
    for label,value in [('parameter_maximum',panel.maximum),('parameter_maximum_sdr',panel.maximum),('parameter_logical_span',panel.logical_max-1)]:
        off=symbols[label]-code_va;op=struct.unpack_from('<I',helper,off)[0]
        if op&0xffe00000!=0x52800000 or not 0<value<65536:raise ValueError('Unsupported brightness domain')
        struct.pack_into('<I',helper,off,(op&0xffe0001f)|(value<<5))
    # Only extend existing read-only and executable segments into their unused gaps.
    for idx,seg,va,payload in [(ri,ro,table_va,table),(xi,rx,code_va,helper)]:
        nextva=min(s['p_vaddr'] for _,s in loads if s['p_vaddr']>seg['p_vaddr'])
        end=va+len(payload);offset=seg['p_offset']+va-seg['p_vaddr']
        if end>nextva or any(patched[offset:offset+len(payload)]):raise ValueError('Native 段间空隙不够，未覆盖原有代码/数据')
        patched[offset:offset+len(payload)]=payload
        size=end-seg['p_vaddr'];struct.pack_into('<QQ',patched,e.elf['e_phoff']+idx*e.elf['e_phentsize']+32,size,size)
    gate=next(DIS.disasm(e.read(sites['gate'],4),sites['gate']))
    aidl=next(DIS.disasm(e.read(sites['aidl_gate'],4),sites['aidl_gate']))
    if gate.mnemonic!='tbz' or aidl.mnemonic!='tbnz':raise ValueError('Native input gate mismatch')
    replace(sites['gate'],bytes.fromhex('1f2003d5'),'feed existing native brightness policy')
    replace(sites['aidl_gate'],branch(sites['aidl_gate'],aidl.operands[-1].imm),'feed actual AIDL entry')
    replace(sites['bridge'],bytes.fromhex('5f2403d5')+branch(sites['bridge']+4,symbols['op13_hdr_output']),'standard HAL output through Apollo inverse')
    sdr=next(DIS.disasm(e.read(sites['sdr_fallback'],4),sites['sdr_fallback']))
    if sdr.mnemonic!='str' or not sdr.op_str.startswith('s1, [x20,'):raise ValueError('SDR store mismatch')
    replace(sites['sdr_fallback'],branch(sites['sdr_fallback'],symbols['op13_sdr_fallback'],True),'SDR uses normalMax, not physical full scale')
    cave=sites['bridge']+80
    color,cs=object_code(ASSETS/'color.o',cave,{'op13_original_insert_intent':sites['insert'],'op13_original_find_mode':sites['find']})
    parameterize(color,cs,cave,{'field_'+key:fields[key] for key in
                 ('color_map','color_savedmap','color_intentset','color_displaced')})
    bridge_name=selected['sites']['bridge']['name']
    if cave+len(color)>e.symbols[bridge_name][0]+e.symbols[bridge_name][1]:raise ValueError('Color helper exceeds bypassed function')
    replace(cave,color,'collect actual P3 intents in bypassed legacy HAL body')
    replace(sites['collect_p3'],branch(sites['collect_p3'],cs['op13_collect_p3_intents'],True),'include P3 modes')
    replace(sites['has_intent'],bytes.fromhex('5f2403d5')+branch(sites['has_intent']+4,cs['op13_has_render_intent']),'SRGB or P3 support check')
    def mov(va,old,new):
        op=struct.unpack('<I',e.read(va,4))[0]
        if op&0xffe00000!=0x52800000 or (op>>5)&65535!=old:raise ValueError('Private render intent opcode mismatch')
        replace(va,struct.pack('<I',(op&0xffe0001f)|(new<<5)),f'private intent {old} -> donor {new}')
    for site in ('unified_hdr_1','unified_hdr_2'):mov(sites[site],278,intents['hdr'])
    for label,mapping in [('hdr10plus',{310:intents['hdr'],311:intents['hdr']}),('dolby_best',{305:intents['dv73'],306:intents['dv73'],307:intents['dv65']})]:
        a,z=e.symbols[selected['sites'][label]['name']]
        for old,new in mapping.items():
            hits=[va for va in range(a,a+z,4) if (w:=struct.unpack('<I',e.read(va,4))[0])&0xffe00000==0x52800000 and (w>>5)&65535==old]
            if len(hits)!=2:raise ValueError('Render intent selection changed')
            for va in hits:mov(va,old,new)
    return bytes(patched),{'recipe':selected['label'],'changes':changes,'helpers':symbols,'color_helpers':cs,
                          'located_sites':sites,'target_member_layout':field_evidence,
                          'logical_minimum':1,'logical_maximum':panel.logical_max,'physical_maximum':panel.maximum,
                          'table_vaddr':table_va,'code_vaddr':code_va,'inverse_bytes':len(table),
                          'new_background_work':False,'color_accuracy_verified':False}
