MIO OriginOS 亮度 / HDR 内置 PATCH 1.0.1
2026-10-04

用途
选择需要修改的、已完成基础修复的 OriginOS 解包，以及实际硬件对应的官方 ColorOS 16 解包。
点击 PATCH 后，直接修改第一份 OriginOS 解包，并在它的同级目录自动备份修改前/后的文件。
官方包只读取。支持 MIO / DNA 的 system/system 双层，其他分区按原来的层级处理。
界面和离线双 ROM 的操作方式参考 https://github.com/Maga-King/oplus-camera-ota-helper 。

一、直接使用
1. 解压完整工具，运行 MIO_OriginOS_Patcher.exe，无需安装 Python、Java、WSL 或 ADB。
2. 第一个框选基础移植修复做过的 OriginOS 解包根目录，例如 E:\MIO\OriginOS_Port。
   应能看到 system、vendor、config 等目录。不要选 system/etc 子目录，不要选未解包的镜像。
3. 第二个框选真实硬件机型的完整官方 ColorOS 16 解包：一加13选自己的，13T选自己的。
   不使用目标 OriginOS 伪装的 vivo 型号来决定面板、亮度范围或 CWB 坐标。
4. 默认 HBM 为“4 万进入即峰值 / 2 万退出”；对于当前 OP13 是 40000 lux -> DBV4094。
   可切换为“ColorOS 官方分档”。实际峰值由官方面板表读取，不把 4094 硬套所有未来机型。
5. 同一 ROM 有不同映射的屏幕时，先点“扫描面板”，选择实际面板。
   相同映射的不同屏幕名字可以自动合并别名；不因同为京东方就假定所有校准表相同。
6. 点击 PATCH，等待完成。窗口会显示要重打的分区，通常是 system、vendor。
   如果目标原来在 odm 放了预编译 SELinux，重编对应缓存时也会列出 odm。
7. 用已更新的 config/*_fs_config 与 config/*_file_contexts 打包，不能继续用旧 config。
   工具不生成 super.img、不刷分区、不安装 Magisk、不执行 gsi_tool、不重启。
8. 缺少已支持的 libsensorservice_ex.so 时，可明确选择“保留目标原生传感器链路”。
   这会跳过 BC05 的 lux 分派补丁，不表示该系统的 HBM 光线链路已经修好。
   没有完整 SELinux 链路或想自行处理 CIL 时，可选“只导出需添加的 CIL 规则”。
   规则导出模式不会改 CIL 或预编译策略，需要由你自行合并规则并更新缓存。

二、自动完成的内容
- 读取所选官方 Apollo、亮度 XML、普通/峰值 DBV 和标称 nit 表，转换 Vivo 的自动亮度标尺。
- 对齐 SensorFrameworkConfig、AutoBrightnessLcm2AgloBrLevel、AutoBrightnessNitMapLcm 及已有后缀版本。
- 对齐 LcmMapNit、XdrBrightnessConfig、LcmBrightnessConfig，兼容 legacy / unified 两条原生亮度路径。
- 对齐 SRE 手动、自动、相册包策略；默认单档 HBM，保留防抖、电量和时限字段。
- 在目标自身的 SurfaceFlinger 中定位亮度输入/输出、Apollo 逆表、SDR 上限和 P3/HDR/杜比色彩入口。
- 在目标自身的 libsensorservice_ex.so 中定位 lux 分发，把已有效的标准光照交给原 Vivo 滤波链，避免重复处理私有别名。
- 处理目标 vivo_config.ini 和已有 SKU 版本的亮度开关。内置后启动早期即可读到，避免晚挂载旧缓存。
- 只修改目标 libsdmcore / demura 库内的只读配置路径，把 /my_product/vendor/etc 指向 /vendor/etc/mio_colors。
- 从官方包复制显示 XML 到该路径，不恢复/替换 vendor 显示库群。
- 合并必要 CIL，实际编译 normal / debug，并在存在时编译 vivo-debug 分支；更新已有预编译策略缓存。
- 更新修改分区的文件权限、SELinux 标签及新目录条目；全部准备通过后才写入目标。

三、多机型和现场定位
补丁位置来自目标 ELF 的符号和指令序列搜索。每个修改点必须唯一；不能把 13 的文件偏移加到 13T 上。
成员偏移、调用继续点、原生函数入口、可用段间空间和 Apollo 最小值也从目标指令/ELF 读取。
读取结果写入 PATCH_REPORT.json 的 located_sites、target_member_layout、unified、lux 等字段。
两份已经分析的 A17 SF（PD2620 / PD2606）在统一亮度调用位置存在真实差异，已独立定位并仿真。
模板用于识别研究过的指令结构；它不是能够自动理解任意厂商二进制的通用反编译器。
新系统出现未知调用结构、libc++ 节点布局、寄存器约定或光照 HAL 时，会报告具体未适配项，保留输入原样。
历史 BC04/BC06 手工补丁仅在保存的修改区域精确匹配时可撤回，然后重新定位新补丁。
自己生成的再次 PATCH 从上一次备份中的原生原件重新生成，避免把补丁叠加两遍。
不要删同级备份后再把已修改的二进制当成全新原件使用。

四、vendor / odm 前提
本工具不提供“套错其他机型 vendor 的恢复 A 包”，也不拿 donor 的 SO 覆盖整套显示库。
目标必须先有与实际机型匹配且能正常工作的 vendor、odm、显示 HAL 和内核。
同时保留基础移植已有的 Vivo 配套，如 vendor/etc/vivo_config.ini、ConfigStore 服务及依赖。
不需要另选第三份 vivo vendor/odm 原包；这些已完成的基础修复应存在于第一个输入目录中。
内核仍需 AL1S /sys/lcm 亮度兼容 ABI。工具不会用 JSON 代替缺失的内核节点，也不刷 msm_drm.ko。
历史 vendor 恢复 A 只保存在范例的 historical_only_NOT_IN_TOOL 中。
属性不自动改：PATCH_REPORT.json 的 properties_reference_only 列出两条显示属性的官方/目标值供你处理。
不修改机型伪装、DPI、分辨率、音频杜比、录像编码器、hals.conf、JAR 或 RRO。

五、CIL 和标签
追加的是以下只读授权：
(allow system_server sysfs (dir (getattr open read search)))
(allow system_server sysfs (file (getattr open read)))
(allow system_server sysfs_oled_hbm (file (getattr open read)))
需要目标本来存在 sysfs_oled_hbm 类型；工具不创建一个没有真实 genfs 标签对应的空类型蒙混过去。
保留目标已有规则和 typepermissive；工具本身不新增全局 permissive。
你之前的 (typepermissive sysfs_oled_hbm) 标的是对象类型，不能代替给 system_server 的访问授权。
使用内置 secilc 真正编译目标完整策略链；参数 -m -M true -G -N 与 Android init fallback 的主要参数一致。
已有 vendor/odm precompiled_sepolicy 及 debug 缓存会用包含新增规则的编译结果更新。
因为修改的是 vendor CIL，保留平台 mapping hash sidecar；缓存和 fallback CIL 都包含新增授权。
不存在缓存时沿用目标原来的启动编译路径，不另造 init 服务。
参考 https://android.googlesource.com/platform/system/core/+/refs/heads/main/init/selinux.cpp 。
Windows 本身不保存 Android SELinux xattr；镜像最终标签由更新后的 file_contexts 决定。
surfaceflinger 是 0:2000 / 0755 / surfaceflinger_exec；system/lib64 是 0644 / system_lib_file；
vendor/etc 的显示配置是 0644 / vendor_configs_file；具体完整清单在每次备份的 PERMISSIONS.txt。

六、备份、失败恢复和报告
备份在 <OriginOS解包名>_MIO_Backups\时间戳\：
  before/                  修改前的文件；第一次修改时不存在的文件记在 absent 列表
  after/                   实际写入的文件
  native_originals/        本次原生补丁所用原件
  TRANSACTION.json         操作记录和目标目录
  PATCH_REPORT.json        面板、策略、全部原生定位、CIL、来源与修改分区
  PERMISSIONS.txt          文件属主、权限、SELinux 标签
  policy-*.log             离线 CIL 编译记录
  hardware_reference/     此机型官方 Fusion/CWB/显示色彩参考
  CWB_PROFILES.json        每份 CWB 原生分辨率、ROI、周期和权重对应关系
发生写入错误会自动恢复已写入文件。需要手动回退时，在界面选择“恢复一次 PATCH”，选该记录的 TRANSACTION.json。
多次 PATCH 要从最后一次开始依次回退；恢复会覆盖那次修改过的文件，因此期间的人工编辑请先另存。
操作过程中不要移动 ROM/备份目录；异常断电留下 applying 状态时可选相应记录恢复。

七、CWB 和实际效果边界
当前采用 Vivo 自动亮度引擎，加一加面板映射和原生传输修复；普通 lux 曲线、学习、滤波、息屏生命周期仍是 Vivo。
工具会按每个机型读取并保存所有 Fusion/CWB 变体及对应权重，13T 的 ROI 不套一加13坐标。
本路线没有新建 OPPO Fusion consumer/CWB 服务，不把“复制配置”说成已实现运行时屏幕漏光补偿。
没有新增轮询、截图线程、开机常驻 root 进程或 LSP/Nyako hook。
HDR 模式、比率、截图及面板实际白点仍需实机测试；离线仿真不证明所有 HDR/杜比色准问题已修好。
满条时 HDR/SDR 头间距、HBM 进入、防抖与底层保护共同决定实际输出，配置目标不是无条件绕过保护。

八、范例和源码
reference/ 保存了修改前后文件、原始备份 TAR、各阶段源码、反编译结果、必要输入、历史模块、HDR 实验室源码/APK。
OP13_BC06_before_after/deployment/phone_backup/original.tar 是 35 文件内置之前的备份。
OP13_BC06_before_after/hbm40k_deployment/original.tar 是改成 4 万单档前的 SRE 表备份。
example_inputs 是为了离线复现整理的采集子集，不是可直接打包开机的完整 ROM。
其中 ColorOS 样例取自当时已工作的主系统采集，不声称整份是未修改官方原包；日常使用请选择实际机型官方完整解包。
AL1S_kernel_repository_HEAD.zip 和 uncommitted_changes.patch 保留内核仓库快照；仅供参考，不由工具刷入。
原来的研究脚本部分仍有当时的本机路径，供过程追溯；新工具代码不依赖 E:\MIO 或那台手机序列号。

源码运行：
  python -m pip install -r requirements.txt
  python app.py
命令行：
  python patcher.py --originos "E:\移植OriginOS" --coloros "E:\官方ColorOS16" --hbm full40k
  python patcher.py --restore "E:\移植OriginOS_MIO_Backups\时间戳"
重新打包 EXE：运行 Build-Windows.cmd。
prepare_* 脚本供维护者从研究原件建立范例/识别模板；一般用户运行 PATCH 不调用这些脚本。

九、此次交付的离线测试
11 项测试通过，覆盖模拟解包、失败回退、重复 PATCH、修改前恢复、动态定位歧义拒绝、
两份目标 SF 的 0～4094 亮度仿真、13T 自身 CWB 参数、原生依赖保留与 lux 分派。
独立 EXE 已用采集样本完成一次完整 PATCH，不依赖系统 Python；GUI 启动通过。
生成的 system / vendor file_contexts 另用 libselinux 编译并实际匹配，共 45 个标签通过。
normal / debug / vivo-debug CIL 真实编译通过，已有 normal / debug 预编译缓存的重建路径也已测试。
这些是离线测试，不等于每个机型均已完成刷机、待机和户外 HBM 实测。
完整版 ZIP 的 reference 与“源码”同级；运行测试请在“源码”执行 python -m unittest test_patcher -v。
独立工具目录不含大体积研究范例；完整资料 ZIP 另含范例、原件与历史源码。
