一加13当前OriginOS DSU专用：官方硬件CWB屏下光感补偿测试 v5 候选

v5 现场定位的变化：
FHD 下硬件仍输出原生38x42区域，但1080x2376分配使色块落在缓冲左上角；
官方算法按ROI坐标取像素，因而读到黑色。QHD恢复后色块回到正确坐标。
仅改 vendor/lib64/libcwb_qcom_aidl.so 中 prepareCwbBuffer 的主屏尺寸加载，
使用本机1440x3168原生取色缓冲；不是将用户屏幕分辨率强制为QHD。
算法、IPC、输出缓冲调用、副屏逻辑不改；只替换4字节指令和8字节只读常量，
不移动ELF表、符号、重定位；只读LOAD延长8字节。
主屏FHD/QHD均允许启动补偿，ROI仍是原生1010,148..1048,190。
目前是待重启实机验证的候选，不能将QHD原包正常等同于FHD修复成功。
FHD缓冲内存增加约5MB；没有增加采样频率，实际功耗未测量。

不是通用一加模块，其他ROM/机型不要直接使用。
使用已运行的OriginOS libsensorservice.so，仅在DT_NEEDED最前追加补偿库；
原.text/.plt和原有依赖顺序不改，libsensorcompat_ovsc.so不替换。
补偿库使用短文件名nc.so，以利用原ELF六字节空隙，不移动符号、字符串或动态表。
只复用冗余DT_FLAGS_1=NOW槽位；原DT_FLAGS=BIND_NOW保留。
v1曾因patchelf搬移字符串表触发既有OVSC扫描越界，已弃用，禁止重新启用。
v2已验证开机，但当前系统走AIDL，只有HIDL订阅回调使补偿保持未启用。
v3同时接入本ROM现场定位的AIDL/HIDL activate回调，成功订阅才记租约。
v3实机发现已有HAL派生0x3e9仅剩lux，积分时间/DBV/RGBC/模式/序号全部丢失。
v4从物理0x6a5完整包的局部副本计算，按严格相同时间戳及订阅代际关联标准副本。
固定32条缓存，无模糊时间匹配；不匹配时保留原事件，不伪造缺失字段。
原始物理包和系统缓存不写；只修改标准光感values[0]，Vivo内部收到补偿后的局部副本。
同一完整原始包的重复交付不重复喂入五样本选择器，订阅代际不同不沿用旧结果。
补偿在Vivo处理前修正标准0x3e9光感副本，物理0x6a5原包和RGBC不改。
使用官方CWB客户端、原生QHD ROI和本机运行时W_VIEW工厂校准。
只完成已审计的普通模式V2.1；FOD/DC/工厂模式不宣称完整复刻。
Vivo自动亮度曲线仍保留当前已修复的版本，HBM/HDR/温控配置不另改。

没有service.sh守护进程、截图取色和额外亮度节点轮询。
官方CWB请求周期250ms；系统进程内工作线程闲置时在条件变量上休眠。
标准光感最终停订阅或DBV=0时停止CWB；亮屏和光感订阅后按样本恢复。
前台动态页匹配失败沿用最近有效补偿，按官方逻辑处理0x20000强制上报包。
官方pending定义是打包标志值小于65536，与bit17强制上报不是同一回事。
初始尚未拿到CWB和校准时保留现有行为，不将未验证结果标为已补偿。
需要验证system_server实际加载、SELinux、息屏停启；root探针成功不是上线证明。

挂载：当前Mountify，普通system/lib64文件覆盖，不自建顶层tmpfs镜像。
system/lib64/*.so：root:root，0644，u:object_r:system_lib_file:s0。
system/vendor/lib64/libcwb_qcom_aidl.so：root:root，0644，u:object_r:vendor_file:s0。
目录：root:root，0755，u:object_r:system_file:s0。
SELinux只追加sepolicy.rule列出的指定允许，不设置permissive。
2026-10-05已加入显示节点权限：init、vendor_init、system_server、
surfaceflinger、hal_graphics_composer_default 对实际三种标签的目录读/搜索、文件读写。
三种标签：sysfs_graphics_ffl、oppo_log_sysfs、alpha_sysfs；不增加通用sysfs写权限。
重启真实AVC另发现一加指纹HAL被拒目录search；新增hal_fingerprint_oppo对sysfs_graphics_ffl读写。
规则按标签生效，不是按路径生效，同标签的其他节点也在授权范围内。
不修改节点已有标签或DAC权限；root:root 0644节点不能仅靠SELinux规则让system用户写入。
ksu已有这些权限；传感器HAL尚无直接写显示节点的必要证据，不额外授予写权限。
display_nodes.cil是相同显示规则的固化版本，需合并并重新编译匹配的完整策略链及缓存。
单独复制CIL不会生效；模块使用sepolicy.rule。
2026-10-05 17:40已安装独立显示权限包v1并重启DSU，实际策略查询确认init写HBM已允许。
后续v3增加指纹HAL目录权限和用户完整CIL规则；同名独立包更新，不替换现有CWB库。
用户规则固化参考user_additions.cil；合并重复项，缺class/权限的截断片段未猜测添加。
v5 安静构建移除每五秒状态日志，保留初始化、订阅切换和异常提示；无日志定时器。

回退：在KernelSU禁用“OP13 OriginOS 官方硬件 CWB 补偿测试”，重启。
ADB回退：su -c 'touch /data/adb/modules/op13_cos_cwb/disable' 后重启。
原始文件保存在电脑cwb_compensation_20261004/preinstall_libsensorservice.so，
既有OVSC副本preinstall_libsensorcompat_ovsc.so。没有刷写实体分区。
