# NeoConverter

把 Fabric 模组一键转换为 NeoFabric 可加载版本的 Windows GUI 工具。图一乐归图一乐，原 jar 会替你保管好。

## 功能

- 拖入一个或多个 jar / 文件夹，或者使用“选择文件”“选择文件夹”按钮。
- 点击“开始转换”，后台逐个处理，进度条和滚动日志实时更新，完成后汇总成功数、跳过数及原因。
- 读取 jar **根目录**的 fabric.mod.json，仅在 JSON 顶层添加或覆盖布尔字段 "neofabric": true；其他 JSON 原文保留，包括顺序、空白、数字写法、Unicode 转义和已有字段。
- 删除 META-INF/ 及其子目录中的 .SF、.RSA、.DSA 签名文件（不区分大小写），其余文件内容、归档注释和条目属性保留。
- 输出到原文件所在目录：example.jar → example_neofabric.jar。重名时自动追加 _1、_2……，独占创建 / 原子发布，**绝不覆盖原 jar 或已有输出**。
- 支持中文、空格、大写 .JAR 扩展名，以及对已转换模组再次转换。
- 默认只扫描所选文件夹的第一层；选择前勾选“包含子文件夹”可递归扫描。队列会先快照、去重，不会在同一批次反复扫描新生成的文件。
- 运行仅使用 Python 标准库（tkinter、zipfile、json、ctypes 等）。Windows 原生拖放无需 tkinterdnd2。

## 使用

下载 [v1.0.0 Release](https://github.com/neofabric-mc/NeoConverter/releases/tag/v1.0.0) 中的 NeoConverter.exe，双击启动，不需要安装 Python。

1. 拖入 jar / 文件夹，或点击选择按钮添加文件。
2. 确认待转换列表后，点击“开始转换”。
3. 查看汇总与日志，在原 jar 同目录找到后缀为 _neofabric 的新文件。
4. 使用转换后的文件。原文件不会被删除。

已有输出再次转换时，会生成新的文件，例如 example_neofabric_neofabric.jar。再次转换同一个原始输入则通过序号避让已有输出。

这个工具只补 NeoFabric 门禁标记、移除失效签名，**不修复模组本身的 Minecraft 版本、依赖、Mixin 或代码兼容性**。请使用匹配游戏版本的模组。嵌套的 jar 不递归修改；如果它们也是需要声明标记的独立模组，仍须单独处理。原作者的许可证、版权声明和其他文件都会保留。

## 报错说明

| 日志 | 含义与处理 |
| --- | --- |
| 非 Fabric 模组 | 根目录没有 fabric.mod.json，跳过，不生成输出。 |
| JSON 损坏 | 非 UTF-8、JSON 不合法、根节点不是对象、重复的元数据条目或元数据超过 8 MiB；使用原作者发布的完整 jar。 |
| jar 损坏 | ZIP 结构或条目 CRC 校验失败；重新下载原文件。 |
| 权限不足或文件被占用 | 输入不可读或输出目录不可写；关闭占用文件的软件，或把 jar 放到可写目录。 |
| 磁盘空间不足 | 写入 / 刷盘失败；释放空间后重试，程序会尝试清理临时文件。 |
| 文件不存在或路径不可用 | 队列中的文件被移动、删除或所在驱动器已断开。 |
| 拖放不可用 | 使用选择按钮。Windows 不允许低权限资源管理器向高权限窗口拖文件，通常无需以管理员身份运行本工具。 |

某个 jar 失败不会中断其他文件。未完成的临时文件使用 .neoconverter-*.tmp 名称；常规异常时会自动清理，清理失败会在原因中注明。断电或强制结束进程后，可在确认程序关闭后手动检查这些临时文件。整个过程不把 jar 解压到磁盘目录。

## 从源码运行

需要带 tkinter 的 Python 3.10+（本次使用 Windows x64、Python 3.14 构建）。

~~~powershell
python NeoConverter.py
~~~

requirements.txt 只含“仅标准库”的说明，没有第三方运行依赖。

## 构建 Windows exe

在 Windows 上执行：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name NeoConverter --version-file version_info.txt NeoConverter.py
~~~

也可以运行 .\scripts\build.ps1（只在项目内创建虚拟环境、缓存、临时文件和构建产物）。生成 dist/NeoConverter.exe。PyInstaller 仅为构建依赖，固定版本见 requirements-build.txt。GitHub Actions 在 Windows 上运行同样的测试和打包，并上传 exe 产物。

自动验收可使用无界面批处理入口：

~~~powershell
.\dist\NeoConverter.exe --batch "E:\mods\example.jar" --report "E:\mods\result.json"
~~~

## 实际验证

测试覆盖签名移除、其他文件与 JSON 原文保留、防覆盖、中文路径、重复转换、ZIP CRC 错误、磁盘满、权限错误、GUI 后台处理和 Windows 原生 WM_DROPFILES 多路径消息。真实模组和 NeoFabric 加载验证的版本、方法及边界见 [VALIDATION.md](VALIDATION.md)。

验收下载的模组、Mojang 游戏文件和 Loader 仅存放在本地 .validation/，不会随源码或 Release 再分发。

## 许可证

本工具采用 [MIT License](LICENSE)。转换不改变原模组的许可证和版权归属。
