"""Dual-ROM in-place workflow. Official hardware tables + target Vivo consumers."""
from pathlib import Path,PurePosixPath
import argparse,bisect,copy,json,re
from configs import discover,hbm_steps,convert,json_read,json_bytes,ini_set,props
from sources import RomSource
from intents import donor_intents
from native import audit_apollo
from native_extra import surfaceflinger,sensor_library
from research_native import Elf
from rom_io import Layout,metadata,new_session,commit,restore
import cil_policy

VERSION='1.0.1'
LIBS=('libsdmcore.so','libdemura_oem_plugin.so')

def relocate(data):
    out=data;positions=[]
    e=Elf(data);sec=e.elf.get_section_by_name('.rodata')
    if sec is None:raise ValueError('显示库缺少 .rodata')
    lo,hi=sec['sh_offset'],sec['sh_offset']+sec['sh_size']
    new=b'/vendor/etc/mio_colors/'
    for old in (b'/my_product/vendor/etc/',b'/vendor/etc/op13_color/',new):
        start=0
        while (i:=data.find(old,start))>=0:
            if not lo<=i<hi or (i and data[i-1]):raise ValueError('配置路径不在独立只读字符串')
            positions.append(i);start=i+len(old)
        out=out.replace(old,new)
    if not positions:raise ValueError('目标显示库没有已研究的配置路径')
    return out,positions

def unified(target,panel,names):
    path='system/etc/LcmConfig/LcmBrightnessConfig.json'
    original=json_read(target.text(path));template=original['panel'][0]
    cfg=template['brightness_config'];dense=template['lcm_level_nit_map']
    old=int(cfg.get('smooth_brightness_max',0))
    if not dense or not 0<=old<len(dense):raise ValueError('目标统一亮度平滑范围异常')
    cutoff=dense[old][1];smooth=min(panel.normal,max(0,bisect.bisect_right([r[1] for r in panel.dense],cutoff)-1))
    result=copy.deepcopy(original);result['panel']=[]
    for name in names:
        p=copy.deepcopy(template);p['panel_name']=name;p['lcm_level_nit_map']=panel.dense
        p['brightness_config'].update(normal_brightness_max=panel.normal,hbm_brightness_max=panel.maximum,
                                      smooth_brightness_max=smooth,brightness_set_by_filenode=False)
        p.setdefault('xdr_config',{})['temperature_limit_hdr_enable']=False
        result['panel'].append(p)
    return json_bytes(result),{'smooth_brightness_max':smooth,'source_nominal_nits':cutoff}

def choose(donor,choice=None):
    panels,profiles,cwb=discover(donor)
    candidates=[p for p in panels if choice in (p.name,p.path)] if choice else panels
    if not candidates:raise ValueError('所选面板不在官方包中')
    p=candidates[0]
    if not choice and any(x.dense!=p.dense or [r[1] for r in x.rows]!=[r[1] for r in p.rows] or
                          (x.mode,x.hbm_mode)!=(p.mode,p.hbm_mode) for x in candidates):
        raise ValueError('官方有不同映射的面板，请先“扫描面板”并选择实际屏幕。')
    return p,candidates,profiles,cwb

def prepare(donor,target,session,choice=None,hbm='full40k',log=print,sensor_mode='patch',cil_mode='compile'):
    panel,panels,profiles,cwb=choose(donor,choice)
    names=list(dict.fromkeys(['panel_name=unknown']+['panel_name='+p.name for p in panels]+[p.name for p in panels]))
    official=hbm_steps(donor,panel)
    ladder=copy.deepcopy(official)
    if hbm=='full40k':ladder.update(up=[40000],down=[20000],dbv=[panel.normal,panel.maximum])
    elif hbm!='official':raise ValueError('Unknown HBM policy')
    log(f'{panel.name}：普通 {panel.normal}，峰值 {panel.maximum}；HBM {hbm}')
    files,report=convert(target,panel,ladder,names)
    payload={p.removeprefix('system/') if p.startswith('system/vendor/') else p:d for p,d in files.items()}
    sre=json_read(payload['system/etc/LcmConfig/LcmSreConfig.json'].decode('utf8'))
    projects=set(re.findall(r'PD\d+[A-Z]*',' '.join(props(target).values())))
    for project in sre:project['project']=sorted(set(project.get('project',[]))|projects)
    payload['system/etc/LcmConfig/LcmSreConfig.json']=json_bytes(sre)
    payload['system/etc/LcmConfig/LcmBrightnessConfig.json'],unified_report=unified(target,panel,names)
    ini=payload['vendor/etc/vivo_config.ini'].decode('utf8')
    ini=ini_set(ini,'vivo.software.brightness.unified_mapping','software_smooth_dimming','true')
    payload['vendor/etc/vivo_config.ini']=ini.encode('utf8')
    # ConfigStore may select a SKU-specific INI before the base file.
    variants=[]
    for name in target.paths('vendor/etc/vivo_config_'):
        if not name.endswith('.ini'):continue
        text=target.text(name)
        for section,key,value in [('brightness.policy','hbm_bl_lvl','true'),('brightness.policy','hbm_bl_diming','false'),
                                  ('brightness.policy','temperature_policy','0'),('hbm.policy','tmp_limit_policy','false'),
                                  ('hbm.policy','peak','false'),('brightness.unified_mapping','software_smooth_dimming','true')]:
            text=ini_set(text,'vivo.software.'+section,key,value)
        payload[name]=text.encode('utf8');variants.append(name)
    log('适配目标自身的 SF'+(' / sensorservice_ex…' if sensor_mode=='patch' else '；保留原传感器链路…'))
    originals={}
    if sensor_mode not in ('patch','preserve'):raise ValueError('Unknown sensor mode')
    if cil_mode not in ('compile','rules-only'):raise ValueError('Unknown CIL mode')
    native_names=['system/bin/surfaceflinger']
    if sensor_mode=='patch':native_names.append('system/lib64/libsensorservice_ex.so')
    for name in native_names:
        if not target.has(name):raise ValueError('目标缺少必要组件 '+name)
        originals[name]=target.native_original(name)
        save=session/'native_originals'/name;save.parent.mkdir(parents=True,exist_ok=True);save.write_bytes(originals[name])
    intents=donor_intents(donor)
    payload['system/bin/surfaceflinger'],sf_report=surfaceflinger(originals['system/bin/surfaceflinger'],panel,intents)
    if sensor_mode=='patch':
        payload['system/lib64/libsensorservice_ex.so'],lux_report=sensor_library(originals['system/lib64/libsensorservice_ex.so'])
    else:
        lux_report={'mode':'preserve','patched':False,'reason':'explicitly preserve target sensor chain',
                    'new_threads':0,'new_polling':False}
    library_report={}
    for name in LIBS:
        key='vendor/lib64/'+name
        if not target.has(key):raise ValueError('目标 vendor 缺少 '+name)
        original=target.read(key)
        if name=='libsdmcore.so':audit_apollo(original)
        payload[key],offsets=relocate(original)
        library_report[key]={'source':'target OriginOS vendor, not donor restoration','string_offsets':offsets}
    for name in donor.paths('my_product/vendor/etc/'):
        basename=PurePosixPath(name).name
        if basename.startswith(('display_','multimedia_display_')) and basename.endswith('.xml'):
            payload['vendor/etc/mio_colors/'+basename]=donor.read(name)
    # Export each CWB/Fusion/colour variant as reference. This Vivo-based route
    # has no added OPPO Fusion consumer, and does not claim one from file copying.
    for name in donor.paths():
        if name.startswith('my_product/etc/fusionlight_profile/') or (name.startswith('odm/etc/') and
            ('/display/' in name or '/dolby/display/' in name)):
            dest=session/'hardware_reference'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(donor.read(name))
    (session/'CWB_PROFILES.json').write_bytes(json_bytes(cwb))
    if cil_mode=='compile':
        policy_files,policy_report=cil_policy.build(target,session,log)
        payload.update(policy_files)
    else:
        policy_report={'mode':'rules-only','compiled':False,'rules':cil_policy.RULES.splitlines()}
        (session/'需要添加的SELinux规则.cil').write_text(cil_policy.RULES+'\n',encoding='utf8')
    dp,tp=props(donor),props(target)
    property_reference={k:{'official':dp.get(k),'target':tp.get(k)} for k in
                        ('vendor.display.force_tonemapping','vendor.gamecolormode_enhance')}
    result={'version':VERSION,'panel':panel.name,'panels':[p.name for p in panels],
            'normal_dbv':panel.normal,'maximum_dbv':panel.maximum,'hbm_policy':hbm,'official_hbm':official,
            'config':report,'unified_config':unified_report,'surfaceflinger':sf_report,'lux':lux_report,
            'vendor_libraries':library_report,'vendor_restoration':False,'sku_ini_updated':variants,
            'cil':policy_report,'properties_reference_only':property_reference,'cwb_profiles':cwb,
            'new_cwb_or_fusion_consumer':False,'runtime_engine':'Vivo, with OnePlus panel maps and native transport',
            'kernel_prerequisite':'matching hardware vendor/odm and AL1S /sys/lcm brightness ABI',
            'runtime_validated':False}
    return payload,result

def patch(originos,coloros,panel=None,hbm='full40k',log=print,sensor_mode='patch',cil_mode='compile'):
    with Layout(originos) as target,RomSource(coloros) as donor:
        if donor.path==target.root or donor.path.is_relative_to(target.root) or target.root.is_relative_to(donor.path):
            raise ValueError('两个 ROM 目录必须互相独立')
        session=new_session(target)
        try:
            payload,report=prepare(donor,target,session,panel,hbm,log,sensor_mode,cil_mode)
            meta,specs,partitions=metadata(target,payload)
            report['packing_metadata']=partitions;report['changed_partitions']=sorted({p.split('/')[0] for p in payload})
            report['file_permissions']=specs
            physical={target.relative(p):d for p,d in payload.items()};physical.update(meta)
            # All parsing/native adaptation/CIL compilation completes before commit.
            (session/'PATCH_REPORT.json').write_bytes(json_bytes(report))
            (session/'PERMISSIONS.txt').write_text('\n'.join(f"{p}\t{s['uid']}:{s['gid']}\t{s['mode']}\t{s['label']}" for p,s in sorted(specs.items()))+'\n',encoding='utf8')
            log('备份并写入解包目录…')
            commit(target,session,physical,report)
            log('PATCH 完成；需要重打：'+', '.join(report['changed_partitions']))
            log('修改前/后文件、源码参数、CIL 编译记录：'+str(session))
            return session,report
        except BaseException as ex:
            (session/'ERROR.txt').write_text(str(ex),encoding='utf8')
            raise

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--originos');parser.add_argument('--coloros');parser.add_argument('--panel')
    parser.add_argument('--hbm',choices=('full40k','official'),default='full40k');parser.add_argument('--restore')
    parser.add_argument('--sensor-mode',choices=('patch','preserve'),default='patch',help='preserve explicitly keeps the original sensor chain')
    parser.add_argument('--cil-mode',choices=('compile','rules-only'),default='compile',help='rules-only exports grants without modifying or compiling CIL')
    a=parser.parse_args()
    if a.restore:return restore(a.restore)
    if not a.originos or not a.coloros:parser.error('--originos and --coloros required')
    patch(a.originos,a.coloros,a.panel,a.hbm,sensor_mode=a.sensor_mode,cil_mode=a.cil_mode)

if __name__=='__main__':main()
