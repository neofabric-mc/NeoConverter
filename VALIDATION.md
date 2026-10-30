# NeoConverter v1.0.0 验收记录

## 环境与范围

- Windows 11 x64、Python 3.14.7、Tcl/Tk 9.0.4、PyInstaller 6.22.3。
- **33 项测试通过，0 失败、0 错误、0 跳过**：28 项核心测试 + 5 项 Windows GUI / 原生拖放测试。
- 原生拖放使用真实 WM_DROPFILES 消息验证多个中文及空格路径；GUI 文件/文件夹选择、后台批处理、滚动日志、进度、汇总和最小窗口尺寸均已验证。
- 测试只在 NeoConverter 项目内生成缓存和验收数据，现有 NeoFabric 和 Installer 项目没有改动。

## 最终 exe 验证

- 文件：dist/NeoConverter.exe
- 大小：13640831 字节
- PE 子系统：Windows GUI（无控制台）。文件版本与产品版本均为 1.0.0。
- 最终 exe 独立启动了打包的 Tk 窗口，原生拖放已安装，开始按钮和底部说明均可见。
- 使用最终 exe 对带 3 种签名文件的中文路径测试 jar 转换：3 个签名条目被删除，其他数据和许可证保留，原文件 SHA-256 未改变；非 Fabric jar 正确跳过。
- 权限不足、磁盘满、发布失败通过故障注入验证；损坏 ZIP 和 CRC 使用实际损坏数据验证。无需填满真实磁盘或修改系统权限。

SHA-256：

~~~text
80e93a1043551bc2b9c0098fac5b491b8e90f42bb435d5f77388e1a0ffa38060
~~~

## 真实 Fabric 模组 + 真实 NeoFabric

输入为 [Lithium 0.15.4+mc1.21.1（Modrinth 版本 N08Z8wog）](https://modrinth.com/mod/lithium/version/N08Z8wog)，由上游下载并按其 SHA-512 校验。真实模组没有签名文件；签名剔除由上面的专门夹具和单元测试覆盖，没有把伪签名当作有效加密签名。

原始 jar 的 SHA-512：

~~~text
182064b00e6315e2255b857eaab8eb759e6b042ebd4cc8b855ff0d93f875a5a7188fac49f878d7b29d4ef7e6b6341190ad7f6f6f39f4a6d2c62003468b08e4c6
~~~

使用最终发布的 exe 转换后，顶层 neofabric 为布尔 true，其他 JSON 字段与原文保留；其余 **847 个归档条目逐字节一致**，没有剩余签名文件，原始 jar 校验值未变。

验收使用 [NeoFabric Loader v1.2.0](https://github.com/neofabric-mc/NeoFabric/releases/tag/v1.2.0)、Mojang 原版 Minecraft 1.21.1 服务端、官方 Intermediary 映射与 Loader 声明的运行库，在 Java 21 的两个独立 JVM 中运行真实 Knot 初始化流程：

1. 原版 Lithium：被 NeoFabric 门禁拒绝，isModLoaded("lithium") 为 false。
2. 转换后的 Lithium：完成游戏识别、模组发现、依赖解析和 Mixin / 类加载器初始化，isModLoaded("lithium") 为 true，入口类由真实 Knot 游戏类加载器成功定义。
3. 真实 ASM 9.10.1 库 jar：正确判定为“非 Fabric 模组”并跳过。

实际探针输出：

~~~text
NEOCONVERTER_REJECTED_ORIGINAL lithium=false
NEOCONVERTER_ACCEPTED lithium=0.15.4+mc1.21.1 entrypoint=net.caffeinemc.mods.lithium.fabric.LithiumFabricMod namespace=intermediary
~~~

这证明了转换产物可被真实 NeoFabric 加载器接收和加载，**未启动完整游戏/世界，也未调用模组游戏生命周期或验证实际游玩**；不是对全部 Fabric 模组、全部游戏版本或所有嵌套依赖的兼容保证。

## 复现

需要 Java 21（java / javac 在 PATH 中）和联网下载公开验收资源。项目根目录执行：

~~~powershell
.\scripts\build.ps1
.\.venv\Scripts\python.exe scripts/prepare_acceptance.py
.\.venv\Scripts\python.exe scripts/validate_real_mod.py --executable dist/NeoConverter.exe
~~~

验收 jar、Minecraft、依赖库、日志和原始 JSON 报告保存在 .validation/，不提交仓库或打进 Release。prepare_acceptance.py 固定上面已验证的 Lithium 版本以便复现。运行软件本身不需要 Java、联网或第三方 Python 运行依赖。
