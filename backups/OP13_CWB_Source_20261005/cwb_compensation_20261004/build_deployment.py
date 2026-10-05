"""OP13-only additive system interposer module; preserves the live OVSC binary."""
from pathlib import Path
import io, json, shutil, struct, zipfile
from elftools.elf.elffile import ELFFile

root=Path(__file__).resolve().parent
stage=root/'deploy'/'module_v5'
libs=stage/'system'/'lib64'
libs.mkdir(parents=True,exist_ok=True)
def elf(path): return ELFFile(io.BytesIO(path.read_bytes()))
def needed(path): return [t.needed for t in elf(path).get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag=='DT_NEEDED']
original=root/'preinstall_libsensorservice.so'
target=libs/'libsensorservice.so'
alignment=max(int(p['p_align']) for p in elf(original).iter_segments() if p['p_type']=='PT_LOAD')
raw=original.read_bytes()
oe=elf(original)
if oe.elfclass!=64 or not oe.little_endian or oe['e_machine']!='EM_AARCH64':
    raise ValueError('Unsupported parent ELF')
# The shipped OVSC scanner treats DT_STRTAB as the end of DT_SYMTAB.
# patchelf moved DT_STRTAB in v1, exposing that scanner's invalid bound.
# Never relocate tables: add a short name in verified existing string padding.
soname=b'nc.so\0'
ds=oe.get_section_by_name('.dynstr')
dyn=oe.get_section_by_name('.dynamic')
end=int(ds['sh_offset'])+int(ds['sh_size'])
new_end=end+len(soname)
following=min(int(s['sh_offset']) for s in oe.iter_sections()
              if s['sh_type']!='SHT_NOBITS' and int(s['sh_size']) and int(s['sh_offset'])>=end)
if new_end>following or any(raw[end:new_end]):
    raise ValueError('No verified zero string padding; do not relocate ELF tables')
if not any(p['p_type']=='PT_LOAD' and int(p['p_offset'])<=end and
           new_end<=int(p['p_offset'])+int(p['p_filesz']) for p in oe.iter_segments()):
    raise ValueError('New string is outside an existing file-backed LOAD')
doff,dsize=int(dyn['sh_offset']),int(dyn['sh_size'])
entries=[]
for pos in range(doff,doff+dsize,16):
    tag,val=struct.unpack_from('<qQ',raw,pos)
    if tag==0: break
    entries.append((tag,val))
else: raise ValueError('Missing DT_NULL')
# DT_FLAGS(BIND_NOW) and DT_FLAGS_1(NOW) are redundant on this ELF.
# Reuse ONLY the latter slot; other FLAGS_1 values are not discardable.
if [v for t,v in entries if t==0x6ffffffb]!=[1] or not any(t==30 and v&8 for t,v in entries):
    raise ValueError('No redundant NOW entry available; do not change other flags')
if [v for t,v in entries if t==5]!=[int(ds['sh_addr'])] or [v for t,v in entries if t==10]!=[int(ds['sh_size'])]:
    raise ValueError('Dynamic string metadata does not match section')
patched_entries=[(1,int(ds['sh_size']))]+[
    (t,v+len(soname) if t==10 else v) for t,v in entries if t!=0x6ffffffb]
if len(patched_entries)!=len(entries): raise ValueError('Dynamic entry count changed')
out=bytearray(raw)
out[end:new_end]=soname
for index,(tag,val) in enumerate(patched_entries):
    struct.pack_into('<qQ',out,doff+index*16,tag,val)
section_index=next(i for i,s in enumerate(oe.iter_sections()) if s.name=='.dynstr')
struct.pack_into('<Q',out,int(oe['e_shoff'])+section_index*int(oe['e_shentsize'])+32,int(ds['sh_size'])+len(soname))
target.write_bytes(out)
old,new=needed(original),needed(target)
if new!=['nc.so',*old]: raise ValueError('Parent dependency order changed unexpectedly')
# The constructor lifecycle probe is compiled from the existing target. Make
# sure patchelf did not relocate its anchor or change any executable bytes.
oe,ne=elf(original),elf(target)
if len(raw)!=len(out): raise ValueError('Parent file size changed')
phoff=int(oe['e_phoff']); phsize=int(oe['e_phnum'])*int(oe['e_phentsize'])
if raw[phoff:phoff+phsize]!=out[phoff:phoff+phsize]: raise ValueError('Program headers changed')
for secname in ('.dynsym','.dynstr','.dynamic'):
    a,b=oe.get_section_by_name(secname),ne.get_section_by_name(secname)
    if a['sh_addr']!=b['sh_addr'] or a['sh_offset']!=b['sh_offset']:
        raise ValueError(f'Metadata relocated: {secname}')
if oe.get_section_by_name('.dynsym').data()!=ne.get_section_by_name('.dynsym').data():
    raise ValueError('Dynamic symbols changed')
for secname in ('.text','.plt'):
    a,b=oe.get_section_by_name(secname),ne.get_section_by_name(secname)
    if int(a['sh_addr'])!=int(b['sh_addr']) or a.data()!=b.data():
        raise ValueError(f'Unexpected executable edit: {secname}')
for name,source in {
    'nc.so':'libcos_cwb_comp.so',
    'libcwb_client.so':'coloros_live_client.so',
    'vendor.oplus.hardware.cwb@1.0.so':'cwb_hidl.so',
    'vendor.oplus.hardware.cwb-V2-ndk.so':'cwb_aidl.so',
    'vendor.oplus.hardware.displaypanelfeature@1.0.so':'displaypanelfeature.so',
}.items(): shutil.copy2(root/source,libs/name)
for name in ('module.prop','customize.sh','sepolicy.rule','display_nodes.cil','user_additions.cil','README.txt'):
    shutil.copy2(root/'module_files'/name,stage/name)
vendor_libs=stage/'system'/'vendor'/'lib64'
vendor_libs.mkdir(parents=True,exist_ok=True)
shutil.copy2(root/'patched_vendor_cwb_v5.so',vendor_libs/'libcwb_qcom_aidl.so')
report={'module':'op13_cos_cwb','version':'v5','files':sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*.so')),
        'original_needed':old,'patched_needed':new,'original_executable_preserved':True,
        'existing_adapter_untouched':True,'original_max_load_alignment':alignment,
        'original_metadata_addresses_preserved':True,'original_program_headers_preserved':True,
        'dependency_string_padding_bytes':len(soname),'only_removed_dynamic_flag':'redundant DT_FLAGS_1=NOW (DT_FLAGS=BIND_NOW retained)',
        'sensor_lifecycle_backends':['AIDL','HIDL'],
        'packet_association':'exact timestamp + lease generation; bounded 32 records; raw physical packet immutable',
        'formula':'official project23821 normal-mode V2.1; runtime device W_VIEW',
        'screenshot_polling':False,'root_service_daemon':False,'target':'current OP13 OriginOS DSU ONLY',
        'cwb_buffer_patch':json.loads((root/'deploy'/'cwb_buffer_patch_v5.json').read_text(encoding='utf8')),
        'quiet_sample_logging':json.loads((root/'deploy'/'helper_build_report.json').read_text(encoding='utf8'))['quiet_sample_logging'],
        'pending_validation':['vendor compositor loading','FHD native allocation and ROI pixels','FHD/QHD transition','screen-off stop/resume','SELinux']}
(root/'deploy'/'build_report_v5.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
output=Path(r'C:\Users\a1510\Videos\OP13_OriginOS_CWB_Compensation_Test_20261005_v5.zip')
output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(stage.rglob('*')):
        if p.is_file(): z.write(p,p.relative_to(stage).as_posix())
print(json.dumps({'zip':str(output),'bytes':output.stat().st_size,'libraries':report['files'],'alignment':alignment},ensure_ascii=False,indent=2))
