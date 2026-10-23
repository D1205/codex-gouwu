# 致谢与项目来源

感谢下列项目为机械设计流程、SolidWorks 自动化和结果验证提供的工作。本程序对它们的使用方式如下；作者名称以各项目的公开资料及版权声明为准。

| 项目 | 作者或来源 | 在本程序中的使用 |
| --- | --- | --- |
| `mechanical-design-sop` | 本项目使用的本地机械设计 SOP | 读取锁定的 `SKILL.md` 及引用资料，作为需求、基线、验证和交付的流程依据。原文快照位于 `vendor/mechanical-design-sop/`。本地材料没有 Git remote、公开作者信息或独立 LICENSE，因此这里不推定其外部作者或开源许可证。 |
| [SolidWorks Automation Skill](https://github.com/wzyn20051216/solidworks-automation-skill) | [wzyn20051216](https://github.com/wzyn20051216) 及 SolidWorks Automation Skill Contributors | 直接加载 `apps/desktop/cad_workbench/agent_providers.py`，用于本地 Agent CLI 发现；其桌面队列和预览接口也提供了设计参考。原模块快照及 MIT 许可证随程序保留。 |
| [SolidWorks Agent](https://github.com/kbedrich/solidworks-agent) | [Kyle Bedrich / kbedrich](https://github.com/kbedrich)、SolidWorks Automation Skill Contributors 及上游贡献者 | 直接调用 `skills/solidworks/scripts/` 中的原生 CAD 辅助模块，完成会话连接、文档归属保护、草图与特征操作、测量、导出和预览。所需模块快照、MIT 许可证及 NOTICE 随程序保留。 |
| [SolidWorks MCP](https://github.com/hjbaard/SolidWorks-MCP) | [Henk Jan Baard / hjbaard](https://github.com/hjbaard) | SolidWorks 建模、数值回读及固定工具接口的方案调研参考。当前运行代码与桌面打包清单未接入该 MCP server，也未收录其源码。其上游许可证为 MIT。 |

SolidWorks Agent 的 [上游 NOTICE](https://github.com/kbedrich/solidworks-agent/blob/3cd587d533ee0f333d453da818e1219dbba9e8c5/NOTICE) 还明确记录了派生来源：[WilliamDee-Huang/solidworks-agentic-automation](https://github.com/WilliamDee-Huang/solidworks-agentic-automation)，以及更早的 [wzyn20051216/solidworks-automation-skill](https://github.com/wzyn20051216/solidworks-automation-skill)。本程序保留该 [NOTICE](vendor/solidworks-agent/NOTICE) 和包含两条原始版权声明的 [LICENSE](vendor/solidworks-agent/LICENSE)。

本次来源核对采用以下固定版本，公开链接与本地快照记录见 [vendor/SOURCES.json](vendor/SOURCES.json)：

- SolidWorks Automation Skill：[`a3ddc5694161299b50b9e9f688fcd6f0bf815da2`](https://github.com/wzyn20051216/solidworks-automation-skill/tree/a3ddc5694161299b50b9e9f688fcd6f0bf815da2)。
- SolidWorks Agent：[`3cd587d533ee0f333d453da818e1219dbba9e8c5`](https://github.com/kbedrich/solidworks-agent/tree/3cd587d533ee0f333d453da818e1219dbba9e8c5)。
- SolidWorks MCP（参考）：[`9ea3c864950569f9b5544bc0aef981eda4ff639e`](https://github.com/hjbaard/SolidWorks-MCP/tree/9ea3c864950569f9b5544bc0aef981eda4ff639e)。
- 机械设计 SOP：以 [rules/lock.json](rules/lock.json) 中的逐文件 SHA-256 固定内容。

具体复用文件、许可证保留方式及其他主要依赖见 [THIRD_PARTY.md](THIRD_PARTY.md)。这些致谢不表示上游作者参与了本程序开发或认可本程序的验证结论。
