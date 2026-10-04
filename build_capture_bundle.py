"""Build a private overwrite bundle from a previously captured ROM subset.

Uses the SAME prepare() backend as GUI/CLI. Does not borrow a sensor library.
Packing metadata here is a test fixture; the bundle updates the user's real
packing metadata when applied, rather than replacing it with fixture files.
"""
import argparse, json, shutil, zipfile
from pathlib import Path
from patcher import patch
from rom_io import file_spec, metadata
from sources import RomSource
from configs import json_bytes


def capture_fixture(capture,destination):
    destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    with RomSource(capture) as source:
        for name in source.paths():
            if name.startswith(('runtime/','metadata/')):continue
            dst=destination/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(source.read(name))
    cfg=destination/'config';cfg.mkdir()
    for part in ('system','vendor'):
        fs=[];fc=[]
        for path in sorted((destination/part).rglob('*')):
            rel=path.relative_to(destination).as_posix();s=file_spec(rel)
            fs.append(f"{rel} {s['uid']} {s['gid']} {'0755' if path.is_dir() else s['mode']}")
            import re
            fc.append(re.escape('/'+rel)+' '+s['label'])
        (cfg/(part+'_fs_config')).write_text('\n'.join(fs)+'\n',encoding='utf8')
        (cfg/(part+'_file_contexts')).write_text('\n'.join(fc)+'\n',encoding='utf8')
    return destination


def build(capture,donor,workspace,zip_path,sensor_mode='preserve',hbm='full40k'):
    workspace=Path(workspace);workspace.mkdir(parents=True,exist_ok=False)
    target=capture_fixture(capture,workspace/'OriginOS')
    session,report=patch(target,donor,hbm=hbm,sensor_mode=sensor_mode,cil_mode='rules-only')
    bundle=workspace/'bundle';bundle.mkdir()
    manifest=json.loads((session/'TRANSACTION.json').read_text(encoding='utf8'))
    original_count=0
    for rel in manifest['written']:
        if rel.startswith('config/') or rel.startswith('.'):continue
        after=session/'after'/rel;dst=bundle/'补丁文件'/rel
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(after,dst)
        before=session/'before'/rel
        if before.is_file():
            original=bundle/'修改前原件'/rel;original.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(before,original);original_count+=1
    for name in ('PATCH_REPORT.json','PERMISSIONS.txt','需要添加的SELinux规则.cil','CWB_PROFILES.json'):
        shutil.copy2(session/name,bundle/name)
    if (session/'hardware_reference').exists():shutil.copytree(session/'hardware_reference',bundle/'官方CWB参考_不安装')
    guide=f'''一加13T / PKX110：OriginOS 亮度与 HDR 内置补丁

输入：用户此前提供的 OriginOS PD2606 采集原件与本机官方 ColorOS16 采集原件。
调用生成器同一个 prepare/patch 流程；没有把一加13的地址套到13T。
普通上限 {report['normal_dbv']}，峰值 {report['maximum_dbv']}；HBM 4万lux进入即峰值、2万退出。
保留原有防抖、时限与底层保护；该数值是策略目标，不代表无条件实际输出。

本 ZIP 是解包内置覆盖包，不是 Magisk 安装包。
“补丁文件/system”覆盖解包的 system/system（双层）或 system（单层）。
“补丁文件/vendor”覆盖解包的 vendor。
请把 PERMISSIONS.txt 的文件和新目录记录合并到真实 config/*_fs_config 与 *_file_contexts。
不要把本次采集样本生成的测试 config 当成整个 ROM 的打包 config。
需要重打 system、vendor；不会修改属性，参考值在 PATCH_REPORT.json。

CIL 只列出需要添加的三条规则；请合并到当前 ROM 的 vendor_sepolicy.cil，
存在独立 vendor_sepolicy_debug.cil 时同步合并，并按现有流程更新预编译缓存。
没有添加 permissive，亦没有替换整份厂商策略。

重要：昨天采集没有 libsensorservice_ex.so，本次明确保留13T原生传感器链路。
不会给其它 libsensorservice.so 套用没有对应入口的 OP13 补丁。
因此这份包尚未补上 BC05 的 lux 分派修复，HBM 实机链路需要后续验证。
官方 CWB 坐标/权重只保存为参考；没有新增 OPPO Fusion/CWB consumer。
HDR / 杜比的实际白点、色准、HBM 与息屏策略仍需13T实机测试。

“修改前原件”保存本次触及的已有文件，共 {original_count} 个；新建文件没有前件。
研究与复现：离线 native 测试、本地/云端生成器比对报告另交付。
'''
    (bundle/'使用说明.txt').write_text(guide,encoding='utf8')
    zip_path=Path(zip_path);zip_path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(zip_path,'x',zipfile.ZIP_DEFLATED,compresslevel=5,strict_timestamps=False) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(bundle).as_posix())
    result={'zip':str(zip_path),'workspace':str(workspace),'files':sum(p.is_file() for p in (bundle/'补丁文件').rglob('*')),
            'original_count':original_count,'report':report}
    (workspace/'BUILD.json').write_bytes(json_bytes(result))
    print(json.dumps({k:v for k,v in result.items() if k!='report'},ensure_ascii=True))
    return target,session,bundle


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--capture',required=True);parser.add_argument('--donor',required=True)
    parser.add_argument('--workspace',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--sensor-mode',choices=('patch','preserve'),default='preserve');a=parser.parse_args()
    build(a.capture,a.donor,a.workspace,a.output,a.sensor_mode)
