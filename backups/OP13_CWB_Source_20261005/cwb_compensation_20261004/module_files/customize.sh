#!/system/bin/sh
ui_print "- OP13 OriginOS CWB 补偿 v5：FHD 原生取色缓冲修正"
ui_print "- 保留 OVSC、HBM、HDR 和自动亮度配置；不替换整套显示库"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/lib64" 0 0 0755 0644
chcon u:object_r:system_file:s0 "$MODPATH/system" "$MODPATH/system/lib64" || abort "系统目录标签设置失败"
for cwb_so in "$MODPATH/system/lib64/"*.so; do
    chcon u:object_r:system_lib_file:s0 "$cwb_so" || abort "无法设置原生库 SELinux 标签"
done
chcon u:object_r:vendor_file:s0 "$MODPATH/system/vendor" "$MODPATH/system/vendor/lib64" "$MODPATH/system/vendor/lib64/libcwb_qcom_aidl.so" || abort "CWB vendor 标签设置失败"
ui_print "- root:root / 目录0755 / 库0644；系统库 system_lib_file，厂商库 vendor_file"
ui_print "- 使用 Mountify 挂载；无截图轮询、root 守护进程、顶层目录自挂载"
ui_print "- 一加13当前 OriginOS 专用候选；重启后需验证 FHD/QHD 取色"
