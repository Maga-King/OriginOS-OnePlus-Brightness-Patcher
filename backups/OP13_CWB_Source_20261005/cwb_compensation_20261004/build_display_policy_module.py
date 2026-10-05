"""Package only the requested SELinux display-node addition, no display libraries."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = Path(r'C:\Users\a1510\Videos\OP13_OriginOS_Display_Node_Permissions_20261005_v3.zip')

module_prop = '''id=op13_display_node_permissions
name=OP13 OriginOS 显示节点权限修复
version=v3-20261005
versionCode=2026100503
author=Nyako
description=显示节点权限及用户指定的指纹属性/vivo HAL允许规则；不替换库、不改亮度表、不重标记、不加守护进程。
'''

customize = '''#!/system/bin/sh
ui_print "- 仅追加显示节点 SELinux 读写权限"
ui_print "- 不替换任何系统库、不写显示节点、不启动守护进程"
set_perm_recursive "$MODPATH" 0 0 0755 0644
ui_print "- 重启后由 KernelSU 加载 sepolicy.rule"
'''

readme = '''一加13当前OriginOS专用，独立策略测试包。
只开放已经在本机确认存在的sysfs_graphics_ffl/oppo_log_sysfs/alpha_sysfs三种类型，
init/vendor_init/system_server/surfaceflinger/hal_graphics_composer_default目录读/搜索和文件读写。
新增hal_fingerprint_oppo仅访问sysfs_graphics_ffl，依据重启后的目录search拒绝日志。
v3另合并用户提供的完整指纹属性/allocator/vivo HAL规则，具体权限见sepolicy.rule。
按标签授权，同标签其他路径也会生效。没有通用sysfs写、permissive或节点重新标记。
原有DAC权限不变。ksu已有权限，不添加依赖ksu的新系统服务。
无system目录，无挂载，无库替换，无service.sh，无轮询；停用并重启可撤销本包新增规则。
display_nodes.cil只是固化参考，运行时仅由sepolicy.rule生效。
本包不包含CWB DC/SF分支修复，不宣称能单独解决所有指纹黑屏问题。
'''

cil = (ROOT / 'module_files' / 'display_nodes.cil').read_bytes()
rules = []
source = (ROOT / 'module_files' / 'sepolicy.rule').read_text(encoding='utf8')
for line in source.splitlines():
    words = line.split()
    if len(words) >= 3 and words[0] == 'allow' and words[2] in {
        'sysfs_graphics_ffl', 'oppo_log_sysfs', 'alpha_sysfs'}:
        rules.append(line)
if len(rules) != 32:
    raise ValueError(f'Unexpected rule block: {len(rules)}')
# Include only the display block and explicitly requested extra rules, NOT
# the existing CWB execmem/execmod/Binder grants (unchanged in the CWB module).
extra_source = source.split('# User-provided complete CIL grants, normalized/deduplicated 2026-10-05.', 1)[1]
extra_rules = [line for line in extra_source.splitlines() if line.startswith('allow ')]
if len(extra_rules) != 14:
    raise ValueError(f'Unexpected user addition block: {len(extra_rules)}')
policy = ('# Display-node and complete user-requested grants only.\n' + '\n'.join(rules + extra_rules) + '\n').encode()
OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name, data in {'module.prop': module_prop.encode(), 'customize.sh': customize.encode(),
                       'README.txt': readme.encode(), 'sepolicy.rule': policy,
                       'display_nodes.cil': cil,
                       'user_additions.cil': (ROOT / 'module_files' / 'user_additions.cil').read_bytes()}.items():
        archive.writestr(name, data)
print(f'{OUT} ({OUT.stat().st_size} bytes, no system payload)')
