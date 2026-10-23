<img src="ui/public/brand/logo.svg" alt="codex的构物标志" width="64" height="64">

# codex的构物

用日常语言提出需求，整理成有来源、有版本的工程任务，确认后在本机 SolidWorks 生成模型并检查。当前已提供 React 三维工作台，需求规则沿用锁定版本的 `mechanical-design-sop`，原生 CAD 操作复用 `solidworks-agent`。

## 启动工作台

在本项目目录双击 **`启动设计台.cmd`**，浏览器会打开 **http://127.0.0.1:8777**。关闭时双击 **`停止设计台.cmd`**；停止脚本只终止本启动器记录并核对身份的服务进程，保留 SolidWorks。

Windows 已打包程序可从 [v0.1.0 版本页](https://github.com/D1205/codex-gouwu/releases/tag/v0.1.0) 下载，解压后保留整个程序文件夹，双击“codex的构物.exe”打开。源码开发、独立安装与构建见 [BUILD.md](docs/BUILD.md)，桌面版数据位置见 [DESKTOP.md](docs/DESKTOP.md)。

点击界面右上角“模型设置”，可切换 DeepSeek、Codex CLI，或添加支持 Chat Completions 和 JSON 输出的兼容 API。API 地址、模型名称、图片能力与密钥均可修改；空白密钥保留已有配置。密钥由后端使用 Windows DPAPI 加密保存，设置页只显示是否已配置，不存入浏览器或打包文件。Codex CLI 使用原有本机登录。不同模型共用相同工程契约和规则，不会跳过尺寸确认或 CAD 审阅。配置及测试接口见 [HTTP API](docs/API-v1.md)。

首次从源码安装，在本目录运行（需 Python、Node.js）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
.\启动设计台.cmd
```

`scripts/start-ui.ps1` 在隐藏进程中启动 Python 服务，日志和进程标记位于 `.local/`；已有同应用服务时直接打开页面。也可以在本目录手动启动：

```powershell
$taskPython = './.venv/Scripts/python.exe'
& $taskPython -m mechanical_app.server --port 8777 --store results/integration
```

手动启动的服务在该终端按 Ctrl+C 退出。数据默认保存在 `results/integration`，重启后保留已发布版本和待审阅任务。

源码包含运行所需的最小 `vendor/` 快照，不需要另外克隆四个项目。首次安装不含任何个人 API 密钥、参考图或 CAD 成果；请在设置中配置自己的模型。发布排除规则见 [SECURITY.md](SECURITY.md)，更新内容见 [CHANGELOG.md](CHANGELOG.md)。文档中的历史验证记录说明开发时的本机测试，原始 `results/` 和日志保留在本机，不随仓库发布。

开发 UI 时运行 `ui` 目录中的 `npm.cmd run dev`，地址为 `http://127.0.0.1:5175`，`/api` 代理到 `8777`。需要换后端时为该进程设置 `MECHANICAL_API_TARGET`。默认使用构建产物时只需保留 `8777` 服务。

## 使用流程与范围

对话区支持连续交流：Enter 发送，Shift + Enter 换行。可通过“＋”选择参考图，也可拖入或粘贴图片；支持 PNG/JPEG/WebP，单张最大 8 MiB，每次最多 6 张。发送前可查看或移除附件，补充需求时继续使用当前参考图。图中标注与比例会作为待确认信息，准确尺寸仍需用文字补充或确认。处理规则见 [工程参考图](docs/REFERENCE-IMAGES-v1.md)。

1. 选择“新建零件”并直接描述用途、尺寸与单位，不限制零件名称或类别。法兰盘、阶梯轴、套筒、垫圈、圆盘和矩形块等入口只是填写示例。缺少关键规格时，需求卡展示本次草稿和追问；补充回答后重新整理。新建澄清会累计原始描述，不把未完成草稿当作已发布基线。
2. 核对需求卡中的动态参数、来源、确认状态、本次变更与中文建模步骤，点击“确认需求并生成”。长度可按 mm/cm/m 输入，角度与数量分别显示为 ° 和个。未就绪的任务无法生成。
3. 查看实际 STL 三维模型、几何检查和原生 CAD 四视图。数值检查完成后，带预览的任务进入“待审阅”，已发布模型保持原版本。
4. 实际看图后填写审阅人和观察记录，选择发布或退回。只有发布成功才推进当前基线；刷新会恢复尚未审阅的候选模型。
5. 修改时选择“修改当前”，或点击已有模型的语义标记。提交时核对当前修订与指纹，旧文件继续保留。

新的特征任务不按零件名称套类别白名单，而是把描述整理为参数与特征组合：当前可表达 XY 平面的圆形、矩形、多边形截面，沿 Z 方向增料或切除，以及圆周或直线重复排列。零件名称开放与几何能力是两回事；无法表达的结构会保留具体缺项或限制供确认，不会自动换成另一种零件。

原有三类模板继续兼容，以下是旧任务定义，不是可输入零件的类别限制：

| 类型 | 必需尺寸 | 支持结构 |
| --- | --- | --- |
| 四孔底板 `plate` | 长、宽、厚、孔径、孔中心边距 | 矩形板与四个等径贯穿孔；点孔调整孔径会同步四孔 |
| L 形支架 `bracket` | 两腿外部长和高、沿 Z 拉伸的宽、统一厚度 | 无附加孔槽的等厚 L 截面 |
| 无盖盒体 `box` | 外部长、宽、高、侧壁/底厚 | 等厚平底与四壁；不含盖子、卡扣、开口和固定柱 |

需求卡与已生成模型分开显示。本次需求未形成可执行任务时，右侧只展示本次草稿、参数和追问，不显示上一零件的尺寸；中间可保留旧模型，并明确标为“上一已发布模型”。本次生成后才能显示新模型的检查与文件。

当前范围固定为 **`geometry_review` 几何评审**。保存重开、数值回读和 STEP 检查不能代替制造工艺、承载强度、装配路径、运动或实机验收。修改按已发布任务重建新修订，尚不支持任意导入零件、任意面/边编辑。预览为 Z-up、毫米单位；稳定参数 ID 与修订指纹用于选择，网格 UUID 不作为 CAD 身份。

真实建模要求本机 SolidWorks 已运行且当前会话无打开文档。这是复用库的文档归属保护：执行器只 attach，不自行启动第二实例，不改动已有用户文档。

## 规则与接口

- `RequirementDraft` 保存原话、来源、未知项、冲突与追问。
- `EngineeringTask` 是技能使用的任务书，包含目标、参数来源、硬约束、修订基线与交付要求；v2 增加有明确结构的建模特征，v1 三模板仍保留兼容。
- `CADPlan` 由本地规则编译，统一长度单位，保留角度和数量，附语义指纹；执行协议不接收任意代码。
- [v2 特征工程规则](docs/RULES-v2.md)、[v1 兼容规则](docs/RULES-v1.md) 与 `schemas/` 定义格式和就绪门槛；`rules/lock.json` 锁定技能及引用文件，变化后需显式迁移。
- [本机 HTTP API](docs/API-v1.md) 说明 UI 传输、任务轮询、候选审阅及资产读取。

HTTP 服务只绑定 `127.0.0.1`，调用同一套规则、模型适配与 CAD 服务；桌面程序在后台运行服务并打开浏览器工作台。[UI 设计稿](docs/ui-design.svg) 是可导入 Penpot 的 SVG 布局示意，未在 Penpot 中创建项目。

Codex 子进程使用现有登录，忽略用户配置以隔离外部工具；固定需求技能随提示输入，模型不执行 CAD 或终端操作。已有显式代理环境优先，否则仅对子进程继承 Windows 系统代理，不改写系统或用户配置。失败、超时与原始输出保留，不能用预录回复替代真实模型调用。

## 技术验证记录

多模型设置、DeepSeek 实际图文请求、密钥加密和界面检查见 [本次验证记录](docs/MODEL-PROVIDERS-VALIDATION.md)；桌面程序及资源检查见 [桌面程序](docs/DESKTOP.md)。

v2 开放特征建模的最新结论见 [开放建模验证报告](docs/OPEN-MODELING-VALIDATION.md)：真实语言已覆盖裸法兰缺项追问和完整法兰三特征计划；真实 CAD 覆盖法兰、阶梯轴、六角隔套、线性孔阵安装块。完整法兰的真实语言结果已复用到界面，完成实际 CAD 执行、看图和发布；浏览器回放不计作新模型请求。

新增依赖 Shapely 2.1.2 已安装到本机复用的 Python 环境；其他环境可在项目目录用该 Python 执行 `-m pip install -e .` 安装 `pyproject.toml` 所列依赖。独立 CSG 仅用于核对几何预期，交付仍由本机 SolidWorks 建立。

以下是保留的 v1 基线验证记录：

真实模型验证已经覆盖等价 mm/cm 表达、关键规格缺项，以及在当前版本上将四孔孔径改为 6 mm 并保留其他尺寸和来源。真实 CAD 验证覆盖三族、保存重开、几何与 STEP 回读，以及带基线的修订流程。

浏览器工作流已验证“盒体缺墙厚 → 补充 3 mm → 生成真实盒体 CAD → 待审阅 → 刷新恢复 → 实际看原生图后明确提交审阅 → 发布”。另用已发布底板验证了三维孔标记点击选择统一孔径及空白点击取消；这次只读验证没有重新建模。人工看图与发布是独立步骤，不能由“模型已生成”推断“已审阅发布”。

完整结论与边界见 [技术验证报告](docs/TECHNICAL-VALIDATION.md)。对应证据位于 `results/agent-verification-proxy/`、`results/agent-modification/`、`results/cad-sixth/`、`results/integration/` 和 `results/ui-verification/`。`tests/` 的故障注入用于验证程序边界，不能替代真实模型和 CAD 证据。仅验证本次改动及直接受影响部分，相关检查通过后不重复扩展检测。

命令行仍可直接调用相同业务层：

```powershell
& $taskPython -m mechanical_app.cli --help
& $taskPython -m mechanical_app.cli validate cases/positive/plate-mm.json --output plan.json
```

## 实现位置

| 位置 | 职责 |
| --- | --- |
| `ui/` | React、TypeScript、Vite 与 Three.js 工作台 |
| `mechanical_app/server.py` | 本机 HTTP、异步操作与资产白名单 |
| `mechanical_app/contracts.py`、`rules.py` | 类型定义、来源/单位/版本门禁、确定性计划 |
| `mechanical_app/feature_contracts.py`、`generic_geometry.py` | v2 特征语言、安全算式、规范单位与独立几何预测 |
| `mechanical_app/agent.py` | 统一需求整理、技能锁和结构化工程门禁 |
| `mechanical_app/model_settings.py`、`model_providers.py` | 提供方配置、Windows 密钥加密和兼容 API 调用 |
| `mechanical_app/cad.py` | SolidWorks 原生辅助库与几何、交换格式回读 |
| `mechanical_app/cad_features.py` | 通用特征的原生建立、草图与起点/深度回读、参数绑定 |
| `mechanical_app/service.py`、`storage.py` | 串行执行、修订、产物指纹与独立审阅 |
| `mechanical_app/cli.py` | 命令行入口 |

没有改写上游 CAD 项目、已安装技能或旧 AR 扫描前端。复用与许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 致谢

本程序使用本地 `mechanical-design-sop` 固定机械设计流程，复用 [wzyn20051216 / SolidWorks Automation Skill](https://github.com/wzyn20051216/solidworks-automation-skill) 的 Agent CLI 发现模块，以及 [Kyle Bedrich / SolidWorks Agent](https://github.com/kbedrich/solidworks-agent) 的原生 CAD 辅助库；[Henk Jan Baard / SolidWorks MCP](https://github.com/hjbaard/SolidWorks-MCP) 为方案调研提供了参考。感谢各项目作者与贡献者。

准确的复用边界、固定版本、传递来源和原始版权声明见 [完整致谢](ACKNOWLEDGEMENTS.md)、[来源记录](vendor/SOURCES.json) 与 [许可证说明](THIRD_PARTY.md)。
