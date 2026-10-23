# 工程任务与执行规则 v1

本协议供 mechanical-design-sop 的产品适配层使用。当前范围是三类单零件的 `geometry_review`，输出模型、按需 STEP 和预览；不作制造、强度、装配路径、活动空间或实机通过结论。`EngineeringTask` 解析成功只证明字段合法，必须通过规则检查后才能生成 `CADPlan`。

## 三层输入与责任

1. 自然语言形成需求草稿；未知量保留为空，软件建议保留来源，问题由适配层呈现。
2. `EngineeringTask` 记录已知参数、单位、来源 ID、确认状态、保护条件、交付项与基线。它是技能接收的任务书。
3. `compile_plan` 把就绪任务转换成确定性的 `CADPlan`，只能使用当前版本支持的操作。执行器在连接 CAD 前再次 `validate_plan`。

自然语言模型不能凭一条“确认”字段提供真实世界事实。调用服务负责保存原始需求、资料或 CAD 读回证据，并核对来源记录与实际输入一致。固定案例属于合成基准输入，不代表实际产品测量或制造认证。

## 固定族与坐标

| family | 参数 ID | 明确几何定义 |
|---|---|---|
| `plate` | `length,width,height,hole_diameter,hole_margin` | XY 矩形板，Z 厚度；四角等径贯穿孔，孔中心距相邻边均为 `hole_margin` |
| `bracket` | `length,width,height,thickness` | XY 内 L 截面，两腿外包络为 length×height，沿 Z 拉伸 width；包络 XYZ 为 length,height,width |
| `box` | `length,width,height,wall` | XY 底面、Z 高度的开口盒体；等厚平底与四壁，不包含盖子、卡扣或固定柱 |

全部坐标以左下底角为原点，右手系。任务必须恰好提供对应参数，不接受额外结构的自由参数。壁厚、间隙等不使用产品尺寸默认值；固定族以外的要求必须明确列为不支持，不能被静默忽略。

## 任务字段

完整可运行输入见 [plate-mm.json](../cases/positive/plate-mm.json)。对应机器格式为 [engineering-task-v1.schema.json](../schemas/engineering-task-v1.schema.json)。

- `schema_version` 固定 `engineering-task/1`；`task_id` 是稳定设计身份；`revision` 从 1 递增。
- `action` 为 `create` 或 `modify`；`scope` 固定 `geometry_review`。
- `parameters` 的键就是稳定参数 ID。每个值为 `{value,unit,source_id,confirmed}`；未知 value 必须为 `null`，不能以 0 或猜测值替代。unit 仅支持 mm、cm、m。
- `sources` 为 `{id,kind,reference}` 列表，ID 不可重复。kind 仅支持 user、rule、derived、cad、spec。参数必须引用真实存在的来源；rule/derived 即使声明 confirmed=true 仍被阻断。实际得到用户确认后，引用新的用户确认记录，原提议出处仍可保留在 sources。
- `hard_constraints` 为 `{parameter_id: 数值}`，数值一律 mm。必须等于当前归一化参数；用户需要改变保护值时，调用层先处理范围变更。几何检查容差不意味着可以更改硬约束。
- `deliverables` 为 native、step、preview 的无重复子集，必须有 native，以便保存重开。输入顺序不影响执行语义。
- `tolerance_mm` 是几何回读允许误差，默认明确记录为 0.01 mm，可设为大于0且不超过0.1。它不是产品制造公差或打印配合建议。
- `rule_set_version` 固定 `engineering-rules/1`；`skill_sha256` 必须匹配锁定技能版本。锁记录同时保存引用文件的哈希，任一文件变化都会阻断现有协议，需明确升级。

## 单位、来源、就绪与几何边界

任务层保留输入单位；编译时使用十进制乘法统一成 mm。CAD 库需要的米制转换只允许在 CAD 适配器发生。有限、正数且不超过 1,000,000 mm 才能进入当前执行器；这个范围是数值边界，不是制造可行性结论。

未知、未确认、无来源、规则自行提议、参数集合不符、冲突或锁版本变化都阻止执行。三类最低几何规则：

- 板：孔不得与边界相切或越界，四个孔不得相切或重叠；需要孔边及孔间净距大于检查容差。
- 支架：厚度必须小于两条腿的外形尺寸，并留有大于检查容差的有效 L 截面。
- 盒：必须留下正的内腔和底厚；内腔长度、宽度及高度均大于检查容差。

这些规则只排除明确几何退化，不证明壁厚、载荷或材料选择可用于生产。

## 基线、版本与局部修改

新建任务：`revision=1, action=create, baseline=null`。修改任务：`action=modify`，baseline 为 `{revision:上一版,semantic_hash:上一版语义哈希}`；任务 revision 必须是 baseline.revision+1。

`validate_task(task, expected_revision=当前台账版本, expected_baseline_hash=当前语义哈希)` 校验外部权威基线；新建的当前版本为0。省略这两个上下文只能检查任务内部自洽，不能证明它是当前版。`compile_plan` 不读取全局台账，最终提交服务必须在串行锁内校验版本、旧模型文件指纹与保护条件，成功才推进当前版本。

本阶段修改采用同族参数重建到新文件；旧原生文件保持可恢复。对同一设计，参数 ID 持续稳定，预览网格 UUID 不作为工程身份。任意几何参数改变后重做该零件的几何、保存重开与相关导出检查；无相关变化不扩大验证范围。

## 执行白名单与哈希

计划操作固定为：族构造 `create_plate/create_bracket/create_box` → rebuild → measure → save → reopen → 按需 export(step) → 按需 preview(stl)。每个操作只有版本化参数，没有任意代码、路径、命令行或脚本字段；合法操作的任意插入、重排或参数漂移也被拒绝。

语义哈希涵盖族、归一化尺寸、操作、交付项、保护值、检查容差、范围和技能/规则版本。任务 ID、修订号、上一版指针、目标措辞和来源叙述不进入哈希。相同确认任务的 mm/cm 表达应有相同哈希，目标尺寸或验收语义改变则必须改变哈希。

哈希用于检测结果漂移、版本关联和证据归属，不是外部调用者的身份认证或数字签名。台账的原版校验与权限仍由服务层执行。

## 调用与验收

```python
import json
from mechanical_app.rules import compile_plan, validate_task, validate_plan

task = json.loads(open("cases/positive/plate-mm.json", encoding="utf-8").read())
blockers = validate_task(task, expected_revision=0)
if blockers:
    raise ValueError([b.model_dump() for b in blockers])
plan = compile_plan(task)
assert not validate_plan(plan)
# CAD 执行器接收 plan.model_dump(mode="json")。
```

`validate_task`/`validate_plan` 返回 `list[RuleViolation]`，每项包含 code、path、message。`compile_plan` 对未就绪任务抛 `TaskRejected`，其 violations 保留同样的结构。计划成功不是 CAD 成功；后者必须有真实模型、回读、重开、文件指纹及未覆盖项。

固定正反例预期见 [manifest.json](../cases/manifest.json)。运行范围仅为本适配层：

```powershell
& '../solidworks-automation-skill/.venv/Scripts/python.exe' -m unittest discover -s tests -p test_contracts.py -v
```

这些规则测试不访问 COM，不替代真实 CAD 技术验证，也不声称已经证明技能相对其他项目的体验优势。
