# 接口约定与 v1 兼容基线

本项目是独立的 mechanical-design 产品适配层，不修改上游技能、CAD 库或旧扫描项目。

当前新增任务采用 v2 参数与特征组合，协议及就绪门槛见 [RULES-v2](docs/RULES-v2.md) 和 `schemas/`；下列三族定义保留为 v1 兼容基线，不限制新需求的零件名称。UI、API、Codex CLI 共用同一套本地规则，运行资源由仓库内 `vendor/` 固定。

- Python 包：`mechanical_app`，从项目根运行。
- 安装脚本创建本工程 `.venv`，依赖见 `pyproject.toml`；独立构建方式见 [BUILD](docs/BUILD.md)。
- 工程范围：`geometry_review`；不声明制造、强度、运动或实机通过。
- 参数族：plate = length,width,height,hole_diameter,hole_margin；bracket = length,width,height,thickness；box = length,width,height,wall。参数任务层支持 mm/cm/m，执行计划统一 mm。
- 坐标：plate/box 为 XY 底面、Z 高度；bracket 为 XY 中 L 形截面、沿 Z 拉伸 width。因此 bracket 包络为 length,height,width。所有轮廓以左下底角为原点、右手系。
- `contracts.py`：`EngineeringTask`、`CADPlan`，严格 Pydantic 模型。
- `rules.py`：`validate_task(task, ...)`、`compile_plan(task)`；compile_plan 返回 CADPlan。阻断未知关键参数、冲突、不支持操作和过期基线。
- CADPlan 公共字段：schema_version=`cad-plan/1`，task_id，revision，family，parameters_mm，operations，baseline，semantic_hash，rule_set_version，skill_sha256。operations 只允许确定的族构造操作及 rebuild/measure/save/reopen/export/preview，不得包含任意代码。
- `cad.py`：`execute_plan(plan: dict, output_dir: Path, *, major: int | None = None) -> dict`。仅该模块/其验证脚本可访问 COM；串行执行，attach 不启动新实例，不触碰已有用户文档。
- CAD 返回：status=`passed`/`failed`，task_id，revision，checks（每项 id/status/actual/expected），artifacts（每项 kind/path/sha256/size_bytes），mapping（稳定 instance_id/feature_id/parameter_id 与预览版本），not_covered，runtime，error（失败时）。不得用占位 CAD 文件或 fake 结果通过。
- 预览优先 STL+明确 `units:mm`、坐标与模型指纹；孔/特征的修改点使用参数化语义标记，不把 Three.js UUID 作为工程身份。不承诺任意面/边点选。
- `agent.py`：通过设置选定的 Codex CLI 或兼容模型 API 调用，提交时固定配置快照，锁定 mechanical-design 技能版本，只做结构化需求/计划；没有真实模型调用成功时必须显式记录失败，禁止用预录回复替代。密钥由 `model_settings.py` 在本机加密保存。
- 阶段门槛：契约验证、真实生成/保存重开、局部修改、单位和语义映射、失败与旧版本拒绝。通过后才设计并实现产品 UI。
