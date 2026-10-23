# 开放零件建模 v2 验证记录

状态：本轮定义范围内的开放零件输入、特征执行、浏览器显示与审阅发布验证通过。本记录只描述本轮 v2 扩展，不改写 v1 的规则、模型或历史报告。

本次取消了以 `plate/bracket/box` 作为新建零件入口白名单的方式。零件名称仅用于表达意图；执行能力由版本化的建模特征决定。已发布的 v1 任务继续使用 v1 协议，避免修改历史模型时发生静默迁移。

## 固定输入和执行规则

新建任务采用 `engineering-task/2`，编译为 `cad-plan/2`，使用 [RULES-v2.md](RULES-v2.md)、[engineering-rules-v2.json](../rules/engineering-rules-v2.json) 和对应 v2 JSON Schema。

任务保存原始需求、参数值、单位、来源、确认状态、保护约束与特征表达式。计划同时保存原始 `feature_recipe`、解析后的数值 `features`、规范参数值及单位、参数到特征字段的绑定。长度使用 mm，角度使用 deg，数量使用 count；数量和角度不会被混入 `parameters_mm`。这些内容和规则、技能版本参与语义指纹计算。

当前执行器支持圆、中心矩形和闭合多边形剖面在 XY 平面沿 +Z 增料或切除，允许不同非负 Z 起点、盲深、圆周阵列和线性阵列。尺寸表达式只接受已确认参数与受限算术，不执行模型生成的代码。缺项、无效轮廓、无材料效果、完全切空、最终不连通或计划被篡改时停止执行，不将未知值补成猜测值。

输入入口接受任意零件描述。遇到尚未实现的曲面、扫掠、螺纹等操作时，需要保留原始要求并指出缺失操作或参数；不能要求用户将零件改名成三种旧模板，也不能静默删除几何要求。取消名称白名单不等于所有工程操作都已自动实现。

## 真实 CAD 证据

使用现有 SolidWorks 2022 SP5 会话，API revision 为 `30.5.0`。执行器只连接既有实例，在无打开文档时开始；各次运行仅创建、保存和关闭本次拥有的文档。以下验证完成后文档列表均为空，没有启动第二实例。

| 明确编写的验证零件 | 实测体积 mm³ | 包络尺寸 mm | 程序检查 |
| --- | ---: | --- | ---: |
| 圆形法兰：中心通孔、4 个均布孔、上端盲台阶孔 | 67811.277428 | 100 × 100 × 10 | 25/25 |
| 同轴阶梯轴 | 38704.421492 | 40 × 40 × 50 | 25/25 |
| 六角外形隔套与中心通孔 | 5829.434856 | 24 × 20.784610 × 18 | 25/25 |
| 矩形安装块与 3 个线性等距孔 | 20582.123980 | 60 × 30 × 12 | 25/25 |
| 真实自然语言生成的法兰：Ø100 × 10、中心孔 Ø40、4 × Ø9 孔、分度圆 Ø75 | 63428.755676 | 100 × 100 × 10 | 25/25 |

合计为五次成功 CAD 用例执行、125 项检查；其中四例为明确编写的专项合成用例，第五例来自真实模型调用的结构化结果并经 UI 触发实际 HTTP/CAD 执行。它们不代表 125 种独立能力。前三例见 [generic-cad-second/generic-cad-verification.json](../results/generic-cad-second/generic-cad-verification.json)，第四例见 [generic-cad-linear/generic-cad-verification.json](../results/generic-cad-linear/generic-cad-verification.json)，第五例见 [UI 集成报告](../results/open-ui/integration-report.json)及其绑定的真实作业。以上仅用于验证，不作为生产设计。

每例均验证创建后的重建、单实体、特征健康、体积、包络和坐标原点；保存原生模型后重新打开检查；独立重新导入 STEP 再检查。原生草图必须完全定义，保存后的盲深、起点及方向必须与计划一致。STL 采用毫米、保留世界坐标，并检查实际网格包络；四张原生视图分别检查非空。原生、STEP、STL、PNG 和语义映射均保存文件大小、时间及 SHA-256。

为避免体积与整体包络相同却孔位错误，前三例另用已有文件做一次只读重开，回读 11 个原生草图的圆心、直径或多边形顶点，结果见 [saved-profile-readback.json](../results/generic-cad-second/saved-profile-readback.json)。原生文件字节未改变。第四例在完整流程内回读 4 个草图；其孔心为 `(-20,0)`、`(0,0)`、`(20,0)` mm。

## 独立几何核对与失败保留

SolidWorks 建模与预期值计算采用不同的几何路径。预期体积和边界由固定版本 Shapely `2.1.2` / GEOS 的分层平面 CSG 得到，同时记录每次增减料后的体积。圆在预测核中以 8192 边近似；原生 CAD 仍是精确圆。体积比较相对容差为 `1e-5`，坐标比较使用任务几何容差，当前四例为 0.01 mm。允许负 X/Y 坐标，不能将中心建模的零件误移到正坐标空间。

第一轮法兰在原生、重开与 STEP 检查通过后，被 STL 检查拦截：默认离散精度造成 Y 边界相对精确圆缩进约 0.0166 mm，超过 0.01 mm 门槛。失败保留于 [generic-cad-first/generic-cad-verification.json](../results/generic-cad-first/generic-cad-verification.json)。随后仅修改 v2 STL 导出为临时自定义偏差 0.0025 mm、角度容差 5°，导出后恢复用户原设置；没有放宽验收容差。第二轮及安装块通过后停止相关验证。

四例专项原生等轴测图已实际查看：法兰的中心台阶孔和四孔、阶梯轴的两段同轴圆柱与肩部、六角隔套的外形与孔、安装块的三孔直线均与所写验证要求一致。观察记录分别位于 [generic-cad-second/visual-observation.json](../results/generic-cad-second/visual-observation.json) 和 [generic-cad-linear/visual-observation.json](../results/generic-cad-linear/visual-observation.json)。第五例的原生等轴测图与浏览器截图也已实际查看，随后通过真实 UI 登记观察并发布，见 [review-report.json](../results/open-ui/review-report.json)。正交视图只完成生成与非空检查，没有冒称逐图人工审阅。原始 CAD 结果中的 `visual_review.pending` 保持不变；第五例的审阅结论单独保存在服务层 `verified-result.json`。

## 程序、自然语言与浏览器证据

根任务会话已执行相关单元测试，66 项通过，用时 2.452 秒；结果位于会话控制台，没有另存日志。自然语言模块曾单独执行 26 项测试，随后新增的 1 项中文数值来源测试通过，提示词调整后再执行直接受影响的 2 项测试。特征模块增加坏表达式阻断检查后，其 11 项子集通过；对无效引用或参数抵消的修正后，同一子集再次通过。以上执行互有重叠，累计覆盖 68 个不同测试方法；没有宣称同一轮执行了 68 项，也不将各子集数量相加。

真实自然语言验证见 [open-vocabulary-language-verification/report.json](../results/open-vocabulary-language-verification/report.json)，7 项检查通过。用户仅说要圆形法兰时，结果保持 `family=flange`，状态为 `needs_input`，追问外径、厚度及孔要求，没有凭空补尺寸或改为旧模板。尺寸齐全的法兰描述经一次 14.485 秒的真实模型调用得到 `ready`、7 个带来源参数、3 个建模特征，并通过本地编译。此前连接、编码及完整描述中虚假来源引用的失败目录保留，未以最终成功覆盖；详细路径见语言报告。

浏览器验证将上述真实模型响应按已记录的文件和 SHA-256 回放到界面，避免重复模型请求。实际旧模型通过 HTTP 加载；后续生成、检查和审阅调用真实本地服务及 SolidWorks，并非模拟 CAD。各报告模式分别记录，不能把响应回放称为新的真实模型请求：

| 证据 | 检查结果 | 本次新增模型请求 / CAD 执行 | 说明 |
| --- | --- | --- | --- |
| [regression-report.json](../results/open-ui/regression-report.json) | 9 项通过 | 0 / 0 | 实际旧模型加载；法兰缺项卡、空任务及传输失败均不回退到旧盒体参数；缺项禁止生成；不改发布状态。 |
| [integration-report.json](../results/open-ui/integration-report.json) | 9 项通过，停止于待审阅 | 0 / 1 | 已记录的真实完整法兰响应进入 UI，真实 HTTP/CAD 生成并完成 25 项检查；数值通过后没有自动发布。 |
| [pending-display-report.json](../results/open-ui/pending-display-report.json) | 10 项通过，停止于待审阅 | 0 / 0 | 只复用同一真实作业，补查待审阅需求卡必须对应已生成任务。 |
| [review-report.json](../results/open-ui/review-report.json) | 5 项通过 | 0 / 0 | 未勾选实际看图时阻止发布；登记原生图观察后，经真实 UI 发布指定法兰 r1，几何未改变。 |

首次集成的 `flange-pending.png` 暴露待审阅阶段仍被历史消息判为正在整理需求，导致右侧卡片显示状态错误；此前 9 项集成检查没有覆盖这一条。修正待审阅阶段的判定后重新构建，仅复用既有 CAD 作业检查需求卡，未重跑模型或建模。原始截图与初始报告保留，后续证据为 `flange-pending-card-fixed.png` 和 `pending-display-report.json`。最终发布截图为 [published-model.png](../results/open-ui/published-model.png)。v2 零件名称显示修正及最后一行状态修正后，前端均已构建通过。

发布作业为 `a8fc3134aa7f442dbe16e9bd343fe28e`，任务为 `task-198b1c300ce2465a935b4746fd0351af`，版本 r1。机器可读汇总及本轮规则、代码、证据文件的指纹见 [open-modeling-verification.json](../results/open-modeling-verification.json)。没有将历史 v1 的成功记录计入本轮 v2 执行结果。

## 结论边界

现有证据支持：新建零件不再依赖三种名称模板；已实现的特征可以组合成多类基础零件，并经真实原生 CAD、独立预测、保存重开和中性文件回读核对。法兰需求已走通真实模型解析、UI 参数确认、真实建模、待审阅、看图和发布；浏览器阶段复用了已记录的模型响应。五次成功执行不能证明任意工程零件、任意组合或未实现操作均可自动完成。

本轮范围仍为几何评审与文件交付。材料、承载能力、制造公差、标准规格、装配运动、生产图纸及实物性能需要按实际任务另行定义与验证。
