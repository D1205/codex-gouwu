# 复用边界与许可证

本程序通过固定资源快照和本地模块适配复用下列内容。来源仓库、固定提交及逐文件记录见 [vendor/SOURCES.json](vendor/SOURCES.json)，作者及项目致谢见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。

## 相关项目与实际复用

| 来源 | 复用内容 | 许可证与随附声明 |
| --- | --- | --- |
| 本地 `mechanical-design-sop` | `vendor/mechanical-design-sop/` 中由 `rules/lock.json` 锁定的 SOP 原文及引用资料；运行时读取 | 本地来源没有独立 LICENSE、Git remote 或公开作者信息；未将它标注为第三方 MIT 项目。内容身份由规则锁记录。 |
| [kbedrich/solidworks-agent](https://github.com/kbedrich/solidworks-agent/tree/3cd587d533ee0f333d453da818e1219dbba9e8c5) | `vendor/solidworks-agent/skills/solidworks/scripts/` 中的 9 个原始辅助模块：`sw_preflight`、`sw_resource_guard`、`sw_connect`、`sw_documents`、`sw_inspect`、`sw_part`、`sw_review`、`sw_runtime`、`sw_evidence`；用于原生 CAD 操作、测量、导出、会话及文档归属保护 | MIT；原文 [LICENSE](vendor/solidworks-agent/LICENSE) 与 [NOTICE](vendor/solidworks-agent/NOTICE) 随附。LICENSE 保留 `SolidWorks Automation Skill Contributors` 与 `Kyle Bedrich` 的两条版权声明。 |
| [wzyn20051216/solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill/tree/a3ddc5694161299b50b9e9f688fcd6f0bf815da2) | 直接加载 `vendor/solidworks-automation-skill/apps/desktop/cad_workbench/agent_providers.py`，用于 Agent CLI 发现；其 `apps/workbench-ui` 的队列和预览接口作为设计参考，未收录原 UI | MIT；原文 [LICENSE](vendor/solidworks-automation-skill/LICENSE) 随附，保留 `SolidWorks Automation Skill Contributors` 版权声明。 |
| [hjbaard/SolidWorks-MCP](https://github.com/hjbaard/SolidWorks-MCP/tree/9ea3c864950569f9b5544bc0aef981eda4ff639e) | 建模、数值回读及固定工具接口的方案参考；当前运行和打包清单未引用该 server 或其源码 | 上游为 [MIT](https://github.com/hjbaard/SolidWorks-MCP/blob/9ea3c864950569f9b5544bc0aef981eda4ff639e/LICENSE)，版权人为 Henk Jan Baard；未作为随包代码分发。 |

SolidWorks Agent 的 NOTICE 说明其派生自 [WilliamDee-Huang/solidworks-agentic-automation](https://github.com/WilliamDee-Huang/solidworks-agentic-automation)，该项目又派生自 SolidWorks Automation Skill；这条来源链随原 NOTICE 保留。

分发上述 MIT 代码的副本或实质性部分时，须保留其版权声明和许可声明。这里随附的原文 LICENSE 同时保留了免责条款；致谢链接不能替代许可原文。机械 SOP 的来源情况单独记录，不从相邻代码仓库的许可证推导其许可。

## 其他主要依赖

以下列出程序和开发流程中的主要依赖；完整传递依赖以 Python 安装元数据和 `ui/package-lock.json` 为准。

| 来源 | 复用内容 | 许可证 |
| --- | --- | --- |
| Pydantic | 单一契约类型定义、严格校验、Schema 生成 | MIT |
| Shapely 2.1.2 / GEOS | v2 特征的独立分层平面 CSG、体积与包络预测；不作为 SolidWorks 模型 | Shapely BSD-3-Clause；wheel 内 GEOS 保留其 LGPL 许可 |
| React / React DOM | 三列工作台、真实状态和审阅交互 | MIT |
| Three.js | 查看真实 CAD 导出的网格与语义标记 | MIT |
| Vite | 本机开发服务与前端构建 | MIT |
| TypeScript | 前端类型检查 | Apache-2.0 |
| Playwright | 浏览器验收脚本；复用工作区已有依赖和本机 Chrome | Apache-2.0 |

桌面打包脚本收录上述两个上游代码项目的原 LICENSE、SolidWorks Agent 的 NOTICE、来源与致谢文档，并从安装元数据及前端依赖目录收集第三方许可证。二进制包内的许可证文件位于 `_internal/resources/licenses` 与 `_internal/resources/mechanical-design-app/vendor/`；实际版本随各次构建记录。

机械 SOP 和执行库分别固定内容。模型只生成候选任务，规则校验与 CAD 数值回读由程序执行；未运行的能力不纳入验收。

SolidWorks 本体及其许可证独立于上述开源项目。本程序连接本机已安装的 SolidWorks，桌面包不包含 SolidWorks 本体。
