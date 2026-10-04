# OriginOS 一加亮度 / HDR PATCH 工具

为已经完成基础适配的 OriginOS 移植系统生成并内置一加屏幕亮度配置与原生修复。
选择 **移植 OriginOS 解包** 和 **实际硬件对应的官方 ColorOS16 解包**，点击 PATCH。
会备份修改前后文件，更新打包权限与 SELinux 标签，并处理 CIL。

当前路径采用 Vivo 自动亮度引擎，接入一加的面板映射及原生亮度输出；
保留 Vivo 的普通环境光曲线形状、滤波、学习及息屏生命周期。
研究过一加13、13T；其它系统的未知二进制结构需要扩展适配。

## 下载与使用

在 [Releases](../../releases) 下载 Windows ZIP，解压后打开 `MIO_OriginOS_Patcher.exe`。
无需安装 Python、Java、WSL 或 ADB。

1. 第一栏选择已经能正常启动、基础显示适配做过的 OriginOS 解包根目录。
2. 第二栏选择本机官方 ColorOS16 解包根目录。硬件是13T就选13T，不按 OriginOS 伪装机型识别。
3. 支持 MIO / DNA 的 `system/system` 双层目录，其他分区保持原本层级。
4. 多个面板映射不同时先“扫描面板”，选择实际面板。
5. 默认 HBM 为4万lux进入即峰值、2万退出，也可以选官方分档。
6. 默认修复已支持的 `libsensorservice_ex.so`。缺少该库或想保留原链路时明确选“保留目标原生传感器链路”。
7. CIL 默认真实编译并更新；没有完整策略输入或准备自行处理时选“只导出需添加的 CIL 规则”。
8. PATCH 完成后按报告重打分区，使用更新后的 `config/*_fs_config` 和 `*_file_contexts`。

详细操作、备份恢复和已知边界见 [使用说明](README.txt)。
工具不会自行刷写或重启手机。

## 当前实现

- 从所选官方包读取 Apollo / Fusion 亮度范围、面板表和 QDCM HDR/杜比 RenderIntent。
- 转换 Vivo 的 SensorConfig、LcmConfig、XDR 和 SRE 配置及 SKU INI。
- 按目标 ELF 符号与指令序列唯一定位补丁点、关键成员偏移、Apollo 参数和可用段间隙。
- 修改目标自身的 SurfaceFlinger，覆盖普通/统一亮度输出及 P3/HDR/杜比颜色入口。
- 已支持的传感器入口通过事件分派修复，不新增轮询、截图或常驻 root 服务。
- 将目标显示库的配置路径指向 `/vendor/etc/cos_color/`，复制实际硬件的显示 XML。
  库内使用等长的 `/vendor/etc/cos_color//`，连续斜线由系统正常解析，ELF 内部地址不移动。
- 合并 CIL，使用目标系统完整策略链编译 normal、debug 及存在时的 vivo-debug 分支。
- 已有预编译策略缓存会同步重建；保留模式只导出三条 allow，需自行合并和更新缓存。

一加官方 CWB/Fusion 参数会按机型读取并保存为参考，本工具没有新增 OPPO Fusion/CWB consumer。
传感器“保留”模式不会执行 BC05 lux 分派修复，不能据此认为 HBM 的 lux 通道已经修好。
目标应已有匹配硬件的 vendor/odm、显示 HAL 和 AL1S `/sys/lcm` 亮度 ABI。
工具不提供之前套错其它机型 vendor 的恢复包，不自动修改 prop，也不修改 hals.conf、JAR 或 RRO。

## 源码与构建

Windows 使用 Python 3.12.10：

```powershell
python -m pip install -r requirements.txt
python app.py
```

完整构建需先从源码生成辅助对象与 secilc：

```bash
# Linux / WSL，安装 clang、make 与 gcc-mingw-w64-x86-64
python ci/build_native.py
```

然后在 Windows：

```powershell
python -m PyInstaller --noconfirm MIO_OriginOS_Patcher.spec
python ci/make_distribution.py
```

仓库的“编译 Windows 生成器”Actions 会完成上述两阶段，固定 Python 与 Python 依赖版本。
云端构建通过不自动发布 Release；先下载 EXE，与本地生成器对相同输入的输出做实际比较后再发布。
EXE 的打包时间、路径与运行库可能影响整文件字节，比较报告分别记录 EXE 字节一致性与生成结果一致性。

## 命令行

```powershell
python patcher.py --originos "E:\OriginOS移植" --coloros "E:\本机官方ColorOS16"
python patcher.py --originos "E:\OriginOS移植" --coloros "E:\本机官方ColorOS16" --sensor-mode preserve --cil-mode rules-only
python patcher.py --restore "E:\OriginOS移植_MIO_Backups\某次时间戳"
```

通过此前采集文件生成手工覆盖包的脚本与 GUI 调用相同后端：

```powershell
python build_capture_bundle.py --capture "E:\OriginOS采集原件" --donor "E:\ColorOS采集原件" --workspace "E:\构建输出" --output "E:\补丁.zip"
```

此脚本默认保留传感器链路、只输出 CIL 规则，ZIP 是用于解包内置的覆盖文件，不是 Magisk 安装包。
采集样本缺少真实打包 config，因此生成的测试 config 不会作为完整 ROM config 分发。

## 测试与贡献

```powershell
python -m unittest test_patcher -v
```

公开 CI 执行模拟解包、事务恢复、CIL 合并和动态定位的独立测试。
完整 ROM 原件不上传到仓库，原生仿真、真实 CIL 与设备相关测试在本地材料上执行。
离线测试不能替代各机型实际启动、HDR白点、待机和户外 HBM 测试。
增加新适配时必须分析目标的调用结构与成员读写，再添加可唯一定位的指令模板。

原创工具代码采用 MIT；SELinux 编译器及其依赖保留原许可证，见 [第三方说明](licenses/THIRD_PARTY.txt)。
