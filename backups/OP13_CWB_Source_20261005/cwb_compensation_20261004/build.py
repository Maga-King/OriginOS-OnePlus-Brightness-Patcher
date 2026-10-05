"""Build scoped OP13 compensation candidates. No device writes."""
from pathlib import Path
import io,lzma,subprocess,sys,json
root=Path(__file__).parent.resolve()
mio=root.parent
sys.path.insert(0,str(mio/'tools/OplusOriginPatcher'))
from research_native import Elf
from native import DIS
from elftools.elf.elffile import ELFFile
from generate_profile import generate
generate(mio/'analysis/screenoff_stall_20261004_143219/official_cwb_zip/my_product/etc/fusionlight_profile/fusionlight_Main_1_3.json',root/'official_profile.h')
subprocess.run([sys.executable,str(root/'generate_timing_oracle.py')],check=True)
e=Elf((root/'libsensorservice_live.so').read_bytes())
mini=ELFFile(io.BytesIO(lzma.decompress(e.elf.get_section_by_name('.gnu_debugdata').data())))
delta=int(e.elf.get_section_by_name('.text')['sh_addr'])-int(mini.get_section_by_name('.text')['sh_addr'])
anchor=next(int(s['st_value']) for s in e.elf.get_section_by_name('.dynsym').iter_symbols() if s.name=='_ZN7android13SensorService22sendRuntimeSensorEventERK15sensors_event_t')
sites={}
header=[]
for backend in ('Hidl','Aidl'):
    name=f'_ZN7android20{backend}SensorHalWrapper8activateEib'
    symbol=next(s for s in mini.get_section_by_name('.symtab').iter_symbols() if s.name==name)
    site=int(symbol['st_value'])+delta
    code=e.read(site,16)
    instructions=list(DIS.disasm(code,site))
    if [i.mnemonic for i in instructions]!=['bti','sub','stp','stp']:
        raise ValueError(f'Cannot safely relocate {backend} lifecycle prologue')
    key=backend.lower()
    header.append(f'static const intptr_t {key}_offset_from_anchor={site-anchor};\nstatic const uint8_t {key}_prologue[16]={{'+','.join(str(v) for v in code)+'};\n')
    sites[backend]={'va':hex(site),'relative_to_anchor':site-anchor}
(root/'lifecycle_site.h').write_text(''.join(header),encoding='utf-8')
compiler=Path(r'C:\Users\a1510\AppData\Local\Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\aarch64-linux-android35-clang++.cmd')
flags=['-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-exceptions','-fno-rtti','-fno-threadsafe-statics','-nostdlib++','-fstack-protector-strong']
for source,output,extra in [
    (['math_probe.cpp'],'math_probe',[]),
    (['timing_test.cpp'],'timing_test',[]),
    (['cwb_state_probe.cpp'],'cwb_state_probe',[]),
    (['comp_status_probe.cpp'],'comp_status_probe',[]),
    (['loader_probe.cpp'],'loader_probe',[]),
    (['vendor_loader_probe.cpp'],'vendor_loader_probe',[]),
    (['light_packet_router_test.cpp'],'light_packet_router_test',[]),
    (['geometry_probe.cpp'],'geometry_probe',[]),
    (['live_probe.cpp','cwb_compensator.cpp'],'live_probe',['-DCOS_COMP_DIAGNOSTIC=1','-Wno-deprecated-declarations','-landroid']),
    (['cwb_compensator.cpp','system_interposer.cpp'],'libcos_cwb_comp.so',['-fPIC','-shared','-fvisibility=hidden','-DCOS_COMP_SYSTEM_SERVER=1','-Wl,-z,relro,-z,now,--no-undefined',*([] if '--quiet' in sys.argv else ['-DCOS_COMP_VERBOSE=1'])]),
]:
    subprocess.run([str(compiler),*flags,*extra,*[str(root/s) for s in source],'-lbinder_ndk','-ldl','-lm','-llog','-o',str(root/output)],check=True)
build_report={'lifecycle_mini_text_delta':delta,'lifecycle_sites':sites,'profile':'official project23821; runtime per-device W_VIEW','quiet_sample_logging':'--quiet' in sys.argv,'status':'experimental; not installed'}
(root/'deploy').mkdir(exist_ok=True)
(root/'deploy'/'helper_build_report.json').write_text(json.dumps(build_report,indent=2),encoding='utf8')
print(json.dumps(build_report,indent=2))
