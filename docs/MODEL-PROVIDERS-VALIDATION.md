# 多模型设置与桌面版验证

本次范围：需求整理的模型提供方、密钥保存、设置界面和 Windows 桌面封装。既有 CAD 发布版本保持不变；没有为界面或 API 设置重新创建 CAD。

## 已验证的行为

- DeepSeek 为默认配置，模型为 `deepseek-flash`。实际最小文本 JSON 请求成功；实际带 PNG 参考图的完整法兰需求返回 v2 草稿，经过同一套本地规则后达到 `ready`，包含 7 个已确认参数及 3 个增减料/阵列特征。
- 设置页可保存 Codex CLI、DeepSeek 和自定义兼容 API；可修改地址、模型与图片能力。浏览器验证了切换、空密钥保留、临时配置密钥删除、保存后密码框清空、关闭焦点恢复及窄屏宽度。
- 密钥通过当前 Windows 用户的 DPAPI 加密，设置文件限制访问并原子替换。公开配置、模型证据和浏览器持久存储没有密钥；未配置或视觉关闭时不会宣称实际调用过模型。不同提供方失败不会自动切换。
- 单次需求排队前固定配置快照；提交后修改设置不会改变该请求。所有提供方沿用技能指纹、严格输出契约、来源与尺寸确认、本地几何校验。

首次带图测试暴露出方向文字的问题：模型正确输出“第一孔位于X正方向”对应 0°，本地来源识别却只支持 `+X` 和“正X”等写法，导致多余追问。已补齐“X正方向”“X轴正方向”及相应 Y/负方向的等价识别。新增正反角度检查通过；只重跑受影响的真实带图调用链，得到就绪任务。保留原失败记录，未将它改写为成功。

## 检查与证据

| 范围 | 本次结果 |
| --- | --- |
| 模型设置/传输与整合 | 初次 20 个测试通过，传输安全补充后 8 个相关测试通过；新增缺密钥与方向回归后 7 个整合测试通过。重叠检查不相加。 |
| 原有模型与图片适配 | 40 个相关测试通过 |
| 图片存储/HTTP 入口 | 13 个相关测试通过 |
| React/TypeScript 生产构建 | 通过 |
| 设置页及真实模型首次检查 | 首次报告前 16 项通过，第 17 项发现方向词问题 |
| 修复后的真实模型及界面 | 12 项通过，未执行 CAD |
| 最终冻结程序资源与依赖 | 12 项通过，包含两个只读辅助子进程 |
| 从实际桌面快捷方式启动的程序 | 后台进程确认为 `codex的构物.exe`，8777 健康接口正常 |
| 打包程序的真实 DeepSeek 连接 | 加密密钥可解密，实际文字 JSON 请求成功 |
| 打包程序的界面和原模型 | 6 项通过，原生服务读取已发布法兰 r1，STL 大小与 SHA-256 一致 |
| 程序包与配置密钥检查 | 176 个打包文件中无提供的明文密钥，配置文件中也无明文密钥 |

浏览器及模型记录位于 `results/model-settings-verification/`：

- `report.json`、`live-model-result.json`：首次运行与问题原始证据。
- `ready-report.json`、`ready-model-result.json`：修复后的真实 DeepSeek 图文调用与界面检查。
- `settings-desktop.png`、`settings-mobile.png`、`deepseek-ready-desktop.png`：设置与需求结果截图，密码输入为空。
- `package-report.json`、`packaged-connection-result.json`、`packaged-ui-report.json`：最终可执行文件指纹、密钥检查、冻结程序实际连接及界面结果；截图为 `packaged-program.png`。最终资源自检位于 `.local/desktop-self-check-final.json`。
- 两次实际带图调用的原始模型输出分别保存在对应结果的 `evidence_dir`，未使用预录回复代替模型调用。首次连接反馈的界面检查复用了当次已成功的连接 operation，没有再次发起付费测试请求。

桌面资源、运行方式与冻结程序检查见 [桌面程序](DESKTOP.md)。连接测试只验证文字 JSON；自定义服务的图片支持仍取决于实际模型和服务端能力。本次 DeepSeek 图片请求确实发送并接收了规范化 PNG；不据此推断所有兼容 API 均支持图像。

实现依据来自 [DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)、[图片输入](https://api-docs.deepseek.com/guides/vision/)、[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/) 与[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。其他提供方使用兼容接口，仍需通过各自连接和真实需求验证。
