"""ColorOS hardware is authoritative; OriginOS contributes schemas/consumers only."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import bisect, copy, json, math, re
import xml.etree.ElementTree as ET

def json_read(text):
    # JsonCpp permits comments/trailing commas; do not alter quoted strings.
    token=re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|,(?=\s*[}\]])')
    return json.loads(token.sub(lambda m:m[0] if m[0].startswith('"') else '',text))

def json_bytes(obj): return (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf8')

def props(source):
    result={}
    for p in source.paths():
        if p.endswith('/build.prop') or p.startswith('my_product/properties/'):
            for line in source.text(p).splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k,v=line.split('=',1);result[k.strip()]=v.strip()
    return result

@dataclass
class Panel:
    name:str
    path:str
    rows:list
    dense:list
    normal:int
    maximum:int
    logical_normal:int
    logical_max:int
    minimum:int
    mode:str
    hbm_mode:str

def dense_nits(rows,maximum):
    anchors={}
    for row in rows: anchors[int(row[1])]=max(anchors.get(int(row[1]),0),row[-1])
    keys=sorted(anchors); result=[]
    for i in range(maximum+1):
        if i in anchors: v=anchors[i]
        else:
            pos=bisect.bisect_left(keys,i);lo,hi=keys[pos-1:pos+1]
            v=anchors[lo]+(anchors[hi]-anchors[lo])*(i-lo)/(hi-lo)
        result.append([i,round(v,9)])
    return result

def discover(source):
    profiles={p:json_read(source.text(p)) for p in source.paths('my_product/etc/fusionlight_profile/') if p.endswith('.json')}
    common=[v['CommonConfig'] for v in profiles.values() if 'CommonConfig' in v]
    if not common: raise ValueError('官方包缺少 fusionlight_profile，无法从源机型确认亮度范围。')
    # Do not select the first of conflicting hardware variants silently.
    domains={(int(c['NormalModeBrightnessMax']),int(c['BrightnessMax'])) for c in common}
    if len(domains)!=1: raise ValueError('Fusion 配置含不同亮度范围，需先选择/研究对应屏幕，不能混用。')
    normal,maximum=domains.pop()
    panels=[]
    for p in source.paths('my_product/vendor/etc/display_apollo_list_'):
        if not p.endswith('.xml'):continue
        name=PurePosixPath(p).stem.removeprefix('display_apollo_list_')
        match=re.search(r'(P_\d+)',name)
        if not match:raise ValueError('无法关联屏幕亮度配置: '+p)
        bp='my_product/vendor/etc/display_brightness_config_'+match[1]+'.xml'
        if not source.has(bp):raise ValueError('缺少 '+bp)
        brightness=ET.fromstring(source.read(bp));table=brightness.find('brightness_table')
        rows=[[float(v) for v in n.text.split(',')] for n in ET.fromstring(source.read(p)).findall('./Levels/Level')]
        if not rows or any(len(r)!=10 or r[0]!=i or r[1]!=r[2] or not all(math.isfinite(v) for v in r) for i,r in enumerate(rows)):
            raise ValueError('Apollo 表格式不支持: '+p)
        if any(b[1]<a[1] or b[-1]<a[-1] for a,b in zip(rows,rows[1:])):raise ValueError('Apollo 表不单调: '+p)
        logical_normal=int(table.get('max'))
        # ApolloService::Init: logicalMax = hardwareMax + normalLogical - normalPhysical.
        logical_max=maximum+logical_normal-normal
        if not 0<normal<maximum or logical_max>=len(rows) or rows[logical_normal][1]!=normal or rows[logical_max][1]!=maximum:
            raise ValueError('官方 Fusion/Apollo/亮度表端点不一致，需人工定位: '+p)
        minimum=int(rows[int(table.get('min'))][1])
        panels.append(Panel(name,p,rows,dense_nits(rows,maximum),normal,maximum,logical_normal,logical_max,minimum,
                            brightness.findtext('lux_table_mode'),brightness.findtext('hbm_lux_table_mode')))
    if not panels:raise ValueError('官方包缺少 display_apollo_list_*.xml')
    cwb=[]
    weights=[]
    for p in source.paths('odm/etc/display/'):
        if 'cwb_weights' in p and p.endswith('.json'):
            w=json_read(source.text(p));count=w.get('count');array=w.get('Weights',[])
            if count!=len(array):raise ValueError('CWB 权重条数不匹配: '+p)
            weights.append({'source':p,'count':count,'area':w.get('Area')})
    for p,v in profiles.items():
        c=v.get('CommonConfig',{});rect=c.get('ScreenShotRect');size=c.get('ScreenResolution')
        if not rect or not size:continue
        x,y,r,b=[int(rect[k]) for k in ('LeftTopX','LeftTopY','RightBottomX','RightBottomY')]
        if not(0<=x<r<=size['Width'] and 0<=y<b<=size['Height']):raise ValueError('CWB ROI 超出官方尺寸: '+p)
        cwb.append({'source':p,'project':c.get('Project'),'rect':[x,y,r,b],'native_resolution':size,
                    'pixels':(r-x)*(b-y),'matching_weight_files':[w['source'] for w in weights if w['count']==(r-x)*(b-y) and w['area'] in ([x,y,r-1,b-1],[x,y,r,b])],
                    'CWBSupported':c.get('CWBSupported'),'period_ms':c.get('CWBScreenshotPeriod'),
                    'runtime_consumer_added':False})
    return panels,profiles,cwb

def hbm_steps(source,panel):
    roots=[]
    for path in source.paths():
        if PurePosixPath(path).name in ('display_brightness_config_common.xml','display_brightness_config_default.xml'):
            roots.append((path,ET.fromstring(source.read(path))))
    for path,root in roots:
        a=root.find(f"./lux_table[@id='{panel.mode}']");b=root.find(f"./hbm_lux_table[@id='{panel.hbm_mode}']")
        if a is not None and b is not None:break
    else:raise ValueError('未找到官方面板指定的 lux/HBM 模式 '+str(panel.mode)+'/'+str(panel.hbm_mode))
    normal_curve=[[float(v) for v in n.text.split(',')] for n in a]
    nit=normal_curve[-1][1];entries=list(b);nits=[r[1] for r in panel.dense]
    up=[];down=[];dbv=[panel.normal]
    for i,e in enumerate(entries):
        enter,leave=int(e.get('enter')),int(e.get('exit'));gap,delta=map(float,e.text.split(','))
        if gap<1 or gap!=int(gap) or delta<=0 or leave>enter:raise ValueError('不支持的官方 HBM 分段')
        end=int(entries[i+1].get('enter')) if i+1<len(entries) else enter+(math.ceil(max(0,nits[-1]-nit)/delta)+1)*int(gap)
        if end-enter>10000000:raise ValueError('HBM 分段异常')
        for lux in range(enter,end,int(gap)):
            nominal=nit+math.floor((lux-enter)/gap)*delta
            target=max(panel.normal+1,min(panel.maximum,bisect.bisect_left(nits,nominal)))
            up.append(lux);down.append(leave);dbv.append(target)
            if target==panel.maximum:return {'source':path,'mode':panel.hbm_mode,'up':up,'down':down,'dbv':dbv,'normal_lux_nits':normal_curve}
        nit+=(end-enter)/gap*delta
    raise ValueError('官方 HBM 阶梯未到端点')

def scale_algo(original,panel):
    result=copy.deepcopy(original);rows=original['LcmMapAlgoBrLevel'];source_max=len(rows)
    if not rows or any(r[0]!=i+1 for i,r in enumerate(rows)):raise ValueError('目标 LcmMapAlgoBrLevel 索引格式不同')
    ratio=panel.normal/source_max
    for k,v in result['AlgoMapLcmBrLevel'].items():
        if k!='sectionkeypoint':result['AlgoMapLcmBrLevel'][k]=[x*ratio for x in v]
    new=[]
    for dbv in range(1,panel.normal+1):
        pos=max(1,min(source_max,dbv/ratio));lo=int(pos);hi=min(source_max,lo+1)
        v=rows[lo-1][-1]+(rows[hi-1][-1]-rows[lo-1][-1])*(pos-lo)
        new.append([dbv,int(v+0.5),v])
    result['LcmMapAlgoBrLevel']=new
    result['minBrightnessLevel']=[max(panel.minimum,int(v*ratio+0.5)) for v in original['minBrightnessLevel']]
    if result.get('specialMinLcmLevel',0)>0:result['specialMinLcmLevel']=max(panel.minimum,int(result['specialMinLcmLevel']*ratio+0.5))
    return result,source_max

def ini_set(text,section,key,value):
    text=text.replace('\r\n','\n');p=re.compile(r'(?ms)^\['+re.escape(section)+r'\]\n(.*?)(?=^\[|\Z)');m=list(p.finditer(text))
    if len(m)>1:raise ValueError('重复 INI section: '+section)
    if not m:return text.rstrip()+f'\n\n[{section}]\n{key}={value}\n'
    m=m[0];body=m[1];kp=re.compile(r'(?m)^'+re.escape(key)+r'=.*$')
    if len(kp.findall(body))>1:raise ValueError('重复 INI key: '+key)
    body=kp.sub(f'{key}={value}',body) if kp.search(body) else body.rstrip()+f'\n{key}={value}\n\n'
    return text[:m.start(1)]+body+text[m.end(1):]

def convert(target,panel,ladder,panel_names,lcm_id='0x0'):
    """Return module-relative payload. Original Vivo schema is never an endpoint authority."""
    files={};report={}
    def load(p):return json_read(target.text(p))
    def put(p,o):files[p]=json_bytes(o)
    sensor='system/etc/SensorConfig/';lcm='system/etc/LcmConfig/'
    framework=load(sensor+'SensorFrameworkConfig.json');report['previous_framework_max']=framework['MaxBrightness'];framework['MaxBrightness']=panel.normal
    algo,old_max=scale_algo(load(sensor+'AutoBrightnessLcm2AgloBrLevel.json'),panel);report['previous_algo_max']=old_max
    # Override every existing suffix for each consumed basename, including base and current selector.
    for name,obj in [('SensorFrameworkConfig',framework),('AutoBrightnessLcm2AgloBrLevel',algo),('AutoBrightnessNitMapLcm',{'LcmMapNit':panel.dense[:panel.normal+1]})]:
        paths={sensor+name+'.json',sensor+name+'_'+lcm_id+'.json'}
        paths.update(p for p in target.paths(sensor+name) if p.endswith('.json'))
        for p in paths:put(p,obj)
    maps={'panel':[{'panel_name':name,'config':{'normal_brightness_max':panel.normal,'hbm_brightness_max':panel.maximum},'lcm_map_nit':panel.dense} for name in panel_names]}
    put(lcm+'LcmMapNit.json',maps)
    xdr=load(lcm+'XdrBrightnessConfig.json');base=copy.deepcopy(xdr.get('panel',[xdr])[0]);base.pop('panel',None)
    if 'hdr_video_coeff' in base and len(base['hdr_video_coeff'])!=3:raise ValueError('HDR 系数不是三项，不能直接移植')
    base['xdr_config']['normal_brightness_max']=panel.normal;base['xdr_config']['hbm_brightness_max']=panel.maximum
    base['brightness_luminance_map']=panel.dense;base['brightness_section']=[]
    xdr['panel']=[dict(copy.deepcopy(base),panel_name=n) for n in panel_names]
    # Also align the legacy reader; no stale 2047/15415 in the inactive fallback.
    for key in ('xdr_config','brightness_luminance_map','brightness_section'):xdr[key]=copy.deepcopy(base[key])
    put(lcm+'XdrBrightnessConfig.json',xdr)
    sre=load(lcm+'LcmSreConfig.json')
    if not isinstance(sre,list) or not sre:raise ValueError('未支持的 SRE 配置结构')
    for project in sre:
        for p in project['panel']:
            old_n,old_h=p['transitionPoint'],p['hdrBrightnessLimit']
            def dbv(v):
                if not 0<=v<=old_h:raise ValueError('SRE 字段超出原来的标尺: '+str(v))
                return round(v*panel.normal/old_n if v<=old_n else panel.normal+(v-old_n)*(panel.maximum-panel.normal)/(old_h-old_n))
            if 'batteryLimit' in p:
                p['batteryLimit']['batteryLimitBrightness']=[dbv(v) for v in p['batteryLimit']['batteryLimitBrightness']]
            for key in ('peakV2BrightnessBound',):
                if key in p:p[key]=dbv(p[key])
            p['panel_name']=panel_names;p['transitionPoint']=panel.normal;p['hdrBrightnessLimit']=panel.maximum;p['needApDiming']=False
            # Prior hand process removed only borrowed Vivo display thermal policy, not kernel/BMS thermal safeguards.
            p.pop('typeTemperatureLimit',None)
            for suffix in ('','_auto'):
                p['hbmMap'+suffix]=ladder['dbv'];p['hbmUpLuxLevel'+suffix]=ladder['up'];p['hbmDownLuxLevel'+suffix]=ladder['down']
            for package in p.get('packagePolicy',[]):
                package['packageHbmMap']=ladder['dbv'];package['packageAutoHbmMap']=ladder['dbv']
    put(lcm+'LcmSreConfig.json',sre)
    if target.has(sensor+'dynamicBrightnessConfig.json'):
        dynamic=load(sensor+'dynamicBrightnessConfig.json')
        for curve in dynamic['dynamicBirghtnessNitParams'].values():curve[-1]=panel.dense[panel.normal][1]
        put(sensor+'dynamicBrightnessConfig.json',dynamic)
    if target.has(lcm+'BrightnessPolicy.json'):
        policy=load(lcm+'BrightnessPolicy.json');count=0
        for p in policy.get('DeviceBrightnessPolicy',[]):
            if p.get('deviceType')!='phone' or p.get('panelType')!='oled':continue
            count+=1;nit=round(panel.dense[panel.normal][1])
            for key in ('actualPanelMaxNit','indoorMaxNitLimit','professionModeIndoorMaxNitLimit','darkModeMaxNitLimit'):
                if key in p:p[key]=nit
            for key in ('controlModeMaxNitLimit','controlModeMaxNitLimitSpecial','appMaxNitLimit','appMaxNitLimitSpecial'):
                for item in p.get(key,[]):item['maxNit']=nit
        put(lcm+'BrightnessPolicy.json',policy);report['oled_policy_profiles']=count
    ini=target.text('vendor/etc/vivo_config.ini')
    for section,key,val in [('brightness.policy','hbm_bl_lvl','true'),('brightness.policy','hbm_bl_diming','false'),
                            ('brightness.policy','temperature_policy','0'),('hbm.policy','tmp_limit_policy','false'),('hbm.policy','peak','false')]:
        ini=ini_set(ini,'vivo.software.'+section,key,val)
    if '[vivo.software.brightness.unified_mapping]' not in ini:ini+='\n[vivo.software.brightness.unified_mapping]\n'
    files['system/vendor/etc/vivo_config.ini']=ini.encode('utf8')
    report['new_normal']=panel.normal;report['new_hbm']=panel.maximum;report['panel_names']=panel_names
    report['retained_engine']='Vivo ALS / normal-lux curve shape / smoothing / learning / lifecycle; same as OP13 B+C hand process'
    report['hbm']=ladder
    return files,report
