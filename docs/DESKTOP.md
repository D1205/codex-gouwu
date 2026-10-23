# codex的构物 Windows 桌面程序

桌面版是 PyInstaller 打包的 Windows GUI 可执行程序，包含 Python、业务后端、生产版前端、规则锁、锁定的机械设计技能文件和 SolidWorks COM 辅助模块。启动时在后台运行本地服务并打开默认浏览器；运行不需要源码虚拟环境、Node.js 或 npm。

## 本机启动

- 程序：构建目录下的 `dist\codex的构物\codex的构物.exe`，分发时保留整个同名文件夹。
- 桌面快捷方式：Windows 当前用户实际桌面目录中的 `codex的构物.lnk`。创建脚本通过 Windows 获取桌面位置，支持桌面重定向。
- 本地地址：`http://127.0.0.1:8777`，仅监听回环地址。
- 已有健康的同一应用服务时，重复启动会打开它；启动互斥锁避免同时启动多个桌面服务。启动程序不会启动 SolidWorks。

关闭浏览器后，本地服务继续在后台运行。需要退出后台进程时，可在 Windows 任务管理器中结束 `codex的构物.exe`，应先等正在进行的模型请求或 CAD 操作结束。再次双击桌面快捷方式即可重新打开。启动失败会显示消息框，详情保存在 `%LOCALAPPDATA%\CodexGouwu\desktop.log`。

## 数据与配置

新构建的桌面版默认使用 `%LOCALAPPDATA%\CodexGouwu\data`，包内不含构建者的数据路径。当前工作区已有 `results\integration` 时，快捷方式安装脚本会为本机快捷方式设置 `--store` 指向该原始目录，继续读取旧记录。现有记录中的 CAD、预览和证据使用绝对路径，所以保留原有数据位置，打包时不复制设计结果、上传图片、密钥或凭据。**请保留该原始目录和其中的成果文件。** 程序的依赖随整个 `dist\codex的构物` 文件夹分发；它并非包含旧设计数据的单文件安装包。

模型配置和 Windows DPAPI 加密密钥保存在 `%LOCALAPPDATA%\CodexGouwu`，不在程序包内。SolidWorks 类型库生成缓存也保存在该目录的 `gen_py` 子目录。桌面服务进程信息保存在 `desktop-8777.json`，其中仅含 PID、程序路径、本地地址和数据目录。

可使用 `--store D:\YourData` 指定其他数据目录，用 `--port 8877` 指定其他回环端口，或用 `--no-browser` 仅启动后台服务。迁移历史记录到其他目录时，需要处理记录中的绝对成果路径，单纯移动文件夹不会更新这些记录。

## 外部依赖

CAD 建模需要本机已安装并手动启动的 SolidWorks。程序只连接现有实例，并沿用文档所有权与资源占用检查；不会另开 CAD 实例。交付资料和规则锁随包提供，SolidWorks 本体与许可证不随包提供。

使用 API 模式时，在设置中填写自己的服务地址、模型与密钥。Codex CLI 模式仍需要本机独立安装并登录 Codex CLI；用户登录凭据不会打包。

## 重建与诊断

在项目目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1
```

首次从源码安装先运行 `scripts/setup.ps1`，完整步骤见 [BUILD.md](BUILD.md)。构建优先使用本项目 `.venv` 的 Python；仅为兼容旧工作区，在其不存在时尝试相邻 `solidworks-automation-skill\.venv`。前端构建需要 Node.js/npm。`-SkipUIBuild` 复用刚生成的 `ui/dist`，`-NoShortcut` 跳过快捷方式创建。固定依赖随本仓库 `vendor/` 提供，并在构建前校验哈希。打包资源采用明确白名单，不收录 `results`、源码 `.local` 或用户配置目录。

只读检查打包资源、Python/COM 依赖与两个前置检查子进程：

```powershell
& '.\dist\codex的构物\codex的构物.exe' --self-check "$env:TEMP\codex-gouwu-self-check.json"
```

检查结果写入指定 JSON；不连接、打开、创建或修改 CAD 文档。GUI 程序没有控制台，前置检查通过临时 JSON 报告回传结果。辅助子进程仅允许两个固定的只读前置检查命令。第三方许可与来源见包内 `_internal\resources\mechanical-design-app\THIRD_PARTY.md`、`ACKNOWLEDGEMENTS.md`、`vendor` 内原始 `LICENSE`/`NOTICE`、`vendor\SOURCES.json` 与 `_internal\resources\licenses`。
