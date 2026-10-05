"""Compile the selected ROM's normal/debug policy chains with the HBM grants."""
from pathlib import Path
import re,struct,subprocess,tempfile

ASSETS=Path(__file__).resolve().parent/'assets'
BEGIN='; BEGIN MIO ORIGIN BRIGHTNESS'
END='; END MIO ORIGIN BRIGHTNESS'
RULES='''(allow system_server sysfs (dir (getattr open read search)))
(allow system_server sysfs (file (getattr open read)))
(allow system_server sysfs_oled_hbm (file (getattr open read)))'''

def merge(text):
    if text.count(BEGIN)!=text.count(END) or text.count(BEGIN)>1:raise ValueError('CIL marker conflict')
    text=re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END),'',text,flags=re.S).rstrip()
    # Object labels do not become permissive process domains by this setting.
    # Retain any user's existing typepermissive but add only the needed allow.
    return text+'\n\n'+BEGIN+'\n'+RULES+'\n'+END+'\n'

def policy_version(data):
    if len(data)<128 or struct.unpack_from('<I',data)[0]!=0xf97cff8c:raise ValueError('Invalid precompiled policy')
    size=struct.unpack_from('<I',data,4)[0]
    if size>80:raise ValueError('Invalid policy identifier')
    return struct.unpack_from('<I',data,8+size)[0]

def inputs(source,debug=False,vivo_debug=False):
    version=source.text('vendor/etc/selinux/plat_sepolicy_vers.txt').strip()
    if not re.fullmatch(r'[0-9.]+',version):raise ValueError('Invalid SELinux mapping version')
    platform='system/etc/selinux/plat_sepolicy.cil'
    if vivo_debug:platform='system/etc/selinux/vivodebug_plat_sepolicy.cil'
    elif debug:
        platform=next((n for n in ('system_ext/etc/selinux/plat_sepolicy_debug.cil',
                                  'system/etc/selinux/plat_sepolicy_debug.cil') if source.has(n)),platform)
    names=[platform,f'system/etc/selinux/mapping/{version}.cil']
    optional=[f'system/etc/selinux/mapping/{version}.compat.cil']
    for part in ('system_ext','product'):
        normal=f'{part}/etc/selinux/{part}_sepolicy.cil'
        variant=f'{part}/etc/selinux/{part}_sepolicy_debug.cil'
        optional.extend([variant if debug and source.has(variant) else normal,
                         f'{part}/etc/selinux/mapping/{version}.cil',f'{part}/etc/selinux/mapping/{version}.compat.cil'])
    for part,base in [('vendor','plat_pub_versioned'),('vendor','vendor_sepolicy'),('odm','odm_sepolicy')]:
        normal=f'{part}/etc/selinux/{base}.cil';variant=f'{part}/etc/selinux/{base}_debug.cil'
        name=variant if debug and source.has(variant) else normal
        if part=='vendor':names.append(name)
        else:optional.append(name)
    gen='vendor/etc/selinux/genfs_labels_version.txt'
    if source.has(gen):
        v=source.text(gen).strip()
        if not v.isdecimal():raise ValueError('Invalid genfs version')
        if int(v)>202404:names.append(f'system/etc/selinux/plat_sepolicy_genfs_{v}.cil')
    for n in names:
        if not source.has(n):raise ValueError('CIL 编译缺少 '+n)
    return list(dict.fromkeys(names+[n for n in optional if source.has(n)]))

def compile_chain(source,names,updates,version,logfile):
    with tempfile.TemporaryDirectory(prefix='mio_origin_cil_') as temp:
        root=Path(temp);args=[]
        for i,name in enumerate(names):
            alias=f'p{i:03}.cil';(root/alias).write_bytes(updates.get(name,source.read(name)));args.append(alias)
        cmd=[str(ASSETS/'native/secilc.exe'),'-m','-M','true','-G','-N','-c',str(version),*args,'-o','policy.bin','-f','contexts']
        run=subprocess.run(cmd,cwd=root,capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        log=(run.stdout+run.stderr).decode('utf8','replace')
        logfile.write_text('\n'.join(f'{a} = {n}' for a,n in zip(args,names))+'\n\n'+log,encoding='utf8')
        if run.returncode:raise ValueError(f'SELinux 编译失败，未写入解包。详情：{logfile}\n'+log[-2200:])
        result=(root/'policy.bin').read_bytes()
        if policy_version(result)!=version:raise ValueError('SELinux compiler output version mismatch')
        return result

def build(source,session,log=print):
    updates={};report={'rules':RULES.splitlines(),'new_permissive':False,'chains':[],
                       'precompiled_rebuilt':[],'neverallow_check':'disabled, matching Android init fallback flags'}
    targets=[]
    for part in ('odm','vendor'):
        for suffix in ('','_debug'):
            name=f'{part}/etc/selinux/precompiled_sepolicy{suffix}'
            if source.has(name):targets.append((name,bool(suffix),policy_version(source.read(name))))
    versions={v for n,d,v in targets} or {33}
    jobs={(debug,v,False) for debug in (False,True) for v in versions}
    if source.has('system/etc/selinux/vivodebug_plat_sepolicy.cil'):
        jobs.update((True,v,True) for v in versions)
    compiled={}
    for debug,v,vivodebug in sorted(jobs):
        names=inputs(source,debug,vivodebug)
        all_text='\n'.join(source.text(n) for n in names)
        for typ in ('system_server','sysfs','sysfs_oled_hbm'):
            if not re.search(r'\(type\s+'+re.escape(typ)+r'\s*\)',all_text):
                raise ValueError('目标策略缺少实际类型 '+typ+'；请完成本机内核/基础移植标签适配。')
        for name in names:
            if re.fullmatch(r'vendor/etc/selinux/vendor_sepolicy(?:_debug)?\.cil',name):
                updates[name]=merge(source.text(name)).encode('utf8')
        label=('vivo-debug' if vivodebug else 'debug' if debug else 'normal')+f'-{v}'
        log('编译 SELinux '+label+'…')
        result=compile_chain(source,names,updates,v,session/f'policy-{label}.log')
        compiled[(debug,v,vivodebug)]=result
        report['chains'].append({'branch':label,'inputs':names,'compiled':True})
    for name,debug,v in targets:
        # Follow the target's existing normal/debug cache; retain hash sidecars
        # because only vendor CIL changed, not platform mapping digest inputs.
        updates[name]=compiled[(debug,v,False)];report['precompiled_rebuilt'].append(name)
    report['fallback_cil_updated']=sorted(n for n in updates if n.endswith('.cil'))
    return updates,report
