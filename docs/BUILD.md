# 从源码安装与构建

本仓库可以单独 clone 到任意目录，不需要相邻的 SolidWorks 项目或它们的虚拟环境。运行所需的固定技能文件与 Python 辅助模块已按白名单放入 `vendor/`，来源、上游提交、复制清单及 SHA-256 见 [SOURCES.json](../vendor/SOURCES.json)。致谢与许可见 [ACKNOWLEDGEMENTS.md](../ACKNOWLEDGEMENTS.md) 和 [THIRD_PARTY.md](../THIRD_PARTY.md)。

## 环境

- Windows 10/11，64 位 Python 3.11 以上；建议使用 Python 3.12。默认安装脚本优先使用 `py -3.12`，也可指定解释器。
- Node.js 22.12 以上及 npm；当前 Vite 的最低要求为 Node 20.19 或 22.12。
- 真正建模时需要本机已安装、获许可且手动启动的 SolidWorks。安装依赖、构建 UI、打包程序和下面的资源检查不需要启动 CAD。
- API 模式在程序设置中填写自己的服务信息与密钥；Codex CLI 模式需要另行安装并登录 CLI。

## 新建本地开发环境

在 clone 得到的仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-ui.ps1
```

`setup.ps1` 创建本仓库的 `.venv`，通过 `pip install --editable '.[cad,desktop]'` 安装依赖，再执行 `npm ci` 和生产版 UI 构建。它不升级共享 Python 环境，也不安装/启动 SolidWorks。已存在 `.venv` 时复用它；Python 包由 `pyproject.toml` 管理，前端依赖由 `ui/package-lock.json` 锁定。Python 依赖包含版本范围，因此不声明不同日期安装得到完全相同的环境。

指定 Python，或暂时跳过前端：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python C:\Python312\python.exe -SkipUI
```

`-SkipUI` 后需要自行在 `ui/` 执行 `npm.cmd ci`、`npm.cmd run build`。源码应使用上述 editable 安装，以便运行时直接访问本仓库的 `vendor`、`rules` 和 UI；普通 wheel 不是本项目的桌面分发格式。

启动脚本优先本仓库 `.venv/Scripts/python.exe`。为兼容既有工作区，仅在本仓库环境不存在时，才尝试旧的相邻 `../solidworks-automation-skill/.venv`。新 clone 不需要这个兼容目录。前端开发入口为 `cd ui; npm.cmd run dev`，后台 API 默认监听 `127.0.0.1:8777`。

## 构建 Windows 桌面版

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-desktop.ps1
```

构建先验证固定资源 SHA，再构建 UI，最后由 PyInstaller 生成 `dist/codex的构物/codex的构物.exe`，并创建当前用户桌面快捷方式。若刚完成 UI 构建可加 `-SkipUIBuild`；不创建快捷方式可加 `-NoShortcut`。

发布时压缩并分发整个 `dist/codex的构物/` 文件夹，保留其中 `_internal/`；单独复制 exe 无法运行。目标机器运行桌面版不需要 Python 或 Node.js。包内有业务代码、生产前端、规则锁、固定技能/辅助模块、图标与第三方许可。`results/`、`.local/`、`.venv/`、用户配置和密钥不在资源白名单中。`desktop-defaults.json` 仅记录 `store_mode: local_appdata`，不会包含构建者的数据目录。

## 数据与既有工作区

源码默认数据目录仍为本仓库 `results/integration`。新构建的桌面版默认使用 `%LOCALAPPDATA%\CodexGouwu\data`；可通过 `--store D:\YourData` 指定其他位置。

若构建时本仓库已有 `results/integration`，快捷方式脚本会把该本机目录写成快捷方式的 `--store` 参数，让当前电脑继续读取原记录。此参数只写入本机 `.lnk`，不写进源码或分发程序。也可手动指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-desktop-shortcut.ps1 -Store D:\YourData
```

既有记录的成果文件可能使用绝对路径，请保留原始数据及成果位置。复制程序不会搬迁旧数据或重写历史记录。重新构建前应自行等待当前任务结束；构建脚本不会关闭正在运行的 8777 服务或 CAD。

## 低成本核验与固定资源更新

```powershell
.\.venv\Scripts\python.exe scripts/verify-vendor.py
```

该检查只读验证复制清单、上游 Git blob 与换行记录、原规则锁和 9 个锁定技能哈希，不访问模型服务，也不连接 CAD。`vendor/**` 与 `rules/lock.json` 通过 `.gitattributes` 保留原始字节，避免 Git 自动换行转换破坏 SHA。

桌面版诊断入口见 [DESKTOP.md](DESKTOP.md)。修改源码后只验证改动与直接受影响部分；已通过且无新改动或失败时，不重复运行无关测试。

不要直接编辑 `vendor` 文件。升级来源时应核对精确上游提交及许可，更新白名单和 `SOURCES.json` 的复制/上游哈希；技能变更必须经过显式规则迁移，不能仅重算 `rules/lock.json` 来绕过旧规则锁。
